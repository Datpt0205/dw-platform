"""The capability analysis's reads and its write, in the submit's transaction
(compliance-pdpl R2.6, R4.1, R4.6, R4.8; ADR-0125 decisions 1-3).

`SqlCapabilityFacts` gathers what the closure the submit pinned says, under
the submitting company's RLS on the submit's own session: each tool's three
classifications (the tool register, by `name@version`); whether each pinned
version (an object, a trigger's data source) holds a field whose
`pd_category` is not `none`, by its artifact's id and its `api_name`; the
assessments of pinned child versions (`VersionAssessmentLookup`); the route
class of the submit, the strictest of the company's and the version's; and
where each route of the run's model profile processes. A version of another
company is not read by RLS, so it is no fact, and the analysis reads a missing
fact as the closed answer.

`SqlVersionAssessments` is the lookup and the writer: a child's row counts
only for the child version's own definition hash and this analyser version;
a submit's row is written `ON CONFLICT DO NOTHING` (R4.6).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.ir import lower
from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_agent_runtime.wflite.validate import ToolSpecLookup
from dw_kernel.errors import NotFoundError
from dw_kernel.ports import IdGenerator
from dw_kernel.residency import effective_route_class
from dw_platform.adapters.persistence.residency import read_route_classes
from dw_studio.core.adapters.tables import artifact_versions, artifacts, version_assessments
from dw_studio.core.application.ports import ArtifactTx, VersionRow
from dw_studio.workflows.application.capability import (
    ANALYSER_VERSION,
    CapabilityAnalysis,
    CapabilityFacts,
    Label,
    LabelTable,
    ToolClasses,
)
from dw_studio.workflows.application.capability_check import VersionAssessmentLookup

ProfileLocations = Callable[[str], tuple[str | None, ...] | None]
"""Every route's `data_location` of a platform model profile; None when the
profile is not registered."""


def _personal(document: Any) -> bool:
    """Whether a document names a field whose `pd_category` is not `none`."""
    if isinstance(document, Mapping):
        category = document.get("pd_category")
        if isinstance(category, str) and category != "none":
            return True
        return any(_personal(value) for value in document.values())
    if isinstance(document, list):
        return any(_personal(item) for item in document)
    return False


@dataclass(frozen=True)
class SqlCapabilityFacts:
    registry: Mapping[str, NodeTypeSpec]
    tools: ToolSpecLookup
    assessments: VersionAssessmentLookup
    profile_locations: ProfileLocations
    model_profiles: tuple[str, ...]

    async def facts(
        self, tx: ArtifactTx, version: VersionRow, document: WorkflowDocument, table: LabelTable
    ) -> CapabilityFacts:
        session = tx.session
        ir = lower(document, self.registry)
        steps = [placed.step for placed in (*ir.triggers, *ir.steps)]
        tools: dict[str, ToolClasses] = {}
        for step in steps:
            tool_of = table.tool_of.get(step.type)
            ref = tool_of(step) if tool_of is not None else None
            if ref is None or ref in tools:
                continue
            name, _, number = ref.partition("@")
            try:
                spec = self.tools.resolve(name, number)
            except NotFoundError:
                continue
            tools[ref] = ToolClasses(
                output_trust=getattr(spec, "output_trust", None),
                data_classification=spec.data_classification,
                side_effect_level=spec.side_effect_level,
            )
        pinned = await tx.pinned_versions(version.id)  # type: ignore[attr-defined]
        personal: dict[str, bool] = {}
        if pinned:
            rows = await session.execute(
                sa.select(
                    artifact_versions.c.id,
                    artifact_versions.c.artifact_id,
                    artifact_versions.c.document,
                    artifacts.c.api_name,
                )
                .join(artifacts, artifacts.c.id == artifact_versions.c.artifact_id)
                .where(artifact_versions.c.id.in_(list(pinned)))
            )
            for row in rows:
                holds = _personal(row.document)
                for key in (str(row.artifact_id), str(row.id), row.api_name):
                    personal[key] = personal.get(key, False) or holds
        children = {
            uuid.UUID(str(step.config["version_id"]))
            for step in steps
            if step.type in table.child_types and _is_uuid(step.config.get("version_id"))
        }
        assessed = await self.assessments.labels(tx, children) if children else {}
        tenant_class, _ = await read_route_classes(session, tx.tenant_id, None)  # type: ignore[attr-defined]
        route_class = effective_route_class(tenant_class, None, document_route_class(version))
        locations = {
            profile: where
            for profile in self.model_profiles
            if (where := self.profile_locations(profile)) is not None
        }
        return CapabilityFacts(
            tools=tools,
            personal_objects=personal,
            personal_sources=personal,
            assessments={str(k): v for k, v in assessed.items()},
            route_class=route_class,
            model_locations=locations,
        )


def document_route_class(version: VersionRow) -> str | None:
    value = version.document.get("route_class") if isinstance(version.document, dict) else None
    return None if value is None else str(value)


def _is_uuid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return value is not None


@dataclass(frozen=True)
class SqlVersionAssessments:
    ids: IdGenerator

    async def labels(
        self, tx: ArtifactTx, version_ids: Iterable[uuid.UUID]
    ) -> Mapping[uuid.UUID, frozenset[Label]]:
        wanted = list(version_ids)
        if not wanted:
            return {}
        rows = await tx.session.execute(
            sa.select(version_assessments.c.version_id, version_assessments.c.signals)
            .join(
                artifact_versions,
                sa.and_(
                    artifact_versions.c.id == version_assessments.c.version_id,
                    artifact_versions.c.definition_hash == version_assessments.c.definition_hash,
                ),
            )
            .where(
                version_assessments.c.version_id.in_(wanted),
                version_assessments.c.analyser_version == ANALYSER_VERSION,
            )
        )
        return {row.version_id: frozenset(row.signals) for row in rows}

    async def write(
        self, tx: ArtifactTx, version: VersionRow, analysis: CapabilityAnalysis
    ) -> None:
        await tx.session.execute(
            pg_insert(version_assessments)
            .values(
                tenant_id=tx.tenant_id,  # type: ignore[attr-defined]
                id=self.ids.new_uuid(),
                version_id=version.id,
                definition_hash=version.definition_hash,
                analyser_version=ANALYSER_VERSION,
                signals=sorted(analysis.signals),
                labels={step: sorted(found) for step, found in analysis.labels.items()},
                verdict="pass",
            )
            .on_conflict_do_nothing()
        )
