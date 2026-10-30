"""Tool catalogue loaded from ``configs/tools``.

A tool's policy and the words the model reads to choose it are configuration,
not code. Splitting the description into fixed parts is what keeps a catalogue
consistent: a model picks the wrong tool mostly when a description says what a
tool does but never when to avoid it.

Per-argument documentation is NOT here — it belongs on the handler's Pydantic
input model, which is what the model actually receives as a JSON schema.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dw_agent_runtime.contracts import (
    ApprovalPolicy,
    MessageSpec,
    SideEffectLevel,
    ToolDefinition,
    approval_policy_disagrees_with_side_effect,
)
from dw_agent_runtime.model.copy import RuntimeCopy
from dw_agent_runtime.registry import ConfigError
from dw_kernel.errors import NotFoundError
from dw_kernel.overlay import TenantOverlay

_SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"


class ToolSpec(BaseModel):
    """Versioned tool contract as written by a bounded context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(pattern=r"^1\.0$")
    name: str
    version: str = Field(pattern=_SEMVER_PATTERN)
    summary: str
    when_to_use: str
    when_not_to_use: str
    returns: str
    required_scopes: frozenset[str]
    side_effect_level: SideEffectLevel
    approval_policy: ApprovalPolicy
    timeout_seconds: int = Field(gt=0, le=600)
    max_retries: int = Field(ge=0, le=10)
    idempotent: bool
    data_classification: frozenset[str]
    # Required of every tool with an effect, true or false: a sending tool that
    # forgot to say so would reach the world past the Send floor
    # (compliance-pdpl R3.2, CP28). `message` comes with `true`, and only then.
    sends_message: bool | None = None
    message: MessageSpec | None = None

    @model_validator(mode="after")
    def _a_tool_with_an_effect_says_whether_it_sends(self) -> ToolSpec:
        if self.side_effect_level != "none" and self.sends_message is None:
            raise ValueError(
                f"side_effect_level is '{self.side_effect_level}', so sends_message must be"
                " declared, true or false"
            )
        if self.sends_message and self.message is None:
            raise ValueError("sends_message: true needs message: {channel, recipient_fields}")
        if not self.sends_message and self.message is not None:
            raise ValueError("message is declared only with sends_message: true")
        return self

    @model_validator(mode="after")
    def _never_only_where_it_is_true(self) -> ToolSpec:
        """Refused at load, not at first use.

        `to_definition` enforces the same rule, but that runs when a worker is
        assembled — a mislabelled spec would sit in the catalogue until then.
        The author finds out when the file is read.
        """
        if approval_policy_disagrees_with_side_effect(
            approval_policy=self.approval_policy,
            side_effect_level=self.side_effect_level,
        ):
            raise ValueError(
                f"approval_policy 'never' claims this tool needs no person, but "
                f"side_effect_level is '{self.side_effect_level}'. Use "
                f"'conditional' to let the autonomy level decide, or 'always' to "
                f"ask every time."
            )
        return self

    def description(self, copy: RuntimeCopy) -> str:
        return copy.tool_description(
            summary=self.summary,
            when_to_use=self.when_to_use,
            when_not_to_use=self.when_not_to_use,
            returns=self.returns,
        )

    def to_definition(self, copy: RuntimeCopy) -> ToolDefinition:
        base = f"contracts/tools/{self.name}@{self.version}"
        return ToolDefinition(
            name=self.name,
            version=self.version,
            description=self.description(copy),
            input_schema_ref=f"{base}/input.json",
            output_schema_ref=f"{base}/output.json",
            required_scopes=self.required_scopes,
            side_effect_level=self.side_effect_level,
            approval_policy=self.approval_policy,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            idempotent=self.idempotent,
            data_classification=self.data_classification,
            message=self.message,
        )


@dataclass(frozen=True)
class LoadedToolSpec:
    spec: ToolSpec
    checksum: str
    source_path: Path


@dataclass
class ToolSpecRegistry:
    copy: RuntimeCopy
    # Platform specs plus per-tenant overrides. A tenant that needs a tool to
    # ask for a different field, or to require approval where the default does
    # not, gets its own spec rather than a fork of the deployment.
    _specs: TenantOverlay[tuple[str, str], LoadedToolSpec] = field(default_factory=TenantOverlay)

    def load_directory(
        self, directory: Path, *, tenant_id: UUID | None = None
    ) -> list[LoadedToolSpec]:
        return [
            self.load_file(path, tenant_id=tenant_id) for path in sorted(directory.rglob("*.yaml"))
        ]

    def load_file(self, path: Path, *, tenant_id: UUID | None = None) -> LoadedToolSpec:
        raw = path.read_bytes()
        try:
            spec = ToolSpec.model_validate(yaml.safe_load(raw))
        except (yaml.YAMLError, ValidationError) as exc:
            raise ConfigError(f"tool spec {path.name} invalid: {exc}") from exc
        loaded = LoadedToolSpec(
            spec=spec, checksum=hashlib.sha256(raw).hexdigest(), source_path=path
        )
        self.register(loaded, tenant_id=tenant_id)
        return loaded

    def register(self, loaded: LoadedToolSpec, *, tenant_id: UUID | None = None) -> None:
        key = (loaded.spec.name, loaded.spec.version)
        # Clashes are checked within a layer: a tenant overriding a platform
        # spec is the feature, two files claiming the same version inside one
        # layer is the mistake.
        existing = self._specs.existing(key, tenant_id=tenant_id)
        if existing is not None:
            raise ConfigError(
                f"tool spec already registered: {key[0]}@{key[1]} "
                f"({existing.source_path.name} and {loaded.source_path.name})"
            )
        self._specs.put(key, loaded, tenant_id=tenant_id)

    def resolve(self, name: str, version: str, *, tenant_id: UUID | None = None) -> ToolSpec:
        loaded = self._specs.get((name, version), tenant_id=tenant_id)
        if loaded is None:
            raise NotFoundError(
                "tool spec not registered", details={"tool": name, "version": version}
            )
        return loaded.spec

    def definition(
        self, name: str, version: str, *, tenant_id: UUID | None = None
    ) -> ToolDefinition:
        return self.resolve(name, version, tenant_id=tenant_id).to_definition(self.copy)
