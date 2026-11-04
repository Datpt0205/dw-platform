"""Studio's path through the one `dw.workflow/v1` validator (workflow-engine
R1.1, R1.4, R2; ADR-0112 Amendments 2026-11-03).

`STUDIO_RULES` is what a Studio document requires and refuses beyond the
model: no `key` or `version` (the envelope holds the artifact and its
`version_no`, ADR-0109 decisions 1, 2), a `retry`, `timeout_s` and `on_error`
on every step, and a lane, `[]` at least, for every port a step's type lists.
`WorkflowValidator` is the `validate` of the kind's registry entry: the core's
function with these rules, each problem at a JSON pointer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from dw_agent_runtime.wflite.registry import NodeTypeSpec
from dw_agent_runtime.wflite.validate import PathRules, Problem, ToolSpecLookup, validate
from dw_studio.core.domain.artifacts import DocumentProblem

STUDIO_RULES: Final = PathRules(
    required_document_keys=frozenset(),
    refused_document_keys=frozenset({"key", "version"}),
    required_step_keys=frozenset({"retry", "timeout_s", "on_error"}),
    refused_step_keys=frozenset(),
    every_port_lane=True,
)


def _pointer(path: str) -> str:
    """A core path (`steps/0/config`) as the JSON pointer the envelope reports;
    the core escaped each segment already."""
    return f"/{path}" if path else ""


def as_document_problem(problem: Problem) -> DocumentProblem:
    return DocumentProblem(_pointer(problem.path), problem.code, problem.message_en)


@dataclass(frozen=True)
class WorkflowValidator:
    """Every problem of a Studio workflow document at once (R2.11). `registry`
    is the step types the composition root builds; `tools` the platform layer
    of the tool register, as wf-lite reads it."""

    registry: Mapping[str, NodeTypeSpec]
    tools: ToolSpecLookup

    def __call__(self, document: Any) -> list[DocumentProblem]:
        if not isinstance(document, Mapping):
            return [
                as_document_problem(
                    Problem.of("", "wf.schema_invalid", "a workflow is a JSON object")
                )
            ]
        return [
            as_document_problem(problem)
            for problem in validate(
                document,
                registry=self.registry,
                rules=STUDIO_RULES,
                tools=self.tools,
                work_schemas={},
            )
        ]
