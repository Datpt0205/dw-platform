"""Seed the digital-worker demo (leadcare ticket 02, R4.1) through the platform's own API.

A tenant, its five people and one `lead_care` DW in `operating`, each made the
way a person would make it, so every invariant those paths hold holds here too:

1. a platform operator signs in once and is put on the allowlist by
   ``scripts/grant_platform_operator.py``, the documented first-operator bootstrap
   (the one step no API can do: the operator API is itself operator-gated);
2. the operator creates the tenant with its two owners, the Business Owner and
   the Technical Owner (``POST /platform/tenants``); it is born in ``setup``;
3. both owners sign in, which links their invitations and makes the tenant
   ``active`` (tenant-rbac R3.9, org-and-principals R4.5);
4. the Business Owner invites the Work Assigner, the Validator and the sales
   person (``POST /admin/invitations``), and each signs in;
5. the Business Owner creates the DW with its four people and its decision
   classes at A2 and A3 (``POST /digital-workers``), and the Technical Owner,
   the second person, puts it into operation (``POST /digital-workers/{id}/state``).

Sign-in is the dev issuer's (``scripts/demo_dw_api.py``). The ids land in
``--state`` for ``demo_dw_run`` and the Playwright spec; the file holds no token.

    DW_DEMO_API_URL=http://localhost:8010 \
    DW_DATABASE_URL=postgresql+asyncpg://dw_migrator:...@127.0.0.1:25445/dw \
        uv run python -m scripts.demo_dw_seed --state .demo/digital-worker/state.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from scripts.demo_dw_api import Api, DemoError, Person, wait_until_up

ROOT = Path(__file__).resolve().parents[1]
TENANT_SLUG = "dw-demo"
TENANT_NAME = "Công ty Demo DW"
SENDER = "dw-leadcare@demo.local"
REPLY_WAIT_SECONDS = 60


OPERATOR = Person("operator", "dev|dwdemo.operator", "operator@dwdemo.local", "Vận hành nền tảng")
BUSINESS_OWNER = Person(
    "business_owner", "dev|dwdemo.chau", "chau.tran@demo.local", "Trần Minh Châu"
)
TECHNICAL_OWNER = Person("technical_owner", "dev|dwdemo.huy", "huy.le@demo.local", "Lê Quốc Huy")
WORK_ASSIGNER = Person(
    "work_assigner", "dev|dwdemo.trang", "trang.pham@demo.local", "Phạm Thu Trang", ("member",)
)
VALIDATOR = Person(
    "validator", "dev|dwdemo.yen", "yen.nguyen@demo.local", "Nguyễn Hải Yến", ("approver",)
)
SALES = Person("sales", "dev|dwdemo.khoa", "khoa.do@demo.local", "Đỗ Văn Khoa", ("member",))
INVITED = (WORK_ASSIGNER, VALIDATOR, SALES)


def grant_operator(email: str) -> None:
    """The documented first-operator bootstrap, run as written."""
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "grant_platform_operator.py"), "--email", email],
        check=False,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise DemoError(f"grant_platform_operator: {done.stderr.strip() or done.stdout.strip()}")


def seed(api: Api) -> dict[str, Any]:
    api.sign_in(OPERATOR)
    grant_operator(OPERATOR.email)
    tenant = api.call(
        "POST",
        "/platform/tenants",
        OPERATOR,
        body={
            "slug": TENANT_SLUG,
            "name": TENANT_NAME,
            "plan_id": "professional",
            "owners": [BUSINESS_OWNER.email, TECHNICAL_OWNER.email],
        },
        expect=201,
    )
    scope = (tenant["tenant_id"], tenant["workspace_id"])
    ids = {
        person.role: api.sign_in(person)["principal_id"]
        for person in (BUSINESS_OWNER, TECHNICAL_OWNER)
    }
    for person in INVITED:
        api.call(
            "POST",
            "/admin/invitations",
            BUSINESS_OWNER,
            scope=scope,
            body={
                "display_name": person.display_name,
                "email": person.email,
                "memberships": [
                    {"workspace_id": tenant["workspace_id"], "role_keys": list(person.role_keys)}
                ],
            },
            expect=201,
        )
        ids[person.role] = api.sign_in(person)["principal_id"]

    worker = api.call(
        "POST",
        "/digital-workers",
        BUSINESS_OWNER,
        scope=scope,
        body={
            "key": "lead_care",
            "name": "Chăm sóc lead",
            "mandate": "Nhận lead từ form website, soạn thư chờ duyệt, theo dõi trả lời"
            " và bàn giao cho sales.",
            "work_kinds": ["marketing.lead"],
            "allowed_tools": ["email.send", "mailbox.fetch_reply", "work.handoff"],
            "workflow_key": "lead_care",
            "workflow_version": "1.0.0",
            "parameters": {
                "sender_address": SENDER,
                "sales_assignee_id": ids[SALES.role],
                "reply_wait_seconds": REPLY_WAIT_SECONDS,
            },
            "role_keys": ["member"],
            "people": {
                "business_owner_id": ids[BUSINESS_OWNER.role],
                "technical_owner_id": ids[TECHNICAL_OWNER.role],
                "work_assigner_id": ids[WORK_ASSIGNER.role],
                "validator_id": ids[VALIDATOR.role],
            },
            # The pack's ceilings (R1.2), earned at them: every mail still waits
            # for its Validator, since `email.send` tops out at A2.
            "decision_classes": [
                {
                    "key": "email.send",
                    "effect_level": "external",
                    "reversible": False,
                    "ceiling": "A2",
                    "earned_level": "A2",
                },
                {
                    "key": "work.handoff",
                    "effect_level": "internal",
                    "reversible": True,
                    "ceiling": "A3",
                    "earned_level": "A3",
                },
            ],
        },
        expect=201,
    )
    operating = api.call(
        "POST",
        f"/digital-workers/{worker['id']}/state",
        TECHNICAL_OWNER,
        scope=scope,
        body={"state": "operating"},
    )
    if operating["state"] != "operating":
        raise DemoError(f"the DW is {operating['state']}, not operating")
    return {
        "api_url": api.base_url,
        "tenant_id": tenant["tenant_id"],
        "workspace_id": tenant["workspace_id"],
        "tenant_name": TENANT_NAME,
        "dw_id": worker["id"],
        "sender_address": SENDER,
        "reply_wait_seconds": REPLY_WAIT_SECONDS,
        "people": {
            person.role: {
                "subject": person.subject,
                "email": person.email,
                "display_name": person.display_name,
                "user_id": ids[person.role],
            }
            for person in (BUSINESS_OWNER, TECHNICAL_OWNER, *INVITED)
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", type=Path, required=True, help="where the ids are written")
    args = parser.parse_args()
    base_url = os.environ.get("DW_DEMO_API_URL", "http://localhost:8010").rstrip("/")
    secret = os.environ.get("DW_API_DEV_SECRET", "")
    if not os.environ.get("DW_DATABASE_URL"):
        print("DW_DATABASE_URL (the demo database's migrator) is required", file=sys.stderr)
        return 2
    with httpx.Client(timeout=30) as http:
        api = Api(base_url=base_url, tokens=DevTokenVerifier(secret), http=http)
        try:
            wait_until_up(http, base_url)
            state = seed(api)
        except DemoError as exc:
            print(f"!! seed: {exc}", file=sys.stderr)
            return 1
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"seeded {TENANT_NAME}: DW {state['dw_id']} operating; state in {args.state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
