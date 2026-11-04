"""A tenant secret's value, held so that printing it prints nothing.

`Secret` is how a secret travels between the credential broker
(`dw_platform.application.secrets.SecretStore`) and the one call that needs it:
`repr`, `str` and `format` show a mask, JSON and pickle refuse it, so a log
line, an exception message, a checkpoint or an audit row that picks one up by
accident carries `***`, not the value (connections-and-vault R1.2, CV4).

`reveal()` is the one way out, and only the modules an architecture test lists
may call it (`test_secret_reveal_scan.py`); each addition is a decision.
"""

from __future__ import annotations

from typing import Any, NoReturn, final

_MASK = "***"


@final
class Secret:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("a Secret holds text")
        self._value = value

    def reveal(self) -> str:
        """The value. Called only from the modules the reveal scan allows."""
        return self._value

    def __repr__(self) -> str:
        return f"Secret({_MASK!r})"

    def __str__(self) -> str:
        return _MASK

    def __format__(self, format_spec: str) -> str:
        return format(_MASK, format_spec)

    def __reduce_ex__(self, protocol: Any) -> NoReturn:
        # Pickle, copy and every checkpoint serialiser built on them: a value
        # that must not be stored is refused rather than stored.
        raise TypeError("a Secret is not serialised")
