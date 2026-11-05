"""The refusals of a record write, each with every problem at its pointer
(custom-objects R6, R7; ADR-0108 decision 1).

Each is a `DocumentInvalidError`, so the API answers it with the one handler
that already turns problems into `errors[]`; the class says which status:
422 `validation_failed`, 403 `permission_denied` (`field_not_editable`), 409
`conflict` (`duplicate_value`). The reason a caller acts on is
`details.reason_code`, as everywhere in Studio. None names a value or another
record: a duplicate says which field, never whose record (R7.1, CO16).

`DuplicateThrottledError` is a 429 with no field at all (R7.6): the caller's
writes to the object wait until `retry_at`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final

from dw_kernel.errors import ErrorCode, QuotaExceededError
from dw_studio.core.domain.artifacts import DocumentInvalidError, DocumentProblem

FIELD_NOT_EDITABLE: Final = "field_not_editable"
FIELD_NOT_WRITABLE: Final = "field_not_writable"
DUPLICATE_VALUE: Final = "duplicate_value"
DUPLICATE_THROTTLED: Final = "duplicate_throttled"


class RecordInvalidError(DocumentInvalidError):
    """422 `validation_failed`: every value problem of one save (R6.1, R6.5, R6.7)."""


class FieldNotEditableError(DocumentInvalidError):
    """403: the save names a field the caller may not write (R6.6, CO7)."""

    code = ErrorCode.PERMISSION_DENIED

    def __init__(self, problems: Sequence[DocumentProblem]) -> None:
        super().__init__("the caller may not write these fields", problems)
        self.details["reason_code"] = FIELD_NOT_EDITABLE


class DuplicateValueError(DocumentInvalidError):
    """409: a unique field's value is already another record's (R7.1, R7.4)."""

    code = ErrorCode.CONFLICT

    def __init__(self, at: str) -> None:
        super().__init__(
            "a record of this object already holds this value",
            [DocumentProblem(at, DUPLICATE_VALUE, "the value is already taken")],
        )
        self.details["reason_code"] = DUPLICATE_VALUE


class DuplicateThrottledError(QuotaExceededError):
    """429: the caller met `duplicate_value` too often on this object (R7.6)."""

    def __init__(self, retry_at: datetime | None, now: datetime, window: timedelta) -> None:
        super().__init__(
            "too many duplicate values on this object; try again later",
            details={"reason_code": DUPLICATE_THROTTLED},
        )
        self.retry_at = retry_at
        # Whole seconds until the oldest refusal leaves the window, at least
        # one; the whole window when no wait would help (`retry_at` None).
        wait = window if retry_at is None else retry_at - now
        self.retry_after_seconds = max(1, math.ceil(wait.total_seconds()))
