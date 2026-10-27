"""How long this deployment keeps data — the contract, not the sweeps.

The rules live here rather than beside any one sweep because "how long do you
keep our data" is one question with one answer. `memory` expires items,
`knowledge` expires deleted documents, and if each owned its own copy of the
schedule the two would drift and the release manifest would carry two versions
of one commitment. Both packages already depend on this one; the kernel, which
is the only layer below it, is deliberately dependency-free and stays that way.

The sweeps themselves stay where the tables are: `dw_memory.retention` and
`dw_knowledge.retention`. This module knows no SQL.

**Deleting, not closing.** `valid_until` answers "this stopped being true" — it
is what supersession writes, and the row stays so a past decision can still be
explained. Retention answers a different question: "we are no longer allowed to
hold this." The two must not share a mechanism, because the second one is what
goes in a contract.

**A class with no `days` never expires.** A legal hold is that shape, deliberately:
an obligation to keep can outlive the ordinary schedule, and the safe way to
express it is a class the sweep cannot touch rather than a flag the sweep must
remember to honour. (`legal_hold` left the policy in 1.5.0 because nothing could
assign it; it returns with the route that sets one.)

**An unknown class is kept, not guessed.** A row naming a class this build does
not have is more likely a newer config than a mistake, and deleting on that
guess is irreversible. It is kept and counted, so the mismatch shows up as a
number rather than as missing data.

**One fragment per store.** How long one store (a table, or a named store such
as an object prefix) is kept is written in its own file,
`configs/policies/retention.d/<schema>.<table>.yaml`, and read only from there
(telemetry-and-audit H-1, R5.13). The versioned file keeps what is shared: the
memory classes, the knowledge windows, how far ahead partitions are made. A
store with no fragment has no term at all, and is never purged on a guess.
"""

from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

__all__ = [
    "NAMED_STORES",
    "RETENTION_FRAGMENTS_DIR",
    "RETENTION_POLICY_PATH",
    "AuditRetention",
    "ChannelDeliveryRetention",
    "CheckpointRetention",
    "KnowledgeRetention",
    "RetentionClass",
    "RetentionFragment",
    "RetentionPolicy",
    "RetentionPurgerRegistry",
    "RetentionTerm",
    "load_retention_fragments",
    "load_retention_policy",
]

# The image sets DW_REPO_ROOT=/app and ships `configs/` there; in a checkout the
# root is derived from this file (`packages/python/dw_platform/src/dw_platform`).
_REPO_ROOT = Path(os.environ.get("DW_REPO_ROOT", str(Path(__file__).resolve().parents[5])))

# The one pin of the retention contract. The worker's sweeps, the terms loader
# and the test holding the policy to the classes code can assign all read these
# two constants, so they cannot read different versions.
RETENTION_POLICY_PATH: Final = _REPO_ROOT / "configs" / "policies" / "retention@1.8.0.yaml"
RETENTION_FRAGMENTS_DIR: Final = _REPO_ROOT / "configs" / "policies" / "retention.d"

# Stores that are not a table, so no `pg_class` row can vouch for their name: a
# column of a table (`platform.worker_runs.payload`) or an object prefix
# (`objects.run_step_payloads`). The ticket that creates such a store adds its
# name here together with its fragment (telemetry-and-audit R5.6).
NAMED_STORES: Final[frozenset[str]] = frozenset()

_STORE_KEY = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$")


class RetentionClass(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # `None` means never swept. Not zero, and not absent — an explicit null, so
    # "keep forever" is something somebody wrote rather than something omitted.
    days: int | None = Field(default=None, ge=1)
    description: str


class KnowledgeRetention(BaseModel):
    """Two windows, because two different things expire on the knowledge side.

    `deleted_grace_days` is how long a document survives somebody marking it
    deleted — marking is a user action and users change their minds.

    `orphan_evidence_grace_days` is how long an evidence row survives losing its
    last citation. It exists because `evidence -> documents` is RESTRICT: until
    orphaned evidence goes, a document that was ever cited can never be hard
    deleted, and the document window above would be a promise the schema cannot
    keep. Today evidence and its `item_evidence` link are written in one
    transaction, so an unlinked row is genuinely unlinked; the window is what
    keeps that from being load-bearing for a writer that later splits them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    deleted_grace_days: int = Field(ge=1)
    orphan_evidence_grace_days: int = Field(ge=1)


class AuditRetention(BaseModel):
    """Partitions made ahead, for every range-partitioned table.

    `months_ahead` has to exceed the gap between two maintenance passes with room
    to spare. A month with no partition sends its rows to the DEFAULT one, and a
    default holding a month's rows blocks that month's partition from ever being
    created — so falling behind is not self-correcting.

    How long each table is kept, and so which months are dropped, is that
    table's fragment's (`RetentionFragment`), since 1.8.0.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    months_ahead: int = Field(ge=1, le=24)


Purger = Literal["drop_partition", "row_delete", "object_delete", "column_clear", "none"]


class RetentionFragment(BaseModel):
    """One store's term, from `retention.d/<store>.yaml`: exactly four keys.

    `days` is a positive number of days; `indefinite` for a store that does not
    expire by age (it goes with `purger: none`, and only with it); `null` when
    nobody has decided yet. A purge destroys data and nothing stands between it
    and the rows, so nothing is purged that somebody did not write a number for.

    `enforced` is separate from `days` because "nobody has decided a term" and
    "a term is decided but may not run yet" are different states, and collapsing
    them loses the decision. It exists so a decided schedule can be recorded
    before the restore procedure it depends on has been rehearsed — enabling an
    irreversible delete on top of an untested safety net is the wrong order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Strict: YAML `true` is not a number of days, nor is `"30"`.
    days: StrictInt | Literal["indefinite"] | None
    purger: Purger
    enforced: bool
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def _a_term_and_its_purger_agree(self) -> RetentionFragment:
        if isinstance(self.days, int) and self.days < 1:
            raise ValueError("`days` is a positive number of days")
        # A purger with no age to measure, or an age with nothing to carry it
        # out, is a promise one side of the pair cannot keep (H-31).
        if (self.days == "indefinite") != (self.purger == "none"):
            raise ValueError("`days: indefinite` goes with `purger: none`, and only with it")
        return self


@dataclass(frozen=True)
class RetentionTerm:
    """A decided term in days, and whether it may be carried out yet."""

    days: int
    enforced: bool


class CheckpointRetention(BaseModel):
    """How long a finished thread's run checkpoints are kept.

    Every checkpoint holds the thread's whole message list, so each superseded
    one is an older verbatim copy of the conversation — including what context
    compaction removed from the live state. Two terms, because two different
    things stop being needed:

    `superseded_days`: a checkpoint that is not its thread's newest. Only the
    newest is needed to continue the thread; the older ones are history.

    `idle_thread_days`: the whole thread, newest included, once nothing has been
    written to it for this long.

    Only threads whose runs have all finished are touched, whatever the terms
    say — a run waiting for a person resumes from these rows.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    superseded_days: int = Field(ge=1)
    idle_thread_days: int = Field(ge=1)

    @model_validator(mode="after")
    def _idle_is_the_longer_term(self) -> CheckpointRetention:
        # The sweep reads candidates by the shorter term and decides by the
        # longer one; the other way round, a thread would be emptied sooner than
        # its own superseded checkpoints expire.
        if self.idle_thread_days < self.superseded_days:
            raise ValueError("idle_thread_days must be at least superseded_days")
        return self


class ChannelDeliveryRetention(BaseModel):
    """How long a queued chat delivery may stay `pending` before it is failed.

    Not a legal term like the rest of this file: a liveness bound. A delivery is
    queued whether or not any host sends, so with the channel unconfigured a row
    would wait forever. A sending lane settles a row within hours, so a row
    pending this long was never going to be sent; it is failed as
    `channel_unconfigured`, on the audit log.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pending_expiry_days: int = Field(ge=1)


class RetentionPolicy(BaseModel):
    """The versioned answer to "how long do you keep our data"."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(pattern=r"^1\.0$")
    policy_id: str
    policy_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    classes: dict[str, RetentionClass]
    knowledge: KnowledgeRetention
    audit: AuditRetention
    checkpoints: CheckpointRetention
    channel_deliveries: ChannelDeliveryRetention
    batch_limit: int = Field(gt=0, le=10_000)
    # From the fragment set, never from the versioned file: `load_retention_policy`
    # fills it, and refuses a file that tries to carry it.
    stores: Mapping[str, RetentionFragment] = Field(default_factory=dict)

    def term(self, store_key: str) -> RetentionTerm | None:
        """`store_key`'s term in days, from its fragment alone.

        `None` when it has no fragment, when nobody has decided (`days: null`),
        and when it does not expire by age (`indefinite`). A term decided but not
        `enforced` is still a term; whether it may run is the caller's question
        (studio-skeleton R3.7, R4.4).
        """
        found = self.stores.get(store_key)
        if found is None or not isinstance(found.days, int):
            return None
        return RetentionTerm(days=found.days, enforced=found.enforced)

    def store_cutoff(self, store_key: str, *, now: datetime) -> datetime | None:
        """The instant before which `store_key`'s rows may be purged, or `None`."""
        found = self.term(store_key)
        if found is None or not found.enforced:
            return None
        return now - timedelta(days=found.days)

    def cutoff_for(self, name: str, *, now: datetime) -> datetime | None:
        """The instant before which rows of this class have outlived their term.

        `None` for a class that never expires and for one this build does not
        know — the caller keeps the row either way, and only the second is worth
        a log line.
        """
        found = self.classes.get(name)
        if found is None or found.days is None:
            return None
        return now - timedelta(days=found.days)


def load_retention_fragments(directory: Path) -> dict[str, RetentionFragment]:
    """Every fragment in `directory`, keyed by its file name less `.yaml`.

    A malformed fragment raises naming its file, so a bad edit stops the process
    that reads it instead of leaving that store without a term.
    """
    fragments: dict[str, RetentionFragment] = {}
    for path in sorted(directory.glob("*.yaml")):
        key = path.name.removesuffix(".yaml")
        if not _STORE_KEY.match(key):
            raise ValueError(f"{path.name}: a fragment is named <schema>.<table>.yaml")
        try:
            fragments[key] = RetentionFragment.model_validate(
                yaml.safe_load(path.read_text(encoding="utf-8"))
            )
        except ValidationError as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
    return fragments


def load_retention_policy(
    path: Path = RETENTION_POLICY_PATH, fragments: Path = RETENTION_FRAGMENTS_DIR
) -> RetentionPolicy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if "stores" in raw:
        raise ValueError(f"{path.name}: a store's term lives in its fragment, not here")
    return RetentionPolicy.model_validate({**raw, "stores": load_retention_fragments(fragments)})


Purge = Callable[[], Awaitable[None]]


class RetentionPurgerRegistry:
    """Store key -> the zero-argument purger that carries out its term.

    Built and frozen at the worker's composition root: the ticket that creates a
    store registers its purger there, and the retention lane runs every entry
    (telemetry-and-audit H-35). A second purger for one key is a build error,
    because two purgers of one store are two answers to how long it is kept.
    """

    def __init__(self, purgers: Mapping[str, Purge] | None = None) -> None:
        self._purgers: dict[str, Purge] = {}
        self._frozen = False
        for key, purge in (purgers or {}).items():
            self.register(key, purge)

    def register(self, store_key: str, purge: Purge) -> None:
        if self._frozen:
            raise RuntimeError("the purger registry is frozen at the composition root")
        if store_key in self._purgers:
            raise ValueError(f"a purger is already registered for {store_key}")
        self._purgers[store_key] = purge

    def freeze(self) -> RetentionPurgerRegistry:
        self._frozen = True
        return self

    def all(self) -> Mapping[str, Purge]:
        return MappingProxyType(self._purgers)
