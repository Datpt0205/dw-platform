"""Export the generated contracts: the OpenAPI snapshot and the JSON Schemas.

`contracts/openapi/openapi.json`: the API app is built with placeholder
connection strings — no live services are contacted; engines/clients are lazy.
The snapshot is the contract-test baseline and the source for the generated
TypeScript types.

`contracts/jsonschema/pd_classification.json`: the personal-data vocabulary of
`dw_kernel.personal_data` (compliance-pdpl R1), which the web's Vietnamese
labels are tested against. Generated, never edited: `--check` fails a hand edit.

Usage:
  uv run python scripts/generate_contracts.py          # write snapshot
  uv run python scripts/generate_contracts.py --check  # fail if drifted
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO_ROOT / "contracts" / "openapi" / "openapi.json"
PD_CLASSIFICATION = REPO_ROOT / "contracts" / "jsonschema" / "pd_classification.json"
# The contract app's dev-token secret: a test that walks the built app signs
# with it to pass the Studio gate, which verifies a token before any dependency.
DEV_SECRET = "contract-snapshot-secret-0123456789"


def build_openapi() -> dict[str, object]:
    return build_app().openapi()


def build_app() -> FastAPI:
    """The app the snapshot describes: every router mounted, no service contacted.

    Also what the error-envelope walker calls, so the routes it proves answer
    in problem+json are the routes the contract publishes.
    """
    from dw_api.bootstrap import build_container
    from dw_api.main import create_app
    from dw_api.settings import ApiSettings

    settings = ApiSettings(
        profile="test",
        database_url="postgresql+asyncpg://contract:contract@localhost:5432/contract",
        # The analyst mounts only when a read-only role is configured, so the
        # snapshot needs one spelled out here: reading it from the developer's
        # environment made the contract depend on who ran the command, and a
        # machine with `.env` loaded produced endpoints CI could never generate.
        agent_ro_database_url="postgresql+asyncpg://contract-ro:contract@localhost:5432/contract",
        # Same reasoning for platform provisioning: spell out the provisioner URL
        # so /api/v1/platform/* is always in the snapshot, not dependent on .env.
        provisioner_database_url="postgresql+asyncpg://contract-prov:contract@localhost:5432/contract",
        # And for the Zalo self-link routes, mounted only with both values set.
        zalo_bot_token="contract-zalo-bot-token",
        zalo_link_secret="contract-zalo-link-secret",
        zalo_bot_link="",
        auth_mode="dev",
        dev_secret=DEV_SECRET,
        s3_endpoint_url="http://localhost:9000",
        s3_access_key="contract",
        s3_secret_key="contract",
        model_provider="mock",
    )
    return create_app(build_container(settings))


def build_pd_classification() -> dict[str, object]:
    """A field's personal-data classification, from the kernel's three enums.

    No `required`: a field without `pd_category` passes this schema, so the
    refusal is the owner's `pd_category_required` from
    `classification_problems`, with its pointer, not the validator's `missing`.
    """
    from dw_kernel.personal_data import PdCategory, SensitiveType, SubjectIdentifierKind

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "pd_classification.json",
        "title": "PdClassification",
        "description": (
            "A field's personal-data classification (ADR-0106 decision 1). Generated from"
            " dw_kernel.personal_data by scripts/generate_contracts.py; do not edit."
        ),
        "type": "object",
        "properties": {
            "pd_category": {"type": "string", "enum": [m.value for m in PdCategory]},
            "sensitive_type": {
                "type": ["string", "null"],
                "enum": [*(m.value for m in SensitiveType), None],
                "description": "Decree 356/2025/ND-CP Art. 4.1; only on a sensitive field.",
            },
            "subject_identifier": {
                "type": ["string", "null"],
                "enum": [*(m.value for m in SubjectIdentifierKind), None],
            },
        },
    }


def render(document: dict[str, object]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def stale(rendered: dict[Path, str]) -> list[Path]:
    """The snapshots whose committed text differs from what generates now."""
    return [
        path
        for path, text in rendered.items()
        if not path.exists() or path.read_text(encoding="utf-8") != text
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify snapshots are current")
    args = parser.parse_args()

    rendered = {
        SNAPSHOT: render(build_openapi()),
        PD_CLASSIFICATION: render(build_pd_classification()),
    }

    if args.check:
        drifted = stale(rendered)
        for path in drifted:
            print(
                f"{path.relative_to(REPO_ROOT).as_posix()} is stale"
                " — run `make generate-contracts`",
                file=sys.stderr,
            )
        if drifted:
            return 1
        print("Generated contracts are current.")
        return 0

    for path, text in rendered.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"Wrote {path.relative_to(REPO_ROOT).as_posix()} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
