"""The mode a run runs in, set by the server and kept for its life
(tenant-config R4; ADR-0111 decisions 1-3).

- `live`: tools act on the world. A published version's triggers and a
  person's manual run of it, and a worker's code-defined graph.
- `test`: W2's run against a list of test recipients; in W1 it is simulated
  like `simulate` (DO-26.1), and the test-runs route refuses it.
- `simulate`: every tool call that is not `simulate_safe` is intercepted at
  the ToolExecutor and answered with a sample (R5).

A child run never runs looser than its parent (`child_mode`).
"""

from __future__ import annotations

from typing import Literal

RunMode = Literal["live", "test", "simulate"]

# Strictest first: a child takes whichever of its parent's and its own
# request comes first.
_ORDER: tuple[RunMode, ...] = ("simulate", "test", "live")


def child_mode(parent: RunMode, requested: RunMode) -> RunMode:
    """R4.4: the stricter of the parent's mode and the one asked for."""
    return parent if _ORDER.index(parent) <= _ORDER.index(requested) else requested


__all__ = ["RunMode", "child_mode"]
