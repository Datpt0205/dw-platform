"""The dated price book: the one owner of what a billable call costs
(usage-and-limits R2; ADR-0121 decision 2).

An entry prices one usage kind of one (provider, model) from `effective_from`
until a later entry of the same key takes over. A call is priced by the entry
with the latest `effective_from` not later than the call, so changing a price
from a date never reprices what was recorded before it (R2.4): a settled usage
record keeps the book version and the cost it was given.

A tier is part of the key. The input tokens of the call, cached or not, pick
the tier, and the tier prices the whole call (M15). No entry for a kind the
call used, at its moment, is `PriceNotFoundError`, never a cost of zero (R2.5).

`price` takes the run's `tenant_id` from the start (`CLAUDE.md`, "Per-tenant
artifacts"): a tenant's own entries are BYOM in W2 and will resolve like
`TenantOverlay`, so W1 answers every tenant from the platform layer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from uuid import UUID

from dw_kernel.errors import ConfigError, PriceNotFoundError

__all__ = [
    "INPUT_KINDS",
    "USAGE_KINDS",
    "PriceBook",
    "PriceEntry",
    "Quote",
    "price_book_from_document",
]

# Per million: what a provider's price list counts tokens in.
_PER_MILLION: Final = Decimal(1_000_000)
_PER_UNIT: Final = Decimal(1)

# The closed set of usage kinds, each with the quantity one price is for. The
# code-step kinds are reserved vCPU and GB times running seconds (DO-45.1).
USAGE_KINDS: Final[Mapping[str, Decimal]] = {
    "input_uncached": _PER_MILLION,
    "cache_read": _PER_MILLION,
    "cache_write_5m": _PER_MILLION,
    "cache_write_1h": _PER_MILLION,
    "output": _PER_MILLION,
    "image_input": _PER_MILLION,
    "audio_input": _PER_MILLION,
    "embedding_input": _PER_MILLION,
    "rerank_search_unit": _PER_UNIT,
    "extraction_page": _PER_UNIT,
    "transcription_second": _PER_UNIT,
    "sandbox_vcpu_second": _PER_UNIT,
    "sandbox_gb_second": _PER_UNIT,
    "server_tool_call": _PER_UNIT,
}

# The kinds that are the call's input, whose sum picks the tier.
INPUT_KINDS: Final = frozenset({"input_uncached", "cache_read", "cache_write_5m", "cache_write_1h"})


@dataclass(frozen=True)
class PriceEntry:
    """`usd` for `USAGE_KINDS[usage_kind]` units of one kind, from one moment."""

    provider: str
    model: str
    usage_kind: str
    min_input_tokens: int
    usd: Decimal
    effective_from: datetime

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.provider, self.model, self.usage_kind, self.min_input_tokens)

    @property
    def entry_id(self) -> str:
        return (
            f"{self.provider}/{self.model}/{self.usage_kind}/{self.min_input_tokens}"
            f"@{self.effective_from.isoformat()}"
        )


@dataclass(frozen=True)
class Quote:
    """What one call cost, and which book and entries said so."""

    cost_usd: Decimal
    price_book_version: str
    entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class PriceBook:
    """The platform layer of the book: one id, one version, its entries.

    Built only through `__post_init__`'s checks (R2.2): an entry of a kind the
    book does not know, a negative price, a moment with no time zone, or two
    entries of one key from the same moment, refuse the whole book.
    """

    book_id: str
    version: str
    entries: tuple[PriceEntry, ...]

    def __post_init__(self) -> None:
        if not self.book_id.strip() or not self.version.strip():
            raise ConfigError("a price book names its id and version")
        seen: set[tuple[tuple[str, str, str, int], datetime]] = set()
        for entry in self.entries:
            if entry.usage_kind not in USAGE_KINDS:
                raise ConfigError(
                    "price book entry of an unknown usage kind",
                    details={"entry": entry.entry_id, "usage_kind": entry.usage_kind},
                )
            if entry.usd < 0:
                raise ConfigError(
                    "price book entry with a negative price", details={"entry": entry.entry_id}
                )
            if entry.min_input_tokens < 0:
                raise ConfigError("price book tier below zero", details={"entry": entry.entry_id})
            if entry.effective_from.tzinfo is None:
                raise ConfigError(
                    "price book entry without a time zone", details={"entry": entry.entry_id}
                )
            moment = (entry.key, entry.effective_from)
            if moment in seen:
                raise ConfigError(
                    "two price book entries of one key from the same moment",
                    details={"entry": entry.entry_id},
                )
            seen.add(moment)

    def price(
        self,
        tenant_id: UUID,
        quantities: Mapping[str, int],
        provider: str,
        model: str,
        at: datetime,
    ) -> Quote:
        """The cost of one call of `quantities`, at `at`.

        `tenant_id` selects the tenant layer in W2 (BYOM); in W1 every tenant
        gets the platform layer, so it is accepted and not yet read.
        """
        del tenant_id  # W1: every tenant is priced from the platform layer.
        if at.tzinfo is None:
            raise ValueError("a call is priced at an aware moment")
        unknown = sorted(set(quantities) - set(USAGE_KINDS))
        if unknown:
            raise ValueError(f"unknown usage kinds {unknown}")
        if any(quantity < 0 for quantity in quantities.values()):
            raise ValueError("a quantity is never negative")
        basis = sum(quantities.get(kind, 0) for kind in INPUT_KINDS)
        cost = Decimal(0)
        used: list[str] = []
        for kind in sorted(quantities):
            quantity = quantities[kind]
            if quantity == 0:
                continue
            entry = self._entry(provider, model, kind, basis, at)
            cost += Decimal(quantity) * entry.usd / USAGE_KINDS[kind]
            used.append(entry.entry_id)
        return Quote(cost_usd=cost, price_book_version=self.version, entry_ids=tuple(used))

    def covers(self, provider: str, model: str, usage_kind: str, at: datetime) -> bool:
        """Whether a call of this kind at `at`, of any size, would be priced:
        the lowest tier has an entry in force."""
        try:
            self._entry(provider, model, usage_kind, 0, at)
        except PriceNotFoundError:
            return False
        return True

    def _entry(self, provider: str, model: str, kind: str, basis: int, at: datetime) -> PriceEntry:
        in_force: dict[int, PriceEntry] = {}
        for entry in self.entries:
            if (entry.provider, entry.model, entry.usage_kind) != (provider, model, kind):
                continue
            if entry.effective_from > at:
                continue
            current = in_force.get(entry.min_input_tokens)
            if current is None or entry.effective_from > current.effective_from:
                in_force[entry.min_input_tokens] = entry
        tiers = [tier for tier in in_force if tier <= basis]
        if not tiers:
            raise PriceNotFoundError(
                "no price book entry covers this call",
                price_book_version=self.version,
                details={
                    "provider": provider,
                    "model": model,
                    "usage_kind": kind,
                    "at": at.isoformat(),
                },
            )
        return in_force[max(tiers)]


def _decimal(value: object, where: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ConfigError(f"{where}: a price is a number", details={"value": repr(value)})
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ConfigError(f"{where}: a price is a number", details={"value": repr(value)}) from exc


def _moment(value: object, where: str) -> datetime:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ConfigError(f"{where}: effective_from is an ISO 8601 moment") from exc
    else:
        raise ConfigError(f"{where}: effective_from is an ISO 8601 moment")
    if moment.tzinfo is None:
        raise ConfigError(f"{where}: effective_from names its time zone (M14)")
    return moment


def _entries(model: Mapping[str, Any], index: int) -> Iterable[PriceEntry]:
    where = f"models[{index}]"
    for field in ("provider", "model", "effective_from", "source", "prices"):
        if field not in model:
            raise ConfigError(f"{where}: missing `{field}`")
    extra = set(model) - {"provider", "model", "effective_from", "source", "prices", "tiers"}
    if extra:
        raise ConfigError(f"{where}: unknown keys {sorted(extra)}")
    provider, name = str(model["provider"]), str(model["model"])
    effective_from = _moment(model["effective_from"], where)
    tiers: list[tuple[int, Mapping[str, object]]] = [(0, model["prices"])]
    for t, tier in enumerate(model.get("tiers") or []):
        if set(tier) != {"min_input_tokens", "prices"}:
            raise ConfigError(f"{where}.tiers[{t}]: `min_input_tokens` and `prices` only")
        tiers.append((int(tier["min_input_tokens"]), tier["prices"]))
    for minimum, prices in tiers:
        if not isinstance(prices, Mapping) or not prices:
            raise ConfigError(f"{where}: `prices` maps usage kinds to prices")
        for kind, usd in prices.items():
            yield PriceEntry(
                provider=provider,
                model=name,
                usage_kind=str(kind),
                min_input_tokens=minimum,
                usd=_decimal(usd, f"{where}.{kind}"),
                effective_from=effective_from,
            )


def price_book_from_document(document: Mapping[str, Any]) -> PriceBook:
    """A book from its parsed file (`configs/pricing/price_book@<semver>.yaml`).

    The file groups entries by model and moment; each kind under `prices` (and
    under a tier's) is one entry. Anything the book's checks refuse refuses the
    file, so a bad edit stops the process that loads it (R2.2).
    """
    if document.get("schema_version") != "1.0":
        raise ConfigError("price book schema_version must be 1.0")
    if document.get("currency") != "USD":
        raise ConfigError("price book prices are in USD")
    models = document.get("models")
    if not isinstance(models, list) or not models:
        raise ConfigError("price book lists its models")
    entries = tuple(entry for i, model in enumerate(models) for entry in _entries(model, i))
    return PriceBook(
        book_id=str(document.get("price_book_id", "")),
        version=str(document.get("version", "")),
        entries=entries,
    )
