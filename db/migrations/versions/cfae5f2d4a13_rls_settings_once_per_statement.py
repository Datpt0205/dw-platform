"""rls settings once per statement

Revision ID: cfae5f2d4a13
Revises: 0fdd32a39d87
Create Date: 2026-10-29 12:16:06.351283+00:00

foundations-hardening ticket 03 (R5.3, FH14). Every policy that reads a session
setting reads it inside a sub-SELECT, so PostgreSQL evaluates it once per
statement as an InitPlan instead of once per row, and the planner can use the
value as an index condition. Measured on PostgreSQL 16.15 before writing this
(the ticket's Comments): a keyset page of 50 over 200,000 rows of one tenant
under the `tenant AND (workspace OR scope)` shape took a median 224 ms per row
and 84 ms with the sub-SELECT, 62% less, above the 20% the ticket set.

The policies are listed as they stood when this revision was written, each with
its old and new expression, so nothing is rewritten by pattern at upgrade time.
A partition's own tenant policy comes from `platform._ensure_one_partition`,
whose predicate changes here too; the partitions that exist on a given database
differ between environments, so those are found in the catalog at upgrade time
and set to the same static predicate. A policy written after this revision must
take the new shape: `test_rls_coverage.py` fails one that reads a setting
outside a sub-SELECT.
"""

# ruff: noqa: E501 - the policy expressions are kept verbatim, as PostgreSQL prints them.
from __future__ import annotations

from alembic import op

revision = "cfae5f2d4a13"
down_revision = "0fdd32a39d87"
branch_labels = None
depends_on = None

# (table, policy, old USING, old WITH CHECK, new USING, new WITH CHECK)
POLICIES: tuple[tuple[str, str, str | None, str | None, str | None, str | None], ...] = (
    (
        "knowledge.chunks",
        "tenant_isolation_chunks",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "knowledge.documents",
        "tenant_isolation_documents",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "knowledge.documents",
        "worker_drain_documents",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
    ),
    (
        "knowledge.evidence",
        "tenant_isolation_evidence",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "knowledge.evidence",
        "worker_drain_evidence",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
    ),
    (
        "knowledge.ingest_jobs",
        "tenant_isolation_ingest_jobs",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "knowledge.ingest_jobs",
        "worker_drain_ingest_jobs",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
    ),
    (
        "memory.item_evidence",
        "tenant_isolation_item_evidence",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "memory.item_evidence",
        "worker_drain_item_evidence",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
    ),
    (
        "memory.items",
        "tenant_isolation_items",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "memory.items",
        "worker_drain_items",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
    ),
    (
        "memory.write_candidates",
        "tenant_isolation_write_candidates",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.agent_store",
        "tenant_isolation_agent_store",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.approval_decision_codes",
        "approval_decision_codes_self_select",
        "(user_id = (NULLIF(current_setting('app.principal_id'::text, true), ''::text))::uuid)",
        None,
        "(user_id = (SELECT NULLIF(current_setting('app.principal_id', true), '')::uuid))",
        None,
    ),
    (
        "platform.approval_decision_codes",
        "tenant_isolation_approval_decision_codes",
        "((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid) AND ((workspace_id = (NULLIF(current_setting('app.workspace_id'::text, true), ''::text))::uuid) OR (current_setting('app.workspace_scope'::text, true) = 'tenant'::text)))",
        "((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid) AND ((workspace_id = (NULLIF(current_setting('app.workspace_id'::text, true), ''::text))::uuid) OR (current_setting('app.workspace_scope'::text, true) = 'tenant'::text)))",
        "((tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)) AND ((workspace_id = (SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid)) OR ((SELECT current_setting('app.workspace_scope', true)) = 'tenant'::text)))",
        "((tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)) AND ((workspace_id = (SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid)) OR ((SELECT current_setting('app.workspace_scope', true)) = 'tenant'::text)))",
    ),
    (
        "platform.approval_decisions",
        "tenant_isolation_approval_decisions",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.approval_requests",
        "tenant_isolation_approval_requests",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.approval_view_receipts",
        "tenant_isolation_approval_view_receipts",
        "((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid) AND ((workspace_id = (NULLIF(current_setting('app.workspace_id'::text, true), ''::text))::uuid) OR (current_setting('app.workspace_scope'::text, true) = 'tenant'::text)))",
        "((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid) AND ((workspace_id = (NULLIF(current_setting('app.workspace_id'::text, true), ''::text))::uuid) OR (current_setting('app.workspace_scope'::text, true) = 'tenant'::text)))",
        "((tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)) AND ((workspace_id = (SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid)) OR ((SELECT current_setting('app.workspace_scope', true)) = 'tenant'::text)))",
        "((tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)) AND ((workspace_id = (SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid)) OR ((SELECT current_setting('app.workspace_scope', true)) = 'tenant'::text)))",
    ),
    (
        "platform.audit_events",
        "tenant_isolation_audit_events",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.channel_deliveries",
        "tenant_isolation_channel_deliveries",
        "((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid) AND ((workspace_id = (NULLIF(current_setting('app.workspace_id'::text, true), ''::text))::uuid) OR (current_setting('app.workspace_scope'::text, true) = 'tenant'::text)))",
        "((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid) AND ((workspace_id = (NULLIF(current_setting('app.workspace_id'::text, true), ''::text))::uuid) OR (current_setting('app.workspace_scope'::text, true) = 'tenant'::text)))",
        "((tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)) AND ((workspace_id = (SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid)) OR ((SELECT current_setting('app.workspace_scope', true)) = 'tenant'::text)))",
        "((tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)) AND ((workspace_id = (SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid)) OR ((SELECT current_setting('app.workspace_scope', true)) = 'tenant'::text)))",
    ),
    (
        "platform.channel_preferences",
        "channel_preferences_self",
        "(user_id = (NULLIF(current_setting('app.principal_id'::text, true), ''::text))::uuid)",
        "(user_id = (NULLIF(current_setting('app.principal_id'::text, true), ''::text))::uuid)",
        "(user_id = (SELECT NULLIF(current_setting('app.principal_id', true), '')::uuid))",
        "(user_id = (SELECT NULLIF(current_setting('app.principal_id', true), '')::uuid))",
    ),
    (
        "platform.effect_keys",
        "tenant_isolation_effect_keys",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.entitlements",
        "tenant_isolation_entitlements",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.feedback",
        "tenant_isolation_feedback",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.feedback_attachments",
        "tenant_isolation_feedback_attachments",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.idempotency_keys",
        "tenant_isolation_idempotency_keys",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.memberships",
        "memberships_self_select",
        "(user_id = (NULLIF(current_setting('app.principal_id'::text, true), ''::text))::uuid)",
        None,
        "(user_id = (SELECT NULLIF(current_setting('app.principal_id', true), '')::uuid))",
        None,
    ),
    (
        "platform.memberships",
        "tenant_isolation_memberships",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.notifications",
        "tenant_isolation_notifications_select",
        "((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid) AND (recipient_user_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::uuid))",
        None,
        "((tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)) AND (recipient_user_id = (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)))",
        None,
    ),
    (
        "platform.notifications",
        "tenant_isolation_notifications_update",
        "((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid) AND (recipient_user_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::uuid))",
        "((tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid) AND (recipient_user_id = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::uuid))",
        "((tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)) AND (recipient_user_id = (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)))",
        "((tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)) AND (recipient_user_id = (SELECT NULLIF(current_setting('app.user_id', true), '')::uuid)))",
    ),
    (
        "platform.outbox_events",
        "tenant_isolation_outbox_events",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.outbox_events",
        "worker_drain_outbox_events",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
    ),
    (
        "platform.policy_overrides",
        "tenant_isolation_policy_overrides",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.run_checkpoint_writes",
        "tenant_isolation_run_checkpoint_writes",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.run_checkpoint_writes",
        "worker_drain_run_checkpoint_writes",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
    ),
    (
        "platform.run_checkpoints",
        "tenant_isolation_run_checkpoints",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.run_checkpoints",
        "worker_drain_run_checkpoints",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
    ),
    (
        "platform.sod_waivers",
        "tenant_isolation_sod_waivers",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.support_grants",
        "tenant_isolation_support_grants",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.tenant_daily_spend_guard",
        "tenant_isolation_tenant_daily_spend_guard",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.tenant_daily_spend_guard",
        "worker_drain_tenant_daily_spend_guard",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
    ),
    (
        "platform.tenant_offboarding_requests",
        "tenant_isolation_tenant_offboarding_requests",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.tenant_offboarding_requests",
        "worker_drain_tenant_offboarding_requests",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
    ),
    (
        "platform.tenants",
        "tenant_isolation_tenants",
        "(id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.tenants",
        "tenants_self_select",
        "(id IN ( SELECT m.tenant_id\n   FROM platform.memberships m\n  WHERE (m.user_id = (NULLIF(current_setting('app.principal_id'::text, true), ''::text))::uuid)))",
        None,
        "(id IN ( SELECT m.tenant_id\n   FROM platform.memberships m\n  WHERE (m.user_id = (SELECT NULLIF(current_setting('app.principal_id', true), '')::uuid))))",
        None,
    ),
    (
        "platform.tool_executions",
        "tenant_isolation_tool_executions",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.worker_runs",
        "tenant_isolation_worker_runs",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.worker_runs",
        "worker_drain_worker_runs",
        "(current_setting('app.worker_drain'::text, true) = 'on'::text)",
        None,
        "((SELECT current_setting('app.worker_drain', true)) = 'on'::text)",
        None,
    ),
    (
        "platform.workspaces",
        "tenant_isolation_workspaces",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (NULLIF(current_setting('app.tenant_id'::text, true), ''::text))::uuid)",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
        "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))",
    ),
    (
        "platform.workspaces",
        "workspaces_self_select",
        "(id IN ( SELECT m.workspace_id\n   FROM platform.memberships m\n  WHERE (m.user_id = (NULLIF(current_setting('app.principal_id'::text, true), ''::text))::uuid)))",
        None,
        "(id IN ( SELECT m.workspace_id\n   FROM platform.memberships m\n  WHERE (m.user_id = (SELECT NULLIF(current_setting('app.principal_id', true), '')::uuid))))",
        None,
    ),
)

_PARTITION_PREDICATE_NEW = (
    "tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)
_PARTITION_PREDICATE_OLD = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"

_ENSURE_ONE_NEW = """
CREATE OR REPLACE FUNCTION platform._ensure_one_partition(schema_name text, parent text, month date)
RETURNS text
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
    part text := parent || '_' || to_char(month, 'YYYY_MM');
    fallback text := parent || '_default';
    stamp text;
    next_month date := (month + interval '1 month')::date;
    predicate constant text :=
        'tenant_id = (SELECT NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid)';
    stranded boolean := false;
BEGIN
    IF to_regclass(format('%I.%I', schema_name, part)) IS NOT NULL THEN
        RETURN NULL;
    END IF;
    -- The partition key, from the table that declares it, and only of a RANGE
    -- partitioned table: a month is a range.
    SELECT a.attname INTO stamp
    FROM pg_partitioned_table p
    JOIN pg_attribute a ON a.attrelid = p.partrelid AND a.attnum = p.partattrs[0]
    WHERE p.partrelid = to_regclass(format('%I.%I', schema_name, parent))
      AND p.partstrat = 'r';
    IF stamp IS NULL THEN
        RAISE EXCEPTION '%.% is not range-partitioned', schema_name, parent;
    END IF;

    -- Asked before the expensive path is taken: detaching the default takes an
    -- ACCESS EXCLUSIVE lock, and this runs hourly on a table that is almost
    -- always already in order.
    IF to_regclass(format('%I.%I', schema_name, fallback)) IS NOT NULL THEN
        EXECUTE format(
            'SELECT EXISTS (SELECT 1 FROM %I.%I WHERE %I >= %L AND %I < %L)',
            schema_name, fallback, stamp, month, stamp, next_month
        ) INTO stranded;
    END IF;
    IF stranded THEN
        EXECUTE format(
            'ALTER TABLE %I.%I DETACH PARTITION %I.%I',
            schema_name, parent, schema_name, fallback
        );
    END IF;

    EXECUTE format(
        'CREATE TABLE %I.%I PARTITION OF %I.%I FOR VALUES FROM (%L) TO (%L)',
        schema_name, part, schema_name, parent, month, next_month
    );
    -- Postgres does not inherit row security to a partition created later, and
    -- a partition addressed by name uses its own settings. FORCE as well:
    -- without it the owner reads straight past the policy, and the owner is
    -- exactly who runs this.
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', schema_name, part);
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY', schema_name, part);
    EXECUTE format(
        'CREATE POLICY %I ON %I.%I USING (%s) WITH CHECK (%s)',
        'tenant_isolation_' || part, schema_name, part, predicate, predicate
    );
    -- `ALTER DEFAULT PRIVILEGES` has already handed this partition what the
    -- schema hands every table. Rows are read and written through the parent,
    -- so nobody but the owner keeps anything on the partition itself.
    PERFORM platform._revoke_all_but_owner(format('%I.%I', schema_name, part)::regclass);

    IF stranded THEN
        -- Back in through the PARENT, so the rows route themselves into the
        -- partition just made. Only this month's: the default may legitimately
        -- be holding other months that nothing has asked for yet.
        EXECUTE format(
            'INSERT INTO %I.%I SELECT * FROM %I.%I WHERE %I >= %L AND %I < %L',
            schema_name, parent, schema_name, fallback, stamp, month, stamp, next_month
        );
        EXECUTE format(
            'DELETE FROM %I.%I WHERE %I >= %L AND %I < %L',
            schema_name, fallback, stamp, month, stamp, next_month
        );
        EXECUTE format(
            'ALTER TABLE %I.%I ATTACH PARTITION %I.%I DEFAULT',
            schema_name, parent, schema_name, fallback
        );
    END IF;
    RETURN part;
END;
$fn$
"""

_ENSURE_ONE_OLD = """
CREATE OR REPLACE FUNCTION platform._ensure_one_partition(schema_name text, parent text, month date)
RETURNS text
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
    part text := parent || '_' || to_char(month, 'YYYY_MM');
    fallback text := parent || '_default';
    stamp text;
    next_month date := (month + interval '1 month')::date;
    predicate constant text :=
        'tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::uuid';
    stranded boolean := false;
BEGIN
    IF to_regclass(format('%I.%I', schema_name, part)) IS NOT NULL THEN
        RETURN NULL;
    END IF;
    -- The partition key, from the table that declares it, and only of a RANGE
    -- partitioned table: a month is a range.
    SELECT a.attname INTO stamp
    FROM pg_partitioned_table p
    JOIN pg_attribute a ON a.attrelid = p.partrelid AND a.attnum = p.partattrs[0]
    WHERE p.partrelid = to_regclass(format('%I.%I', schema_name, parent))
      AND p.partstrat = 'r';
    IF stamp IS NULL THEN
        RAISE EXCEPTION '%.% is not range-partitioned', schema_name, parent;
    END IF;

    -- Asked before the expensive path is taken: detaching the default takes an
    -- ACCESS EXCLUSIVE lock, and this runs hourly on a table that is almost
    -- always already in order.
    IF to_regclass(format('%I.%I', schema_name, fallback)) IS NOT NULL THEN
        EXECUTE format(
            'SELECT EXISTS (SELECT 1 FROM %I.%I WHERE %I >= %L AND %I < %L)',
            schema_name, fallback, stamp, month, stamp, next_month
        ) INTO stranded;
    END IF;
    IF stranded THEN
        EXECUTE format(
            'ALTER TABLE %I.%I DETACH PARTITION %I.%I',
            schema_name, parent, schema_name, fallback
        );
    END IF;

    EXECUTE format(
        'CREATE TABLE %I.%I PARTITION OF %I.%I FOR VALUES FROM (%L) TO (%L)',
        schema_name, part, schema_name, parent, month, next_month
    );
    -- Postgres does not inherit row security to a partition created later, and
    -- a partition addressed by name uses its own settings. FORCE as well:
    -- without it the owner reads straight past the policy, and the owner is
    -- exactly who runs this.
    EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY', schema_name, part);
    EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY', schema_name, part);
    EXECUTE format(
        'CREATE POLICY %I ON %I.%I USING (%s) WITH CHECK (%s)',
        'tenant_isolation_' || part, schema_name, part, predicate, predicate
    );
    -- `ALTER DEFAULT PRIVILEGES` has already handed this partition what the
    -- schema hands every table. Rows are read and written through the parent,
    -- so nobody but the owner keeps anything on the partition itself.
    PERFORM platform._revoke_all_but_owner(format('%I.%I', schema_name, part)::regclass);

    IF stranded THEN
        -- Back in through the PARENT, so the rows route themselves into the
        -- partition just made. Only this month's: the default may legitimately
        -- be holding other months that nothing has asked for yet.
        EXECUTE format(
            'INSERT INTO %I.%I SELECT * FROM %I.%I WHERE %I >= %L AND %I < %L',
            schema_name, parent, schema_name, fallback, stamp, month, stamp, next_month
        );
        EXECUTE format(
            'DELETE FROM %I.%I WHERE %I >= %L AND %I < %L',
            schema_name, fallback, stamp, month, stamp, next_month
        );
        EXECUTE format(
            'ALTER TABLE %I.%I ATTACH PARTITION %I.%I DEFAULT',
            schema_name, parent, schema_name, fallback
        );
    END IF;
    RETURN part;
END;
$fn$
"""


def _alter(table: str, policy: str, using: str | None, check: str | None) -> str:
    clauses = []
    if using is not None:
        clauses.append(f"USING ({using})")
    if check is not None:
        clauses.append(f"WITH CHECK ({check})")
    return f'ALTER POLICY "{policy}" ON {table} ' + " ".join(clauses)


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _partitions(predicate: str) -> str:
    """Every partition's tenant policy, found in the catalog of this database."""
    return f"""
        DO $$
        DECLARE
            p record;
        BEGIN
            FOR p IN
                SELECT n.nspname AS schema_name, c.relname AS part, pol.polname AS policy
                FROM pg_policy pol
                JOIN pg_class c ON c.oid = pol.polrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relispartition AND pol.polname LIKE 'tenant_isolation_%'
            LOOP
                EXECUTE format(
                    'ALTER POLICY %I ON %I.%I USING (%s) WITH CHECK (%s)',
                    p.policy, p.schema_name, p.part, {_lit(predicate)}, {_lit(predicate)}
                );
            END LOOP;
        END
        $$
        """


def upgrade() -> None:
    for table, policy, _old_using, _old_check, using, check in POLICIES:
        op.execute(_alter(table, policy, using, check))
    op.execute(_ENSURE_ONE_NEW)
    op.execute(_partitions(_PARTITION_PREDICATE_NEW))


def downgrade() -> None:
    for table, policy, using, check, _new_using, _new_check in POLICIES:
        op.execute(_alter(table, policy, using, check))
    op.execute(_ENSURE_ONE_OLD)
    op.execute(_partitions(_PARTITION_PREDICATE_OLD))
