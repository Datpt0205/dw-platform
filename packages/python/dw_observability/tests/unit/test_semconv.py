"""The pinned GenAI snapshot and the contract every emitter is held to (spec R1.1, TA2).

Each test here can fail for one reason, and the docstring says which change
turns it red: the snapshot drifting from `semconv.py`, a name we call
upstream's that upstream does not have, or a generator that starts reading our
module instead of upstream's YAML.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from scripts.genai_semconv_snapshot import build_snapshot

from dw_observability.metrics import ALL_METRICS
from dw_observability.semconv import (
    ALLOWED_KEYS,
    DW_ATTRIBUTES,
    DW_SPAN_NAMES,
    GENAI_ATTRIBUTES,
    GENAI_OPERATIONS,
    GENAI_SEMCONV_COMMIT,
    OTEL_CORE_ATTRIBUTES,
    contract_violations,
    dw_names,
    load_snapshot,
    snapshot_path,
)
from dw_observability.telemetry import RecordingTelemetry

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]
SNAPSHOT = load_snapshot(snapshot_path(REPO_ROOT))


def test_the_committed_snapshot_is_the_pinned_commits_and_matches_semconv() -> None:
    """Red when `semconv.py` declares a name the committed snapshot does not
    carry: the module changed and `scripts/genai_semconv_snapshot.py` was not run."""
    assert SNAPSHOT["commit"] == GENAI_SEMCONV_COMMIT
    assert SNAPSHOT["dw"] == dw_names()


def test_every_name_we_call_upstreams_is_in_upstreams_yaml() -> None:
    """Red when `semconv.py` claims an upstream name the pinned YAML lacks,
    `gen_ai.system` for one: it left the conventions for `gen_ai.provider.name`."""
    upstream = SNAPSHOT["upstream"]
    assert set(GENAI_OPERATIONS) - set(upstream["operations"]) == set()
    assert set(GENAI_ATTRIBUTES | OTEL_CORE_ATTRIBUTES) - set(upstream["attributes"]) == set()
    assert "gen_ai.system" not in upstream["attributes"]


def test_what_is_ours_carries_our_prefix() -> None:
    """The `dw` half is added from our module, so it may hold only our names;
    an unprefixed one would be a way to slip an upstream-looking name past the YAML."""
    assert all(name.startswith("dw.") for name in DW_SPAN_NAMES)
    assert all(key.startswith("dw.") for key in DW_ATTRIBUTES)
    assert all(name.startswith("dw_") for name in ALL_METRICS)


def _write(root: Path, relative: str, document: object) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document), encoding="utf-8")


def test_the_snapshot_is_built_from_upstreams_yaml_not_from_semconv(tmp_path: Path) -> None:
    """An upstream whose YAML has `chat` but not `execute_tool`: the snapshot must
    not have `execute_tool`, although `semconv.py` claims it. A generator that
    read our module would put it there, and the span would pass."""
    _write(
        tmp_path,
        "model/gen-ai/registry.yaml",
        {
            "attributes": [
                {"key": "gen_ai.operation.name", "type": {"members": [{"value": "chat"}]}},
                {"key": "gen_ai.request.model"},
            ]
        },
    )
    _write(tmp_path, "docs/not-the-model.yaml", {"attributes": [{"key": "gen_ai.from.docs"}]})
    from scripts.genai_semconv_snapshot import _directory_documents

    snapshot = build_snapshot(_directory_documents(tmp_path))

    assert snapshot["upstream"]["operations"] == ["chat"]
    assert snapshot["upstream"]["attributes"] == ["gen_ai.operation.name", "gen_ai.request.model"]
    recording = RecordingTelemetry()
    with recording.span("execute_tool lookup", {"gen_ai.tool.name": "lookup"}):
        pass
    assert contract_violations(snapshot, recording) == [
        "attribute 'gen_ai.tool.name' on span 'execute_tool lookup'",
        "span 'execute_tool lookup'",
    ]


@pytest.mark.parametrize(
    ("emit", "violation"),
    [
        (lambda t: t.span("chatx gpt", {}), "span 'chatx gpt'"),
        (lambda t: t.span("dw.unlisted", {}), "span 'dw.unlisted'"),
        # Upstream's content keys are in the snapshot; the allowlist refuses them.
        (
            lambda t: t.span("chat gpt", {"gen_ai.input.messages": "[]"}),
            "attribute 'gen_ai.input.messages' on span 'chat gpt'",
        ),
        (lambda t: t.span("chat gpt", {"user.id": "u1"}), "attribute 'user.id' on span 'chat gpt'"),
        (lambda t: t.add_metric("dw_node_failure_total", 1, {}), "metric 'dw_node_failure_total'"),
        (
            lambda t: t.add_metric("dw_run_total", 1, {"tenant": "t1"}),
            "label 'tenant' on metric 'dw_run_total'",
        ),
    ],
)
def test_a_name_outside_the_snapshot_is_refused(emit: object, violation: str) -> None:
    recording = RecordingTelemetry()
    result = emit(recording)  # type: ignore[operator]
    if hasattr(result, "__enter__"):
        with result:
            pass
    assert contract_violations(SNAPSHOT, recording) == [violation]


def test_the_allowlist_holds_no_content_key() -> None:
    """The content keys upstream defines at the pinned commit, by name."""
    content = {
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        "exception.message",
        "exception.stacktrace",
        "user.id",
    }
    assert ALLOWED_KEYS & content == set()
