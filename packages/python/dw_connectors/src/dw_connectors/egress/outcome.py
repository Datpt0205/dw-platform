"""How a call that left, or did not, ends: one table for HTTP and SMTP
(connections-and-vault R3.13-R3.16, R7.6-R7.8; ADR-0115 decision 6; V4.30).

Every call ends in exactly one of four outcomes, decided by the phase it
stopped in, never by the type of exception a library happened to raise:

| Phase                                                        | Outcome           |
| ------------------------------------------------------------ | ----------------- |
| stopped before the first byte of the first request was       | `not_dispatched`  |
| written (resolving, connecting, TLS, an `egress_blocked:*`   |                   |
| refusal, the caller's own `credential_revoked`); SMTP:       |                   |
| before the end-of-data marker of `DATA`                      |                   |
| HTTP: a 4xx read in full; SMTP: a 4yz or 5yz reply           | `rejected`        |
| HTTP: stopped after that byte without a 2xx or 4xx read in   | `outcome_unknown` |
| full within the cap (a timeout, a reset, a 5xx, a 3xx not    |                   |
| followed, a redirect refused at a later step, a body over    |                   |
| the cap); SMTP: end-of-data sent and no 250                  |                   |
| HTTP: a 2xx read in full within the cap; SMTP: 250 after     | `succeeded`       |
| end-of-data                                                  |                   |

`raise_for` turns the first three into the kernel's typed errors, the only
error classes the egress client raises about a send. An error this table does
not know is not this module's to classify: it propagates, and the ToolExecutor
records it `outcome_unknown` (runtime-hardening R6.12).
"""

from __future__ import annotations

from typing import Literal

from dw_kernel.dispatch import NotDispatchedError, OutcomeUnknownError, RejectedError

__all__ = [
    "Outcome",
    "http_answer",
    "not_dispatched",
    "raise_for",
    "smtp_answer",
    "stopped",
]

Outcome = Literal["succeeded", "not_dispatched", "rejected", "outcome_unknown"]


def stopped(*, sent: bool) -> Outcome:
    """A call that ended without an answer read in full: certain only while no
    byte of a request was written."""
    return "outcome_unknown" if sent else "not_dispatched"


def http_answer(status: int) -> Outcome:
    """A status whose body was read in full within the cap."""
    if 200 <= status < 300:
        return "succeeded"
    if 400 <= status < 500:
        return "rejected"
    return "outcome_unknown"


def smtp_answer(*, end_of_data_sent: bool, reply: int | None) -> Outcome:
    """The last reply of an SMTP exchange, and whether the end-of-data marker of
    `DATA` was written before it ended (None: no reply was read)."""
    if reply is not None and 400 <= reply < 600:
        return "rejected"
    if not end_of_data_sent:
        return "not_dispatched"
    if reply == 250:
        return "succeeded"
    return "outcome_unknown"


def raise_for(outcome: Outcome, *, code: str, provider_code: str | None = None) -> None:
    """Raise the typed error of a call that did not succeed; return for one that did.

    `code` is the stop's reason (`details.reason_code`); `provider_code` the
    status or reply a rejection carries (an HTTP 422, an SMTP 550).
    """
    if outcome == "succeeded":
        return
    if outcome == "not_dispatched":
        raise not_dispatched(code)
    details: dict[str, object] = {"reason_code": code}
    if outcome == "rejected":
        raise RejectedError(
            "the provider refused the call", provider_code=provider_code or code, details=details
        )
    raise OutcomeUnknownError("the call may have been applied", details=details)


def not_dispatched(code: str) -> NotDispatchedError:
    """A stop before any byte: the table's own, and a caller's refusal before
    it calls (`credential_revoked`, R3.14)."""
    return NotDispatchedError("the call did not leave", details={"reason_code": code})
