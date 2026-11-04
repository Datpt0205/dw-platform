"""The `object` kind's pure parts (custom-objects ticket 02): the field types
and slots, the `dw.object/v1` parse, `validate_object` (R1.6, R2.1-R2.3, R2.5,
R2.6), `check_against_live` (R2.4, R2.5; CO6, CO24), the comparator (R1.8,
CO23, over generated pairs) and `definition_of`, and the lock key.
"""

from __future__ import annotations

import copy
import random
import unicodedata
import uuid
from typing import Any

import pytest

from dw_kernel.personal_data import PdCategory
from dw_studio.core.domain.artifacts import DocumentInvalidError
from dw_studio.records.domain.document import definition_of, parse_object
from dw_studio.records.domain.field_types import (
    FIELD_TYPES,
    SLOTS,
    family_of,
    smallest_free_slot,
)
from dw_studio.records.domain.locks import object_lock_key
from dw_studio.records.domain.rules import (
    IMMUTABLE_ATTRIBUTES,
    check_against_live,
    compare_object,
    extract_object,
    validate_object,
)

pytestmark = pytest.mark.unit


def a_field(api_name: str = "phone", **over: Any) -> dict[str, Any]:
    field: dict[str, Any] = {
        "api_name": api_name,
        "labels": {"vi": "Số điện thoại"},
        "type": "phone",
        "pd_category": "basic",
    }
    field.update(over)
    return field


def a_document(*fields: dict[str, Any], **over: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "labels": {"vi": "Khách hàng tiềm năng"},
        "name_field": {"labels": {"vi": "Họ tên"}, "pd_category": "basic"},
        "fields": list(fields),
    }
    document.update(over)
    return document


def codes(problems: Any) -> list[tuple[str, str]]:
    return [(p.pointer, p.code) for p in problems]


# ---- field types and slots ---------------------------------------------------


def test_the_field_types_are_the_twelve_of_the_check() -> None:
    assert set(FIELD_TYPES) == {
        "text",
        "number",
        "currency",
        "date",
        "datetime",
        "boolean",
        "picklist",
        "email",
        "phone",
        "url",
        "owner",
        "workspace",
    }


def test_the_provisional_slot_set_is_a0() -> None:
    assert {family: len(slots) for family, slots in SLOTS.items()} == {
        "t": 24,
        "i": 12,
        "f": 8,
        "d": 8,
        "z": 8,
        "b": 8,
        "u": 4,
    }
    assert SLOTS["t"][0] == "t01" and SLOTS["u"][-1] == "u04"


@pytest.mark.parametrize(
    ("type_", "mode", "unique", "family"),
    [
        ("text", None, False, "t"),
        ("email", None, True, "u"),
        ("picklist", None, False, "t"),
        ("number", "exact", False, "i"),
        ("currency", None, False, "i"),
        ("number", "float", False, "f"),
        ("date", None, False, "d"),
        ("datetime", None, False, "z"),
        ("boolean", None, False, "b"),
        ("owner", None, False, None),
    ],
)
def test_each_type_has_its_family(
    type_: str, mode: str | None, unique: bool, family: str | None
) -> None:
    assert family_of(type_, number_mode=mode, is_unique=unique) == family


def test_the_smallest_free_slot_is_given_and_none_when_full() -> None:
    assert smallest_free_slot("t", frozenset({"t01", "t03"})) == "t02"
    assert smallest_free_slot("u", frozenset(SLOTS["u"])) is None


# ---- the parse and the validator ----------------------------------------------


def test_a_valid_document_has_no_problem() -> None:
    choice = a_field(
        "stage",
        type="picklist",
        pd_category="none",
        indexed=True,
        options=[{"key": "new", "labels": {"vi": "Mới"}, "position": 0}],
    )
    money = a_field("budget", type="currency", currency_code="VND", pd_category="none")
    assert validate_object(a_document(a_field(), choice, money)) == []


@pytest.mark.parametrize("type_", ["json", "user", "owner", "workspace"])
def test_r2_1_a_type_outside_the_ten_is_refused(type_: str) -> None:
    """R2.1: the company defines ten types; `owner`, `workspace` are system rows'."""
    found = codes(validate_object(a_document(a_field(type=type_))))
    assert found == [("/fields/0/type", "value_not_allowed")]


def test_r2_2_a_field_without_a_category_is_named_at_the_field() -> None:
    """R2.2 (CO5): `pd_category_required`, never a silent `none`."""
    field = a_field()
    del field["pd_category"]
    document = a_document(a_field("email", type="email"), field)
    del document["name_field"]["pd_category"]

    found = codes(validate_object(document))

    assert ("/fields/1", "pd_category_required") in found
    assert ("/name_field/pd_category", "pd_category_required") in found


def test_r2_2_the_sensitive_pairing_is_the_kernels() -> None:
    found = codes(validate_object(a_document(a_field(pd_category="sensitive"))))
    assert found == [("/fields/0", "sensitive_type_required")]


@pytest.mark.parametrize(
    ("api_name", "code"),
    [
        ("a" + "b" * 39, None),
        ("a" + "b" * 40, "api_name_invalid"),
        ("Lead", "api_name_invalid"),
        ("name", "reserved_api_name"),
        ("owner", "reserved_api_name"),
        ("workspace", "reserved_api_name"),
    ],
)
def test_r2_3_a_field_name_is_forty_lower_case_characters(api_name: str, code: str | None) -> None:
    found = codes(validate_object(a_document(a_field(api_name))))
    assert found == ([] if code is None else [("/fields/0/api_name", code)])


def test_r2_3_the_objects_api_name_is_the_envelopes() -> None:
    """The root takes no `api_name`: tenant-config R2.2, R2.10 own it."""
    found = codes(validate_object(a_document(a_field(), api_name="lead")))
    assert found == [("/api_name", "not_allowed")]


def test_r2_3_a_name_used_twice_is_named() -> None:
    found = codes(validate_object(a_document(a_field("phone"), a_field("phone"))))
    assert found == [("/fields/1/api_name", "api_name_repeated")]


def test_r2_5_a_sensitive_field_is_never_open() -> None:
    field = a_field(pd_category="sensitive", sensitive_type="health", access_mode="open")
    found = codes(validate_object(a_document(a_field("email", type="email"), field)))
    assert found == [("/fields/1/access_mode", "sensitive_field_open")]


def test_r2_5_access_mode_defaults_by_category() -> None:
    parsed = parse_object(a_document(a_field(pd_category="none"), a_field("email")))
    assert [f.access_mode for f in parsed.fields] == ["open", "secured"]


def _vietnamese(length: int) -> str:
    """`length` characters in NFC, each a precomposed Vietnamese letter."""
    return ("Đạt ơi, ừ " * length)[:length]


def test_r2_6_an_ai_description_is_500_characters_counted_in_nfc() -> None:
    at_limit = _vietnamese(500)
    decomposed = unicodedata.normalize("NFD", at_limit)
    assert len(decomposed) > 500  # the same text, longer before NFC

    for text in (at_limit, decomposed, None):
        document = a_document(a_field(ai_description=text), ai_description=text)
        assert validate_object(document) == [], text

    too_long = _vietnamese(501)
    found = codes(
        validate_object(a_document(a_field(ai_description=too_long), ai_description=too_long))
    )
    assert found == [
        ("/ai_description", "ai_description_too_long"),
        ("/fields/0/ai_description", "ai_description_too_long"),
    ]


def test_r1_6_the_document_holds_no_more_filtering_fields_than_slots() -> None:
    """R1.6: the 25th filtering text field has no `t` slot."""
    fields = [a_field(f"f_{n}", type="text", pd_category="none", indexed=True) for n in range(25)]
    found = codes(validate_object(a_document(*fields)))
    assert found == [("/fields/24", "slot_budget_exceeded")]
    assert validate_object(a_document(*fields[:24])) == []


def test_r1_6_unique_is_text_email_phone_url_only() -> None:
    field = a_field(
        "amount", type="number", number_mode="exact", pd_category="none", is_unique=True
    )
    assert codes(validate_object(a_document(field))) == [
        ("/fields/0/is_unique", "unique_not_supported")
    ]
    assert validate_object(a_document(a_field("email", type="email", is_unique=True))) == []


@pytest.mark.parametrize(
    ("over", "found"),
    [
        ({"type": "number"}, ("/fields/0/number_mode", "number_mode_required")),
        ({"max_length": 300}, ("/fields/0/max_length", "max_length_out_of_range")),
        ({"scale": 2}, ("/fields/0/scale", "attribute_not_allowed")),
        (
            {"type": "currency", "currency_code": "vnd"},
            ("/fields/0/currency_code", "currency_code_invalid"),
        ),
        ({"type": "picklist"}, ("/fields/0/options", "options_required")),
        ({"labels": {"vi": "  "}}, ("/fields/0/labels/vi", "label_vi_required")),
    ],
)
def test_every_check_constraint_of_a_field_is_validated_first(
    over: dict[str, Any], found: tuple[str, str]
) -> None:
    """Nothing `seal` accepts breaks a CHECK of `studio.field_defs` after the
    approval (gate, 3/11/2026)."""
    assert found in codes(validate_object(a_document(a_field(**over))))


def test_a_document_that_is_not_an_object_is_refused_at_the_root() -> None:
    assert codes(validate_object([])) == [("", "wrong_type")]


def test_the_extractor_finds_no_reference_in_w1() -> None:
    assert extract_object(a_document(a_field())) == []


# ---- a version against the live one ----------------------------------------------


def test_r2_4_a_published_field_or_option_cannot_go() -> None:
    """CO6: a rename is the old name removed and a new one added."""
    choice = a_field(
        "stage",
        type="picklist",
        pd_category="none",
        options=[
            {"key": "new", "labels": {"vi": "Mới"}, "position": 0},
            {"key": "won", "labels": {"vi": "Thắng"}, "position": 1},
        ],
    )
    live = a_document(a_field("phone"), choice)
    renamed = copy.deepcopy(live)
    renamed["fields"][0]["api_name"] = "mobile"
    renamed["fields"][1]["options"].pop()

    found = codes(check_against_live(live, renamed))

    assert found == [("/fields", "field_removed"), ("/fields/1/options", "option_removed")]


def test_r2_4_an_option_switched_off_stays() -> None:
    choice = a_field(
        "stage",
        type="picklist",
        pd_category="none",
        options=[{"key": "new", "labels": {"vi": "Mới"}, "position": 0}],
    )
    off = copy.deepcopy(choice)
    off["options"][0]["active"] = False
    assert check_against_live(a_document(choice), a_document(off)) == []


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ({"type": "phone"}, {"type": "text"}),
        ({"type": "number", "number_mode": "exact"}, {"type": "number", "number_mode": "float"}),
        (
            {"type": "number", "number_mode": "exact", "scale": 0},
            {"type": "number", "number_mode": "exact", "scale": 2},
        ),
        (
            {"type": "currency", "currency_code": "VND"},
            {"type": "currency", "currency_code": "USD"},
        ),
        ({"type": "phone", "is_unique": False}, {"type": "phone", "is_unique": True}),
        ({"type": "phone", "indexed": False}, {"type": "phone", "indexed": True}),
    ],
)
def test_r2_4_what_a_stored_value_means_is_fixed(
    before: dict[str, Any], after: dict[str, Any]
) -> None:
    live = a_document(a_field(pd_category="none", **before))
    new = a_document(a_field(pd_category="none", **after))
    found = codes(check_against_live(live, new))
    assert found and all(code == "field_immutable" for _, code in found)
    assert all(pointer.startswith("/fields/0/") for pointer, _ in found)
    assert {pointer.rsplit("/", 1)[1] for pointer, _ in found} <= set(IMMUTABLE_ATTRIBUTES)


def test_r2_5_a_new_field_with_personal_data_starts_secured() -> None:
    """CO24: `basic` and open is refused for a new field, allowed for none."""
    live = a_document(a_field())
    opened = a_document(a_field(), a_field("email", type="email", access_mode="open"))
    plain = a_document(a_field(), a_field("note", type="text", pd_category="none"))
    assert codes(check_against_live(live, opened)) == [
        ("/fields/1/access_mode", "personal_data_field_open")
    ]
    assert check_against_live(live, plain) == []
    # With no live version every field is new.
    assert codes(check_against_live(None, opened)) == [
        ("/fields/1/access_mode", "personal_data_field_open")
    ]


def test_r2_5_no_category_is_lowered_the_name_fields_included() -> None:
    live = a_document(
        a_field(pd_category="sensitive", sensitive_type="financial"),
        name_field={
            "labels": {"vi": "Họ tên"},
            "pd_category": "sensitive",
            "sensitive_type": "health",
        },
    )
    lowered = a_document(
        a_field(pd_category="none"),
        name_field={"labels": {"vi": "Họ tên"}, "pd_category": "none"},
    )
    retyped = a_document(
        a_field(pd_category="sensitive", sensitive_type="health"),
        name_field={
            "labels": {"vi": "Họ tên"},
            "pd_category": "sensitive",
            "sensitive_type": "health",
        },
    )
    assert codes(check_against_live(live, lowered)) == [
        ("/name_field/pd_category", "pd_category_lowered"),
        ("/fields/0/pd_category", "pd_category_lowered"),
    ]
    # Between sensitive types it is allowed (a second person still decides).
    assert check_against_live(live, retyped) == []


def test_check_against_live_names_a_new_documents_own_problems() -> None:
    assert codes(check_against_live(None, {"labels": {"vi": "x"}})) == [("/name_field", "required")]


# ---- the comparator (R1.8, CO23) ---------------------------------------------------

_ACCESS = ("private", "public_read", "public_read_write")
_TIGHTENING = frozenset({"secure", "narrow"})
_NEUTRAL = frozenset({"reorder", "explicit"})


def _random_document(rng: random.Random) -> dict[str, Any]:
    fields = []
    for n in range(rng.randint(1, 6)):
        type_ = rng.choice(["text", "phone", "number", "date", "boolean", "picklist"])
        category = rng.choice(["none", "basic"])
        field: dict[str, Any] = {
            "api_name": f"f_{n}",
            "labels": {"vi": f"Trường {n}"},
            "type": type_,
            "pd_category": category,
            "access_mode": rng.choice(["open", "secured"]) if category == "none" else "secured",
        }
        if type_ == "number":
            field["number_mode"] = "exact"
        if type_ == "picklist":
            field["options"] = [{"key": "a", "labels": {"vi": "A"}, "position": 0}]
        fields.append(field)
    return a_document(*fields, default_access=rng.choice(_ACCESS))


def _mutate(rng: random.Random, live: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """A version from `live` and the kinds of change it made, each field and
    `default_access` changed at most once, so the kinds are the net change."""
    new = copy.deepcopy(live)
    made: set[str] = set()
    touched: set[str] = set()
    for _ in range(rng.randint(1, 3)):
        kind = rng.choice(
            [
                "secure",
                "open",
                "narrow",
                "widen",
                "relabel",
                "describe",
                "add",
                "reorder",
                "explicit",
            ]
        )
        fields = [f for f in new["fields"] if f["api_name"] not in touched]
        rank = _ACCESS.index(new["default_access"])
        if kind == "secure" and (pick := [f for f in fields if f["access_mode"] == "open"]):
            field = rng.choice(pick)
            field["access_mode"] = "secured"
        elif kind == "open" and (pick := [f for f in fields if f["access_mode"] == "secured"]):
            field = rng.choice(pick)
            field["access_mode"] = "open"
        elif kind == "narrow" and "access" not in touched and rank > 0:
            new["default_access"] = _ACCESS[rng.randrange(rank)]
            field = {"api_name": "access"}
        elif kind == "widen" and "access" not in touched and rank < 2:
            new["default_access"] = _ACCESS[rng.randrange(rank + 1, 3)]
            field = {"api_name": "access"}
        elif kind == "relabel" and fields:
            field = rng.choice(fields)
            field["labels"] = {"vi": field["labels"]["vi"] + " mới"}
        elif kind == "describe" and "object" not in touched:
            new["ai_description"] = f"Mô tả {rng.random()}"
            field = {"api_name": "object"}
        elif kind == "add":
            field = {"api_name": f"added_{len(new['fields'])}"}
            new["fields"].append(
                {
                    "api_name": field["api_name"],
                    "labels": {"vi": "Mới"},
                    "type": "text",
                    "pd_category": "none",
                }
            )
        elif kind == "reorder":
            rng.shuffle(new["fields"])
            field = {"api_name": "order"}
        elif kind == "explicit" and fields:
            field = rng.choice(fields)
            field.setdefault("required", False)
            field.setdefault("is_unique", False)
        else:
            continue
        touched.add(field["api_name"])
        made.add(kind)
    return new, made


def test_r1_8_tighten_only_holds_exactly_when_every_change_tightens() -> None:
    """A property over 600 generated pairs: tighten-only exactly when the
    version secures a field or narrows `default_access` and changes nothing
    else; reordering and writing out a default change nothing."""
    rng = random.Random(20261104)
    seen = {True: 0, False: 0}
    for _ in range(600):
        live = _random_document(rng)
        new, made = _mutate(rng, live)
        changes = made - _NEUTRAL
        expected = bool(changes) and changes <= _TIGHTENING
        result = compare_object(live, new)
        assert result.tighten_only is expected, (made, result.differences)
        if not changes:
            assert result.differences == (), made
        seen[expected] += 1
    assert seen[True] > 50 and seen[False] > 50, seen


def test_r1_8_a_first_version_is_never_tighten_only() -> None:
    assert compare_object(None, a_document(a_field())).tighten_only is False


def test_r1_8_securing_phone_alone_tightens_and_with_a_label_does_not() -> None:
    live = a_document(a_field(pd_category="none", access_mode="open"))
    secured = a_document(a_field(pd_category="none", access_mode="secured"))
    mixed = a_document(
        a_field(pd_category="none", access_mode="secured", labels={"vi": "Điện thoại"})
    )
    assert compare_object(live, secured).tighten_only is True
    assert compare_object(live, mixed).tighten_only is False


@pytest.mark.parametrize(
    ("live_access", "new_access", "tightens"),
    [
        ("public_read_write", "public_read", True),
        ("public_read", "private", True),
        ("private", "public_read", False),
    ],
)
def test_r1_8_default_access_narrows_one_way(
    live_access: str, new_access: str, tightens: bool
) -> None:
    result = compare_object(
        a_document(a_field(), default_access=live_access),
        a_document(a_field(), default_access=new_access),
    )
    assert result.tighten_only is tightens


def test_r1_8_an_unchanged_version_is_not_tighten_only() -> None:
    """Nothing tightened, so the second person decides (decision under
    delegation, 4/11/2026)."""
    document = a_document(a_field(), a_field("email", type="email"))
    reordered = a_document(a_field("email", type="email"), a_field(required=False))
    result = compare_object(document, reordered)
    assert result.differences == ()
    assert result.tighten_only is False


# ---- definition_of and the lock key ---------------------------------------------------


def test_definition_of_is_order_and_default_blind_and_carries_the_name_row() -> None:
    first = a_document(a_field(), a_field("email", type="email"))
    second = a_document(
        a_field("email", type="email", max_length=255, required=False),
        a_field(access_mode="secured"),
    )
    definition = definition_of(first)
    assert definition == definition_of(second)
    assert set(definition.fields) == {"name", "phone", "email"}
    assert definition.fields["name"].pd_category == PdCategory.BASIC.value
    assert definition.default_access == "private"


def test_definition_of_refuses_an_invalid_document() -> None:
    with pytest.raises(DocumentInvalidError):
        definition_of({"fields": []})


def test_the_lock_key_is_one_signed_bigint_per_tenant_and_object() -> None:
    tenant, other, object_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    key = object_lock_key(tenant, object_id)
    assert key == object_lock_key(tenant, object_id)
    assert key != object_lock_key(other, object_id)
    assert -(2**63) <= key < 2**63
