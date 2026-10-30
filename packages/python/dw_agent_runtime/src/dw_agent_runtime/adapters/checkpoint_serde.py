"""What a run checkpoint may rebuild as an object (foundations-hardening R2.5, FH6).

ADR-0112 decision 10: the composition root builds the checkpoint serializer
with an explicit ``allowed_msgpack_modules`` and injects it; the process-wide
``LANGGRAPH_STRICT_MSGPACK`` flag is not used. A type outside LangGraph's own
safe set and outside ``ALLOWED`` loads as plain data, never as an object of
that type: a row in ``platform.run_checkpoints`` is not trusted to name the
classes the process constructs.

``ALLOWED`` was measured, not guessed (FOG-37): the integration suites of
``dw_agent_runtime``, ``apps/worker`` and ``apps/api`` were run with a recorder
on LangGraph's serde events, and no type outside the safe set was loaded
(foundations-hardening ticket 02, Comments of 2026-10-29). A context whose graph
state holds a type of its own adds its ``(module, name)`` pair here, with the
test that loads it.

Here rather than in one app (moved from `dw_api.bootstrap`, wf-lite/02): the
API resumes a wf-lite run a person decided, the worker one its timer woke, and
each reads checkpoints the other wrote. Two allowlists would be two answers to
what a checkpoint may rebuild.
"""

from __future__ import annotations

from dw_agent_runtime.adapters.checkpoint import SerializerProtocol, allowlisted_serializer

ALLOWED: tuple[tuple[str, str], ...] = ()


def checkpoint_serializer() -> SerializerProtocol:
    return allowlisted_serializer(ALLOWED)
