"""What `GET /api/v1/studio/node-types` answers (workflow-nodes R1.1, R1.2).

The catalogue is the platform core's `catalogue_document` of the one step
registry, read at the platform layer only: what a deployment can do does not
depend on who asks (`CLAUDE.md`, Per-tenant artifacts). Its `catalogue_hash`
is the same function the worker's compiler would answer for its registry.
Plan clamps and lock reasons for the caller join here, beside the hash and
outside it, with the first type that declares them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from dw_agent_runtime.wflite.registry import NodeTypeSpec, catalogue_document, catalogue_hash

__all__ = ["NodeTypeCatalogueView", "NodeTypeView", "node_type_catalogue"]


class _View(BaseModel):
    model_config = ConfigDict(populate_by_name=True, frozen=True)


class PortView(_View):
    """An outcome a step leaves by ("Nhánh ra"), by name and label."""

    name: str
    label_vi: str


class FixedPortsView(_View):
    """The same ports on every step of the type."""

    kind: Literal["fixed"]
    ports: list[PortView]


class KeyedPortsView(_View):
    """One port per key of the config object under `key`, read as the key,
    and `default` when the step holds a lane under its name."""

    kind: Literal["keyed"]
    key: str
    default: PortView | None


class FixedOutputView(_View):
    kind: Literal["fixed"]
    schema_: dict[str, Any] = Field(alias="schema")


class ConfigOutputView(_View):
    """The output the step declares in its own config under `key`."""

    kind: Literal["config"]
    key: str


class StepErrorView(_View):
    """The `error` a step adds to its output under these `on_error` values."""

    on_error: list[str]
    schema_: dict[str, Any] = Field(alias="schema")


class NodeTypeView(_View):
    type: str
    label_vi: str
    config_schema: dict[str, Any]
    output: Annotated[FixedOutputView | ConfigOutputView, Field(discriminator="kind")]
    error: StepErrorView
    ports: Annotated[FixedPortsView | KeyedPortsView, Field(discriminator="kind")]
    side_effect_level: str


class NodeTypeCatalogueView(_View):
    catalogue_hash: str
    types: list[NodeTypeView]


def node_type_catalogue(registry: Mapping[str, NodeTypeSpec]) -> NodeTypeCatalogueView:
    return NodeTypeCatalogueView.model_validate(
        {**catalogue_document(registry), "catalogue_hash": catalogue_hash(registry)}
    )
