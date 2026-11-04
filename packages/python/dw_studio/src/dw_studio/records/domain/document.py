"""`dw.object/v1`: the document an `object` artifact's versions carry, and what
it decides once applied.

One parse (`parse_object`) for every reader: the validator, the live check,
the comparator and the publish hook all read a document through it, defaults
filled, so a value written out and the same value left to its default are the
same document (custom-objects ticket 02 step 4). The object's API name is not
here: it is the envelope's `studio.artifacts.api_name` (tenant-config R2.2,
R2.10), and the model refuses one at the root (`extra="forbid"`).

`pd_category` has no valid default. It reads as None when the document leaves
it out, which `classification_problems` of `dw_kernel.personal_data` names
`pd_category_required`: never a silent `none` (ADR-0106 decision 1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, ValidationError

from dw_kernel.personal_data import PdCategory, SensitiveType, SubjectIdentifierKind
from dw_studio.core.domain.artifacts import DocumentInvalidError, DocumentProblem
from dw_studio.records.domain.field_types import TEXT_LIKE

OBJECT_KIND: Final = "object"
OBJECT_DOCUMENT_SCHEMA: Final = "dw.object/v1"

CompanyFieldType = Literal[
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
]
NumberMode = Literal["exact", "float"]
AccessMode = Literal["open", "secured"]
DefaultAccess = Literal["private", "public_read", "public_read_write"]

# Narrower first (R1.8): a later entry opens more.
DEFAULT_ACCESS_ORDER: Final[tuple[DefaultAccess, ...]] = (
    "private",
    "public_read",
    "public_read_write",
)
# Lower first (R2.5): `sensitive`, `basic`, `none` is the order of lowering.
PD_ORDER: Final[tuple[PdCategory, ...]] = (PdCategory.NONE, PdCategory.BASIC, PdCategory.SENSITIVE)

# The text-like default length and the exact-number default scale, filled by
# the parse so that writing them out changes nothing (R1.8).
DEFAULT_MAX_LENGTH: Final = 255
DEFAULT_SCALE: Final = 0


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Labels(_Model):
    vi: StrictStr
    en: StrictStr | None = None

    def as_json(self) -> dict[str, str]:
        return {"vi": self.vi} if self.en is None else {"vi": self.vi, "en": self.en}


class OptionDocument(_Model):
    key: StrictStr
    labels: Labels
    position: StrictInt
    active: StrictBool = True


class NameField(_Model):
    """The record's `name`: its labels and personal-data category, both stated."""

    labels: Labels
    pd_category: PdCategory | None = None
    sensitive_type: SensitiveType | None = None
    subject_identifier: SubjectIdentifierKind | None = None


class FieldDocument(_Model):
    api_name: StrictStr
    labels: Labels
    ai_description: StrictStr | None = None
    type: CompanyFieldType
    number_mode: NumberMode | None = None
    scale: StrictInt | None = None
    currency_code: StrictStr | None = None
    max_length: StrictInt | None = None
    required: StrictBool = False
    is_unique: StrictBool = False
    indexed: StrictBool = False
    pd_category: PdCategory | None = None
    sensitive_type: SensitiveType | None = None
    subject_identifier: SubjectIdentifierKind | None = None
    # Filled by the parse: `secured` unless the field holds no personal data
    # (ADR-0106 decision 2). field-security/01 adds its column.
    access_mode: AccessMode | None = None
    options: tuple[OptionDocument, ...] = ()

    @property
    def filters(self) -> bool:
        """Lives in a slot: filterable and sortable (ADR-0107 decision 1)."""
        return self.indexed or self.is_unique

    @property
    def holds_scale(self) -> bool:
        return self.type == "currency" or (self.type == "number" and self.number_mode == "exact")


class ObjectDocument(_Model):
    labels: Labels
    ai_description: StrictStr | None = None
    default_access: DefaultAccess = "private"
    name_field: NameField
    fields: tuple[FieldDocument, ...] = ()


# ---- the parse ----------------------------------------------------------------

_CODES: Final[Mapping[str, str]] = {
    "missing": "required",
    "extra_forbidden": "not_allowed",
    "literal_error": "value_not_allowed",
    "enum": "value_not_allowed",
}


def _pointer(location: tuple[int | str, ...]) -> str:
    parts = (str(part).replace("~", "~0").replace("/", "~1") for part in location)
    return "".join(f"/{part}" for part in parts)


def _problems(error: ValidationError) -> list[DocumentProblem]:
    # A fixed sentence per code, never pydantic's message: it may echo the value.
    return [
        DocumentProblem(
            _pointer(tuple(item["loc"])),
            _CODES.get(item["type"], "wrong_type"),
            "the value is not one this document takes",
        )
        for item in error.errors()
    ]


def _filled(field: FieldDocument) -> FieldDocument:
    values: dict[str, Any] = {}
    if field.access_mode is None:
        values["access_mode"] = "open" if field.pd_category is PdCategory.NONE else "secured"
    if field.type in TEXT_LIKE and field.max_length is None:
        values["max_length"] = DEFAULT_MAX_LENGTH
    if field.holds_scale and field.scale is None:
        values["scale"] = DEFAULT_SCALE
    return field.model_copy(update=values) if values else field


def parse_object(document: Any) -> ObjectDocument:
    """The document, defaults filled; `DocumentInvalidError` with every
    structural problem at its pointer otherwise."""
    try:
        parsed = ObjectDocument.model_validate(document)
    except ValidationError as exc:
        raise DocumentInvalidError("the object document is not valid", _problems(exc)) from None
    return parsed.model_copy(update={"fields": tuple(_filled(f) for f in parsed.fields)})


# ---- what a document decides --------------------------------------------------


@dataclass(frozen=True, slots=True)
class OptionDefinition:
    key: str
    labels: Mapping[str, str]
    position: int
    active: bool


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    """Every attribute of a field the document decides and `studio.field_defs`
    has a column for (`access_mode` joins with field-security/01's column)."""

    api_name: str
    type: str
    labels: Mapping[str, str]
    ai_description: str | None
    number_mode: str | None
    scale: int | None
    currency_code: str | None
    max_length: int | None
    required: bool
    is_unique: bool
    indexed: bool
    pd_category: str
    sensitive_type: str | None
    subject_identifier: str | None
    options: tuple[OptionDefinition, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentDefinition:
    """What one document decides of an object, keyed by `api_name` and `key`:
    no id, slot, field number or time. The definition store reads back the same
    shape, so an apply is checked by equality (R1.1)."""

    labels: Mapping[str, str]
    ai_description: str | None
    default_access: str
    fields: Mapping[str, FieldDefinition] = field(default_factory=dict)


NAME: Final = "name"
OWNER: Final = "owner"
WORKSPACE: Final = "workspace"
SYSTEM_FIELDS: Final = frozenset({NAME, OWNER, WORKSPACE})


def name_definition(name_field: NameField) -> FieldDefinition:
    """The `name` system row the document decides, from its `name_field`; the
    one owner of that shape, which the hook writes and `definition_of` reads."""
    return FieldDefinition(
        api_name=NAME,
        type="text",
        labels=name_field.labels.as_json(),
        ai_description=None,
        number_mode=None,
        scale=None,
        currency_code=None,
        max_length=DEFAULT_MAX_LENGTH,
        required=True,
        is_unique=False,
        indexed=False,
        pd_category=_category(name_field.pd_category),
        sensitive_type=_value(name_field.sensitive_type),
        subject_identifier=_value(name_field.subject_identifier),
    )


def field_definition(field: FieldDocument) -> FieldDefinition:
    return FieldDefinition(
        api_name=field.api_name,
        type=field.type,
        labels=field.labels.as_json(),
        ai_description=field.ai_description,
        number_mode=field.number_mode,
        scale=field.scale,
        currency_code=field.currency_code,
        max_length=field.max_length,
        required=field.required,
        is_unique=field.is_unique,
        indexed=field.indexed,
        pd_category=_category(field.pd_category),
        sensitive_type=_value(field.sensitive_type),
        subject_identifier=_value(field.subject_identifier),
        options=tuple(
            OptionDefinition(o.key, o.labels.as_json(), o.position, o.active)
            for o in sorted(field.options, key=lambda option: option.key)
        ),
    )


def definition_of(document: Any) -> DocumentDefinition:
    """R1.1: what the version's document decides, to compare with what the
    store holds after an apply. `owner` and `workspace` are not the document's."""
    parsed = parse_object(document)
    fields = {NAME: name_definition(parsed.name_field)}
    fields.update((f.api_name, field_definition(f)) for f in parsed.fields)
    return DocumentDefinition(
        labels=parsed.labels.as_json(),
        ai_description=parsed.ai_description,
        default_access=parsed.default_access,
        fields=fields,
    )


def _category(category: PdCategory | None) -> str:
    # Only a validated document reaches a definition; a missing category reads
    # as the strictest, never as `none` (failure-modes #7).
    return (category or PdCategory.SENSITIVE).value


def _value(member: SensitiveType | SubjectIdentifierKind | None) -> str | None:
    return None if member is None else member.value
