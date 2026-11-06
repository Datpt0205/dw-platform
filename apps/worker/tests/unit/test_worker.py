import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from dw_worker.consumers import ConsumerRegistry
from dw_worker.health import beat, is_alive
from dw_worker.main import build_registry, run_worker
from dw_worker.settings import WorkerSettings

pytestmark = pytest.mark.unit


def test_heartbeat_roundtrip(tmp_path: Path) -> None:
    hb = tmp_path / "heartbeat"
    beat(hb)
    assert is_alive(hb, max_age_seconds=10)
    assert not is_alive(tmp_path / "missing", max_age_seconds=10)


def test_registry_rejects_duplicates_and_blank_names() -> None:
    registry = ConsumerRegistry()

    async def consumer() -> None: ...

    registry.register("outbox", consumer)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("outbox", consumer)
    with pytest.raises(ValueError, match="blank"):
        registry.register("  ", consumer)


async def test_worker_runs_consumers_and_shuts_down(tmp_path: Path) -> None:
    settings = WorkerSettings(
        heartbeat_file=tmp_path / "hb",
        heartbeat_interval_seconds=0.05,
        poll_interval_seconds=0.05,
    )
    registry = ConsumerRegistry()
    calls = 0

    async def counting_consumer() -> None:
        nonlocal calls
        calls += 1

    registry.register("counter", counting_consumer)
    shutdown = asyncio.Event()

    worker_task = asyncio.create_task(run_worker(settings, registry, shutdown))
    await asyncio.sleep(0.3)
    shutdown.set()
    await asyncio.wait_for(worker_task, timeout=2)

    assert calls >= 2, "consumer should run repeatedly"
    assert is_alive(settings.heartbeat_file, max_age_seconds=5)


async def test_failing_consumer_does_not_kill_worker(tmp_path: Path) -> None:
    settings = WorkerSettings(
        heartbeat_file=tmp_path / "hb",
        heartbeat_interval_seconds=0.05,
        poll_interval_seconds=0.05,
    )
    registry = ConsumerRegistry()

    async def broken_consumer() -> None:
        raise RuntimeError("boom")

    registry.register("broken", broken_consumer)
    shutdown = asyncio.Event()
    worker_task = asyncio.create_task(run_worker(settings, registry, shutdown))
    await asyncio.sleep(0.3)
    assert not worker_task.done(), "worker must survive consumer failures"
    shutdown.set()
    await asyncio.wait_for(worker_task, timeout=2)


def bare_settings(**overrides: object) -> WorkerSettings:
    """Settings with every lane's infra explicitly absent.

    Stated rather than defaulted because these fields read plain environment
    variables (``S3_ENDPOINT_URL``, ``LANGFUSE_ENABLED``, …): a developer shell
    with a dev stack exported would otherwise decide what this process wires.
    """
    absent: dict[str, object] = {
        "database_url": None,
        "s3_endpoint_url": None,
        "qdrant_url": None,
        "langfuse_enabled": False,
        "otel_endpoint": None,
        "zalo_bot_token": "",
        "zalo_link_secret": "",
    }
    absent.update(overrides)
    return WorkerSettings(**absent)  # type: ignore[arg-type]


def test_a_host_with_no_infrastructure_wires_no_lane() -> None:
    """Every lane is conditional, so the heartbeat-only worker is a real shape."""
    assert set(build_registry(bare_settings()).all()) == set()


def test_only_the_platform_lanes_are_wired() -> None:
    """The lanes a database alone is enough for, and no more.

    The outbox, and retention twice. Retention joined the platform set the day
    memory got a lifecycle: `memory.items` is a platform table, so the platform
    is what expires it — a context adds its own rules on top rather than owning
    the only ones. Ingest still needs object storage, and the reaper is
    registered only when something above it gave it a queue.

    Two retention lanes and not one because memory and knowledge expire on
    different terms and a pass that failed would otherwise take the other's work
    down with it. They read ONE policy file, which is the part that matters: a
    build where the two halves of a compliance commitment disagreed is the
    failure this split would otherwise invite. `partitions` reads the same file
    but only ever creates ahead of need, never deletes, so it carries none of
    that risk.

    `retention_limits` is the fifth: the limit counters of past periods and
    leases closed long ago (usage-and-limits R5.7), on the terms of their two
    retention fragments, never a number in code; it replaced the spend guard's
    lane with the guard itself (ADR-0121 decision 7).
    `notifications_retention` is the sixth: the in-app inbox's 90 days live in
    `platform.prune_notifications()` itself.
    `checkpoint_retention` is the seventh, and reads the policy file again:
    a checkpoint holds a conversation verbatim, so how long it stays is a
    compliance answer like memory's (`checkpoints` in the same file).
    `channel_link_nonces_retention` is the eighth: one-time link tokens a day
    past their expiry, a technical bound like the spend guard's.
    `channel_inbound_messages_retention` is the ninth: inbound chat message ids
    kept seven days for the dedupe (`INBOUND_MESSAGE_RETENTION`), its own lane
    because each pruner is.
    `channel_deliveries_retention` is the tenth: notifications sent (or not)
    through a linked chat, 90 days and never a pending one, the database's
    constant (`platform.prune_channel_deliveries()`). Wired without a bot
    token too: rows are queued for anyone linked whether or not this host sends.
    `approval_codes_retention` is the eleventh: single-use decision codes
    (channels Z5) a day old, the database's constant
    (`platform.prune_approval_decision_codes()`), whether or not this host polls.
    `tool_claims_retention` is the twelfth: tool claims past `expires_at`, which
    guard nothing once a later call may take them over (runtime-hardening R6.7).
    `dw_work` is the thirteenth: Digital Workers take their work from the
    shared queue (digital-worker R3.6), a database being all it needs.
    `dw_timers` is the fourteenth: a DW's run that waited on a timer runs on
    once `wake_at` has passed (wf-lite R6.12), on the same database.
    `usage_rollup` is the fifteenth: today and yesterday of each company with
    recent usage, recomputed into `platform.usage_daily` every five minutes
    (usage-and-limits R3.5).
    `reaper` is the sixteenth, since it has a queue on every host with a
    database: the leases of runs whose process died (usage-and-limits R5.4).
    `studio_runs` is the seventeenth: Studio runs are taken from the run row
    itself, fairly by tenant, and run only here, never in the API
    (workflow-engine R5.1); `studio_run_reaper` the eighteenth, which ends
    overdue runs and queues again or dead-letters those whose worker died
    (R5.6, R5.7, R5.23). Both need a database alone.

    Naming the whole set is the point: a context's lane arriving in this process
    becomes a visible change rather than a silent one.
    """
    settings = bare_settings(database_url="postgresql+asyncpg://dw:dw@localhost/dw")
    assert set(build_registry(settings).all()) == {
        "outbox",
        "retention",
        "retention_knowledge",
        "partitions",
        "retention_limits",
        "notifications_retention",
        "checkpoint_retention",
        "channel_link_nonces_retention",
        "channel_inbound_messages_retention",
        "channel_deliveries_retention",
        "approval_codes_retention",
        "tool_claims_retention",
        "dw_work",
        "dw_timers",
        "usage_rollup",
        "reaper",
        "studio_runs",
        "studio_run_reaper",
    }


def test_the_offboarding_lane_needs_object_storage_too_not_just_a_database() -> None:
    """Unlike every lane above, a database alone is not enough for this one:
    export/purge touch three buckets and the vector index alongside Postgres,
    so it stays unregistered — not half-wired against infra that is not
    there — until `s3_endpoint_url` is set too."""
    db_only = bare_settings(database_url="postgresql+asyncpg://dw:dw@localhost/dw")
    assert "offboarding" not in build_registry(db_only).all()

    db_and_s3 = bare_settings(
        database_url="postgresql+asyncpg://dw:dw@localhost/dw",
        s3_endpoint_url="http://localhost:9000",
    )
    assert "offboarding" in build_registry(db_and_s3).all()


def test_the_pinned_retention_policy_promises_only_classes_code_can_assign() -> None:
    """A memory class nothing can put on a row is a promise in a compliance
    file that the code does not keep (`failure-modes.md` #1). `sensitive`,
    `ephemeral` and `legal_hold` were exactly that until 1.5.0; a class comes
    back together with the path that assigns it, and this goes red until then.

    Equality, so the other direction holds too: the class the service writes
    has a term in the file the sweep reads.
    """
    from dw_memory.service import RETENTION_CLASS
    from dw_platform.retention_policy import load_retention_policy

    assert set(load_retention_policy().classes) == {RETENTION_CLASS}


def test_the_channel_delivery_lane_needs_a_bot_token_and_runs_on_its_own_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wired with a database and a bot token, whatever ZALO_UPDATES_MODE says:
    a webhook host sends the same way. Thirty seconds unless configured."""
    monkeypatch.delenv("DW_WORKER_CHANNEL_DELIVERY_INTERVAL_SECONDS", raising=False)
    db = "postgresql+asyncpg://dw:dw@localhost/dw"
    assert "channel_delivery" not in build_registry(bare_settings(database_url=db)).all()

    webhook = build_registry(
        bare_settings(database_url=db, zalo_bot_token="t", zalo_updates_mode="webhook")
    )
    assert "channel_delivery" in webhook.all()
    assert "zalo_link_poll" not in webhook.all()
    assert webhook.interval_for("channel_delivery", 1.0) == 30.0

    quick = build_registry(
        bare_settings(database_url=db, zalo_bot_token="t", channel_delivery_interval_seconds=5)
    )
    assert quick.interval_for("channel_delivery", 1.0) == 5.0


def test_every_purged_fragment_has_its_purger() -> None:
    """A fragment whose purger is a lane's (`row_delete`, `object_delete`,
    `column_clear`) and that is enforced names a store the retention lane must
    reach; with no entry in the registry, its term would be written and never
    carried out (`failure-modes.md` #1). `drop_partition` is the `partitions`
    lane's own, and `none` has nothing to run."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from dw_platform.retention_policy import load_retention_policy
    from dw_worker.main import build_retention_purgers

    purged = {
        key
        for key, fragment in load_retention_policy().stores.items()
        if fragment.enforced and fragment.purger in {"row_delete", "object_delete", "column_clear"}
    }
    assert purged - set(build_retention_purgers(async_sessionmaker()).all()) == set()


def test_the_worker_registers_offboarding_alone_for_the_tenant_wide_scope() -> None:
    """record-access ticket 03 (ADR-0105 decision 5): W1's registry, built at
    this composition root, holds the offboarding lane, which says it reads the
    tables private to one person."""
    from dw_worker.main import build_tenant_wide_scopes

    [lane] = build_tenant_wide_scopes().lanes()
    assert lane.lane == "offboarding"
    assert lane.reads_private_tables is True
    assert lane.reason.strip()


# runtime-hardening R10.6: how many companies a tick of the outbox serves.
@pytest.mark.parametrize("tenants", [0, 65])
def test_outbox_tenants_per_tick_outside_its_range_is_refused(tenants: int) -> None:
    with pytest.raises(ValidationError):
        WorkerSettings(outbox_tenants_per_tick=tenants)
