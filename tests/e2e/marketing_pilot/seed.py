"""The marketing pilot's two companies, built only through the public API
(marketing-pilot ticket 02; spec R1.1-R1.7, MP17).

`seed` builds, for each company, as its spec's "Dữ liệu" says:

1. the company, created by the platform operator with exactly two owners
   (`POST /platform/tenants`), each owner's first sign-in, and a wait until it
   is `active`, nothing else reaching it while it is in `setup` (R1.7);
2. the workspaces Marketing and Sales, and each owner placed by the other in
   both with no role (`PUT .../memberships`, `role_keys: []`; tenant-rbac/16);
3. `mkt_lead` and `mkt_campaign` under Marketing: created, saved, refused once
   without a `pd_category` (R1.4), saved again, submitted by the first owner and
   approved by the second, then waited on until live (R1.5);
4. the five roles, each created and filled by the first owner and confirmed by
   the second, the protected fields' ids read from describe (custom-objects/12);
5. the members, each invited by the first owner (confirmed by the second) and
   signed in; the workflow's service account with its one role (R1.1);
6. the company's and Marketing's limits, set once (R1.6).

Every widening change is proposed by one owner and confirmed by the other (D11).
The harness reaches nothing but HTTP: no `dw_*` import, no database (MP17,
`marketing_pilot_independence`). `stop_after` ends a run at a named step, for
the two phases of R1.5; `second_owner_signs_in=False` leaves the company in
`setup`, for R1.7's timeout.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

import httpx

from marketing_pilot.api import Api, Person, SeedError, wait_until_ready

PLAN: Final = "professional"
OWNER_ROLE: Final = "tenant_owner"
LEAD: Final = "mkt_lead"
CAMPAIGN: Final = "mkt_campaign"
# The five protected fields of `mkt_lead` (DO-34.1; Đạt, Q-h10): `name` is the
# object's name field.
PROTECTED: Final = ("name", "phone_e164", "email", "message", "score_reason")
SETUP_SECONDS: Final = 60.0
PUBLISH_SECONDS: Final = 90.0

Step = Literal["object_submit", "role_proposal"]


def _labels(vi: str) -> dict[str, str]:
    return {"vi": vi}


def _options(*pairs: tuple[str, str]) -> list[dict[str, Any]]:
    return [
        {"key": key, "labels": _labels(label), "position": n}
        for n, (key, label) in enumerate(pairs)
    ]


def lead_document(*, without_pd: str | None = None) -> dict[str, Any]:
    """`mkt_lead` as the spec's "Dữ liệu" says; ``without_pd`` names a field
    sent without its `pd_category` (R1.4's refusal)."""
    fields: list[dict[str, Any]] = [
        {
            "api_name": "phone_e164",
            "labels": _labels("Số điện thoại"),
            "type": "phone",
            "is_unique": True,
            "pd_category": "basic",
            "access_mode": "secured",
        },
        {
            "api_name": "email",
            "labels": _labels("Email"),
            "type": "email",
            "pd_category": "basic",
            "access_mode": "secured",
        },
        {
            "api_name": "lead_source",
            "labels": _labels("Nguồn"),
            "type": "picklist",
            "pd_category": "none",
            "indexed": True,
            "options": _options(("web", "Web"), ("zalo", "Zalo"), ("su_kien", "Sự kiện")),
        },
        {
            "api_name": "message",
            "labels": _labels("Lời nhắn"),
            "type": "text",
            "max_length": 255,
            "pd_category": "basic",
            "access_mode": "secured",
        },
        {
            "api_name": "lead_score",
            "labels": _labels("Điểm"),
            "type": "number",
            "number_mode": "exact",
            "pd_category": "none",
            "indexed": True,
        },
        {
            "api_name": "lead_tier",
            "labels": _labels("Hạng"),
            "type": "picklist",
            "pd_category": "none",
            "indexed": True,
            "options": _options(
                ("nong", "Nóng"), ("am", "Ấm"), ("lanh", "Lạnh"), ("chua_ro", "Chưa rõ")
            ),
        },
        {
            "api_name": "score_reason",
            "labels": _labels("Lý do chấm điểm"),
            "type": "text",
            "max_length": 255,
            "pd_category": "basic",
            "access_mode": "secured",
        },
    ]
    for item in fields:
        if item["api_name"] == without_pd:
            del item["pd_category"]
            item.pop("access_mode", None)
    return {
        "labels": _labels("Khách hàng tiềm năng"),
        "default_access": "private",
        "name_field": {"labels": _labels("Họ tên"), "pd_category": "basic"},
        "fields": fields,
    }


def campaign_document() -> dict[str, Any]:
    return {
        "labels": _labels("Chiến dịch"),
        "default_access": "private",
        "name_field": {"labels": _labels("Tên chiến dịch"), "pd_category": "none"},
        "fields": [
            {
                "api_name": "channel",
                "labels": _labels("Kênh"),
                "type": "picklist",
                "pd_category": "none",
                "options": _options(("email", "Email"), ("zalo", "Zalo")),
            },
            {
                "api_name": "status",
                "labels": _labels("Trạng thái"),
                "type": "picklist",
                "pd_category": "none",
                "options": _options(("nhap", "Nháp"), ("dang_chay", "Đang chạy"), ("xong", "Xong")),
            },
            {
                "api_name": "start_date",
                "labels": _labels("Bắt đầu"),
                "type": "date",
                "pd_category": "none",
            },
            {
                "api_name": "end_date",
                "labels": _labels("Kết thúc"),
                "type": "date",
                "pd_category": "none",
            },
        ],
    }


# ---- the roles of the spec's "Dữ liệu" -------------------------------------------


@dataclass(frozen=True)
class RoleSpec:
    key: str
    name: str
    lead: tuple[str, ...]
    lead_depth: str
    campaign: tuple[str, ...]
    keys: tuple[str, ...]
    fields: bool

    def body(self, objects: dict[str, str], field_ids: dict[str, str]) -> dict[str, Any]:
        privileges = [
            {"object_id": objects[LEAD], "action": a, "depth": self.lead_depth} for a in self.lead
        ] + [
            {"object_id": objects[CAMPAIGN], "action": a, "depth": "workspace"}
            for a in self.campaign
        ]
        return {
            "permissions": [{"key": k, "depth": "workspace"} for k in self.keys],
            "object_privileges": privileges,
            "field_permissions": (
                [{"field_id": field_ids[f], "access": "edit"} for f in PROTECTED]
                if self.fields
                else []
            ),
        }


WORKFLOW_KEYS: Final = ("studio.workflows.read", "studio.workflows.edit")
ROLES: Final = (
    RoleSpec(
        "marketing",
        "Marketing",
        ("read", "create", "update"),
        "workspace",
        ("read",),
        WORKFLOW_KEYS,
        True,
    ),
    RoleSpec(
        "marketing_lead",
        "Trưởng Marketing",
        ("read", "create", "update", "assign"),
        "workspace",
        ("read", "update"),
        (*WORKFLOW_KEYS, "approvals.decide"),
        True,
    ),
    RoleSpec("sales", "Sales", ("read", "create", "update"), "own", (), (), True),
    RoleSpec(
        "marketing_collaborator", "Cộng tác viên Marketing", ("read",), "workspace", (), (), False
    ),
    RoleSpec(
        "lead_intake",
        "Quy trình Tiếp nhận lead",
        ("read", "create", "update", "assign"),
        "workspace",
        ("read",),
        (),
        True,
    ),
)


# ---- what a run leaves -----------------------------------------------------------


@dataclass
class Company:
    key: str
    slug: str
    tenant_id: str = ""
    main: str = ""
    marketing: str = ""
    sales: str = ""
    owners: tuple[Person, ...] = ()
    objects: dict[str, str] = field(default_factory=dict)
    field_ids: dict[str, str] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    # key -> (person, workspace the person works in)
    members: dict[str, tuple[Person, str]] = field(default_factory=dict)
    service_principal: str = ""
    # person key -> principal id, as each first sign-in answered it.
    principals: dict[str, str] = field(default_factory=dict)
    # R1.4's refusal, as the submit answered it.
    pd_refusal: Any = None
    # Positions in the call log: the call that created the company, and the
    # first call after it was read `active` (R1.7).
    created_at: int = -1
    active_at: int = -1
    # A role change left unconfirmed by `stop_after="role_proposal"` (R1.5).
    pending: list[dict[str, Any]] = field(default_factory=list)

    @property
    def first(self) -> Person:
        return self.owners[0]

    @property
    def second(self) -> Person:
        return self.owners[1]


@dataclass(frozen=True)
class Limits:
    company_cost_usd: str = "200"
    company_runs: str = "150"
    marketing_cost_usd: str = "100"
    marketing_runs: str = "100"


def person(key: str, company: str, run: str, display_name: str) -> Person:
    subject = f"mp-{run}-{company}-{key}"
    return Person(key, subject, f"{subject}@example.com", display_name)


# ---- the steps -------------------------------------------------------------------


def _wait(check: Callable[[], bool], seconds: float, what: str) -> None:
    deadline = time.monotonic() + seconds
    while not check():
        if time.monotonic() > deadline:
            raise SeedError(f"{what}: still not done after {seconds:.0f}s")
        time.sleep(0.5)


def create_company(api: Api, operator: Person, company: Company, owners: Sequence[Person]) -> None:
    made = api.call(
        "POST",
        "/platform/tenants",
        operator,
        expect=201,
        body={
            "name": f"Công ty {company.key.upper()} ({company.slug})",
            "slug": company.slug,
            "owners": [o.email for o in owners],
            "plan_id": PLAN,
        },
    )
    company.tenant_id, company.main = made["tenant_id"], made["workspace_id"]
    company.owners = tuple(owners)
    company.created_at = len(api.log) - 1


def tenant_status(api: Api, operator: Person, tenant_id: str) -> str:
    listed = api.call("GET", "/platform/tenants", operator)
    items = listed["items"] if isinstance(listed, dict) else listed
    return next(str(t["status"]) for t in items if t["id"] == tenant_id)


def activate(
    api: Api, operator: Person, company: Company, *, second_signs_in: bool, seconds: float
) -> None:
    """R1.7: only the owners' sign-ins and the operator's reads reach a
    company in `setup`; the seed waits for `active` before anything else."""
    signed_in(api, company, company.first)
    if second_signs_in:
        signed_in(api, company, company.second)
    _wait(
        lambda: tenant_status(api, operator, company.tenant_id) == "active",
        seconds,
        f"company {company.slug} is not active",
    )
    company.active_at = len(api.log)


def _member_rows(api: Api, company: Company, who: Person, user_id: str) -> dict[str, list[str]]:
    members = api.call(
        "GET", "/admin/members", who, tenant=company.tenant_id, workspace=company.main
    )
    found = next(m for m in members if m["user_id"] == user_id)
    return {m["workspace_id"]: list(m["role_keys"]) for m in found["memberships"]}


def signed_in(api: Api, company: Company, who: Person) -> None:
    """The person's first sign-in (`GET /auth/bootstrap`), which links an
    invitation and makes them active; their principal kept."""
    company.principals[who.key] = str(api.sign_in(who)["principal_id"])


def principal_of(api: Api, company: Company, who: Person) -> str:
    return company.principals[who.key]


def workspaces(api: Api, company: Company) -> None:
    for name, slug in (("Marketing", "marketing"), ("Sales", "sales")):
        made = api.call(
            "POST",
            "/admin/workspaces",
            company.first,
            expect=201,
            tenant=company.tenant_id,
            workspace=company.main,
            body={"name": name, "slug": slug},
        )
        setattr(company, slug, made["workspace_id"])
    # Each owner places the other, never themself (tenant-rbac/16), keeping
    # what `GET /admin/members` shows of them.
    for placer, placed in ((company.first, company.second), (company.second, company.first)):
        user_id = principal_of(api, company, placed)
        rows = _member_rows(api, company, placer, user_id)
        rows.setdefault(company.marketing, [])
        rows.setdefault(company.sales, [])
        api.call(
            "PUT",
            f"/admin/members/{user_id}/memberships",
            placer,
            tenant=company.tenant_id,
            workspace=company.main,
            body={"memberships": [{"workspace_id": w, "role_keys": k} for w, k in rows.items()]},
        )


def _pending(api: Api, company: Company, who: Person, approval_type: str) -> list[dict[str, Any]]:
    page = api.call(
        "GET",
        "/approvals",
        who,
        tenant=company.tenant_id,
        workspace=company.marketing,
        params={"status": "pending"},
    )
    return [a for a in page["items"] if a["approval_type"] == approval_type]


def _save(api: Api, company: Company, artifact: str, document: dict[str, Any]) -> tuple[str, str]:
    """The draft saved with the ETag of the draft read before it; the saved
    version's id and its ETag."""
    where = {"tenant": company.tenant_id, "workspace": company.marketing}
    draft = api.request("GET", f"/studio/artifacts/{artifact}/draft", company.first, **where)
    if draft.status != 200:
        raise SeedError(f"draft of {artifact}: {draft.status} {draft.body}")
    saved = api.request(
        "PUT",
        f"/studio/artifacts/{artifact}/draft",
        company.first,
        body={"document": document},
        if_match=draft.headers["ETag"],
        **where,
    )
    if saved.status != 200:
        raise SeedError(f"save of {artifact}: {saved.status} {saved.body}")
    return str(saved.body["id"]), saved.headers["ETag"]


def objects(api: Api, company: Company, *, stop_after: Step | None) -> bool:
    """Both objects created, saved and submitted by the first owner, then
    approved by the second and waited on until live. False when the run stops
    after the submit (R1.5, phase one)."""
    where = {"tenant": company.tenant_id, "workspace": company.marketing}
    submitted: list[str] = []
    for api_name, document in ((LEAD, lead_document()), (CAMPAIGN, campaign_document())):
        made = api.call(
            "POST",
            "/studio/artifacts",
            company.first,
            expect=201,
            body={"kind": "object", "api_name": api_name, "labels": [], "document": document},
            **where,
        )
        artifact = str(made["id"])
        company.objects[api_name] = artifact
        if api_name == LEAD:
            # R1.4: a draft saved without a field's `pd_category` is kept; its
            # submit is refused with the field's pointer. Then saved right.
            version, etag = _save(api, company, artifact, lead_document(without_pd="message"))
            refused = api.request(
                "POST",
                f"/studio/objects/{artifact}/versions/{version}/submit",
                company.first,
                if_match=etag,
                **where,
            )
            company.pd_refusal = (refused.status, refused.body)
        version, etag = _save(api, company, artifact, document)
        api.call(
            "POST",
            f"/studio/objects/{artifact}/versions/{version}/submit",
            company.first,
            expect=202,
            if_match=etag,
            **where,
        )
        submitted.append(artifact)
    if stop_after == "object_submit":
        return False
    for approval in _pending(api, company, company.second, "studio.publish.object"):
        api.call(
            "POST",
            f"/approvals/{approval['id']}/decisions",
            company.second,
            body={"approve": True, "comment": "Duyệt phát hành đối tượng của lát thí điểm"},
            **where,
        )
    for api_name in (LEAD, CAMPAIGN):
        _wait(
            lambda n=api_name: (
                api.request("GET", f"/studio/objects/{n}/describe", company.first, **where).status
                == 200
            ),
            PUBLISH_SECONDS,
            f"{api_name} of {company.slug} is not live",
        )
    described = api.call("GET", f"/studio/objects/{LEAD}/describe", company.first, **where)
    company.field_ids = {
        f["api_name"]: str(f["field_id"]) for f in described["fields"] if f.get("field_id")
    }
    return True


def confirm(api: Api, company: Company, proposal: dict[str, Any]) -> dict[str, Any]:
    confirmed: dict[str, Any] = api.call(
        "POST",
        f"/admin/role-changes/{proposal['id']}/confirm",
        company.second,
        tenant=company.tenant_id,
        workspace=company.main,
    )
    return confirmed


def roles(api: Api, company: Company, *, stop_after: Step | None) -> bool:
    """Each role created and filled by the first owner, each change confirmed
    by the second. False when the run stops after the first fill's proposal
    (R1.5, phase two)."""
    where = {"tenant": company.tenant_id, "workspace": company.main}
    for spec in ROLES:
        proposal = api.call(
            "POST",
            "/admin/roles",
            company.first,
            expect=202,
            body={"key": spec.key, "name": spec.name},
            **where,
        )
        confirm(api, company, proposal)
        listed = api.call("GET", "/admin/roles", company.first, **where)
        items = listed["items"] if isinstance(listed, dict) else listed
        role_id = next(str(r["id"]) for r in items if r["key"] == spec.key)
        company.roles[spec.key] = role_id
        detail = api.request("GET", f"/admin/roles/{role_id}", company.first, **where)
        change = api.call(
            "PUT",
            f"/admin/roles/{role_id}/permissions",
            company.first,
            expect=(200, 202),
            if_match=detail.headers["ETag"],
            body=spec.body(company.objects, company.field_ids),
            **where,
        )
        if stop_after == "role_proposal":
            company.pending.append(change["proposal"])
            return False
        if change.get("proposal"):
            confirm(api, company, change["proposal"])
    return True


def invite(
    api: Api, company: Company, who: Person, memberships: Sequence[tuple[str, Sequence[str]]]
) -> None:
    invited = api.call(
        "POST",
        "/admin/invitations",
        company.first,
        expect=(201, 202),
        tenant=company.tenant_id,
        workspace=company.main,
        body={
            "display_name": who.display_name,
            "email": who.email,
            "memberships": [{"workspace_id": w, "role_keys": list(k)} for w, k in memberships],
        },
    )
    for proposal in invited.get("proposals", []):
        confirm(api, company, {"id": proposal})
    signed_in(api, company, who)


def members(api: Api, company: Company, run: str) -> None:
    c = company.key
    people = (
        ("head_1", "Trưởng Marketing 1", [(company.marketing, ["marketing_lead"])]),
        ("head_2", "Trưởng Marketing 2", [(company.marketing, ["marketing_lead"])]),
        ("marketer", "Nhân viên Marketing", [(company.marketing, ["marketing"])]),
        ("sales_c", "Nhân viên Sales C", [(company.sales, ["sales"])]),
        ("sales_d", "Nhân viên Sales D", [(company.sales, ["sales"])]),
        (
            "collaborator",
            "Cộng tác viên Marketing",
            [(company.marketing, ["marketing_collaborator"])],
        ),
    )
    for key, name, memberships in people:
        who = person(key, c, run, name)
        invite(api, company, who, memberships)
        company.members[key] = (who, memberships[0][0])
    # Sales C and D are members of Marketing too, with no role there
    # (record-access R8.5): `POST /admin/invitations` keeps only a workspace
    # with a role, so an owner places them with `role_keys: []`
    # (tenant-rbac/16), their Sales role kept as it is.
    for key in ("sales_c", "sales_d"):
        api.call(
            "PUT",
            f"/admin/members/{company.principals[key]}/memberships",
            company.first,
            tenant=company.tenant_id,
            workspace=company.main,
            body={
                "memberships": [
                    {"workspace_id": company.sales, "role_keys": ["sales"]},
                    {"workspace_id": company.marketing, "role_keys": []},
                ]
            },
        )


def service_account(api: Api, company: Company) -> None:
    where = {"tenant": company.tenant_id, "workspace": company.main}
    head, _ = company.members["head_1"]
    made = api.call(
        "POST",
        "/admin/service-principals",
        company.first,
        expect=201,
        body={
            "name": "Quy trình tiếp nhận lead",
            "owner_user_id": principal_of(api, company, head),
            "owning_workspace_id": company.marketing,
        },
        **where,
    )
    company.service_principal = str(made["id"])
    placed = api.call(
        "PUT",
        f"/admin/members/{company.service_principal}/memberships",
        company.first,
        expect=(200, 202),
        body={"memberships": [{"workspace_id": company.marketing, "role_keys": ["lead_intake"]}]},
        **where,
    )
    for proposal in placed.get("proposals", []):
        confirm(api, company, {"id": proposal})


def limits(api: Api, company: Company, values: Limits) -> None:
    where = {"tenant": company.tenant_id, "workspace": company.main}
    for scope, scope_id, metric, window, value in (
        ("tenant", company.tenant_id, "cost_usd", "month", values.company_cost_usd),
        ("tenant", company.tenant_id, "runs", "day", values.company_runs),
        ("workspace", company.marketing, "cost_usd", "month", values.marketing_cost_usd),
        ("workspace", company.marketing, "runs", "day", values.marketing_runs),
    ):
        api.call(
            "PUT",
            f"/limits/{scope}/{scope_id}/{metric}/{window}",
            company.first,
            body={"kind": "hard", "limit_value": value},
            **where,
        )


# ---- the run ---------------------------------------------------------------------


def seed(
    api: Api,
    operator: Person,
    *,
    prefix: str,
    companies: int = 2,
    limits_of: Limits | None = None,
    stop_after: Step | None = None,
    second_owner_signs_in: bool = True,
    setup_seconds: float = SETUP_SECONDS,
    into: list[Company] | None = None,
) -> list[Company]:
    """Companies `a`, `b`, ... under slugs `<prefix>-a`, ...; each with its
    own people, none a member of two companies. ``into`` keeps each company as
    soon as it exists, for a caller reading a run that stopped with an error."""
    built: list[Company] = [] if into is None else into
    for n in range(companies):
        key = chr(ord("a") + n)
        company = Company(key, f"{prefix}-{key}")
        owners = (
            person("owner_1", key, prefix, "Chủ sở hữu 1"),
            person("owner_2", key, prefix, "Chủ sở hữu 2"),
        )
        create_company(api, operator, company, owners)
        built.append(company)
        activate(
            api, operator, company, second_signs_in=second_owner_signs_in, seconds=setup_seconds
        )
        workspaces(api, company)
        if not objects(api, company, stop_after=stop_after):
            continue
        if not roles(api, company, stop_after=stop_after):
            continue
        members(api, company, prefix)
        service_account(api, company)
        limits(api, company, limits_of or Limits())
    return built


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m marketing_pilot.seed --api-url ... --secret ... --operator-email ...`
    against a running platform whose operator has signed in and been granted."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-url", default=os.environ.get("MP_API_URL", "http://127.0.0.1:8010"))
    parser.add_argument("--secret", default=os.environ.get("DW_API_DEV_SECRET", ""))
    parser.add_argument("--operator-subject", required=True)
    parser.add_argument("--operator-email", required=True)
    parser.add_argument("--prefix", default=f"mp-{secrets.token_hex(3)}")
    parser.add_argument("--companies", type=int, default=2)
    args = parser.parse_args(argv)
    with httpx.Client(timeout=30) as http:
        wait_until_ready(http, args.api_url)
        api = Api(args.api_url, args.secret, http)
        operator = Person("operator", args.operator_subject, args.operator_email, "Người vận hành")
        for company in seed(api, operator, prefix=args.prefix, companies=args.companies):
            print(company.slug, company.tenant_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
