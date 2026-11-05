"""The record policy template's own rules (record-access ticket 03, step 4).

The catalog half, that PostgreSQL holds what this module renders, is
`test_record_policies.py`; here, the text it renders."""

from __future__ import annotations

import pytest

from dw_studio.records.adapters.record_policy import (
    SCOPE,
    TENANT,
    USER_OK,
    actor_sql,
    reach_sql,
    record_policies,
)

pytestmark = pytest.mark.unit


def test_the_record_set_is_one_restrictive_tenant_policy_and_four_permissive_ones() -> None:
    policies = {p.name: p for p in record_policies("records")}
    assert set(policies) == {
        "tenant_isolation_records",
        "record_access_records_select",
        "record_access_records_insert",
        "record_access_records_update",
        "record_access_records_delete",
    }
    tenant = policies["tenant_isolation_records"]
    assert (tenant.permissive, tenant.command) == (False, "ALL")
    assert "AS RESTRICTIVE" in tenant.create_sql("studio.records")
    for command in ("select", "insert", "update", "delete"):
        policy = policies[f"record_access_records_{command}"]
        assert policy.permissive and policy.command == command.upper()
        actor = actor_sql(command)
        for clause in (policy.using, policy.with_check):
            if clause is not None:
                assert clause.startswith(f"({TENANT}) AND ({SCOPE} OR ({actor} AND ")


def test_each_command_reads_its_own_action_and_insert_reads_create() -> None:
    assert "'read'" in reach_sql("select") and "'update'" not in reach_sql("select")
    assert "acl_create_own_keys" in reach_sql("insert") and "'create'" in reach_sql("insert")
    assert "'assign'" in reach_sql("assign")
    for command in ("select", "update", "delete", "assign", "insert"):
        assert "(SELECT studio.acl_user())" in reach_sql(command)


def test_a_soft_delete_needs_update_and_delete_reach() -> None:
    """Gate (b), (o): the WITH CHECK of `_update` adds delete reach when the new
    row is deleted, and `soft_delete` is both reaches."""
    assert reach_sql("soft_delete") == f"({reach_sql('update')} AND {reach_sql('delete')})"
    update = {p.name: p for p in record_policies("records")}["record_access_records_update"]
    assert update.using is not None and update.with_check is not None
    assert (
        f"(deleted_at IS NULL OR ({actor_sql('delete')} AND {reach_sql('delete')}))"
        in update.with_check
    )
    assert "deleted_at" not in update.using


def test_an_agent_or_a_workflow_is_admitted_only_within_its_boundary_for_the_command() -> None:
    """record-access ticket 04, step 6: `user` on its reach alone; `agent` and
    `workflow` for an object the boundary allows that command on; a soft
    delete asks the boundary's `delete` (gate (j))."""
    for command in ("select", "insert", "update", "delete", "assign"):
        actor = actor_sql(command)
        assert actor.startswith(f"({USER_OK} OR ")
        assert "IN ('agent', 'workflow')" in actor
        assert f"studio.acl_boundary_objects('{command}')" in actor
    policies = {p.name: p for p in record_policies("records")}
    for command in ("select", "insert", "update", "delete"):
        policy = policies[f"record_access_records_{command}"]
        for clause in (policy.using, policy.with_check):
            if clause is not None:
                assert f"studio.acl_boundary_objects('{command}')" in clause
    update = policies["record_access_records_update"]
    assert update.with_check is not None
    assert "studio.acl_boundary_objects('delete')" in update.with_check
