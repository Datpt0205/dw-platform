"""The two scales the harness runs at, each named once.

`d12` is the ticket's own numbers (D12: 10^7 records per object, 5x10^7 per
tenant). `smoke` keeps the same shape at 10^6 records for T1, every record count
divided by 50 and the organisation kept whole, so the dev machine can run the
harness, the seed, the load and the self-check. No smoke number stands in for a
D12 number (ticket 01 step 1).
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Scale:
    name: str
    t1_records: int
    lead_every: int  # one record in `lead_every` is a `mkt_lead` (D12: 10^7 of 5x10^7)
    t2_records: int
    small_tenants: int
    small_tenant_records: int
    objects: int
    people: int
    workspaces: int
    teams: int
    campaign_children: int
    service_account_leads: int
    share_recipient_shares: int
    sharing_rule_versions: int
    # Load.
    sessions: int
    read_samples: int  # per series, warm and cold; a p95 needs >= 1000 (ticket 01 step 4)
    soak_seconds: int
    soak_writes_per_second: int
    import_rows: int
    import_sessions: int
    campaign_writers: int
    campaign_creates_per_writer: int
    qerror_queries: int
    hot_updates: int
    # Smoke only: a shortened soak scales autovacuum's trigger on T1's partition
    # by the same factor, so cycles happen inside it. Empty at d12, where the
    # image defaults apply (ticket 01 step 1, the host's configuration).
    t1_partition_reloptions: tuple[tuple[str, str], ...] = ()


D12 = Scale(
    name="d12",
    t1_records=50_000_000,
    lead_every=5,
    t2_records=1_000_000,
    small_tenants=98,
    small_tenant_records=10_000,
    objects=50,
    people=5_000,
    workspaces=200,
    teams=300,
    campaign_children=100_000,
    service_account_leads=1_000_000,
    share_recipient_shares=500,
    sharing_rule_versions=50,
    sessions=50,
    read_samples=1_000,
    soak_seconds=7_200,
    soak_writes_per_second=200,
    import_rows=1_000_000,
    import_sessions=8,
    campaign_writers=32,
    campaign_creates_per_writer=100,
    qerror_queries=300,
    hot_updates=5_000,
)

SMOKE = Scale(
    name="smoke",
    t1_records=1_000_000,
    lead_every=5,
    t2_records=20_000,
    small_tenants=98,
    small_tenant_records=200,
    objects=50,
    people=5_000,
    workspaces=200,
    teams=300,
    campaign_children=2_000,
    service_account_leads=20_000,
    share_recipient_shares=500,
    sharing_rule_versions=50,
    sessions=50,
    read_samples=1_000,
    soak_seconds=300,
    soak_writes_per_second=200,
    import_rows=20_000,
    import_sessions=8,
    campaign_writers=32,
    campaign_creates_per_writer=50,
    qerror_queries=200,
    hot_updates=2_000,
    # 2 h -> 5 min is a factor 24; 0.2 / 24 rounded down.
    t1_partition_reloptions=(
        ("autovacuum_vacuum_scale_factor", "0.008"),
        ("autovacuum_vacuum_insert_scale_factor", "0.008"),
    ),
)

# The harness's own check of itself (seconds, not minutes): the same code path
# on a seed small enough to break a guard and watch the exit code change.
TINY = replace(
    SMOKE,
    name="tiny",
    t1_records=20_000,
    t2_records=2_000,
    small_tenant_records=20,
    campaign_children=200,
    service_account_leads=500,
    soak_seconds=20,
    soak_writes_per_second=100,
    import_rows=1_000,
    campaign_creates_per_writer=10,
    qerror_queries=40,
    hot_updates=500,
    t1_partition_reloptions=(),
)

SCALES: dict[str, Scale] = {s.name: s for s in (TINY, SMOKE, D12)}
