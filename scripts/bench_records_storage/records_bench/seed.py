"""`seed(scale)`: the one seed of ticket 01, reused unchanged by record-access/01.

Deterministic: every value is a hash of a record number and a fixed salt, every
id a pure function (`model.bench_uuid`, `studio.bench_record_id`), so two runs
at one scale write the same rows. The seed is written by `dw_migrator` and is
not part of what is measured; every write the load, the import (R9.10) and
R9.12 make goes through the simulated write path under `dw_app` instead
(`writepath.py`).

T1: `scale.t1_records` records on 50 objects, one in `lead_every` a `mkt_lead`;
`t01` holds a picklist of few values on `mkt_lead` and near-unique e-mails on
`account`; every slot family has NULLs, duplicates and accented Vietnamese.
T2: `scale.t2_records` records, its tenant id chosen to hash into T1's
partition. 98 small tenants spread over every partition.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .ddl import Variant
from .model import (
    ACCOUNT,
    CAMPAIGN,
    KIND_AGENT,
    KIND_FIELD,
    KIND_OBJECT,
    KIND_PERSON,
    KIND_RULE,
    KIND_TEAM,
    KIND_TENANT,
    KIND_WORKSPACE,
    LEAD,
    LEAD_STATUSES,
    PERSON_COMPANY,
    PERSON_OWN,
    PERSON_PUBLIC,
    PERSON_SHARE,
    PERSON_TEAM,
    PERSON_WS1,
    PERSON_WS40,
    ObjectLayout,
    Organisation,
    bench_uuid,
    record_uuid,
    slot_names,
    slots_of,
)
from .scales import Scale

NIL = uuid.UUID(int=0)
SEED = 20261102  # the one salt; changing it is a different seed
BASE_TIME = datetime(2024, 1, 1, tzinfo=UTC)
SPAN_SECONDS = 2 * 365 * 86_400  # records are created over two years

FAMILY_NAMES = (
    "Nguyễn",
    "Trần",
    "Lê",
    "Phạm",
    "Hoàng",
    "Huỳnh",
    "Phan",
    "Vũ",
    "Võ",
    "Đặng",
    "Bùi",
    "Đỗ",
    "Hồ",
    "Ngô",
    "Dương",
    "Lý",
)
MIDDLE_NAMES = ("Văn", "Thị", "Hữu", "Đức", "Minh", "Ngọc", "Thanh", "Quốc")
GIVEN_NAMES = (
    "An",
    "Ánh",
    "Ân",
    "Bình",
    "Đạt",
    "Dũng",
    "Đức",
    "Em",
    "Hà",
    "Hải",
    "Hạnh",
    "Hiếu",
    "Hoa",
    "Hùng",
    "Hương",
    "Khánh",
    "Lan",
    "Linh",
    "Long",
    "Mai",
    "Nam",
    "Nga",
    "Ngân",
    "Phúc",
    "Phương",
    "Quân",
    "Quang",
    "Sơn",
    "Tâm",
    "Thảo",
    "Thắng",
    "Trang",
    "Trung",
    "Tú",
    "Tuấn",
    "Uyên",
    "Vân",
    "Việt",
    "Yến",
)
WORDS = (
    "Hà Nội",
    "Đà Nẵng",
    "Hồ Chí Minh",
    "Cần Thơ",
    "Hải Phòng",
    "Huế",
    "Nha Trang",
    "Biên Hòa",
    "Vũng Tàu",
    "Quy Nhơn",
    "bán lẻ",
    "sản xuất",
    "giáo dục",
    "y tế",
    "tài chính",
    "bất động sản",
    "du lịch",
    "nông nghiệp",
    "vận tải",
    "công nghệ",
)
SOURCES = ("Zalo", "Website", "Hội thảo", "Giới thiệu", "Quảng cáo")


def _sql_array(values: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join("'" + v.replace("'", "''") + "'" for v in values) + "]::text[]"


@dataclass(frozen=True)
class TenantPlan:
    idx: int
    tenant_id: uuid.UUID
    records: int
    objects: int
    people: int
    workspaces: int
    teams: int
    campaign_children: int = 0
    service_account_leads: int = 0
    share_recipient: int = -1
    share_recipient_shares: int = 0
    rule_versions: int = 0

    @property
    def step_ms(self) -> int:
        return max(1, SPAN_SECONDS * 1000 // max(1, self.records))

    def created_ms(self, n: int) -> int:
        return int(BASE_TIME.timestamp() * 1000) + n * self.step_ms

    def record_id(self, n: int) -> uuid.UUID:
        return record_uuid(self.idx, n, self.created_ms(n))

    def object_of(self, n: int) -> int:
        return LEAD if n % 5 == 0 else 1 + n % (self.objects - 1)

    def object_id(self, k: int) -> uuid.UUID:
        return bench_uuid(KIND_OBJECT, self.idx, k)

    def person(self, p: int) -> uuid.UUID:
        return bench_uuid(KIND_PERSON, self.idx, p)

    def team(self, t: int) -> uuid.UUID:
        return bench_uuid(KIND_TEAM, self.idx, t)

    def workspace(self, w: int) -> uuid.UUID:
        return bench_uuid(KIND_WORKSPACE, self.idx, w)

    @property
    def leads(self) -> int:
        return (self.records + 4) // 5

    @property
    def first_campaign(self) -> int:
        """The first record number whose object is mkt_campaign."""
        n = 1
        while self.object_of(n) != CAMPAIGN:
            n += 1
        return n

    @property
    def campaign_span(self) -> int:
        return max(1, min(1000, self.records // (self.objects - 1) - 3))


def access_key(object_id: uuid.UUID, workspace_id: uuid.UUID) -> uuid.UUID:
    return uuid.UUID(hashlib.md5(f"{object_id}/{workspace_id}".encode()).hexdigest())


def _h(n: str, salt: int) -> str:
    return f"abs(hashint8extended({n}, {SEED * 1000 + salt}))"


def generator_sql(plan: TenantPlan, variant: Variant, layouts: list[ObjectLayout]) -> str:
    """SELECT producing the plan's records, one column per target column."""
    families = variant.families
    lead_every = 5
    objm1 = plan.objects - 1
    layout_rows = ", ".join(
        "(" + ", ".join([str(lay.index)] + [str(lay.used.get(f, 0)) for f in families]) + ")"
        for lay in layouts[: plan.objects]
    )
    layout_cols = ", ".join(["obj"] + [f"n_{f}" for f in families])
    layout_used = ", ".join(f"layout.n_{f}" for f in families)
    statuses = _sql_array(LEAD_STATUSES)
    words = _sql_array(WORDS)
    fam_names, mid_names, giv_names = (
        _sql_array(FAMILY_NAMES),
        _sql_array(MIDDLE_NAMES),
        _sql_array(GIVEN_NAMES),
    )
    sources = _sql_array(SOURCES)
    near_unique = max(1, int(plan.records * 0.98))
    created = (
        f"(timestamptz '{BASE_TIME.isoformat()}' + (n * {plan.step_ms}) * interval '1 millisecond')"
    )

    def ref_account(x: str) -> str:
        # A record of `account` near x/2: number b with b % objm1 == ACCOUNT - 1
        # and b % 5 <> 0, so object_of(b) == ACCOUNT.
        b = f"(({x}) / 2 - (({x}) / 2) % {objm1} + {ACCOUNT - 1})"
        b = f"(CASE WHEN {b} % {lead_every} = 0 THEN {b} + {objm1} ELSE {b} END)"
        return (
            f"studio.bench_record_id({plan.idx}, {b}, timestamptz '{BASE_TIME.isoformat()}'"
            f" + ({b} * {plan.step_ms}) * interval '1 millisecond')"
        )

    def ref_campaign(j: str) -> str:
        nc = f"(({j}) * {objm1})"
        return (
            f"studio.bench_record_id({plan.idx}, {nc}, timestamptz '{BASE_TIME.isoformat()}'"
            f" + ({nc} * {plan.step_ms}) * interval '1 millisecond')"
        )

    first_campaign = ref_campaign(str(plan.first_campaign // objm1))
    slot_exprs: list[str] = []
    salt = 100
    for fam, (_sql_type, count) in families.items():
        for j, slot in enumerate(slot_names(fam, count), start=1):
            salt += 1
            h = _h("n", salt)
            used = f"n_{fam} >= {j}"
            if fam == "t" and j == 1:
                value = (
                    f"CASE WHEN obj = {LEAD} THEN CASE WHEN {h} % 33 = 0 THEN NULL"
                    f" ELSE ({statuses})[1 + {h} % {len(LEAD_STATUSES)}] END"
                    f" WHEN obj = {ACCOUNT} THEN CASE WHEN {h} % 50 = 0 THEN NULL"
                    f" ELSE 'kh' || (n % {near_unique}) || '@vi-du.vn' END"
                    f" ELSE CASE WHEN {h} % 10 = 0 THEN NULL"
                    f" ELSE ({words})[1 + {h} % {len(WORDS)}] || ' ' || ({h} / 97) % 500 END END"
                )
            elif fam == "t":
                value = (
                    f"CASE WHEN {h} % 10 = 0 THEN NULL"
                    f" ELSE ({words})[1 + {h} % {len(WORDS)}] || ' ' || ({h} / 97) % 500 END"
                )
            elif fam == "u":
                value = (
                    f"CASE WHEN {h} % 5 = 0 THEN NULL ELSE '{slot}-' || {plan.idx} || '-' || n END"
                )
            elif fam == "i":
                value = f"CASE WHEN {h} % 10 = 0 THEN NULL ELSE ({h} / 10) % 1000000 END"
            elif fam == "f":
                value = f"CASE WHEN {h} % 10 = 0 THEN NULL ELSE (({h} / 10) % 10000000) / 100.0 END"
            elif fam == "d":
                value = (
                    f"CASE WHEN {h} % 10 = 0 THEN NULL"
                    f" ELSE date '2018-01-01' + (({h} / 10) % 3000)::int END"
                )
            elif fam == "z":
                value = (
                    f"CASE WHEN {h} % 10 = 0 THEN NULL ELSE timestamptz '2020-01-01 00:00:00+00'"
                    f" + (({h} / 10) % 157680000) * interval '1 second' END"
                )
            elif fam == "b":
                value = f"CASE WHEN {h} % 10 = 0 THEN NULL ELSE ({h} / 10) % 2 = 0 END"
            elif fam == "l":
                value = f"CASE WHEN {h} % 10 = 0 THEN NULL ELSE {ref_account('n')} END"
            else:  # m: a lead's campaign; T1's first campaign holds the children of R9.12
                jc = f"(2 + {h} % {plan.campaign_span})"
                other_campaign = f"{jc} + ({jc} % {lead_every} = 0)::int"
                value = (
                    f"CASE WHEN obj = {LEAD} AND n / {lead_every} < {plan.campaign_children}"
                    f" THEN {first_campaign}"
                    f" WHEN {h} % 4 = 0 THEN NULL"
                    f" ELSE {ref_campaign(other_campaign)} END"
                )
            slot_exprs.append(f"CASE WHEN {used} THEN {value} END AS {slot}")

    hown, hname, hshare, hrule = _h("n", 1), _h("n", 2), _h("n", 3), _h("n", 4)
    svc_from = plan.leads - plan.service_account_leads
    share_from = plan.campaign_children
    share_to = plan.campaign_children + (
        plan.share_recipient_shares if plan.share_recipient >= 0 else 0
    )
    owner_kind = (
        f"CASE WHEN obj = {LEAD} AND n / {lead_every} >= {svc_from} AND"
        f" {plan.service_account_leads} > 0"
        f" THEN 'user' WHEN {hown} % 20 = 0 THEN 'team' ELSE 'user' END"
    )
    owner_no = (
        f"CASE WHEN obj = {LEAD} AND n / {lead_every} >= {svc_from} AND"
        f" {plan.service_account_leads} > 0"
        f" THEN {plan.people} WHEN {hown} % 20 = 0 THEN ({hown} / 20) % {plan.teams}"
        f" ELSE {hown} % {plan.people} END"
    )
    grants = ""
    if variant.w2:
        recipient = (
            f"CASE WHEN obj = {LEAD} AND n / {lead_every} >= {share_from} AND n / {lead_every} <"
            f" {share_to}"
            f" THEN studio.bench_uuid({KIND_PERSON}, {plan.idx}, {max(plan.share_recipient, 0)})"
            " END"
        )
        manual = (
            f"CASE WHEN {hshare} % 1000 < 4 OR (obj = {LEAD} AND {hshare} % 100 < 5)"
            f" THEN studio.bench_uuid({KIND_PERSON}, {plan.idx}, ({hshare} / 1000) %"
            f" {plan.people}) END"
        )
        rule = (
            f"CASE WHEN obj = {LEAD} AND {plan.rule_versions} > 0 AND {hrule} % 10 = 0"
            f" THEN studio.bench_uuid({KIND_RULE}, {plan.idx}, ({hrule} / 10) %"
            f" {max(plan.rule_versions, 1)}) END"
        )
        grants = (
            f",\n    array_remove(array_remove(array_remove(ARRAY[{recipient}, {manual}, {rule}],"
            f" NULL), NULL), NULL)::uuid[] AS read_grants"
        )
    slots_sql = ",\n    ".join(slot_exprs)
    return f"""
SELECT
    studio.bench_record_id({plan.idx}, n, created) AS id,
    '{plan.tenant_id}'::uuid AS tenant_id,
    studio.bench_uuid({KIND_OBJECT}, {plan.idx}, obj) AS object_id,
    CASE WHEN owner_no = {plan.people} AND owner_kind = 'user'
         THEN studio.bench_uuid({KIND_WORKSPACE}, {plan.idx}, 0)
         ELSE studio.bench_uuid({KIND_WORKSPACE}, {plan.idx}, owner_no % {plan.workspaces})
    END AS workspace_id,
    owner_kind,
    CASE WHEN owner_kind = 'team' THEN studio.bench_uuid({KIND_TEAM}, {plan.idx}, owner_no)
         ELSE studio.bench_uuid({KIND_PERSON}, {plan.idx}, owner_no) END AS owner_id,
    ({fam_names})[1 + {hname} % {len(FAMILY_NAMES)}] || ' '
        || ({mid_names})[1 + ({hname} / 16) % {len(MIDDLE_NAMES)}] || ' '
        || ({giv_names})[1 + ({hname} / 128) % {len(GIVEN_NAMES)}] AS name,
    jsonb_build_object('f90', 'ghi chú ' || ({words})[1 + {hname} % {len(WORDS)}],
                       'f91', {hname} % 1000, 'diem_ai', 0,
                       'nguon', ({sources})[1 + {hshare} % {len(SOURCES)}]) AS data,
    {slots_sql}{grants},
    created AS created_at,
    studio.bench_uuid({KIND_PERSON}, {plan.idx}, owner_no % {plan.people}) AS created_by,
    created AS updated_at,
    studio.bench_uuid({KIND_PERSON}, {plan.idx}, owner_no % {plan.people}) AS updated_by
FROM (
    SELECT n, obj, {created} AS created, {owner_kind} AS owner_kind, {owner_no} AS owner_no,
           {layout_used}
    FROM (SELECT n, CASE WHEN n % {lead_every} = 0 THEN {LEAD} ELSE 1 + n % {objm1} END AS obj
          FROM generate_series(0::bigint, {plan.records - 1}::bigint) AS n) s
    JOIN (VALUES {layout_rows}) AS layout({layout_cols}) USING (obj)
) g
"""


def generated_columns(variant: Variant) -> list[str]:
    cols = [
        "id",
        "tenant_id",
        "object_id",
        "workspace_id",
        "owner_kind",
        "owner_id",
        "name",
        "data",
    ]
    cols += [s for s, _f, _t in (variant.slots or _pivot_slots(variant))]
    if variant.w2:
        cols.append("read_grants")
    return [*cols, "created_at", "created_by", "updated_at", "updated_by"]


def _pivot_slots(variant: Variant) -> list[tuple[str, str, str]]:
    return slots_of(variant.families)


# --------------------------------------------------------------- the facts --
@dataclass
class Profile:
    """A read profile: one real principal of the seed and the object it pages."""

    name: str
    tenant_idx: int
    principal: uuid.UUID
    actor_kind: str
    object_index: int
    order: str = "created"  # created | updated | name | slot
    note: str = ""


@dataclass
class SeedFacts:
    scale: Scale
    plans: list[TenantPlan]
    layouts: list[ObjectLayout]
    org: Organisation
    profiles: list[Profile] = field(default_factory=list)
    scopes: list[tuple[uuid.UUID, uuid.UUID, str, str, list[uuid.UUID]]] = field(
        default_factory=list
    )
    writer: uuid.UUID = NIL
    t2_reader: uuid.UUID = NIL
    shape: dict[str, Any] = field(default_factory=dict)

    @property
    def t1(self) -> TenantPlan:
        return self.plans[0]

    @property
    def t2(self) -> TenantPlan:
        return self.plans[1]

    def campaign_id(self) -> uuid.UUID:
        return self.t1.record_id(self.t1.first_campaign)


def tenant_plans(scale: Scale, t2_id: uuid.UUID, small_ids: list[uuid.UUID]) -> list[TenantPlan]:
    t1 = TenantPlan(
        idx=0,
        tenant_id=bench_uuid(KIND_TENANT, 0, 0),
        records=scale.t1_records,
        objects=scale.objects,
        people=scale.people,
        workspaces=scale.workspaces,
        teams=scale.teams,
        campaign_children=scale.campaign_children,
        service_account_leads=scale.service_account_leads,
        share_recipient=PERSON_SHARE,
        share_recipient_shares=scale.share_recipient_shares,
        rule_versions=scale.sharing_rule_versions,
    )
    t2 = TenantPlan(1, t2_id, scale.t2_records, scale.objects, 50, 5, 5)
    smalls = [
        TenantPlan(2 + i, tid, scale.small_tenant_records, 3, 10, 2, 1)
        for i, tid in enumerate(small_ids)
    ]
    return [t1, t2, *smalls]


def candidate_ids(tenant_idx: int, count: int) -> list[uuid.UUID]:
    return [bench_uuid(KIND_TENANT, tenant_idx, j) for j in range(count)]


def profiles_and_scopes(facts: SeedFacts, variant: Variant) -> None:
    """The read profiles of ticket 01 step 4 and the arrays each principal holds."""
    t1, org = facts.t1, facts.org
    all_objects = [t1.object_id(k) for k in range(t1.objects)]
    lead = t1.object_id(LEAD)
    tid = t1.tenant_id
    scopes = facts.scopes

    def put(
        principal: uuid.UUID, action: str, arm: str, ids: list[uuid.UUID], tenant: uuid.UUID = tid
    ) -> None:
        scopes.append((tenant, principal, action, arm, ids))

    def keys(workspaces: set[int]) -> list[uuid.UUID]:
        return [access_key(o, t1.workspace(w)) for o in all_objects for w in sorted(workspaces)]

    def own_everywhere(p: uuid.UUID) -> None:
        put(p, "read", "objects:own", all_objects)

    profiles = facts.profiles
    # Của tôi
    own = t1.person(PERSON_OWN)
    own_everywhere(own)
    profiles += [
        Profile("own", 0, own, "user", LEAD),
        Profile(
            "own_sort_slot", 0, own, "user", LEAD, order="slot", note="sắp theo slot t02, tầm hẹp"
        ),
    ]
    # Của nhóm tôi
    team_member = t1.person(PERSON_TEAM)
    own_everywhere(team_member)
    team_no = PERSON_TEAM % org.teams
    closure = [t1.team(team_no)] + [t1.person(p) for p in org.team_members(team_no)]
    put(team_member, "read", "owners:team", closure)
    profiles += [
        Profile("team", 0, team_member, "user", LEAD),
        Profile(
            "team_sort_slot",
            0,
            team_member,
            "user",
            LEAD,
            order="slot",
            note="sắp theo slot t02, tầm hẹp",
        ),
    ]
    # Workspace của tôi, một workspace
    ws1 = t1.person(PERSON_WS1)
    put(ws1, "read", "keys", keys({org.leaf_workspace()}))
    profiles.append(Profile("workspace_1", 0, ws1, "user", LEAD))
    # Workspace của tôi và cấp dưới, 40 workspace
    ws40 = t1.person(PERSON_WS40)
    root40 = org.workspace_near(40)
    sub40 = org.workspace_subtree(root40)
    put(ws40, "read", "keys", keys(sub40))
    profiles.append(Profile("workspace_40", 0, ws40, "user", LEAD, note=f"{len(sub40)} workspace"))
    # Toàn công ty
    company = t1.person(PERSON_COMPANY)
    put(company, "read", "objects:tenant", all_objects)
    profiles += [
        Profile("company", 0, company, "user", LEAD),
        Profile(
            "company_updated", 0, company, "user", LEAD, order="updated", note="trang mới cập nhật"
        ),
        Profile(
            "company_name",
            0,
            company,
            "user",
            LEAD,
            order="name",
            note='ORDER BY name "vi-VN-x-icu"',
        ),
    ]
    # public_read trên mkt_lead: một người chỉ có Của tôi, lead mở đọc toàn tenant
    public = t1.person(PERSON_PUBLIC)
    own_everywhere(public)
    put(public, "read", "objects:tenant", [lead])
    profiles.append(Profile("public_read", 0, public, "user", LEAD))
    # Quản lý có 50, 500, 5.000 cấp dưới
    for name, manager in (
        ("manager_50", org.M50),
        ("manager_500", org.M500),
        ("manager_5000", org.M5000),
    ):
        m = t1.person(manager)
        own_everywhere(m)
        subs = org.subordinates(manager)
        put(m, "read", "owners:subordinate", [t1.person(p) for p in sorted(subs)])
        profiles.append(Profile(name, 0, m, "user", LEAD, note=f"{len(subs)} cấp dưới"))
    # Người nhận 500 chia sẻ
    recipient = t1.person(PERSON_SHARE)
    own_everywhere(recipient)
    put(recipient, "read", "grants", [recipient])
    profiles.append(Profile("share_recipient", 0, recipient, "user", LEAD))
    # Agent có giới hạn dữ liệu một đối tượng
    agent = bench_uuid(KIND_AGENT, 0, 1)
    put(agent, "read", "objects:tenant", [lead])
    profiles.append(Profile("agent_one_object", 0, agent, "agent", LEAD))
    # Tài khoản dịch vụ sở hữu 10^6 lead
    svc = t1.person(org.service_account)
    own_everywhere(svc)
    profiles.append(Profile("service_account", 0, svc, "user", LEAD))
    # The writer: the AI scoring flow and the import run as the service account,
    # tenant-wide update and create (actor `workflow` where W2 admits it).
    facts.writer = svc
    for action in ("read", "update", "create", "delete"):
        put(svc, action, "objects:tenant", all_objects)
    # T2's reader (R9.9), Toàn công ty in T2.
    t2 = facts.t2
    reader = t2.person(0)
    put(
        reader,
        "read",
        "objects:tenant",
        [t2.object_id(k) for k in range(t2.objects)],
        tenant=t2.tenant_id,
    )
    facts.t2_reader = reader


def writer_actor_kind(variant: Variant) -> str:
    # W1's policy admits people only (record-access/03 step 4).
    return "workflow" if variant.w2 else "user"


def field_rows(
    plan: TenantPlan, layouts: list[ObjectLayout], variant: Variant
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    type_of = {
        "t": "text",
        "u": "text",
        "i": "number",
        "f": "number",
        "d": "date",
        "z": "datetime",
        "b": "boolean",
        "l": "lookup",
        "m": "master_detail",
    }
    creator = plan.person(0)
    for lay in layouts[: plan.objects]:
        field_no = 1
        for slot in lay.used_slots(variant.families):
            rows.append(
                (
                    plan.tenant_id,
                    field_id(plan, lay.index, slot),
                    plan.object_id(lay.index),
                    f"f_{slot}",
                    type_of[slot[0]],
                    "slot",
                    slot,
                    field_no,
                    creator,
                    creator,
                )
            )
            field_no += 1
        for key in ("f90", "f91", "diem_ai", "nguon"):
            rows.append(
                (
                    plan.tenant_id,
                    bench_uuid(KIND_FIELD, plan.idx, lay.index * 1000 + 900 + field_no),
                    plan.object_id(lay.index),
                    key,
                    "text",
                    "data",
                    None,
                    field_no,
                    creator,
                    creator,
                )
            )
            field_no += 1
    return rows


def field_id(plan: TenantPlan, object_index: int, slot: str) -> uuid.UUID:
    fam_no = "tuifdzblm".index(slot[0])
    return bench_uuid(KIND_FIELD, plan.idx, object_index * 1000 + fam_no * 100 + int(slot[1:]))
