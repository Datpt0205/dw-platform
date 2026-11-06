"""marketing-pilot ticket 02: the two companies seeded only through the public
API (R1.1-R1.7; MP4, MP6, MP17).

The platform is fresh for the module (`marketing_pilot_stack`: a new database,
migrated, the API and the worker as processes on the host, the first operator
granted by the documented bootstrap). The seed itself reaches nothing but HTTP;
each test reads what it built through the same API, as a person of the right
company.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from marketing_pilot_stack import Stack, grant_operator, running_stack

from marketing_pilot.api import Api, Person, SeedError
from marketing_pilot.seed import (
    CAMPAIGN,
    LEAD,
    PROTECTED,
    Company,
    Limits,
    confirm,
    invite,
    person,
    seed,
    tenant_status,
)

pytestmark = pytest.mark.e2e

HARNESS = Path(__file__).resolve().parent
REPO = HARNESS.parents[2]
LIMITS = Limits(
    company_cost_usd="200", company_runs="150", marketing_cost_usd="100", marketing_runs="100"
)


@dataclass
class World:
    stack: Stack
    api: Api
    operator: Person
    prefix: str
    a: Company
    b: Company


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    logs = tmp_path_factory.mktemp("marketing_pilot")
    with running_stack(logs) as stack, httpx.Client(timeout=60) as http:
        api = Api(stack.api_url, stack.secret, http)
        operator = Person("operator", "mp-operator", "operator@example.com", "Người vận hành")
        api.sign_in(operator)
        grant_operator(stack, operator.email)
        prefix = f"mp-{secrets.token_hex(3)}"
        a, b = seed(api, operator, prefix=prefix, limits_of=LIMITS)
        yield World(stack, api, operator, prefix, a, b)


def at(company: Company, workspace: str | None = None) -> dict[str, str]:
    return {"tenant": company.tenant_id, "workspace": workspace or company.marketing}


def grants(world: World, company: Company, key: str) -> set[str]:
    who, workspace = company.members[key]
    me = world.api.call("GET", "/me", who, **at(company, workspace))
    return {g["key"] for g in me["grants"]}


def lead_of(world: World, company: Company, key: str = "marketer") -> tuple[dict[str, Any], str]:
    who, workspace = company.members[key]
    # The synthetic range of ticket 01: +84900000000 to +84900009999.
    phone = f"+8490000{secrets.randbelow(10_000):04d}"
    made = world.api.call(
        "POST",
        f"/studio/objects/{LEAD}/records",
        who,
        expect=201,
        body={"name": "Nguyễn Thị Lan", "fields": {"phone_e164": phone}},
        **at(company, workspace),
    )
    return made, phone


# ---- R1.1: two companies, built over HTTP alone ----------------------------------


def test_r1_1_each_member_holds_exactly_the_keys_of_their_role(world: World) -> None:
    for company in (world.a, world.b):
        fields = {f"fld.{LEAD}.{f}.{a}" for f in PROTECTED for a in ("read", "edit")}
        marketer = grants(world, company, "marketer")
        assert {f"obj.{LEAD}.read", f"obj.{LEAD}.create", f"obj.{LEAD}.update"} <= marketer
        assert f"obj.{CAMPAIGN}.read" in marketer and fields <= marketer
        head = grants(world, company, "head_1")
        assert {f"obj.{LEAD}.assign", f"obj.{CAMPAIGN}.update", "approvals.decide"} <= head
        assert fields <= head
        sales = grants(world, company, "sales_c")
        assert {f"obj.{LEAD}.read", f"obj.{LEAD}.create", f"obj.{LEAD}.update"} <= sales
        collaborator = grants(world, company, "collaborator")
        assert f"obj.{LEAD}.read" in collaborator
        assert not {f"obj.{LEAD}.create", f"obj.{LEAD}.update"} & collaborator
        assert not [k for k in collaborator if k.startswith(f"fld.{LEAD}.")]
        for key in ("sales_c", "sales_d", "collaborator"):
            assert f"obj.{CAMPAIGN}.update" not in grants(world, company, key)


def test_r1_1_everyone_is_active_and_the_service_account_holds_one_role(world: World) -> None:
    for company in (world.a, world.b):
        listed = world.api.call("GET", "/admin/members", company.first, **at(company, company.main))
        by_id = {m["user_id"]: m for m in listed}
        for key in company.members:
            assert by_id[company.principals[key]]["status"] == "active", key
        held = {
            key
            for key, role_id in company.roles.items()
            if any(
                str(a["user_id"]) == company.service_principal
                for a in world.api.call(
                    "GET",
                    f"/admin/roles/{role_id}/assignments",
                    company.first,
                    **at(company, company.main),
                )
            )
        }
        assert held == {"lead_intake"}
        sales = by_id[company.principals["sales_c"]]
        assert {m["workspace_id"]: m["role_keys"] for m in sales["memberships"]} == {
            company.sales: ["sales"],
            company.marketing: [],
        }
    people = {who.email for c in (world.a, world.b) for who, _ in c.members.values()}
    assert len(people) == 2 * len(world.a.members)


def test_r1_1_two_owners_exactly_or_no_company(world: World) -> None:
    def tenants() -> set[str]:
        listed = world.api.call("GET", "/platform/tenants", world.operator)
        return {t["slug"] for t in (listed["items"] if isinstance(listed, dict) else listed)}

    before = tenants()
    for n, owners in enumerate(
        (
            ["solo@example.com"],
            ["twin@example.com", "twin@example.com"],
            ["Case@example.com", "case@example.com"],
        )
    ):
        answer = world.api.request(
            "POST",
            "/platform/tenants",
            world.operator,
            body={
                "name": "Sai",
                "slug": f"{world.prefix}-bad-{n}",
                "owners": owners,
                "plan_id": "professional",
            },
        )
        assert (answer.status, answer.body["code"]) == (422, "validation_failed"), owners
    assert tenants() == before


# ---- R1.2 (MP17): the harness imports no platform internals ----------------------


def test_r1_2_an_adapter_import_in_the_harness_turns_lint_imports_red() -> None:
    probe = HARNESS / f"_probe_{secrets.token_hex(4)}.py"
    probe.write_text("import dw_platform.adapters.persistence.tables  # noqa: F401\n")
    try:
        done = subprocess.run(
            ["uv", "run", "lint-imports"],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            check=False,
        )
    finally:
        probe.unlink()
    assert done.returncode != 0
    assert "The marketing pilot harness imports no platform package BROKEN" in done.stdout
    assert probe.stem in done.stdout


# ---- R1.3 (MP4): company B sees nothing of company A -----------------------------


def test_r1_3_company_b_reads_and_writes_nothing_of_company_a(world: World) -> None:
    made, phone = lead_of(world, world.a)
    theirs, workspace = world.b.members["marketer"]
    record = f"/studio/objects/{LEAD}/records/{made['id']}"
    assert world.api.request("GET", record, theirs, **at(world.b, workspace)).status == 404
    listed = world.api.call(
        "GET", f"/studio/objects/{LEAD}/records", theirs, **at(world.b, workspace)
    )
    assert made["id"] not in str(listed) and phone not in str(listed)
    for method, path, body in (
        ("GET", f"/studio/objects/{LEAD}/records", None),
        ("POST", f"/studio/objects/{LEAD}/records", {"name": "Lọt", "fields": {}}),
    ):
        foreign = world.api.request(method, path, theirs, body=body, **at(world.a))
        assert foreign.status in (403, 404), (method, foreign.status)
        assert phone not in str(foreign.body)


# ---- R1.4 (MP6): every field declares its personal data --------------------------


def test_r1_4_each_published_field_declares_its_personal_data(world: World) -> None:
    for company in (world.a, world.b):
        for api_name, artifact in company.objects.items():
            version = world.api.call(
                "GET", f"/studio/artifacts/{artifact}/versions/1", company.first, **at(company)
            )
            document = version["document"]
            assert document["default_access"] == "private", api_name
            assert document["name_field"]["pd_category"] in ("basic", "none")
            for field in document["fields"]:
                assert field["pd_category"] in ("basic", "none", "sensitive"), field
        described = world.api.call(
            "GET",
            f"/studio/objects/{LEAD}/describe",
            company.members["collaborator"][0],
            **at(company),
        )
        hidden = {f["api_name"] for f in described["fields"] if f["access"] == "hidden"}
        assert set(PROTECTED) <= hidden
        status, body = company.pd_refusal
        assert (status, body["code"]) == (422, "validation_failed")
        assert {"pointer": "/fields/3", "code": "pd_category_required"}.items() <= next(
            e for e in body["errors"] if e["code"] == "pd_category_required"
        ).items()


# ---- R1.5: phase one, the objects wait for the second owner ----------------------


def test_r1_5_objects_submitted_by_one_owner_are_not_live_until_the_other_approves(
    world: World,
) -> None:
    [company] = seed(
        world.api,
        world.operator,
        prefix=f"{world.prefix}-p1",
        companies=1,
        stop_after="object_submit",
    )
    for artifact in company.objects.values():
        view = world.api.call("GET", f"/studio/artifacts/{artifact}", company.first, **at(company))
        assert view["display_stage"] in ("awaiting_approval", "candidate"), view
    records = world.api.request(
        "GET", f"/studio/objects/{LEAD}/records", company.first, **at(company)
    )
    assert records.status == 404
    page = world.api.call(
        "GET", "/approvals", company.second, params={"status": "pending"}, **at(company)
    )
    for approval in page["items"]:
        world.api.call(
            "POST",
            f"/approvals/{approval['id']}/decisions",
            company.second,
            body={"approve": True, "comment": "Duyệt"},
            **at(company),
        )
    _until_live(world, company)


def _until_live(world: World, company: Company) -> None:
    deadline = time.monotonic() + 90
    while (
        world.api.request(
            "GET", f"/studio/objects/{LEAD}/describe", company.first, **at(company)
        ).status
        != 200
    ):
        assert time.monotonic() < deadline, "the object never went live"
        time.sleep(0.5)


# ---- R1.5: phase two, a role in force only once the other owner confirms ---------


def test_r1_5_a_role_proposed_by_one_owner_grants_nothing_until_the_other_confirms(
    world: World,
) -> None:
    [company] = seed(
        world.api,
        world.operator,
        prefix=f"{world.prefix}-p2",
        companies=1,
        stop_after="role_proposal",
    )
    marketer = person("marketer", "a", f"{world.prefix}-p2", "Nhân viên Marketing")
    invite(world.api, company, marketer, [(company.marketing, ["marketing"])])
    body = {"name": "Trần Văn Bình", "fields": {"phone_e164": "+84900001234"}}
    refused = world.api.request(
        "POST", f"/studio/objects/{LEAD}/records", marketer, body=body, **at(company)
    )
    assert refused.status in (403, 404), refused.body
    [proposal] = company.pending
    confirm(world.api, company, proposal)
    made = world.api.call(
        "POST", f"/studio/objects/{LEAD}/records", marketer, expect=201, body=body, **at(company)
    )
    read = world.api.call(
        "GET", f"/studio/objects/{LEAD}/records/{made['id']}", marketer, **at(company)
    )
    assert read["fields"]["phone_e164"] == "+84900001234"


# ---- R1.6: the limits set once ---------------------------------------------------


def test_r1_6_limits_are_set_once_and_a_raise_needs_a_second_person(world: World) -> None:
    company = world.a

    def policies() -> dict[tuple[str, str, str, str], str]:
        listed = world.api.call("GET", "/limits", company.first, **at(company, company.main))
        items = listed["items"] if isinstance(listed, dict) else listed
        return {
            (p["scope_type"], p["scope_id"], p["metric"], p["window_kind"]): p["limit_value"]
            for p in items
        }

    expected = {
        ("tenant", company.tenant_id, "cost_usd", "month"): LIMITS.company_cost_usd,
        ("tenant", company.tenant_id, "runs", "day"): LIMITS.company_runs,
        ("workspace", company.marketing, "cost_usd", "month"): LIMITS.marketing_cost_usd,
        ("workspace", company.marketing, "runs", "day"): LIMITS.marketing_runs,
    }
    found = policies()
    for key, value in expected.items():
        assert float(found[key]) == float(value), key
    listed = world.api.call("GET", "/limits", company.first, **at(company, company.main))
    marketing_runs = next(
        p
        for p in (listed["items"] if isinstance(listed, dict) else listed)
        if (p["scope_id"], p["metric"]) == (company.marketing, "runs")
    )
    raised = world.api.request(
        "PUT",
        f"/limits/workspace/{company.marketing}/runs/day",
        company.first,
        body={"kind": "hard", "limit_value": "150"},
        if_match=f'"{marketing_runs["version"]}"',
        **at(company, company.main),
    )
    assert raised.status == 409, raised.body
    assert "second_person_required" in str(raised.body), raised.body
    with pytest.raises(SeedError):
        seed(world.api, world.operator, prefix=world.prefix, companies=1)
    assert policies() == found


# ---- R1.7: nothing reaches a company in `setup` ----------------------------------


def test_r1_7_nothing_but_the_owners_sign_ins_reaches_a_company_in_setup(world: World) -> None:
    log = world.api.log
    for company in (world.a, world.b):
        between = log[company.created_at + 1 : company.active_at]
        assert between and all(call.tenant_id != company.tenant_id for call in between)
        assert log[company.active_at].tenant_id == company.tenant_id


def test_r1_7_a_company_whose_second_owner_never_signs_in_stops_the_seed(world: World) -> None:
    started: list[Company] = []
    mark = len(world.api.log)
    with pytest.raises(SeedError, match="not active"):
        seed(
            world.api,
            world.operator,
            prefix=f"{world.prefix}-stuck",
            companies=1,
            second_owner_signs_in=False,
            setup_seconds=6,
            into=started,
        )
    [company] = started
    assert tenant_status(world.api, world.operator, company.tenant_id) == "setup"
    calls = world.api.log[mark:]
    assert all(call.tenant_id != company.tenant_id for call in calls)
    listed = world.api.call("GET", "/platform/tenants", world.operator)
    row = next(
        t
        for t in (listed["items"] if isinstance(listed, dict) else listed)
        if t["id"] == company.tenant_id
    )
    assert row["workspace_count"] == 1
