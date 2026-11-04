# ruff: noqa: TID252  (relative: `records_bench` is reachable only through its own directory)
"""record-access/01: the policy variants, their declared replacement and the self-checks of step 7.

What runs here needs no database: the DDL each variant renders, the static half
of the catalog check, the array comparison, the winner rule and the exit code.
The database half (a session with no tenant, a stale epoch, an expired share)
runs in every cell of `make bench-record-access` and is recorded in the ticket.
"""

from __future__ import annotations

import random
import re
import uuid
from datetime import UTC, datetime

import pytest

from ..ddl import TENANT, VARIANTS, partitions
from ..ddl import record_policies as harness_policies
from ..model import LEAD, object_layouts, organisation
from ..policy import checks, measure, variants
from ..policy.run import choose_winner, expected_cells
from ..policy.variants import AXES, P0, POLICY_VARIANTS, combination, declared, schema
from ..report import READ_PROFILES, Report, Row
from ..scales import TINY
from ..seed import SeedFacts, profiles_and_scopes, tenant_plans

pytestmark = pytest.mark.unit
Catalog = dict[checks.CatalogKey, str]

MODULUS = 8


def _facts() -> SeedFacts:
    t2 = uuid.UUID(int=2)
    small = [uuid.UUID(int=10 + i) for i in range(TINY.small_tenants)]
    facts = SeedFacts(
        scale=TINY,
        plans=tenant_plans(TINY, t2, small),
        layouts=object_layouts(TINY.objects),
        org=organisation(TINY),
    )
    profiles_and_scopes(facts, VARIANTS["A1"])
    return facts


# ---------------------------------------------------------------- the DDL --
@pytest.mark.parametrize("name", list(POLICY_VARIANTS))
def test_every_variant_keeps_a1s_restrictive_tenant_policy(name: str) -> None:
    """The cross-tenant check's structural half: the RESTRICTIVE policy is A1's, word for word."""
    variant = POLICY_VARIANTS[name]
    for table in ["studio.records", *partitions("studio.records", MODULUS)]:
        short = table.split(".")[1]
        ours = variants.record_policies(table, short, variant)[0]
        a1 = next(s for s in harness_policies(table, short, True) if "AS RESTRICTIVE" in s)
        assert ours == a1
        assert f"USING ({TENANT}) WITH CHECK ({TENANT})" in ours


@pytest.mark.parametrize("name", list(POLICY_VARIANTS))
def test_the_share_arm_honours_grants_valid_until(name: str) -> None:
    variant = POLICY_VARIANTS[name]
    for action in ("read", "update"):
        text = variants.reach(action, variant)
        grants = [line for line in text.splitlines() if "_grants" in line]
        assert grants, f"{action} has no share arm"
        assert all(variants.NOT_EXPIRED in line for line in grants)
    assert variants.NOT_EXPIRED == "(grants_valid_until IS NULL OR grants_valid_until > now())"


def test_every_policy_variant_is_built_on_a1() -> None:
    assert {v.base for v in POLICY_VARIANTS.values()} == {"A1"}
    assert combination({"K": "K"}).base == "A1"


@pytest.mark.parametrize("name", list(POLICY_VARIANTS))
def test_the_acl_functions_are_stable_invoker_with_a_fixed_search_path(name: str) -> None:
    for fn in variants.acl_functions(POLICY_VARIANTS[name]):
        assert "LANGUAGE sql STABLE SET search_path = pg_catalog" in fn
        assert "SECURITY DEFINER" not in fn
        if "principal_scopes" in fn:
            # A missing row, a stale row or another epoch reads as nothing.
            assert "s.state = 'valid'" in fn
            assert "s.epoch = (SELECT e.epoch FROM studio.access_epochs e" in fn
            assert "coalesce(" in fn


@pytest.mark.parametrize("name", list(POLICY_VARIANTS))
def test_the_door_publishes_only_from_the_version_it_started_on(name: str) -> None:
    text = variants.ensure_function(POLICY_VARIANTS[name])
    assert "SECURITY DEFINER SET search_path = pg_catalog" in text
    assert "WHERE s.version = v0;" in text
    assert "IF ok THEN RETURN; END IF;" in text
    assert "version = version + 1" in variants.TRIGGERS


def test_the_door_runs_in_every_scoped_transaction() -> None:
    assert variants.door_sql().endswith("studio.ensure_principal_scope()")
    assert str(variants.AGENT_BOUNDARY) in variants.door_sql()


def test_only_the_door_assign_and_share_are_granted_to_dw_app() -> None:
    granted = [s for s in schema(P0, MODULUS) if s.startswith("GRANT EXECUTE")]
    assert sorted(re.findall(r"studio\.(\w+)\(", " ".join(granted))) == [
        "assign_record",
        "ensure_principal_scope",
        "share_record",
    ]


def test_the_row_ledger_has_one_row_per_principal_and_one_array_per_action_and_arm() -> None:
    ddl = variants.ledger_ddl(P0)[0]
    assert "PRIMARY KEY (tenant_id, principal_id)" in ddl
    for action, arms in variants.ARMS_OF.items():
        for arm in arms:
            assert f"{action}_{arm} " in ddl
    per_action = variants.ledger_ddl(AXES["L"])[0]
    assert "PRIMARY KEY (tenant_id, principal_id, action)" in per_action


def test_the_key_axis_keys_are_bigint_and_p0s_are_uuid() -> None:
    assert "access_key = ANY ((SELECT studio.acl_keys('read'))::uuid[])" in variants.reach(
        "read", P0
    )
    k = AXES["K"]
    assert "access_key = ANY ((SELECT studio.acl_keys('read'))::bigint[])" in variants.reach(
        "read", k
    )
    assert "ALTER TABLE studio.records ADD COLUMN access_key bigint" in schema(k, MODULUS)


def test_the_exists_axis_joins_the_ledger_and_reads_no_bound_array() -> None:
    text = variants.reach("read", AXES["E"])
    assert "EXISTS (SELECT 1 FROM studio.principal_scopes s" in text
    assert "acl_objects" not in text
    assert "acl_boundary" in text  # the boundary stays outside the join


_CREATES = (
    (r"CREATE (?:UNIQUE )?INDEX (\w+) ON ([\w.]+)", lambda m: ("index", m[2], m[1])),
    (r"CREATE TABLE ([\w.]+)", lambda m: ("table", m[1])),
    (r"CREATE FUNCTION studio\.(\w+)\(", lambda m: ("function", m[1])),
    (r"CREATE TRIGGER (\w+) [^;]*? ON ([\w.]+)", lambda m: ("trigger", m[2], m[1])),
    (r"CREATE POLICY (\w+) ON ([\w.]+)", lambda m: ("policy", m[2], m[1])),
    (r"ALTER TABLE ([\w.]+) ADD COLUMN (\w+)", lambda m: ("column", m[1], m[2])),
)


def created_objects(statements: list[str]) -> set[tuple[str, ...]]:
    out: set[tuple[str, ...]] = set()
    for statement in statements:
        for pattern, key in _CREATES:
            for m in re.finditer(pattern, statement, re.DOTALL):
                out.add(key(m))
    return out


@pytest.mark.parametrize("name", [*POLICY_VARIANTS, "W"])
def test_a_variant_creates_nothing_outside_its_declared_replacement(name: str) -> None:
    """The static half of the catalog check: an index outside the declaration fails here first."""
    variant = POLICY_VARIANTS.get(name) or combination({a: a for a in AXES})
    made = created_objects(schema(variant, MODULUS) + variants.post_load(variant))
    allowed = declared(variant, MODULUS)
    restrictive = {
        ("policy", t, f"tenant_isolation_{t.split('.')[1]}")
        for t in ["studio.records", *partitions("studio.records", MODULUS)]
    }
    outside = {k for k in made if not variants.is_declared(k, allowed)} - restrictive
    assert outside == set()


# ---------------------------------------------------------- catalog diff --
def test_the_catalog_diff_fails_what_was_not_declared() -> None:
    reference: Catalog = {
        ("index", "studio.records", "ix_records_t01"): "CREATE INDEX ...",
        ("column", "studio.records", "read_grants"): "uuid[]",
        ("policy", "studio.records", "record_access_records_select"): "PERMISSIVE a",
        ("policy", "studio.records", "tenant_isolation_records"): "RESTRICTIVE t",
    }
    allowed = declared(P0, MODULUS)
    same_but_reach: Catalog = {
        **reference,
        ("policy", "studio.records", "record_access_records_select"): "PERMISSIVE b",
        ("table", "studio.principal_scopes"): "r",
        ("column", "studio.principal_scopes", "read_keys"): "uuid[]",
    }
    assert checks.catalog_diff(reference, same_but_reach, allowed) == []
    extra_index: Catalog = {**reference, ("index", "studio.records", "ix_records_extra"): "CREATE"}
    assert checks.catalog_diff(reference, extra_index, allowed) == [
        "thêm ngoài phần thay đã khai: index studio.records ix_records_extra"
    ]
    on_a0: Catalog = {k: v for k, v in reference.items() if k[-1] != "read_grants"}
    assert checks.catalog_diff(reference, on_a0, allowed) == [
        "thiếu so với A1: column studio.records read_grants"
    ]
    no_tenant: Catalog = {
        **reference,
        ("policy", "studio.records", "tenant_isolation_records"): "x",
    }
    assert len(checks.catalog_diff(reference, no_tenant, allowed)) == 1
    crossing = checks.restrictive_differs(reference, no_tenant, 1)
    assert "policy RESTRICTIVE tenant của studio.records khác A1: x" in crossing
    assert checks.restrictive_differs(reference, reference, 1) == [
        "policy RESTRICTIVE tenant của studio.records_p0 khác A1: None"
    ]


def test_the_key_column_may_differ_only_on_the_key_axis() -> None:
    reference: Catalog = {("column", "studio.records", "access_key"): "uuid gen=s"}
    cell: Catalog = {("column", "studio.records", "access_key"): "bigint gen="}
    assert checks.catalog_diff(reference, cell, declared(AXES["K"], MODULUS)) == []
    assert checks.catalog_diff(reference, cell, declared(P0, MODULUS)) != []


# ---------------------------------------------------------------- arrays --
def test_the_door_reach_must_equal_the_harness_arrays() -> None:
    expected = [("p", "read", "objects_tenant", ["a", "b"]), ("p", "read", "grants", ["p"])]
    ok = {("p", "read", "objects_tenant"): ["b", "a"], ("p", "read", "grants"): ["p"]}
    assert checks.compare_arrays(expected, ok, set()).failures == []
    short = {**ok, ("p", "read", "objects_tenant"): ["a"]}
    assert checks.compare_arrays(expected, short, set()).failures
    wide = {**ok, ("p", "read", "objects_tenant"): ["a", "b", "c"]}
    assert checks.compare_arrays(expected, wide, set()).failures


def test_extra_grant_keys_pass_only_while_no_record_carries_them() -> None:
    expected = [("p", "read", "grants", ["p"])]
    computed = {("p", "read", "grants"): ["p", "team"], ("p", "update", "objects_own"): ["x"]}
    result = checks.compare_arrays(expected, computed, carried_grants={"p", "rule"})
    assert result.failures == []
    assert any("grants" in e for e in result.extras)
    assert any("update objects_own" in e for e in result.extras)
    carried = checks.compare_arrays(expected, computed, carried_grants={"team"})
    assert carried.failures


def test_the_public_principal_is_compared_only_where_its_object_is_public_read() -> None:
    facts = _facts()
    public = next(p for p in facts.profiles if p.name == "public_read").principal
    private = checks.expected_arrays(facts, "private", public)
    opened = checks.expected_arrays(facts, "public_read", public)
    assert str(public) not in {e[0] for e in private}
    assert {e[0] for e in opened} == {str(public)}
    assert ("objects_tenant", [str(facts.t1.object_id(LEAD))]) in [(e[2], e[3]) for e in opened]


def test_the_key_axis_compares_bigint_keys() -> None:
    facts = _facts()
    public = next(p for p in facts.profiles if p.name == "public_read").principal
    harness = [e for e in checks.expected_arrays(facts, "private", public) if e[2] == "keys"]
    assert harness
    mapping = {k: "9" for e in harness for k in e[3]}
    as_bigint = [
        e for e in checks.expected_arrays(facts, "private", public, mapping) if e[2] == "keys"
    ]
    assert all(set(e[3]) == {"9"} for e in as_bigint)


# ------------------------------------------------------------------ reads --
def _reader(name: str) -> measure.Reader:
    facts = _facts()
    return measure.Reader(
        POLICY_VARIANTS[name],
        facts,
        [(datetime(2024, 1, 1, tzinfo=UTC), facts.t1.record_id(1))],
        {p.name: [facts.t1.record_id(1)] for p in facts.profiles},
    )


def test_the_own_filter_is_a_parameter_except_on_the_hint_axis() -> None:
    p0, h = _reader("P0"), _reader("H")
    own = next(p for p in p0.facts.profiles if p.name == "own")
    company = next(p for p in p0.facts.profiles if p.name == "company")
    rng = random.Random(1)
    sql, args = p0.query(own, "page_lead", rng)
    assert "AND owner_id = $3" in sql and args[-1] == own.principal
    sql, args = h.query(own, "page_lead", rng)
    assert "AND owner_id = (SELECT studio.acl_user())" in sql and len(args) == 2
    sql, _args = p0.query(company, "page_lead", rng)
    assert "owner_id" not in sql
    sql, _args = p0.query(own, "next", rng)
    assert "(created_at, id) < ($3, $4)" in sql and "owner_id = $5" in sql


def test_each_read_kind_reads_what_step_5_names() -> None:
    reader = _reader("P0")
    company = next(p for p in reader.facts.profiles if p.name == "company")
    rng = random.Random(2)
    filtered, args = reader.query(company, "page_other_f", rng)
    assert measure.SLOT_FILTER in filtered and args[1] == reader.facts.t1.object_id(measure.OTHER)
    plain, _ = reader.query(company, "page_lead", rng)
    assert measure.SLOT_FILTER not in plain
    count, _ = reader.query(company, "count", rng)
    assert "LIMIT 1001" in count


def test_the_agent_runs_as_the_company_person() -> None:
    facts = _facts()
    profiles = measure.policy_profiles(facts)
    agent = next(p for p in profiles if p.name == "agent_one_object")
    company = next(p for p in profiles if p.name == "company")
    assert agent.principal == company.principal and agent.actor_kind == "agent"


# --------------------------------------------------------------- winners --
def _report_with(worst: dict[str, float], verdict: dict[str, str]) -> Report:
    report = Report("tiny", [], [MODULUS])
    for name, value in worst.items():
        report.rows.append(
            Row(
                "record-access:R9.1",
                "page_lead_warm:own",
                name,
                MODULUS,
                value,
                "ms",
                "page_p95_ms",
                1000,
                verdict=verdict[name],
            )
        )
    return report


def test_the_axis_winner_is_the_passing_one_with_the_lower_worst_page() -> None:
    report = _report_with({"P0": 40.0, "K": 20.0}, {"P0": "đạt", "K": "đạt"})
    assert choose_winner(report, "K", MODULUS)[0] == "K"
    report = _report_with({"P0": 40.0, "K": 20.0}, {"P0": "đạt", "K": "trượt"})
    assert choose_winner(report, "K", MODULUS)[0] == "P0"


def test_under_ten_percent_apart_p0_is_kept() -> None:
    report = _report_with({"P0": 100.0, "L": 91.0}, {"P0": "trượt", "L": "trượt"})
    assert choose_winner(report, "L", MODULUS)[0] == "P0"
    report = _report_with({"P0": 100.0, "L": 89.0}, {"P0": "trượt", "L": "trượt"})
    assert choose_winner(report, "L", MODULUS)[0] == "L"


def test_the_combination_switches_only_the_winning_axes() -> None:
    w = combination({"K": "P0", "L": "L", "E": "P0", "H": "H"})
    assert w.options() == {"key": "uuid", "ledger": "action", "arms": "array", "hint": True}
    assert combination(dict.fromkeys(AXES, "P0")).options() == P0.options()


# ------------------------------------------------------------- exit code --
def _complete_report() -> Report:
    report = Report("tiny", [], [MODULUS])
    for name in ("P0", *AXES):
        report.policy_cells += expected_cells(name, MODULUS, soak=name == "P0")
    for metric, name, modulus in report.policy_cells:
        report.add(Row("x", metric, name, modulus, 1.0, "s", "page_p95_ms", 1000))
    return report


def test_a_complete_policy_run_exits_zero_even_when_a_threshold_misses() -> None:
    report = _complete_report()
    assert report.exit_code() == 0
    missed = Report("tiny", [], [MODULUS], thresholds={**report.thresholds})
    missed.thresholds["page_p95_ms"] = ("<=", 0.0, "R9.1")
    missed.policy_cells = report.policy_cells
    for r in report.rows:
        missed.add(
            Row(r.req, r.metric, r.variant, r.modulus, r.value, r.unit, r.threshold_key, 1000)
        )
    assert missed.exit_code() == 0
    assert all(r.verdict == "trượt" for r in missed.rows)


def test_a_policy_cell_without_its_numbers_exits_non_zero() -> None:
    report = _complete_report()
    report.rows = [r for r in report.rows if r.variant != "K"]
    assert report.exit_code() == 1
    assert any("của K" in p for p in report.problems())


def test_a_failed_self_check_exits_non_zero() -> None:
    report = _complete_report()
    report.check_failures.append("P0 m8: dòng của T2 xuất hiện trong phiên của T1")
    assert report.exit_code() == 1


def test_the_matrix_names_every_profile_kind_and_temperature() -> None:
    metrics = measure.cell_metrics(list(READ_PROFILES), soak=True)
    assert len([m for m in metrics if ":" in m and not m.startswith("scope")]) == (
        len(READ_PROFILES) * len(measure.KINDS) * 2
    )
    assert "write_update_slot_soak" in metrics and "stale_reads_after_revoke" in metrics
    assert "write_update_slot_soak" not in measure.cell_metrics(list(READ_PROFILES), soak=False)


def test_profile_grants_give_each_profile_exactly_its_harness_depth() -> None:
    from ..policy.inputs import profile_grants

    facts = _facts()
    grants = profile_grants(facts)
    t1, org = facts.t1, facts.org
    company = t1.person(4_567)
    held = {(g[2].rsplit(".", 1)[1], g[3]) for g in grants if g[1] == company}
    assert held == {("read", "tenant"), ("assign", "tenant"), ("share", "tenant")}
    ws40 = {g[4] for g in grants if g[1] == t1.person(3_456)}
    assert ws40 == {t1.workspace(org.workspace_near(40))}


def test_results_never_present_a_smoke_number_as_d12() -> None:
    from ..policy.run import results_markdown

    text = results_markdown(_complete_report(), MODULUS, "chưa chọn")
    assert text.startswith("## smoke, máy dev, không phải số D12\n")
    assert "d12, máy tham chiếu" not in text
