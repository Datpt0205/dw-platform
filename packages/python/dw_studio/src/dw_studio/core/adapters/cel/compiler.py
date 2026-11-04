"""Compiling a source against an environment, with the two per-process caches
every process that compiles keeps: the caller, which checks, and each
evaluator, which evaluates (workflow-nodes 01 step 2; ADR-0114 decision 4).

Both caches are keyed by the tenant first (R3.7; `CLAUDE.md`, Tenancy: cache
keys include the tenant): two tenants with the same source and the same
variables hold two entries, never one.
"""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import NamedTuple

from cel_expr_python import cel

from dw_kernel.expressions import (
    DW_CEL_LIBRARY,
    ExpressionEnv,
    ExpressionIssue,
    IssueKind,
)
from dw_studio.core.adapters.cel.library import library_extensions
from dw_studio.core.adapters.cel.schema import BoundSchema, bind_schema

CACHE_ENTRIES = 10_000
MAX_SOURCE_BYTES = 2048


class EnvKey(NamedTuple):
    tenant_id: str | None
    library: str
    env_hash: str


class ProgramKey(NamedTuple):
    tenant_id: str | None
    library: str
    env_hash: str
    source_sha256: str


def env_key(env: ExpressionEnv) -> EnvKey:
    tenant = None if env.tenant_id is None else str(env.tenant_id)
    return EnvKey(tenant, env.library, env.env_hash())


def program_key(source: str, env: ExpressionEnv) -> ProgramKey:
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return ProgramKey(*env_key(env), digest)


class LruCache[K, V]:
    """A bounded least-recently-used map."""

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._entries: OrderedDict[K, V] = OrderedDict()

    def get(self, key: K) -> V | None:
        value = self._entries.get(key)
        if value is not None:
            self._entries.move_to_end(key)
        return value

    def put(self, key: K, value: V) -> None:
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    def keys(self) -> list[K]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


@dataclass(frozen=True, slots=True)
class BoundEnv:
    schema: BoundSchema
    env: cel.Env


class CompileError(Exception):
    def __init__(self, issues: list[ExpressionIssue]) -> None:
        super().__init__(f"{len(issues)} issue(s)")
        self.issues = issues


def require_library(env: ExpressionEnv) -> None:
    """An environment naming a library this adapter does not ship is a
    programming error."""
    if env.library != DW_CEL_LIBRARY:
        raise ValueError(
            f"library {env.library!r} is not shipped; this adapter has {DW_CEL_LIBRARY!r}"
        )


class Compiler:
    """The bound environments and compiled programs of one process."""

    def __init__(self, capacity: int = CACHE_ENTRIES) -> None:
        self._envs: LruCache[EnvKey, BoundEnv] = LruCache(capacity)
        self._programs: LruCache[ProgramKey, cel.Expression] = LruCache(capacity)

    def program_keys(self) -> list[ProgramKey]:
        return self._programs.keys()

    def bound(self, env: ExpressionEnv) -> BoundEnv:
        key = env_key(env)
        bound = self._envs.get(key)
        if bound is None:
            schema = bind_schema(env)
            binding_env = cel.NewEnv(
                descriptor_pool=schema.pool,
                variables=dict(schema.variables),
                extensions=library_extensions(),
            )
            bound = BoundEnv(schema, binding_env)
            self._envs.put(key, bound)
        return bound

    def compile(self, source: str, env: ExpressionEnv) -> tuple[cel.Expression, BoundEnv]:
        """The compiled program, or `CompileError` with its issues."""
        require_library(env)
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise CompileError(
                [
                    ExpressionIssue(
                        "source_too_large",
                        None,
                        None,
                        None,
                        f"source is over {MAX_SOURCE_BYTES} bytes",
                    )
                ]
            )
        bound = self.bound(env)
        key = program_key(source, env)
        program = self._programs.get(key)
        if program is None:
            try:
                program = bound.env.compile(source)
            except RuntimeError as exc:
                raise CompileError(parse_issues(str(exc))) from None
            self._programs.put(key, program)
        return program, bound


# ---------------------------------------------------------------------------
# Compile errors, by the text the binding writes (measured on 0.1.3). A binding
# that changes its wording turns a case of the contract suite red instead of
# filing an issue under the wrong kind (failure-modes #4).
# ---------------------------------------------------------------------------

_LOCATED = re.compile(r"ERROR: <input>:(-?\d+):(-?\d+): (.*)")
_KINDS: tuple[tuple[re.Pattern[str], IssueKind], ...] = (
    (re.compile(r"Syntax error"), "syntax"),
    (re.compile(r"undeclared reference to '([^']*)'"), "undeclared_reference"),
    (re.compile(r"undefined field '([^']*)'"), "undefined_field"),
    (re.compile(r"found no matching overload"), "no_matching_overload"),
    (re.compile(r"Exceeded max recursion depth"), "too_deep"),
    # The parser's own nesting guard, which writes no position (measured).
    (re.compile(r"recursion limit exceeded"), "too_deep"),
)


def parse_issues(text: str) -> list[ExpressionIssue]:
    issues: list[ExpressionIssue] = []
    for line in text.splitlines():
        match = _LOCATED.search(line)
        if match is None:
            continue
        row, col, message = int(match[1]), int(match[2]), match[3].strip()
        issue = _issue(message, row if row > 0 else None, col if col > 0 else None)
        if issue not in issues:
            issues.append(issue)
    if not issues:
        issues.append(_issue(text.split("\n", 1)[0].strip(), None, None))
    return issues


def _issue(message: str, line: int | None, column: int | None) -> ExpressionIssue:
    message = re.sub(r"\s*\[[A-Z_]+\]$", "", message)
    for pattern, kind in _KINDS:
        found = pattern.search(message)
        if found is not None:
            name = found[1] if found.groups() else None
            return ExpressionIssue(kind, line, column, name, message)
    return ExpressionIssue("other", line, column, None, message)
