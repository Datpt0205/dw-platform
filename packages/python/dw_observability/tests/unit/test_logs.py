"""JSON log lines carry identifiers only (spec R1.5, TA8)."""

from __future__ import annotations

import ast
import json
import logging
import logging.config
import sys
from pathlib import Path

import pytest

from dw_observability.logs import (
    DROPPED_MESSAGE,
    IdentifierOnlyJsonFormatter,
    looks_like_a_value,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]


def _line(
    msg: str, *args: object, extra: dict[str, object] | None = None, exc: bool = False
) -> dict[str, object]:
    record = logging.LogRecord(
        "dw_test", logging.WARNING, __file__, 1, msg, args, sys.exc_info() if exc else None
    )
    for key, value in (extra or {}).items():
        setattr(record, key, value)
    rendered: dict[str, object] = json.loads(IdentifierOnlyJsonFormatter().format(record))
    return rendered


def test_logs_carry_ids_only() -> None:
    """The one test the spec names. Each field is a way a value reaches a line:
    the template's arguments, an allowed key holding a value, an unlisted key,
    and an exception's message."""
    try:
        raise ValueError("refused 0912 345 678 for an@example.vn")
    except ValueError:
        line = _line(
            "lead refused: %s",
            "an@example.vn",
            extra={
                "run_id": "8f1d2c4e-0000-4000-8000-000000000001",
                "worker_id": "an@example.vn",
                "status": "/leads?phone=0912345678",
                "customer_name": "Nguyễn Văn An",
            },
            exc=True,
        )
    text = json.dumps(line, ensure_ascii=False)
    assert "example.vn" not in text
    assert "345" not in text
    assert "phone=" not in text
    assert "Nguyễn" not in text
    assert line["message"] == "lead refused: %s"
    assert line["run_id"] == "8f1d2c4e-0000-4000-8000-000000000001"
    assert "worker_id" not in line and "status" not in line and "customer_name" not in line
    assert line["exception.type"] == "ValueError"
    frames = line["exception.frames"]
    assert isinstance(frames, list) and all(":" in frame for frame in frames)


def test_a_template_carrying_a_value_is_dropped() -> None:
    """An f-string passed as the template interpolates before the formatter sees it."""
    email = "an@example.vn"
    assert _line(f"sent to {email}")["message"] == DROPPED_MESSAGE


def test_identifiers_dates_and_versions_are_not_mistaken_for_values() -> None:
    for text in (
        "8f1d2c4e-0000-4000-8000-000000000001",
        "2026-10-27",
        "1.8.0",
        "audit_events_2026_10",
    ):
        assert not looks_like_a_value(text), text
    for text in ("0912345678", "+84 912 345 678", "an@example.vn", "/runs?cursor=abc"):
        assert looks_like_a_value(text), text


def _src_files() -> list[Path]:
    roots = [
        *(REPO_ROOT / "packages" / "python").glob("*/src"),
        *(REPO_ROOT / "apps").glob("*/src"),
    ]
    return [path for root in roots for path in root.rglob("*.py")]


_LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})


def non_constant_templates(files: list[Path]) -> list[str]:
    found = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LOG_METHODS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"logger", "_LOG", "log", "_logger"}
                and not (
                    node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                )
            ):
                found.append(f"{path.as_posix()}:{node.lineno}")
    return found


def test_log_templates_are_constants() -> None:
    """A template that is an f-string or a variable is where a value is
    interpolated before the formatter can refuse it."""
    assert non_constant_templates(_src_files()) == []


def test_an_interpolated_template_is_found(tmp_path: Path) -> None:
    source = tmp_path / "m.py"
    source.write_text("def f(logger, x):\n    logger.info(f'got {x}')\n", encoding="utf-8")
    assert len(non_constant_templates([source])) == 1


def test_the_api_runs_uvicorn_under_the_identifier_only_config() -> None:
    dockerfile = (REPO_ROOT / "infra" / "docker" / "api.Dockerfile").read_text(encoding="utf-8")
    (cmd,) = [line for line in dockerfile.splitlines() if line.startswith('CMD ["uvicorn"')]
    assert '"--log-config", "/app/configs/logging/uvicorn.json"' in cmd
    config = json.loads((REPO_ROOT / "configs" / "logging" / "uvicorn.json").read_text("utf-8"))
    formatter = config["formatters"][config["handlers"]["stdout"]["formatter"]]
    assert formatter["()"] == "dw_observability.logs.IdentifierOnlyJsonFormatter"
    # Every uvicorn logger hands its records to the root handler, none keeps its own.
    assert all(
        logger["handlers"] == [] and logger["propagate"] for logger in config["loggers"].values()
    )
    assert config["root"]["handlers"] == ["stdout"]


def test_the_worker_installs_the_formatter_in_main() -> None:
    tree = ast.parse(
        (REPO_ROOT / "apps" / "worker" / "src" / "dw_worker" / "main.py").read_text("utf-8")
    )
    (main,) = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    calls = [
        n.func.id
        for n in ast.walk(main)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert "configure_json_logging" in calls
    assert not any(isinstance(n, ast.Attribute) and n.attr == "basicConfig" for n in ast.walk(main))
