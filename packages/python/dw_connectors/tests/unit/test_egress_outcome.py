"""The outcome table, HTTP and SMTP (connections-and-vault R3.13-R3.16,
R7.6-R7.8; CV26).

Every phase of the table ends in exactly one of: success, or one of the
kernel's three typed errors, and nothing else. `SmtpEgress` (ticket 05) reads
the SMTP half; the egress client the HTTP half.
"""

from __future__ import annotations

from typing import get_args

import pytest

from dw_connectors.egress.outcome import (
    Outcome,
    http_answer,
    not_dispatched,
    raise_for,
    smtp_answer,
    stopped,
)
from dw_kernel.dispatch import NotDispatchedError, OutcomeUnknownError, RejectedError

pytestmark = pytest.mark.unit

TYPED = (NotDispatchedError, RejectedError, OutcomeUnknownError)

# (phase, outcome the table gives, the class it raises or None for success)
Case = tuple[str, Outcome, type[Exception] | None]
HTTP_CASES: list[Case] = [
    ("stopped before any byte", stopped(sent=False), NotDispatchedError),
    ("stopped after a byte", stopped(sent=True), OutcomeUnknownError),
    ("200 read in full", http_answer(200), None),
    ("204 read in full", http_answer(204), None),
    ("400", http_answer(400), RejectedError),
    ("422", http_answer(422), RejectedError),
    ("499", http_answer(499), RejectedError),
    ("100", http_answer(100), OutcomeUnknownError),
    ("301 not followed", http_answer(301), OutcomeUnknownError),
    ("500", http_answer(500), OutcomeUnknownError),
    ("503", http_answer(503), OutcomeUnknownError),
]

SMTP_CASES: list[Case] = [
    ("cut before end-of-data", smtp_answer(end_of_data_sent=False, reply=None), NotDispatchedError),
    ("250 to MAIL before data", smtp_answer(end_of_data_sent=False, reply=250), NotDispatchedError),
    ("550 to RCPT", smtp_answer(end_of_data_sent=False, reply=550), RejectedError),
    ("550 after data", smtp_answer(end_of_data_sent=True, reply=550), RejectedError),
    ("451 after data", smtp_answer(end_of_data_sent=True, reply=451), RejectedError),
    ("250 after data", smtp_answer(end_of_data_sent=True, reply=250), None),
    ("timeout after data", smtp_answer(end_of_data_sent=True, reply=None), OutcomeUnknownError),
]


def _ends(outcome: Outcome, provider_code: str | None = None) -> type[Exception] | None:
    try:
        raise_for(outcome, code="why", provider_code=provider_code)
    except TYPED as error:
        assert error.details["reason_code"] == "why"
        return type(error)
    return None


@pytest.mark.parametrize(("phase", "outcome", "expected"), HTTP_CASES + SMTP_CASES)
def test_each_phase_ends_in_exactly_one_typed_result(
    phase: str, outcome: Outcome, expected: type[Exception] | None
) -> None:
    """R3.13: a `None` branch or a `RuntimeError` for a phase turns this red."""
    assert _ends(outcome) is expected, phase


def test_every_outcome_raises_its_own_class_or_returns() -> None:
    assert {o: _ends(o) for o in get_args(Outcome)} == {
        "succeeded": None,
        "not_dispatched": NotDispatchedError,
        "rejected": RejectedError,
        "outcome_unknown": OutcomeUnknownError,
    }


def test_a_rejection_carries_the_providers_code() -> None:
    """R3.16: an HTTP 422, an SMTP 550."""
    for code in ("422", "550"):
        with pytest.raises(RejectedError) as refused:
            raise_for("rejected", code="http", provider_code=code)
        assert refused.value.provider_code == code


def test_a_callers_own_refusal_did_not_leave() -> None:
    """R3.14: `credential_revoked`, raised by the caller through the table."""
    error = not_dispatched("credential_revoked")
    assert isinstance(error, NotDispatchedError)
    assert error.details == {"reason_code": "credential_revoked"}
