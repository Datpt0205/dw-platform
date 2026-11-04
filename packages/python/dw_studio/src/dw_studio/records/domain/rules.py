"""The rules over one `dw.object/v1` document, or a version and the live one.

Three pure functions, each returning every problem at once with its pointer
(app-standards R1.3):

- `validate_object`: the registry's `validate`, which `seal` runs, so its
  problems are a 422 `validation_failed` and no version number is given;
- `check_against_live`: what a version may not change of the live one (R2.4,
  R2.5, CO6, CO24); the publish hook runs it as the last fence and ticket 06
  registers it at submit (agent-lifecycle R2.7);
- `compare_object`: the kind's comparator (R1.8), which says whether a
  version only tightens.

Fields are matched by `api_name` and options by `key`; order counts for
nothing (custom-objects ticket 02 step 4).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from dw_kernel.personal_data import (
    ClassificationCode,
    ClassificationProblem,
    PdCategory,
    classification_problems,
)
from dw_studio.core.domain.artifacts import (
    API_NAME,
    DocumentInvalidError,
    DocumentProblem,
    Reference,
)
from dw_studio.records.domain.document import (
    DEFAULT_ACCESS_ORDER,
    PD_ORDER,
    SYSTEM_FIELDS,
    FieldDocument,
    ObjectDocument,
    OptionDocument,
    parse_object,
)
from dw_studio.records.domain.field_types import SLOTS, TEXT_LIKE, family_of

MAX_AI_DESCRIPTION: Final = 500
_OPTION_KEY: Final = re.compile(r"^[a-z0-9_]{1,40}$")
_CURRENCY: Final = re.compile(r"^[A-Z]{3}$")
# What a published field keeps (R2.4, CO6): the meaning of a stored value.
IMMUTABLE_ATTRIBUTES: Final = (
    "type",
    "number_mode",
    "scale",
    "currency_code",
    "is_unique",
    "indexed",
)


class ObjectVersionRejected(DocumentInvalidError):  # noqa: N818 - the name the spec gives it
    """The publish hook's refusal: the version would change what the live one
    published (R2.4, R2.5) or has no slot left (R1.6). A 422 with every
    problem, and the publish transaction rolls back (ADR-0109 decision 1)."""


def _problem(pointer: str, code: str, detail: str) -> DocumentProblem:
    return DocumentProblem(pointer, code, detail)


def _nfc_length(text: str) -> int:
    return len(unicodedata.normalize("NFC", text))


# ---- one document ---------------------------------------------------------------


def _label_problems(labels_vi: str, at: str) -> list[DocumentProblem]:
    if labels_vi.strip():
        return []
    return [_problem(f"{at}/labels/vi", "label_vi_required", "a Vietnamese label is required")]


def _ai_description_problems(text: str | None, at: str) -> list[DocumentProblem]:
    if text is None or _nfc_length(text) <= MAX_AI_DESCRIPTION:
        return []
    return [
        _problem(
            f"{at}/ai_description",
            "ai_description_too_long",
            f"at most {MAX_AI_DESCRIPTION} characters",
        )
    ]


def _classification(problems: Iterable[ClassificationProblem]) -> list[DocumentProblem]:
    found = []
    for item in problems:
        pointer = item.pointer
        # The name field's missing category points at its own key (R2.2).
        if item.code is ClassificationCode.PD_CATEGORY_REQUIRED and pointer == "/name_field":
            pointer = "/name_field/pd_category"
        found.append(_problem(pointer, item.code.value, item.detail))
    return found


def _option_problems(field: FieldDocument, at: str) -> list[DocumentProblem]:
    found: list[DocumentProblem] = []
    if field.type != "picklist":
        if field.options:
            found.append(
                _problem(f"{at}/options", "attribute_not_allowed", "only a picklist has options")
            )
        return found
    if not field.options:
        found.append(_problem(f"{at}/options", "options_required", "a picklist has options"))
    seen: set[str] = set()
    for m, option in enumerate(field.options):
        here = f"{at}/options/{m}"
        if not _OPTION_KEY.fullmatch(option.key):
            found.append(_problem(f"{here}/key", "option_key_invalid", "1-40 of [a-z0-9_]"))
        elif option.key in seen:
            found.append(_problem(f"{here}/key", "option_key_repeated", "each key once"))
        seen.add(option.key)
        if option.position < 0:
            found.append(_problem(f"{here}/position", "position_invalid", "a position is >= 0"))
        found += _label_problems(option.labels.vi, here)
    return found


def _attribute_problems(field: FieldDocument, at: str) -> list[DocumentProblem]:
    """Each attribute against its type, so no validated document breaks a
    CHECK of `studio.field_defs` after its approval (gate, 3/11/2026)."""
    found: list[DocumentProblem] = []

    def not_allowed(name: str) -> None:
        found.append(
            _problem(f"{at}/{name}", "attribute_not_allowed", f"a {field.type} has no {name}")
        )

    if field.type == "number":
        if field.number_mode is None:
            found.append(_problem(f"{at}/number_mode", "number_mode_required", "exact or float"))
    elif field.number_mode is not None:
        not_allowed("number_mode")
    if field.scale is not None:
        if not field.holds_scale:
            not_allowed("scale")
        elif not 0 <= field.scale <= 6:
            found.append(_problem(f"{at}/scale", "scale_out_of_range", "a scale is 0 to 6"))
    if field.type == "currency":
        if field.currency_code is None or not _CURRENCY.fullmatch(field.currency_code):
            found.append(
                _problem(f"{at}/currency_code", "currency_code_invalid", "three capital letters")
            )
    elif field.currency_code is not None:
        not_allowed("currency_code")
    if field.max_length is not None:
        if field.type not in TEXT_LIKE:
            not_allowed("max_length")
        elif not 1 <= field.max_length <= 255:
            found.append(
                _problem(f"{at}/max_length", "max_length_out_of_range", "1 to 255 characters")
            )
    if field.is_unique and field.type not in TEXT_LIKE:
        found.append(
            _problem(
                f"{at}/is_unique",
                "unique_not_supported",
                "only text, email, phone and url are unique",
            )
        )
    return found


def _slot_budget(fields: Sequence[FieldDocument]) -> list[DocumentProblem]:
    """R1.6, counted on the document: in W1 no field is removed, so the
    document holds every field the object ever published."""
    used: dict[str, int] = {}
    found: list[DocumentProblem] = []
    for n, field in enumerate(fields):
        if not field.filters:
            continue
        family = family_of(field.type, number_mode=field.number_mode, is_unique=field.is_unique)
        if family is None:
            continue
        used[family] = used.get(family, 0) + 1
        if used[family] > len(SLOTS[family]):
            found.append(
                _problem(
                    f"/fields/{n}",
                    "slot_budget_exceeded",
                    f"the object has {len(SLOTS[family])} slots of family {family}",
                )
            )
    return found


def document_problems(document: ObjectDocument) -> list[DocumentProblem]:
    found = _label_problems(document.labels.vi, "")
    found += _ai_description_problems(document.ai_description, "")
    found += _label_problems(document.name_field.labels.vi, "/name_field")
    found += _classification(classification_problems([("/name_field", document.name_field)]))
    names: set[str] = set()
    for n, field in enumerate(document.fields):
        at = f"/fields/{n}"
        if not API_NAME.fullmatch(field.api_name):
            found.append(
                _problem(f"{at}/api_name", "api_name_invalid", "2-40 of [a-z0-9_], a letter first")
            )
        elif field.api_name in SYSTEM_FIELDS:
            found.append(
                _problem(f"{at}/api_name", "reserved_api_name", "the name is a system field's")
            )
        elif field.api_name in names:
            found.append(_problem(f"{at}/api_name", "api_name_repeated", "each name once"))
        names.add(field.api_name)
        found += _label_problems(field.labels.vi, at)
        found += _ai_description_problems(field.ai_description, at)
        found += _attribute_problems(field, at)
        found += _option_problems(field, at)
        # R2.5: a sensitive field is never open (ADR-0106 decision 2).
        if field.pd_category is PdCategory.SENSITIVE and field.access_mode == "open":
            found.append(
                _problem(
                    f"{at}/access_mode", "sensitive_field_open", "a sensitive field is secured"
                )
            )
    found += _classification(
        classification_problems((f"/fields/{n}", f) for n, f in enumerate(document.fields))
    )
    found += _slot_budget(document.fields)
    return found


def validate_object(document: Any) -> list[DocumentProblem]:
    """The registry's `validate` for `object`: pure, every problem at once."""
    try:
        parsed = parse_object(document)
    except DocumentInvalidError as exc:
        return list(exc.problems)
    return document_problems(parsed)


def extract_object(document: Any) -> list[Reference]:
    """The registry's `extract` for `object`: W1 has no reference field, so an
    object uses nothing else; the lookup fields of W2 add theirs here."""
    del document
    return []


# ---- a version against the live one -------------------------------------------


def _lowered(live: PdCategory | None, new: PdCategory | None) -> bool:
    if live is None or new is None:
        return False
    return PD_ORDER.index(new) < PD_ORDER.index(live)


def _by_name(document: ObjectDocument) -> dict[str, tuple[int, FieldDocument]]:
    return {field.api_name: (n, field) for n, field in enumerate(document.fields)}


def live_problems(live: ObjectDocument | None, new: ObjectDocument) -> list[DocumentProblem]:
    found: list[DocumentProblem] = []
    published = {} if live is None else _by_name(live)
    proposed = _by_name(new)
    for api_name in published:
        if api_name not in proposed:
            found.append(
                _problem("/fields", "field_removed", f"the published field {api_name} is missing")
            )
    if live is not None and _lowered(live.name_field.pd_category, new.name_field.pd_category):
        found.append(
            _problem(
                "/name_field/pd_category",
                "pd_category_lowered",
                "a published category is not lowered",
            )
        )
    for api_name, (n, field) in proposed.items():
        at = f"/fields/{n}"
        if api_name not in published:
            # CO24: a new field holding personal data starts secured.
            if field.pd_category is not PdCategory.NONE and field.access_mode == "open":
                found.append(
                    _problem(
                        f"{at}/access_mode",
                        "personal_data_field_open",
                        "a new field with personal data starts secured",
                    )
                )
            continue
        _, before = published[api_name]
        found += [
            _problem(f"{at}/{name}", "field_immutable", f"{name} of a published field is fixed")
            for name in IMMUTABLE_ATTRIBUTES
            if getattr(before, name) != getattr(field, name)
        ]
        if _lowered(before.pd_category, field.pd_category):
            found.append(
                _problem(
                    f"{at}/pd_category",
                    "pd_category_lowered",
                    "a published category is not lowered",
                )
            )
        keys = {option.key for option in field.options}
        found += [
            _problem(f"{at}/options", "option_removed", f"the published option {o.key} is missing")
            for o in before.options
            if o.key not in keys
        ]
    return found


def check_against_live(live_document: Any | None, document: Any) -> list[DocumentProblem]:
    """R2.4, R2.5 (CO6, CO24): every problem at once; None for the live one
    when the object has none, and then every field is new."""
    try:
        new = parse_object(document)
    except DocumentInvalidError as exc:
        return list(exc.problems)
    live = None if live_document is None else parse_object(live_document)
    return live_problems(live, new)


# ---- the comparator -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Difference:
    """One thing a version changes of the live one, and whether it tightens."""

    pointer: str
    tightens: bool


@dataclass(frozen=True, slots=True)
class Comparison:
    has_live: bool
    differences: tuple[Difference, ...]

    @property
    def tighten_only(self) -> bool:
        """R1.8: a live version exists and every difference secures a field or
        narrows `default_access`. A version that changes nothing tightens
        nothing, so it is not tighten-only and takes the second person."""
        return (
            self.has_live
            and bool(self.differences)
            and all(difference.tightens for difference in self.differences)
        )


def _options(options: Iterable[OptionDocument]) -> dict[str, Any]:
    return {o.key: o.model_dump() for o in options}


def _field_view(field: FieldDocument) -> dict[str, Any]:
    view = field.model_dump(exclude={"options", "access_mode"})
    view["options"] = _options(field.options)
    return view


def _changed(live: Mapping[str, Any], new: Mapping[str, Any], at: str) -> list[Difference]:
    return [
        Difference(f"{at}/{key}", tightens=False)
        for key in sorted(set(live) | set(new))
        if live.get(key) != new.get(key)
    ]


def compare_object(live_document: Any | None, document: Any) -> Comparison:
    """The kind's comparator, over parsed documents (defaults filled, fields by
    `api_name`, options by `key`)."""
    new = parse_object(document)
    if live_document is None:
        return Comparison(has_live=False, differences=())
    live = parse_object(live_document)
    found: list[Difference] = []
    if new.default_access != live.default_access:
        narrower = DEFAULT_ACCESS_ORDER.index(new.default_access) < DEFAULT_ACCESS_ORDER.index(
            live.default_access
        )
        found.append(Difference("/default_access", tightens=narrower))
    found += _changed(
        live.model_dump(include={"labels", "ai_description", "name_field"}),
        new.model_dump(include={"labels", "ai_description", "name_field"}),
        "",
    )
    published, proposed = _by_name(live), _by_name(new)
    for api_name in sorted(set(published) | set(proposed)):
        if api_name not in published or api_name not in proposed:
            found.append(Difference(f"/fields/{api_name}", tightens=False))
            continue
        before, after = published[api_name][1], proposed[api_name][1]
        at = f"/fields/{api_name}"
        found += _changed(_field_view(before), _field_view(after), at)
        if before.access_mode != after.access_mode:
            found.append(
                Difference(
                    f"{at}/access_mode",
                    tightens=before.access_mode == "open" and after.access_mode == "secured",
                )
            )
    return Comparison(has_live=True, differences=tuple(found))
