"""The pure rules of a two-person publication (agent-lifecycle ticket 04):
who the authors are (R5.1), the guard every kind's request is decided under
(R5.2, R5.3), and what changed between two documents (R5.11)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from dw_kernel.errors import ConflictError
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_platform.application.access_context import AccessContext
from dw_platform.domain.approval import ApprovalRequest
from dw_studio.lifecycle.application.publish import (
    PUBLISH_APPROVE_SCOPE,
    Change,
    author_ids,
    document_changes,
    publish_decision_guards,
    require_not_author,
)

pytestmark = pytest.mark.unit

A, B, C = (uuid.uuid4() for _ in range(3))


def _request(payload: dict[str, Any]) -> ApprovalRequest:
    return ApprovalRequest(
        id=uuid.uuid4(),
        tenant_id=TenantId(uuid.uuid4()),
        workspace_id=WorkspaceId(uuid.uuid4()),
        approval_type="studio.publish.object",
        requested_by=UserId(C),
        reason="studio.publish.object",
        payload=payload,
        required_scope=PUBLISH_APPROVE_SCOPE,
    )


def _who(person: uuid.UUID) -> AccessContext:
    return AccessContext(
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        principal_id=person,
        roles=frozenset(),
        plan_id="professional",
    )


def _reason(caught: pytest.ExceptionInfo[ConflictError]) -> object:
    return caught.value.details.get("reason_code")


# ---- R5.1: the authors -----------------------------------------------------------


def test_r5_1_the_authors_are_every_contributor_then_the_submitter_once_each() -> None:
    assert author_ids((A, B), C) == [str(A), str(B), str(C)]
    assert author_ids((A, B), A) == [str(A), str(B)]


# ---- R5.2, R5.3: the guard ------------------------------------------------------


@pytest.mark.parametrize("author", [A, B, C])
def test_r5_2_every_author_is_refused(author: uuid.UUID) -> None:
    with pytest.raises(ConflictError) as refused:
        require_not_author(_request({"author_ids": author_ids((A, B), C)}), _who(author))
    assert _reason(refused) == "author_cannot_approve"


def test_r5_2_someone_who_wrote_nothing_passes() -> None:
    require_not_author(_request({"author_ids": author_ids((A, B), C)}), _who(uuid.uuid4()))


@pytest.mark.parametrize(
    "payload",
    [{}, {"author_ids": []}, {"author_ids": "a"}, {"author_ids": [1]}, {"author_ids": None}],
)
def test_r5_3_a_payload_without_its_authors_is_refused_for_everyone(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ConflictError) as refused:
        require_not_author(_request(payload), _who(uuid.uuid4()))
    assert _reason(refused) == "author_ids_missing"


def test_one_guard_under_the_exact_type_of_each_kind() -> None:
    """`decision_guards` is keyed by the exact type, so each kind needs its own."""
    guards = publish_decision_guards(["object", "endpoint", "workflow"])
    assert set(guards) == {
        "studio.publish.object",
        "studio.publish.endpoint",
        "studio.publish.workflow",
    }


# ---- R5.11: what changed -----------------------------------------------------------


def test_r5_11_with_no_live_version_every_top_level_field_is_an_add() -> None:
    assert document_changes(None, {"title": "x", "fields": [1, 2]}) == [
        Change("/fields", "add", after=[1, 2]),
        Change("/title", "add", after="x"),
    ]


def test_r5_11_nested_changes_by_pointer_and_an_array_compared_whole() -> None:
    live = {"title": "a", "rules": {"max": 5, "gone": True}, "fields": [1, 2], "a/b": 1}
    candidate = {"title": "a", "rules": {"max": 3, "new": "x"}, "fields": [1, 2, 3], "a/b": 2}
    assert document_changes(live, candidate) == [
        Change("/a~1b", "replace", before=1, after=2),
        Change("/fields", "replace", before=[1, 2], after=[1, 2, 3]),
        Change("/rules/gone", "remove", before=True),
        Change("/rules/max", "replace", before=5, after=3),
        Change("/rules/new", "add", after="x"),
    ]


def test_r5_11_equal_documents_in_another_key_order_have_no_change() -> None:
    assert document_changes({"a": {"x": 1, "y": 2}}, {"a": {"y": 2, "x": 1}}) == []
