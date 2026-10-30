import re
from pathlib import Path

import pytest

from dw_agent_runtime.model.copy import load_runtime_copy
from dw_agent_runtime.registry import ConfigError
from dw_agent_runtime.tool_specs import ToolSpecRegistry
from dw_kernel.errors import NotFoundError

pytestmark = pytest.mark.unit

COPY = load_runtime_copy(
    Path(__file__).resolve().parents[5] / "configs" / "copy" / "runtime@1.3.0.yaml"
)

# A tool with an effect says whether it sends a message (compliance-pdpl CP28).
EXTERNAL = "side_effect_level: external\nsends_message: false"
SPEC = """\
schema_version: "1.0"
name: crm.read_account
version: "1.0.0"
summary: Đọc hồ sơ account trong CRM theo account_id.
when_to_use: Khi cần thông tin công ty, ngành, quy mô để trả lời hoặc chấm điểm.
when_not_to_use: Khi chưa có account_id — hãy hỏi lại người dùng, không được đoán.
returns: Hồ sơ account gồm tên, ngành, quy mô, owner, trạng thái.
required_scopes: [sales_chat.read]
side_effect_level: none
approval_policy: never
timeout_seconds: 15
max_retries: 2
idempotent: true
data_classification: [internal]
"""


def write_spec(directory: Path, body: str, filename: str = "crm.read_account@1.0.0.yaml") -> Path:
    path = directory / filename
    path.write_text(body, encoding="utf-8")
    return path


def test_spec_becomes_a_tool_definition(tmp_path: Path) -> None:
    registry = ToolSpecRegistry(copy=COPY)
    registry.load_file(write_spec(tmp_path, SPEC))

    definition = registry.definition("crm.read_account", "1.0.0")
    assert definition.required_scopes == frozenset({"sales_chat.read"})
    assert definition.side_effect_level == "none"
    assert not definition.always_requires_approval()
    assert definition.input_schema_ref == "contracts/tools/crm.read_account@1.0.0/input.json"


def test_description_tells_the_model_when_to_avoid_the_tool(tmp_path: Path) -> None:
    registry = ToolSpecRegistry(copy=COPY)
    registry.load_file(write_spec(tmp_path, SPEC))

    description = registry.resolve("crm.read_account", "1.0.0").description(COPY)
    assert description.splitlines() == [
        "Đọc hồ sơ account trong CRM theo account_id.",
        "Dùng khi: Khi cần thông tin công ty, ngành, quy mô để trả lời hoặc chấm điểm.",
        "Không dùng khi: Khi chưa có account_id — hãy hỏi lại người dùng, không được đoán.",
        "Trả về: Hồ sơ account gồm tên, ngành, quy mô, owner, trạng thái.",
    ]


def test_load_directory_reads_nested_context_folders(tmp_path: Path) -> None:
    nested = tmp_path / "sales_chat"
    nested.mkdir()
    write_spec(nested, SPEC)

    loaded = ToolSpecRegistry(copy=COPY).load_directory(tmp_path)
    assert [entry.spec.name for entry in loaded] == ["crm.read_account"]
    assert len(loaded[0].checksum) == 64


def test_incomplete_spec_is_refused(tmp_path: Path) -> None:
    body = SPEC.replace(
        "when_not_to_use: Khi chưa có account_id — hãy hỏi lại người dùng, không được đoán.\n", ""
    )
    with pytest.raises(ConfigError, match="invalid"):
        ToolSpecRegistry(copy=COPY).load_file(write_spec(tmp_path, body))


def test_a_never_that_reaches_outside_is_refused_at_load(tmp_path: Path) -> None:
    """The author finds out when the file is read, not when a worker is assembled.

    `never` says this tool does nothing a person would need to approve. On an
    external tool that is false, and a false claim used to be accepted and then
    read as `conditional` — the tool spec said one thing and the runtime did
    another.
    """
    body = SPEC.replace("side_effect_level: none", EXTERNAL)
    with pytest.raises(ConfigError, match="never"):
        ToolSpecRegistry(copy=COPY).load_file(write_spec(tmp_path, body))


def test_the_same_tool_loads_once_it_says_conditional(tmp_path: Path) -> None:
    body = SPEC.replace("side_effect_level: none", EXTERNAL).replace(
        "approval_policy: never", "approval_policy: conditional"
    )
    loaded = ToolSpecRegistry(copy=COPY).load_file(write_spec(tmp_path, body))
    assert loaded.spec.side_effect_level == "external"


def test_malformed_yaml_names_the_file_it_came_from(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=re.escape("crm.read_account@1.0.0.yaml")):
        ToolSpecRegistry(copy=COPY).load_file(write_spec(tmp_path, "name: [unbalanced\n"))


def test_duplicate_version_is_refused(tmp_path: Path) -> None:
    registry = ToolSpecRegistry(copy=COPY)
    registry.load_file(write_spec(tmp_path, SPEC))
    with pytest.raises(ConfigError, match="already registered"):
        registry.load_file(write_spec(tmp_path, SPEC, filename="copy.yaml"))


def test_unknown_version_is_not_found(tmp_path: Path) -> None:
    registry = ToolSpecRegistry(copy=COPY)
    registry.load_file(write_spec(tmp_path, SPEC))
    with pytest.raises(NotFoundError):
        registry.resolve("crm.read_account", "2.1.0")


def test_a_tool_with_an_effect_must_say_whether_it_sends_a_message(tmp_path: Path) -> None:
    """compliance-pdpl CP28: an external tool's spec that is silent about
    sending is refused at load (closed when missing), and a sending one must
    name its channel and every address field."""
    silent = SPEC.replace("side_effect_level: none", "side_effect_level: external").replace(
        "approval_policy: never", "approval_policy: conditional"
    )
    with pytest.raises(ConfigError, match="sends_message"):
        ToolSpecRegistry(copy=COPY).load_file(write_spec(tmp_path, silent))
    unnamed = silent.replace(
        "side_effect_level: external",
        "side_effect_level: external" + chr(10) + "sends_message: true",
    )
    with pytest.raises(ConfigError, match="message"):
        ToolSpecRegistry(copy=COPY).load_file(write_spec(tmp_path, unnamed))
    named = unnamed.replace(
        "sends_message: true",
        "sends_message: true" + chr(10) + "message: {channel: email, recipient_fields: [to, cc]}",
    )
    loaded = ToolSpecRegistry(copy=COPY).load_file(write_spec(tmp_path, named))
    definition = loaded.spec.to_definition(COPY)
    assert definition.message is not None
    assert definition.message.recipient_fields == ("to", "cc")
