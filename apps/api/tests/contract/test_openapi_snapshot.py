"""Contract test: the committed OpenAPI snapshot matches the live app schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SNAPSHOT = REPO_ROOT / "contracts" / "openapi" / "openapi.json"

pytestmark = pytest.mark.contract

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def test_openapi_snapshot_is_current() -> None:
    from generate_contracts import build_openapi  # type: ignore[import-not-found]

    assert SNAPSHOT.exists(), "run `make generate-contracts` to create the snapshot"
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    live = json.loads(json.dumps(build_openapi(), sort_keys=True))
    assert committed == live, "OpenAPI drifted — run `make generate-contracts` and commit"


def test_key_endpoints_present() -> None:
    from generate_contracts import build_openapi

    paths = build_openapi()["paths"]
    for expected in (
        "/api/v1/health",
        "/api/v1/me",
        "/api/v1/approvals",
        "/api/v1/approvals/{approval_id}/decisions",
        "/api/v1/runs/{run_id}",
        "/api/v1/audit/events",
        "/api/v1/knowledge/documents",
        "/api/v1/memory/items",
        "/api/v1/integrations",
    ):
        assert expected in paths, f"missing endpoint {expected}"


def test_every_operation_describes_its_errors_as_a_problem() -> None:
    from generate_contracts import build_openapi

    schema = build_openapi()
    components = schema["components"]["schemas"]  # type: ignore[index]
    assert "HTTPValidationError" not in components
    assert "ValidationError" not in components
    problem = {"$ref": "#/components/schemas/Problem"}
    for path, item in schema["paths"].items():  # type: ignore[attr-defined]
        for method, operation in item.items():
            for status in ("4XX", "5XX"):
                content = operation["responses"][status]["content"]
                assert content == {"application/problem+json": {"schema": problem}}, (
                    f"{method.upper()} {path} {status}"
                )
