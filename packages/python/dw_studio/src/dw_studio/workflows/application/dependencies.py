"""What a `workflow` document uses, for `studio.dependencies` (workflow-engine
R1.3; tenant-config R3.1).

Pure, over the document's `WorkflowIR`, so every step at every depth counts:
lanes, error lanes and `triggers[]`. One `node_type` reference per distinct
`type@major`, at the first step that names it, and one `artifact` reference
per use a step's type declares through `NodeTypeSpec.dependencies` (a
trigger's data source, a step's object). A binding's reference is the shared
extractor's of tenant-config/05, with `bindings[]`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.ir import lower
from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_studio.core.domain.artifacts import Reference, TargetKind, Usage


@dataclass(frozen=True)
class WorkflowDependencies:
    registry: Mapping[str, NodeTypeSpec]

    def __call__(self, document: Any) -> list[Reference]:
        """A document that does not read as one uses nothing yet: its draft's
        warnings say why, and a seal refuses it before it extracts."""
        try:
            parsed = WorkflowDocument.model_validate(document)
        except ValidationError:
            return []
        ir = lower(parsed, self.registry)
        found: list[Reference] = []
        types: set[str] = set()
        for placed in (*ir.triggers, *ir.steps):
            pointer = f"/{placed.path}"
            if placed.step.type not in types:
                types.add(placed.step.type)
                found.append(
                    Reference(
                        TargetKind.NODE_TYPE, placed.step.type, Usage.INVOKE, f"{pointer}/type"
                    )
                )
            if placed.spec is None:
                continue
            for use in placed.spec.dependencies(placed.step.config):
                found.append(
                    Reference(
                        TargetKind(use.to_kind),
                        use.to_key,
                        Usage(use.usage),
                        f"{pointer}/config{use.path}",
                    )
                )
        return found
