"""The workflows packs ship, read, checked and pinned before any work is taken
(wf-lite R1, R3.5).

`configs/packs/<pack>/workflows/<key>@<semver>.yaml` is a `dw.workflow/v1`
document; `configs/packs/<pack>/schemas/*.json` the JSON Schemas its work kinds
name. Every file is hashed (sha256 of its bytes, what a run pins), every
document validated in one pass, and one bad file refuses the whole catalog with
its path and its codes: a process that starts with a workflow it cannot run
takes work it will fail.

The catalog is the `WorkKindSchemas` of the work queue (digital-worker R3.3):
the schema of a kind is the one its DW's pinned workflow declares.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from dw_agent_runtime.tool_specs import ToolSpec
from dw_agent_runtime.wflite.document import WorkflowDocument
from dw_agent_runtime.wflite.registry import JsonSchema, NodeTypeSpec, build_node_registry
from dw_agent_runtime.wflite.validate import Problem, ToolSpecLookup, validate
from dw_kernel.errors import ConfigError, NotFoundError
from dw_platform.application.json_schema import validator_for


class _Yaml12Loader(yaml.SafeLoader):
    """`yaml.SafeLoader` with YAML 1.2 booleans: only `true` and `false`.

    PyYAML follows YAML 1.1, where `on`, `off`, `yes` and `no` are booleans, so
    a `logic.switch` written `on: ...` reached the validator as the key `True`
    (measured on PyYAML 6, 30/10/2026: `on: x` loads as `{True: 'x'}`).
    """


_Yaml12Loader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Yaml12Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def load_yaml(text: str | bytes) -> Any:
    """A workflow document as the catalog reads it (YAML 1.2 booleans)."""
    return yaml.load(text, Loader=_Yaml12Loader)


@dataclass(frozen=True)
class PinnedWorkflow:
    document: WorkflowDocument
    sha256: str
    path: Path
    work_schemas: Mapping[str, JsonSchema]


@dataclass
class PackCatalog:
    _workflows: dict[tuple[str, str], PinnedWorkflow] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        root: Path,
        tools: ToolSpecLookup,
        *,
        registry: Mapping[str, NodeTypeSpec] | None = None,
    ) -> PackCatalog:
        """Every workflow under `root`; `ConfigError` naming each bad file and
        its codes. A missing `root` is an empty catalog: no pack shipped."""
        nodes = registry or build_node_registry()
        catalog = cls()
        failures: list[str] = []
        for path in sorted(root.glob("*/workflows/*.yaml")) if root.is_dir() else []:
            try:
                pinned, problems = _read(path, tools, nodes)
            except ConfigError as exc:
                failures.append(f"{path}: {exc.message}")
                continue
            if problems:
                failures.append(
                    f"{path}: "
                    + "; ".join(f"{p.code} at {p.path} ({p.message_en})" for p in problems)
                )
                continue
            assert pinned is not None
            key = (pinned.document.key, pinned.document.version)
            if key in catalog._workflows:
                failures.append(f"{path}: {key[0]}@{key[1]} is shipped twice")
                continue
            catalog._workflows[key] = pinned
        if failures:
            raise ConfigError("workflow packs are invalid:\n" + "\n".join(failures))
        return catalog

    def workflow(self, key: str, version: str) -> PinnedWorkflow | None:
        return self._workflows.get((key, version))

    def all(self) -> list[PinnedWorkflow]:
        return list(self._workflows.values())

    def schema(
        self, *, workflow_key: str, workflow_version: str, kind: str
    ) -> Mapping[str, Any] | None:
        """`WorkKindSchemas`: the schema a pinned workflow declares for a kind;
        None for a kind it does not declare, or a workflow not shipped."""
        pinned = self._workflows.get((workflow_key, workflow_version))
        return None if pinned is None else pinned.work_schemas.get(kind)


def _read(
    path: Path, tools: ToolSpecLookup, registry: Mapping[str, NodeTypeSpec]
) -> tuple[PinnedWorkflow | None, list[Problem]]:
    raw_bytes = path.read_bytes()
    try:
        raw = load_yaml(raw_bytes)
    except yaml.YAMLError as exc:
        raise ConfigError(f"not YAML: {exc}") from exc
    if not isinstance(raw, Mapping):
        return None, [Problem.of("", "wf.schema_invalid", "the document is not a mapping")]
    stem = path.name.removesuffix(".yaml")
    key, _, version = stem.partition("@")
    schemas, problems = _work_schemas(raw, path.parent.parent / "schemas")
    problems += validate(
        raw, registry=registry, tools=tools, work_schemas=schemas, file_key=(key, version)
    )
    if problems:
        return None, problems
    return (
        PinnedWorkflow(
            document=WorkflowDocument.model_validate(raw),
            sha256=hashlib.sha256(raw_bytes).hexdigest(),
            path=path,
            work_schemas=schemas,
        ),
        [],
    )


def _work_schemas(
    raw: Mapping[str, Any], directory: Path
) -> tuple[dict[str, JsonSchema], list[Problem]]:
    schemas: dict[str, JsonSchema] = {}
    problems: list[Problem] = []
    kinds = raw.get("work_kinds")
    for i, entry in enumerate(kinds if isinstance(kinds, list) else []):
        if not isinstance(entry, Mapping):
            continue
        name, kind = entry.get("schema"), entry.get("kind")
        if not isinstance(name, str) or not isinstance(kind, str):
            continue
        file = directory / name
        where = f"work_kinds/{i}/schema"
        if not file.is_file() or file.parent != directory:
            problems.append(Problem.of(where, "wf.config_invalid", f"no schema file {name}"))
            continue
        try:
            schema = json.loads(file.read_text(encoding="utf-8"))
            validator_for(schema)
        except (json.JSONDecodeError, ConfigError) as exc:
            problems.append(Problem.of(where, "wf.config_invalid", f"{name}: {exc}"))
            continue
        schemas[kind] = schema
    return schemas, problems


@dataclass(frozen=True)
class ShippedToolSpecs:
    """The platform layer of `configs/tools`, read for the validator: what a
    tool is called and what effect it has. `ToolSpecRegistry` needs the
    runtime's copy to build definitions; checking a document needs neither,
    and the worker, which loads no tools, checks documents too."""

    specs: Mapping[tuple[str, str], ToolSpec]

    @classmethod
    def load(cls, directory: Path) -> ShippedToolSpecs:
        specs: dict[tuple[str, str], ToolSpec] = {}
        for path in sorted(directory.rglob("*.yaml")) if directory.is_dir() else []:
            try:
                spec = ToolSpec.model_validate(yaml.safe_load(path.read_bytes()))
            except (yaml.YAMLError, ValidationError) as exc:
                raise ConfigError(f"tool spec {path.name} invalid: {exc}") from exc
            key = (spec.name, spec.version)
            if key in specs:
                raise ConfigError(f"tool spec shipped twice: {key[0]}@{key[1]}")
            specs[key] = spec
        return cls(specs)

    def resolve(self, name: str, version: str, *, tenant_id: Any = None) -> ToolSpec:
        found = self.specs.get((name, version))
        if found is None:
            raise NotFoundError(
                "tool spec not registered", details={"tool": name, "version": version}
            )
        return found


def load_shipped_packs(configs: Path) -> PackCatalog:
    """What both composition roots call before anything else (R3.5): the packs
    of `configs/packs`, checked against the tools of `configs/tools`."""
    return PackCatalog.load(configs / "packs", ShippedToolSpecs.load(configs / "tools"))
