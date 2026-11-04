"""Bindings for a test that runs the door or the seal (tenant-config ticket 05).

`unasked_pins()` is the door's `BindingPins` for a suite whose roots declare no
binding: its connection rule is never asked, and says so if it is, rather than
answering yes (`.claude/rules/code-quality.md`, a fake honours its contract).
A suite that binds connections passes the real `ConnectionUsability`.
"""

from __future__ import annotations

import uuid

from dw_platform.application.connections import Usability, UsableContext
from dw_studio.core.application.bindings import BindingPins, platform_binding_types


class UnaskedUsability:
    async def connection_usable(
        self, connection: uuid.UUID, context: UsableContext, purpose: str
    ) -> Usability:
        raise NotImplementedError("not exercised: this suite's roots bind no connection")


def unasked_pins() -> BindingPins:
    usability = UnaskedUsability()
    return BindingPins(platform_binding_types(usability), usability)
