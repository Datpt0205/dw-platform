"""Model profile configuration: routing, capabilities, data route, budgets.

`ModelProfile` v2 (model-connections R2.3, R3; ADR-0118 decision 2, ADR-0123
decision 5). Every route declares where it processes (`data_location`,
`processor`), how long the processor keeps what it is sent (`retention_days`)
and whether it trains on it (`no_training`), with no default: a route that does
not say is a file that does not load, so "undeclared" never reads as `vn`.
Capabilities are the closed set of twelve under `capabilities`; one not
declared is unsupported, and a name outside the set fails to load. Prices are
not here: the price book owns them (usage-and-limits R2.1), and a route's price
reference is its (`provider`, `model`) pair, the key `PricingPort` prices by.

Numbers that reach a hash are `Decimal`, read from the YAML text of the value,
never through a float, so the same file hashes the same everywhere (ADR-0109
Consequences).

`ModelProfileRegistry` holds the two layers. It is read by `ModelResolver`
(`model/resolver.py`) and nothing else; a door asks the resolver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Literal
from uuid import UUID

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from dw_agent_runtime.registry import ConfigError
from dw_kernel.overlay import TenantOverlay

PROFILE_SCHEMA_VERSION: Final = "2.0"

# The routes a profile may declare, in the order they are written. `embedding`
# is retrieval: a run pins the others, never it (ADR-0118, Amendments 2026-11-04).
GENERATION_ROUTES: Final = ("structured_extraction", "reasoning", "chat", "deep_reasoning")
PINNED_ROUTES: Final = (*GENERATION_ROUTES, "fallback")


class Provider(StrEnum):
    """Providers this repo ships an adapter for. ``ModelRoute.provider`` stays
    ``str``: the adapter registry is an open seam."""

    MOCK = "mock"
    OPENAI_COMPATIBLE = "openai_compatible"
    OPENAI_RESPONSES = "openai_responses"


def _decimal_text(value: Any) -> Any:
    """A YAML float reaches the model as a float; its text is what was written,
    so it becomes a `Decimal` through `str`, never through binary."""
    if isinstance(value, float):
        return str(value)
    return value


class ModelCapabilities(BaseModel):
    """The closed set of twelve (ADR-0118 decision 2, Amendments 2026-11-04).

    An undeclared flag is unsupported. Readers in W1: tools-and-skills/04
    (`strict_tools`, `max_strict_tools`, `numeric_bounds`) and context
    compaction (`max_input_tokens`); `make check-model` compares what it
    probes with what is declared (R2.5). The rest are read in W2.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_calling: bool = False
    parallel_tool_calls: bool = False
    strict_tools: bool = False
    # The most `strict: true` tools one call may carry; unset is no ceiling
    # (tools-and-skills/04, `adapters.studio_tools.turn_capabilities`).
    max_strict_tools: int | None = Field(default=None, gt=0)
    numeric_bounds: bool = False
    structured_output: bool = False
    reasoning_effort: bool = False
    usage_reporting: bool = False
    stream_usage: bool = False
    provider_tool_search: bool = False
    # The most input one call on this route is sent. Read by context
    # compaction, which splits what it summarises into calls no larger than
    # this; a summariser route must declare it, and compaction refuses to build
    # otherwise rather than fall back to a number nobody chose.
    max_input_tokens: int | None = Field(default=None, gt=0)
    vision: bool = False


class ModelRoute(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str
    # Where this route processes what it is sent, and who processes it
    # (ADR-0123 decision 5). No default: a route on a gateway alias FOG-18 has
    # not located says `foreign`, never `vn`.
    data_location: Literal["vn", "foreign"]
    processor: str = Field(min_length=1)
    # Days the processor keeps a request; `null` written out says "not known".
    retention_days: int | None = Field(ge=0)
    no_training: bool
    timeout_seconds: int = Field(default=60, gt=0, le=600)
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None
    # Chat routes on the Responses dialect only: ask the provider to return a
    # readable summary of the reasoning it already did and charged for. Off by
    # default because the summary is extra output tokens on every call, and it
    # is worth paying for only where a human watches the answer being written.
    reasoning_summary: Literal["auto", "concise", "detailed"] | None = None
    temperature: Decimal | None = Field(default=None, ge=0, le=2)
    # Embedding routes only: the vector width to build the index at. Required
    # there because it decides the Qdrant collection's shape, and a shape is not
    # something to discover at runtime from whatever the provider returned.
    dimensions: int | None = Field(default=None, gt=0)
    capabilities: ModelCapabilities = ModelCapabilities()

    @field_validator("processor")
    @classmethod
    def _processor_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("processor is blank")
        return value

    @field_validator("temperature", mode="before")
    @classmethod
    def _temperature_text(cls, value: Any) -> Any:
        return _decimal_text(value)


class ModelBudgets(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_input_tokens_per_run: int = Field(default=120_000, gt=0)
    max_cost_usd_per_run: Decimal = Field(default=Decimal("2.0"), gt=0)

    @field_validator("max_cost_usd_per_run", mode="before")
    @classmethod
    def _cost_text(cls, value: Any) -> Any:
        return _decimal_text(value)


class ModelProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2.0"]
    profile_id: str
    # The profile's version (semver), pinned with its content hash.
    routing_policy_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    structured_extraction: ModelRoute
    reasoning: ModelRoute
    chat: ModelRoute | None = None
    deep_reasoning: ModelRoute | None = None
    fallback: ModelRoute | None = None
    # Retrieval, not generation. Absent means this profile cannot build an index,
    # which is deliberate for the mock profiles: an embedding route that silently
    # fell back to a default would produce a collection nobody chose the width of.
    embedding: ModelRoute | None = None
    budgets: ModelBudgets = ModelBudgets()

    @model_validator(mode="after")
    def _embedding_route_declares_its_width(self) -> ModelProfile:
        if self.embedding is not None and self.embedding.dimensions is None:
            raise ValueError("an embedding route must declare `dimensions`")
        return self

    def pinned_routes(self) -> dict[str, dict[str, Any]]:
        """Every route a run may use, by value: all but `embedding`, as JSON
        values (`Decimal` as text). What a run manifest pins and what
        `content_hash` is taken over, so the two cannot disagree."""
        routes: dict[str, dict[str, Any]] = {}
        for name in PINNED_ROUTES:
            route: ModelRoute | None = getattr(self, name)
            if route is not None:
                routes[name] = route.model_dump(mode="json")
        return routes


@dataclass
class ModelProfileRegistry:
    # Platform profiles plus per-tenant overrides. A customer on their own
    # model contract, or one whose data may not leave a region, routes through
    # its own profile rather than through a second deployment. In W1 no
    # production code loads a tenant layer (ADR-0118 decision 1); its source is
    # tenant-config's `model_profile` versions in W2.
    _profiles: TenantOverlay[str, ModelProfile] = field(default_factory=TenantOverlay)

    def load_directory(self, directory: Path, *, tenant_id: UUID | None = None) -> None:
        for path in sorted(directory.glob("*.yaml")):
            self.load_file(path, tenant_id=tenant_id)

    def load_file(self, path: Path, *, tenant_id: UUID | None = None) -> ModelProfile:
        profile = load_profile(path)
        self.register(profile, tenant_id=tenant_id)
        return profile

    def register(self, profile: ModelProfile, *, tenant_id: UUID | None = None) -> None:
        if self._profiles.existing(profile.profile_id, tenant_id=tenant_id) is not None:
            raise ConfigError(f"model profile already registered: {profile.profile_id}")
        self._profiles.put(profile.profile_id, profile, tenant_id=tenant_id)

    def layer(self, profile_id: str, *, tenant_id: UUID | None) -> ModelProfile | None:
        """One layer's own profile, never the other's: the tenant's when
        `tenant_id` is given, the platform's when it is None. The resolver
        decides the order and the plan filter; this only answers."""
        return self._profiles.existing(profile_id, tenant_id=tenant_id)

    def platform_ids(self) -> frozenset[str]:
        return frozenset(profile.profile_id for profile in self._profiles.platform_values())


def load_profile(path: Path) -> ModelProfile:
    """One profile file, or `ConfigError` naming it: a schema `"1.0"`, a price
    key, a capability outside the twelve or a route without its data route
    stops the process that loads it (R2.3, R3.1)."""
    try:
        return ModelProfile.model_validate(yaml.safe_load(path.read_bytes()))
    except (yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"model profile {path.name} invalid: {exc}") from exc
