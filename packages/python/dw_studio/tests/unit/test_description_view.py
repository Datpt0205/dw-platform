"""Describe's presentation (custom-objects ticket 12: R3.1, R3.2; CO7).

`description_view` is the second layer holding the hidden-field rule: built
straight from a `Description` (never through the service, which already
leaves a hidden field's id `None`), a hidden field comes out with `api_name`,
`label` and `access` only, whatever the view it was handed carries, and a
readable one with its `field_id`.
"""

from __future__ import annotations

import uuid

import pytest

from dw_studio.records.application.record_views import Description, FieldView
from dw_studio.records.presentation.views import description_view

pytestmark = pytest.mark.unit

HIDDEN_ID = uuid.UUID(int=0xF1)
READABLE_ID = uuid.UUID(int=0xF2)


def _described() -> Description:
    return Description(
        object_id=uuid.UUID(int=0xA1),
        api_name="mkt_lead",
        label="Lead",
        ai_description=None,
        schema_version=1,
        fields=(
            FieldView(api_name="phone", label="Điện thoại", access="hidden", field_id=HIDDEN_ID),
            FieldView(api_name="note", label="Ghi chú", access="read", field_id=READABLE_ID),
        ),
    )


def test_a_hidden_field_carries_no_id_whatever_its_view_holds() -> None:
    shown = description_view(_described()).model_dump(mode="json", exclude_none=True)
    phone, note = shown["fields"]
    assert phone == {"api_name": "phone", "label": "Điện thoại", "access": "hidden"}
    assert str(HIDDEN_ID) not in str(shown)
    assert note["field_id"] == str(READABLE_ID)
