"""What the seed is made of: slot families, object layouts, ids and the organisation.

Every id is a pure function of a kind, a tenant index and a number, the same in
Python (`bench_uuid`) and in SQL (`studio.bench_uuid`, `ddl.STUB_FUNCTIONS`), so a
profile's principal, a campaign or a lookup target is named without a query and
the seed is the same on every run (one seed, reused unchanged by record-access/01).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property

from .scales import Scale

# --------------------------------------------------------------------- slots --
# Family -> (SQL type, slot count) of the proposed P1 set (ADR-0107 decision 1,
# ticket 01 step 2), then W2's known families `l` and `m` (A1).
W1_FAMILIES: dict[str, tuple[str, int]] = {
    "t": ('text COLLATE "vi-VN-x-icu"', 24),
    "i": ("bigint", 12),
    "f": ("double precision", 8),
    "d": ("date", 8),
    "z": ("timestamptz", 8),
    "b": ("boolean", 8),
    "u": ("text", 4),
}
# Decision of this ticket (no count is written anywhere): four lookups and two
# master-detail slots, each a composite FK into studio.records.
W2_FAMILIES: dict[str, tuple[str, int]] = {"l": ("uuid", 4), "m": ("uuid", 2)}


def slot_names(family: str, count: int) -> list[str]:
    return [f"{family}{n:02d}" for n in range(1, count + 1)]


def slots_of(families: dict[str, tuple[str, int]]) -> list[tuple[str, str, str]]:
    """(slot, family, SQL type) for every slot of the families, in order."""
    return [
        (slot, family, sql_type)
        for family, (sql_type, count) in families.items()
        for slot in slot_names(family, count)
    ]


# ----------------------------------------------------------------------- ids --
KIND_TENANT = 1
KIND_WORKSPACE = 2
KIND_OBJECT = 3
KIND_PERSON = 4
KIND_TEAM = 5
KIND_RULE = 6
KIND_AGENT = 7
KIND_FIELD = 8


def bench_uuid(kind: int, tenant_idx: int, n: int) -> uuid.UUID:
    """Mirror of `studio.bench_uuid(kind, tenant_idx, n)`."""
    return uuid.UUID(f"{kind:04x}{tenant_idx:012x}{n:016x}")


def record_uuid(tenant_idx: int, n: int, created_ms: int) -> uuid.UUID:
    """Mirror of `studio.bench_record_id`: a UUIDv7 layout, time first."""
    return uuid.UUID(f"{created_ms:012x}7{tenant_idx:03x}8{n:015x}")


# ------------------------------------------------------------------- objects --
LEAD = 0
CAMPAIGN = 1
ACCOUNT = 2  # the other object whose t01 holds near-unique e-mails
NAMES_OBJECT = 49  # holds the five names of the collation check

# t01 of mkt_lead: a picklist of few values (R9.8's shared slot, first distribution).
LEAD_STATUSES = ("Mới", "Đang liên hệ", "Đã hẹn", "Đủ điều kiện", "Không phù hợp", "Đã chốt")


@dataclass(frozen=True)
class ObjectLayout:
    index: int
    api_name: str
    used: dict[str, int]  # family -> number of slots used, from 01

    def used_slots(self, families: dict[str, tuple[str, int]]) -> list[str]:
        return [
            slot
            for family, (_t, count) in families.items()
            for slot in slot_names(family, min(count, self.used.get(family, 0)))
        ]


def object_layouts(count: int) -> list[ObjectLayout]:
    layouts = [
        ObjectLayout(
            LEAD,
            "mkt_lead",
            {"t": 16, "u": 2, "i": 8, "f": 4, "d": 4, "z": 4, "b": 6, "l": 1, "m": 1},
        ),
        ObjectLayout(CAMPAIGN, "mkt_campaign", {"t": 8, "i": 4, "d": 2, "z": 2, "b": 2}),
    ]
    for k in range(2, count):
        layouts.append(
            ObjectLayout(
                k,
                "account" if k == ACCOUNT else f"obj_{k:02d}",
                {
                    "t": 6 + k % 12,
                    "u": k % 3,
                    "i": 3 + k % 6,
                    "f": 1 + k % 4,
                    "d": 2 + k % 4,
                    "z": 1 + k % 4,
                    "b": 2 + k % 5,
                    "l": 1 if k % 7 == 0 else 0,
                },
            )
        )
    return layouts


# -------------------------------------------------------------- organisation --
def attach_heap(parent: dict[int, int], root: int, ids: Iterable[int], k: int) -> None:
    """Hang `ids` under `root` as a k-ary heap: the first k under the root."""
    members = list(ids)
    for j, node in enumerate(members):
        parent[node] = root if j < k else members[(j - k) // k]


def depth_of(parent: dict[int, int], node: int) -> int:
    depth = 1
    while node in parent:
        node = parent[node]
        depth += 1
    return depth


def subtree(parent: dict[int, int], root: int) -> set[int]:
    children: dict[int, list[int]] = {}
    for child, p in parent.items():
        children.setdefault(p, []).append(child)
    seen, stack = {root}, [root]
    while stack:
        for child in children.get(stack.pop(), []):
            seen.add(child)
            stack.append(child)
    return seen


@dataclass(frozen=True)
class Organisation:
    """T1's people, workspace tree and teams (ticket 01 step 3)."""

    people: int
    workspaces: int
    teams: int

    # People 0 (5,000 subordinates), 1 (500) and 2 (50) are the three managers
    # of the read profiles; the tree is 8 levels deep.
    M5000, M500, M50 = 0, 1, 2

    @cached_property
    def manager_of(self) -> dict[int, int]:
        parent: dict[int, int] = {self.M500: self.M5000, self.M50: self.M500}
        m50_team = range(3, 3 + 50)
        m500_rest = range(3 + 50, 2 + 500)
        attach_heap(parent, self.M50, m50_team, 2)
        attach_heap(parent, self.M500, m500_rest, 4)
        attach_heap(parent, self.M5000, range(2 + 500, self.people), 5)
        return parent

    @cached_property
    def workspace_parent(self) -> dict[int, int]:
        parent: dict[int, int] = {}
        attach_heap(parent, 0, range(1, self.workspaces), 3)
        return parent

    def subordinates(self, manager: int) -> set[int]:
        return subtree(self.manager_of, manager) - {manager}

    def workspace_subtree(self, root: int) -> set[int]:
        return subtree(self.workspace_parent, root)

    def workspace_near(self, size: int) -> int:
        """The workspace whose sub-tree is closest to `size` (40 for a profile)."""
        return min(
            range(self.workspaces),
            key=lambda w: (abs(len(self.workspace_subtree(w)) - size), w),
        )

    def leaf_workspace(self) -> int:
        return self.workspaces - 1

    def home_workspace(self, person: int) -> int:
        return person % self.workspaces

    def team_members(self, team: int) -> list[int]:
        return [p for p in range(self.people) if p % self.teams == team]

    @property
    def service_account(self) -> int:
        return self.people  # one past the people: the service account (person id)

    @property
    def max_manager_depth(self) -> int:
        return max(depth_of(self.manager_of, p) for p in range(self.people))

    @property
    def max_workspace_depth(self) -> int:
        return max(depth_of(self.workspace_parent, w) for w in range(self.workspaces))


def organisation(scale: Scale) -> Organisation:
    return Organisation(scale.people, scale.workspaces, scale.teams)


# A handful of seed people the read profiles act as.
PERSON_OWN = 777
PERSON_TEAM = 1_234
PERSON_WS1 = 2_345
PERSON_WS40 = 3_456
PERSON_COMPANY = 4_567
PERSON_PUBLIC = 4_678
PERSON_SHARE = 4_789
TEAM_OF_PERSON_TEAM = PERSON_TEAM % 300
