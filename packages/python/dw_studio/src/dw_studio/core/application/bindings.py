"""Binding sets: the values a document's bindings take, proposed by one person
and approved by another (tenant-config R3.7, R7, R8; ADR-0110 decisions 3-8).

The generic machinery is the platform's (`dw_platform.application.config_versions`):
the proposal row, its strict run-less `config.version` request, the decision
guard and the settlement. Studio registers one kind there, `binding_set`
(`BindingSets`), whose key is an artifact's id, and answers the questions
only it can:

- what the key is and who reads it: the artifact's kind's read key at its
  owning workspace (`platform.workspace_reach`), else 404 (R8.17);
- what a value must be: every binding the latest sealed version's closure
  declares, the root's and each version it pins, plus what the `live`
  version declares if it differs (gate 4/11/2026 (n), (o)); a value is
  checked by its kind's check in `BindingTypes`, the one place a kind's check
  is registered, and a kind without one is refused at startup (gate (h));
- whether a version may be published (`BindingStatus.satisfied`,
  `PublishBindingsCheck` of agent-lifecycle R2.11, R5.10) and what a run pins
  at admission (`BindingPins`, R7.3, R7.4, R7.6), each against the version's
  own declarations.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Protocol

from dw_kernel.canonical import content_hash
from dw_kernel.errors import ConfigError, ConflictError, NotFoundError
from dw_platform.application.access_context import AccessContext
from dw_platform.application.config_versions import ConfigTarget
from dw_platform.application.connection_admin import ConnectionDependents, DependentRef
from dw_platform.application.connections import (
    CONNECTIONS_READ_SCOPE,
    CallSite,
    Usability,
    UsableContext,
)
from dw_platform.application.json_schema import tool_problems, tool_validator_for
from dw_studio.core.application.ports import (
    ArtifactRow,
    BindingSetRow,
    BindingStore,
    BindingTx,
    ConnectionFacts,
    VersionRow,
)
from dw_studio.core.application.registry import ArtifactKindRegistry
from dw_studio.core.domain.artifacts import DocumentInvalidError, DocumentProblem, Stage
from dw_studio.core.domain.bindings import (
    BindingDecl,
    BindingKind,
    Union,
    as_uuid,
    binding_set_values,
    bindings_hash,
    document_problems,
    merge,
    parse_declarations,
    unset_required,
)

BINDING_SET: Final = "binding_set"
# tenant-rbac/01's catalogue, workspace depth (migration of ticket 05).
BINDINGS_PROPOSE_SCOPE = "studio.bindings.propose"
BINDINGS_APPROVE_SCOPE = "studio.bindings.approve"
# The one purpose a W1 connection serves (ADR-0115 decision 2).
TOOL_PURPOSE: Final = "tool"


class ConnectionUsablePort(Protocol):
    """`ConnectionUsability.connection_usable` (connections-and-vault/04),
    declared by this consumer and handed over at the composition root."""

    async def connection_usable(
        self, connection: uuid.UUID, context: UsableContext, purpose: str
    ) -> Usability: ...


@dataclass(frozen=True, slots=True)
class Review:
    """Whose value is checked, and where: the proposer at the owning workspace
    at a proposal and an approval; the run's principal at its workspace at
    admission."""

    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    principal_id: uuid.UUID
    call_site: CallSite


def _problem(at: str, code: str, detail: str) -> DocumentProblem:
    return DocumentProblem(at, code, detail)


def _wrapped(schema: Mapping[str, Any]) -> dict[str, Any]:
    """A variable's scalar schema as `dw.tool-schema/v1`'s closed object."""
    return {
        "type": "object",
        "properties": {"value": dict(schema)},
        "required": ["value"],
        "additionalProperties": False,
    }


def variable_problems(decl: BindingDecl, value: Any, at: str) -> list[DocumentProblem]:
    """A variable's value against its schema, by the platform's one validator
    with its closed format list; the value itself is never in a problem."""
    try:
        found = tool_problems(_wrapped(decl.schema or {}), {"value": value})
    except ConfigError:
        return [_problem(at, "binding_schema_invalid", "the variable's schema is not valid")]
    return [_problem(at, "binding_value_invalid", f"{p.keyword}: does not match") for p in found]


def declaration_problems(
    decls: Iterable[BindingDecl], paths: Mapping[str, str]
) -> list[DocumentProblem]:
    """What the seal adds to the shape check: each variable's schema is a
    valid schema, and its `default` keeps it (gate 4/11/2026 (k), (l))."""
    problems: list[DocumentProblem] = []
    for decl in decls:
        if decl.kind is not BindingKind.VARIABLE:
            continue
        at = paths.get(decl.name, "/bindings")
        try:
            tool_validator_for(_wrapped(decl.schema or {}))
        except ConfigError:
            problems.append(_problem(f"{at}/schema", "binding_schema_invalid", "not a schema"))
            continue
        if decl.has_default:
            problems += variable_problems(decl, decl.default, f"{at}/default")
    return problems


# ---- the kind checks ---------------------------------------------------------


class ValueCheck(Protocol):
    """One kind's check of a proposed value (ticket 05 step 1). Returns the
    problems at `at`; raises `NotFoundError` for another company's id."""

    async def __call__(
        self, tx: BindingTx, review: Review, decl: BindingDecl, value: Any, at: str
    ) -> list[DocumentProblem]: ...


@dataclass(frozen=True)
class ConnectionCheck:
    """The tenant's connection (404), of the declared connector and major
    (422), usable by the reviewed principal at the reviewed workspace for a
    tool (422, `connection_usable`, ADR-0115 decision 2)."""

    usable: ConnectionUsablePort

    async def __call__(
        self, tx: BindingTx, review: Review, decl: BindingDecl, value: Any, at: str
    ) -> list[DocumentProblem]:
        connection_id = as_uuid(value)
        if connection_id is None:
            return [_problem(at, "binding_value_invalid", "a connection's id")]
        facts = (await tx.connections([connection_id])).get(connection_id)
        if facts is None:
            raise NotFoundError("connection not found", details={"id": str(connection_id)})
        if (facts.connector_key, facts.connector_major) != (
            decl.connector_key,
            decl.connector_major,
        ):
            return [_problem(at, "binding_connector_mismatch", "another connector or major")]
        answer = await self.usable.connection_usable(
            connection_id,
            UsableContext(
                tenant_id=review.tenant_id,
                principal_id=review.principal_id,
                workspace_id=review.workspace_id,
                call_site=review.call_site,
                run_requested_at=None,
            ),
            TOOL_PURPOSE,
        )
        if not answer.usable:
            return [_problem(at, "connection_unusable", str(answer.reason))]
        return []


async def variable_check(
    tx: BindingTx, review: Review, decl: BindingDecl, value: Any, at: str
) -> list[DocumentProblem]:
    return variable_problems(decl, value, at)


async def principal_check(
    tx: BindingTx, review: Review, decl: BindingDecl, value: Any, at: str
) -> list[DocumentProblem]:
    """An identity of this company, active (gate 4/11/2026 (h)): another
    company's or none is a 404, an inactive one 422 `principal_inactive`."""
    principal_id = as_uuid(value)
    if principal_id is None:
        return [_problem(at, "binding_value_invalid", "a principal's id")]
    active = (await tx.principal_status([principal_id])).get(principal_id)
    if active is None:
        raise NotFoundError("principal not found", details={"id": str(principal_id)})
    return [] if active else [_problem(at, "principal_inactive", "not active")]


class BindingTypes:
    """The one register of a binding kind's check (ticket 05 step 1): every
    kind `BindingKind` declares has one, or the composition root fails, so no
    kind takes every value of the right type (failure-modes #7)."""

    def __init__(self, checks: Mapping[BindingKind, ValueCheck | None]) -> None:
        missing = sorted(kind.value for kind in BindingKind if checks.get(kind) is None)
        if missing:
            raise ValueError(f"binding kinds without a proposal check: {missing}")
        self._checks: Mapping[BindingKind, ValueCheck] = MappingProxyType(
            {kind: check for kind, check in checks.items() if check is not None}
        )

    def check(self, kind: BindingKind) -> ValueCheck:
        return self._checks[kind]

    async def problems(
        self, tx: BindingTx, review: Review, union: Mapping[str, BindingDecl], values: Any
    ) -> list[DocumentProblem]:
        problems: list[DocumentProblem] = []
        for name, value in sorted(binding_set_values(values).items()):
            at = "/values/" + str(name).replace("~", "~0").replace("/", "~1")
            decl = union.get(name)
            if decl is None:
                problems.append(_problem(at, "binding_unknown", "no binding of this name"))
                continue
            problems += await self.check(decl.kind)(tx, review, decl, value, at)
        return problems


def platform_binding_types(usable: ConnectionUsablePort) -> BindingTypes:
    """The W1 register: workflow-triggers/01 adds the run identity's own check
    to `principal` here when it ships."""
    return BindingTypes(
        {
            BindingKind.CONNECTION: ConnectionCheck(usable),
            BindingKind.VARIABLE: variable_check,
            BindingKind.PRINCIPAL: principal_check,
        }
    )


# ---- what a version declares ----------------------------------------------------


async def declarations_of(tx: BindingTx, version: VersionRow) -> list[BindingDecl]:
    """The bindings a sealed version's closure declares: the root's, then each
    version its where-used index pins."""
    pinned = await tx.pinned_versions(version.id)
    documents = await tx.version_documents(pinned) if pinned else {}
    groups = [parse_declarations(version.document).items]
    groups += [parse_declarations(documents[v]).items for v in pinned if v in documents]
    return list(merge(groups).items.values())


@dataclass(frozen=True, slots=True)
class Base:
    """The latest sealed version, what it declares, and the union a Binding
    set of the artifact may carry."""

    latest: VersionRow
    declared: tuple[BindingDecl, ...]
    union: Union
    sealed: frozenset[int]


def _no_sealed() -> ConflictError:
    return ConflictError(
        "nothing is sealed to check a value against yet",
        details={"reason_code": "no_sealed_version"},
    )


async def base_of(tx: BindingTx, artifact_id: uuid.UUID) -> Base:
    """Gate 4/11/2026 (n)-(p): the latest sealed version is the highest
    number not in `draft`; a version taken back to its draft is not one."""
    versions = await tx.versions(artifact_id)
    sealed = [v for v in versions if v.stage is not Stage.DRAFT and v.version_no is not None]
    if not sealed:
        raise _no_sealed()
    latest = max(sealed, key=lambda v: v.version_no or 0)
    declared = await declarations_of(tx, latest)
    groups = [declared]
    live = next((v for v in versions if v.stage is Stage.LIVE), None)
    if live is not None and live.id != latest.id:
        groups.append(await declarations_of(tx, live))
    return Base(
        latest,
        tuple(declared),
        merge(groups),
        frozenset(v.version_no for v in sealed if v.version_no is not None),
    )


async def readable_artifact(
    tx: BindingTx, registry: ArtifactKindRegistry, artifact_id: uuid.UUID
) -> tuple[str, ArtifactRow]:
    """The artifact and its kind's read key, if the caller reads it at its
    owning workspace; 404 otherwise, another company's included (R8.17)."""
    row = await tx.artifact(artifact_id)
    entry = None if row is None else registry.get(row.kind)
    if (
        row is None
        or entry is None
        or row.owning_workspace_id not in await tx.reach(entry.read_key)
    ):
        raise NotFoundError("artifact not found")
    return entry.read_key, row


# ---- the registered kind ---------------------------------------------------------


@dataclass(frozen=True)
class BindingSets:
    """`binding_set` of `ConfigKindRegistry`: the key is an artifact's id."""

    store: BindingStore
    registry: ArtifactKindRegistry
    types: BindingTypes
    usability: ConnectionUsablePort

    @property
    def kind(self) -> str:
        return BINDING_SET

    @property
    def propose_key(self) -> str:
        return BINDINGS_PROPOSE_SCOPE

    @property
    def approve_key(self) -> str:
        return BINDINGS_APPROVE_SCOPE

    @staticmethod
    def _artifact_id(key: str) -> uuid.UUID:
        artifact_id = as_uuid(key)
        if artifact_id is None:
            raise NotFoundError("artifact not found")
        return artifact_id

    async def readable(self, context: AccessContext, key: str) -> None:
        artifact_id = self._artifact_id(key)
        async with self.store.transaction(context) as tx:
            await readable_artifact(tx, self.registry, artifact_id)

    async def target(self, context: AccessContext, key: str) -> ConfigTarget:
        artifact_id = self._artifact_id(key)
        async with self.store.transaction(context) as tx:
            read_key, row = await readable_artifact(tx, self.registry, artifact_id)
            base = await base_of(tx, artifact_id)
        return ConfigTarget(
            key=key,
            owning_workspace_id=row.owning_workspace_id,
            read_key=read_key,
            base_version=base.latest.version_no or 0,
            base_hash=bindings_hash(base.declared),
            sealed_versions=base.sealed,
            label=row.api_name,
        )

    async def check(self, context: AccessContext, target: ConfigTarget, document: Any) -> None:
        problems = document_problems(document)
        if problems:
            raise DocumentInvalidError("the Binding set is not valid", problems)
        artifact_id = self._artifact_id(target.key)
        review = Review(
            context.tenant_id, target.owning_workspace_id, context.principal_id, "binding_review"
        )
        async with self.store.transaction(context) as tx:
            base = await base_of(tx, artifact_id)
            problems = await self.types.problems(tx, review, base.union.items, document)
        if problems:
            raise DocumentInvalidError("a value is not valid", problems)

    async def usable(
        self,
        tenant_id: uuid.UUID,
        key: str,
        workspace_id: uuid.UUID,
        proposer: uuid.UUID,
        document: Any,
    ) -> bool:
        """Every connection the proposal binds, asked again for its proposer at
        its workspace when it is approved (R8.9)."""
        artifact_id = self._artifact_id(key)
        async with self.store.for_tenant(tenant_id) as tx:
            union = (await base_of(tx, artifact_id)).union.items
        context = UsableContext(
            tenant_id=tenant_id,
            principal_id=proposer,
            workspace_id=workspace_id,
            call_site="binding_review",
            run_requested_at=None,
        )
        for name, value in binding_set_values(document).items():
            decl = union.get(name)
            connection_id = as_uuid(value)
            if decl is None or decl.kind is not BindingKind.CONNECTION or connection_id is None:
                continue
            answer = await self.usability.connection_usable(connection_id, context, TOOL_PURPOSE)
            if not answer.usable:
                return False
        return True


# ---- publish, admission, the run's pins --------------------------------------------


@dataclass(frozen=True, slots=True)
class BindingVerdict:
    """`PublishBindingsCheck`'s answer: the bindings that keep a version from
    `live`, by name; empty when it may go."""

    unset: tuple[str, ...] = ()

    @property
    def satisfied(self) -> bool:
        return not self.unset


async def _invalid_names(
    types: BindingTypes,
    tx: BindingTx,
    review: Review | None,
    decls: Sequence[BindingDecl],
    values: Mapping[str, Any],
) -> list[str]:
    """Each declared name whose value fails its kind's check; with no review
    (no approved set to name a proposer), the type alone."""
    names: list[str] = []
    for decl in decls:
        if decl.name not in values:
            continue
        value = values[decl.name]
        if review is None:
            wrong = (
                variable_problems(decl, value, "")
                if decl.kind is BindingKind.VARIABLE
                else ([] if as_uuid(value) is not None else ["invalid"])
            )
        else:
            try:
                wrong = await types.check(decl.kind)(tx, review, decl, value, "")
            except NotFoundError:
                wrong = ["gone"]
        if wrong:
            names.append(decl.name)
    return names


@dataclass(frozen=True)
class BindingStatus:
    """`PublishBindingsCheck` (agent-lifecycle R2.11, R5.10; tenant-config
    R7.2): every required binding of the version has a value in the
    artifact's approved Binding set (or a default), and every value passes its
    kind's check against the version's own declarations, its connections
    asked for the approved set's proposer at the owning workspace, with or
    without a caller (the publish handler runs on the outbox lane)."""

    store: BindingStore
    types: BindingTypes

    async def satisfied(self, tenant_id: uuid.UUID, version_id: uuid.UUID) -> BindingVerdict:
        """In a transaction of its own, under the tenant alone."""
        async with self.store.for_tenant(tenant_id) as tx:
            return await self.satisfied_in(tx, tenant_id, version_id)

    async def satisfied_in(
        self, tx: BindingTx, tenant_id: uuid.UUID, version_id: uuid.UUID
    ) -> BindingVerdict:
        """In the caller's transaction: a submit asks it after its seal wrote
        the where-used index, under the component's lock (agent-lifecycle
        ticket 04)."""
        root = await tx.root_version(version_id)
        if root is None:
            raise NotFoundError("version not found")
        decls = await declarations_of(tx, root.version)
        approved = await tx.binding_set(root.version.artifact_id, "approved")
        values = binding_set_values(None if approved is None else approved.document)
        review = (
            None
            if approved is None
            else Review(tenant_id, root.owning_workspace_id, approved.proposed_by, "binding_review")
        )
        invalid = await _invalid_names(self.types, tx, review, decls, values)
        return BindingVerdict(tuple(sorted({*unset_required(decls, values), *invalid})))


def bound_value(decl: BindingDecl, value: Any) -> dict[str, Any]:
    """One entry of the manifest's `bindings.values`: a connection's id, a
    principal's id, a variable's `content_hash`, never a secret or a value."""
    if decl.kind is BindingKind.CONNECTION:
        return {"kind": decl.kind.value, "connection_id": str(as_uuid(value))}
    if decl.kind is BindingKind.PRINCIPAL:
        return {"kind": decl.kind.value, "principal_id": str(as_uuid(value))}
    return {"kind": decl.kind.value, "content_hash": content_hash(value)}


@dataclass(frozen=True, slots=True)
class PinnedBindings:
    """What a run's manifest pins of the artifact's bindings (R7.4)."""

    config_version_id: uuid.UUID | None
    values: Mapping[str, dict[str, Any]]

    def as_section(self) -> dict[str, Any]:
        return {
            "config_version_id": None
            if self.config_version_id is None
            else str(self.config_version_id),
            "values": dict(self.values),
        }


def _refused(message: str, reason: str, names: Sequence[str]) -> ConflictError:
    return ConflictError(message, details={"reason_code": reason, "bindings": list(names)})


@dataclass(frozen=True)
class BindingPins:
    """At admission, in the door's transaction (R7.3, R7.4, R7.6; gate
    4/11/2026 (g), (s)): the approved Binding set checked against the run's
    root version's own declarations, its connections usable by the run's
    principal at the run's workspace, before a manifest is written. A
    `simulate` run is refused for neither and pins what is approved."""

    types: BindingTypes
    usability: ConnectionUsablePort

    async def pin(
        self,
        tx: BindingTx,
        decls: Sequence[BindingDecl],
        artifact_id: uuid.UUID,
        *,
        simulate: bool,
        tenant_id: uuid.UUID,
        workspace_id: uuid.UUID,
        principal_id: uuid.UUID,
    ) -> PinnedBindings | None:
        if not decls:
            return None
        approved: BindingSetRow | None = await tx.binding_set(artifact_id, "approved")
        values = binding_set_values(None if approved is None else approved.document)
        invalid = await _invalid_names(self.types, tx, None, decls, values)
        if not simulate:
            unset = sorted({*unset_required(decls, values), *invalid})
            if unset:
                raise _refused("a required binding has no valid value", "binding_unset", unset)
            await self._usable(
                tx,
                decls,
                values,
                UsableContext(
                    tenant_id=tenant_id,
                    principal_id=principal_id,
                    workspace_id=workspace_id,
                    call_site="run_admission",
                    run_requested_at=None,
                ),
            )
        pinned: dict[str, dict[str, Any]] = {}
        for decl in decls:
            if decl.name in values and decl.name not in invalid:
                pinned[decl.name] = bound_value(decl, values[decl.name])
            elif decl.has_default:
                pinned[decl.name] = bound_value(decl, decl.default)
        return PinnedBindings(None if approved is None else approved.id, pinned)

    async def _usable(
        self,
        tx: BindingTx,
        decls: Sequence[BindingDecl],
        values: Mapping[str, Any],
        context: UsableContext,
    ) -> None:
        degraded: list[str] = []
        for decl in decls:
            connection_id = as_uuid(values.get(decl.name))
            if decl.kind is not BindingKind.CONNECTION or connection_id is None:
                continue
            facts: ConnectionFacts | None = (await tx.connections([connection_id])).get(
                connection_id
            )
            answer = await self.usability.connection_usable(connection_id, context, TOOL_PURPOSE)
            if facts is None or not answer.usable:
                degraded.append(decl.name)
        if degraded:
            raise _refused("a bound connection cannot be used", "binding_degraded", degraded)


# ---- what uses a connection (R3.7) -----------------------------------------------


@dataclass(frozen=True)
class BindingConnectionDependents:
    """`ConnectionDependentsPort` of connections-and-vault (R5.8): a connection
    is in use while an `approved` Binding set of an artifact not soft-deleted
    has it as a value; one source, `studio.dependencies` never names a
    connection (R7.1, gate 4/11/2026 (c)). Named where the caller reads the
    artifact, counted otherwise (R3.4)."""

    store: BindingStore
    registry: ArtifactKindRegistry

    async def dependents(
        self, context: AccessContext, connection_id: uuid.UUID
    ) -> ConnectionDependents:
        visible: list[DependentRef] = []
        async with self.store.transaction(context) as tx:
            users = await tx.binding_sets_using(connection_id)
            reach: dict[str, frozenset[uuid.UUID]] = {}
            for artifact_id in users:
                row = await tx.artifact(artifact_id)
                entry = None if row is None else self.registry.get(row.kind)
                if row is None or entry is None:
                    continue
                if entry.read_key not in reach:
                    reach[entry.read_key] = await tx.reach(entry.read_key)
                if row.owning_workspace_id in reach[entry.read_key]:
                    visible.append(DependentRef(row.kind, row.id, row.api_name))
        return ConnectionDependents(total=len(users), visible=tuple(visible))


# ---- what `GET .../bindings` shows ----------------------------------------------


@dataclass(frozen=True, slots=True)
class BindingItem:
    decl: BindingDecl
    state: str
    value: Any
    proposed_value: Any
    has_proposed: bool


@dataclass(frozen=True, slots=True)
class BindingsOverview:
    artifact_id: uuid.UUID
    base_version: int | None
    items: tuple[BindingItem, ...]
    approved: BindingSetRow | None
    proposal: BindingSetRow | None
    # The connections named by a value the caller may read, by id.
    readable_connections: Mapping[uuid.UUID, ConnectionFacts]


@dataclass(frozen=True)
class BindingsReader:
    """R8.17 (gate 4/11/2026 (e), (t)): the kind's read key at the owning
    workspace, else 404; the declarations, the approved values and the open
    proposal's; a connection the caller does not read is its id alone.
    `connection_usable` is not asked for the caller."""

    store: BindingStore
    registry: ArtifactKindRegistry

    async def overview(self, context: AccessContext, artifact_id: uuid.UUID) -> BindingsOverview:
        async with self.store.transaction(context) as tx:
            await readable_artifact(tx, self.registry, artifact_id)
            try:
                base: Base | None = await base_of(tx, artifact_id)
            except ConflictError:
                base = None
            approved = await tx.binding_set(artifact_id, "approved")
            proposal = await tx.binding_set(artifact_id, "proposed")
            values = binding_set_values(None if approved is None else approved.document)
            proposed = binding_set_values(None if proposal is None else proposal.document)
            union = {} if base is None else dict(base.union.items)
            ids = [
                found
                for found in (as_uuid(v) for v in [*values.values(), *proposed.values()])
                if found is not None
            ]
            connections = await tx.connections(ids) if ids else {}
            readable = await tx.reach(CONNECTIONS_READ_SCOPE)
        items = []
        for name in sorted(union):
            decl = union[name]
            state = "set" if name in values else ("default" if decl.has_default else "unset")
            items.append(
                BindingItem(
                    decl,
                    state,
                    values.get(name),
                    proposed.get(name),
                    name in proposed,
                )
            )
        return BindingsOverview(
            artifact_id=artifact_id,
            base_version=None if base is None else base.latest.version_no,
            items=tuple(items),
            approved=approved,
            proposal=proposal,
            readable_connections={
                key: facts
                for key, facts in connections.items()
                if facts.owning_workspace_id in readable
            },
        )
