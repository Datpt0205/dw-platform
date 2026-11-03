"""Unit: the `dw.audience/v1` document and its validator (org-and-principals
ticket 04, R8.1, R8.2; OP12).

The validator is run with a fake workspaces port that answers like the SQL
adapter: the subset of the asked ids that are the caller's company's, and it
records each call so "the database is never asked" can fail.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from dw_platform.application.access_context import AccessContext
from dw_platform.application.audience import AudienceValidator
from dw_platform.domain.audience import (
    AUDIENCE_SCHEMA,
    MAX_CONDITIONS,
    AudienceDocument,
    AudienceInvalidError,
    parse_audience,
)

pytestmark = pytest.mark.unit

W1, W2, W3 = (uuid.uuid4() for _ in range(3))
OTHER_TENANTS = uuid.uuid4()


class FakeWorkspaces:
    """`AudienceWorkspacesPort` over a fixed set of the tenant's workspaces."""

    def __init__(self, *ids: uuid.UUID) -> None:
        self._ids = frozenset(ids)
        self.asked: list[frozenset[uuid.UUID]] = []

    async def known(
        self, context: AccessContext, ids: frozenset[uuid.UUID]
    ) -> frozenset[uuid.UUID]:
        self.asked.append(ids)
        return ids & self._ids


def _context() -> AccessContext:
    return AccessContext(
        tenant_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        principal_id=uuid.uuid4(),
        roles=frozenset({"member"}),
        scopes=frozenset(),
        plan_id="professional",
    )


def _doc(*groups: list[object]) -> dict[str, Any]:
    return {"schema": AUDIENCE_SCHEMA, "any_of": [{"all_of": list(g)} for g in groups]}


def _ws(workspace: uuid.UUID | str) -> dict[str, str]:
    return {"workspace_subtree": str(workspace)}


def _refused(raw: object, *, at: str = "") -> AudienceInvalidError:
    with pytest.raises(AudienceInvalidError) as caught:
        parse_audience(raw, at=at)
    return caught.value


async def _refused_by(
    validator: AudienceValidator, raw: object, at: str = ""
) -> AudienceInvalidError:
    with pytest.raises(AudienceInvalidError) as caught:
        await validator.validate(_context(), raw, at=at)
    return caught.value


# R8.1 -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [_doc(), _doc([]), _doc([], [])],
    ids=["no group", "one empty group", "only empty groups"],
)
async def test_a_document_naming_no_condition_is_empty_and_never_reaches_the_database(
    raw: dict[str, Any],
) -> None:
    workspaces = FakeWorkspaces(W1)

    refused = await _refused_by(AudienceValidator(workspaces), raw, at="/audience")

    assert refused.reason_code == "audience_empty"
    assert refused.details == {"reason_code": "audience_empty"}
    assert [(p.pointer, p.code) for p in refused.problems] == [
        ("/audience/any_of", "audience_empty")
    ]
    assert workspaces.asked == []


# R8.2 -----------------------------------------------------------------------


def test_a_condition_of_another_kind_is_unsupported_not_malformed() -> None:
    refused = _refused(_doc([{"team": str(uuid.uuid4())}]))

    assert refused.reason_code == "audience_invalid"
    assert refused.details == {"reason_code": "audience_invalid"}
    assert [(p.pointer, p.code) for p in refused.problems] == [
        ("/any_of/0/all_of/0", "audience_condition_unsupported")
    ]


def test_the_twenty_first_condition_is_one_too_many() -> None:
    refused = _refused(_doc([_ws(W1)] * (MAX_CONDITIONS + 1)))

    assert refused.reason_code == "audience_invalid"
    assert (refused.problems[0].pointer, refused.problems[0].code) == (
        "/any_of/0/all_of/20",
        "audience_too_many_conditions",
    )


def test_twenty_conditions_across_groups_are_accepted_and_twenty_one_are_not() -> None:
    assert parse_audience(_doc([_ws(W1)] * 10, [_ws(W2)] * 10))
    refused = _refused(_doc([_ws(W1)] * 10, [_ws(W2)] * 11))
    assert (refused.problems[0].pointer, refused.problems[0].code) == (
        "/any_of/1/all_of/10",
        "audience_too_many_conditions",
    )


def test_an_empty_group_beside_a_real_one_is_refused() -> None:
    """An empty group is true for everyone, so beside a real group it would
    open the agent to the whole company."""
    refused = _refused(_doc([_ws(W1)], []))

    assert refused.reason_code == "audience_invalid"
    assert [(p.pointer, p.code) for p in refused.problems] == [
        ("/any_of/1/all_of", "audience_group_empty")
    ]


@pytest.mark.parametrize(
    ("raw", "pointer"),
    [
        ({"schema": "dw.audience/v2", "any_of": [{"all_of": [_ws(W1)]}]}, "/schema"),
        ({"schema_": AUDIENCE_SCHEMA, "any_of": [{"all_of": [_ws(W1)]}]}, ""),
        ({**_doc([_ws(W1)]), "SECRET-member": 1}, ""),
        (
            _doc([{"workspace_subtree": "SECRET-not-a-uuid"}]),
            "/any_of/0/all_of/0/workspace_subtree",
        ),
        (_doc([{"workspace_subtree": str(W1), "team": str(W2)}]), "/any_of/0/all_of/0"),
        ({"schema": AUDIENCE_SCHEMA, "any_of": "SECRET"}, "/any_of"),
        ("SECRET", ""),
        (None, ""),
    ],
    ids=[
        "another schema",
        "schema_ by field name",
        "unknown member",
        "not a uuid",
        "two members",
        "any_of not a list",
        "a string",
        "null",
    ],
)
def test_a_document_of_the_wrong_shape_is_malformed_and_echoes_no_value(
    raw: object, pointer: str
) -> None:
    refused = _refused(raw)

    assert refused.reason_code == "audience_invalid"
    assert all(p.code == "audience_malformed" for p in refused.problems)
    assert pointer in {p.pointer for p in refused.problems}
    for problem in refused.problems:
        assert "SECRET" not in problem.pointer + problem.detail


def test_every_pointer_starts_with_where_the_caller_put_the_document() -> None:
    refused = _refused(_doc([{"team": str(W1)}], []), at="/audience")

    assert [p.pointer for p in refused.problems] == [
        "/audience/any_of/0/all_of/0",
        "/audience/any_of/1/all_of",
    ]


async def test_a_workspace_the_port_does_not_know_is_refused_at_each_condition_naming_it() -> None:
    """Another tenant's workspace and one that does not exist are the same
    answer: the port returns neither, and the problem carries no value."""
    workspaces = FakeWorkspaces(W1)

    refused = await _refused_by(
        AudienceValidator(workspaces),
        _doc([_ws(W1), _ws(OTHER_TENANTS)], [_ws(W3)]),
        at="/audience",
    )

    assert refused.reason_code == "audience_invalid"
    assert [(p.pointer, p.code, p.detail) for p in refused.problems] == [
        (
            "/audience/any_of/0/all_of/1",
            "audience_workspace_unknown",
            "the workspace is not one of this company's",
        ),
        (
            "/audience/any_of/1/all_of/0",
            "audience_workspace_unknown",
            "the workspace is not one of this company's",
        ),
    ]
    assert workspaces.asked == [frozenset({W1, OTHER_TENANTS, W3})]


async def test_a_malformed_document_never_reaches_the_database() -> None:
    workspaces = FakeWorkspaces(W1)

    await _refused_by(AudienceValidator(workspaces), _doc([_ws(W1)], []))

    assert workspaces.asked == []


async def test_a_valid_document_is_returned_in_its_stored_form() -> None:
    raw = _doc([_ws(W1), _ws(W2)], [_ws(str(W3).upper())])

    document = await AudienceValidator(FakeWorkspaces(W1, W2, W3)).validate(_context(), raw)

    assert isinstance(document, AudienceDocument)
    assert document.workspace_ids() == {W1, W2, W3}
    assert document.as_json() == _doc([_ws(W1), _ws(W2)], [_ws(W3)])


def test_the_json_schema_names_the_wire_member_and_forbids_others() -> None:
    schema = AudienceDocument.json_schema()

    assert set(schema["properties"]) == {"schema", "any_of"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema"]["const"] == AUDIENCE_SCHEMA
