"""The three typed answers about a send that did not simply succeed
(ADR-0115 decision 6; V4.30; runtime-hardening/01 step 3).

What a handler raises once its send has begun, read by the ToolExecutor to
write the terminal row and by the node wrapper to decide whether a retry is
safe. They live in the kernel, beside `DWError`, because two packages that do
not depend on each other raise them: the agent runtime (`dw_agent_runtime.
dispatch` re-exports these very classes) and the egress client in
`dw_connectors`, which the runtime depends on, so it cannot import from it
(connections-and-vault R3.13).

They carry an `outcome` and the existing `upstream_unavailable` code:
`ErrorCode` is the API's public contract (ADR-0108 decision 1), and these are a
runtime's answer about a send, not a new kind of API error. The reason, where
there is one, is `details["reason_code"]`.
"""

from __future__ import annotations

from typing import Literal

from dw_kernel.errors import DWError, ErrorCode

__all__ = [
    "DispatchOutcome",
    "NotDispatchedError",
    "OutcomeUnknownError",
    "RejectedError",
]

DispatchOutcome = Literal["not_dispatched", "rejected", "outcome_unknown"]


class NotDispatchedError(DWError):
    """Certain that no byte left: the send may be made again with the same key."""

    code = ErrorCode.UPSTREAM_UNAVAILABLE
    outcome: DispatchOutcome = "not_dispatched"


class RejectedError(DWError):
    """The provider answered that it did not apply the call, with its own code."""

    code = ErrorCode.UPSTREAM_UNAVAILABLE
    outcome: DispatchOutcome = "rejected"

    def __init__(
        self, message: str, *, provider_code: str, details: dict[str, object] | None = None
    ) -> None:
        super().__init__(message, details=details)
        self.provider_code = provider_code


class OutcomeUnknownError(DWError):
    """The call may have been applied; nobody may send it again without a person."""

    code = ErrorCode.UPSTREAM_UNAVAILABLE
    outcome: DispatchOutcome = "outcome_unknown"
