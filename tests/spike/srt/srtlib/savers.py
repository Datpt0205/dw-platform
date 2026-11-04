"""Two savers with the lease fence of question 1 (workflow-engine/04 step 4).

`FencedSaver` is the platform's `SqlAlchemyCheckpointSaver` with the fence
added inside the transaction of `aput` and `aput_writes`, as ticket 04 asks
("đây là sửa saver, không chỉ bọc"); reads are the platform's own. Three fence
variants:

- `none`: the saver as shipped, no fence;
- `select`: a separate `SELECT ... FOR SHARE` after the tenant bind, one more
  round trip per write;
- `fused`: `srt.lease_held()` called in the very statement that binds the
  tenant, so the fence costs no round trip of its own.

`BlobSaver` is a prototype of ADR-0112 decision 10's later saver: the
checkpoint row holds channel versions only, each channel value is one blob row
per version, written once, and the writes of a task go in one statement.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any, cast

import sqlalchemy as sa
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.checkpoint import (
    SerializerProtocol,
    SqlAlchemyCheckpointSaver,
    _scope,
)
from dw_agent_runtime.adapters.runtime_tables import run_checkpoint_writes, run_checkpoints

from .compiler import LeaseLostError

_BIND = (
    "SELECT set_config('app.tenant_id', :tenant_id, true),"
    " set_config('app.workspace_id', :workspace_id, true)"
)
_BIND_FUSED = _BIND + ", srt.lease_held(CAST(:run AS uuid), :token) AS held"
_FENCE = "SELECT 1 FROM srt.runs WHERE id = CAST(:run AS uuid) AND lease_owner = :token FOR SHARE"

_CHECKPOINT_KEY = ["thread_id", "checkpoint_ns", "checkpoint_id"]
_WRITE_KEY = [*_CHECKPOINT_KEY, "task_id", "idx"]

# Counted per process, read by the harness from the worker's log.
STATS: dict[str, int] = {"fence_rejected": 0, "aput": 0, "aput_writes": 0}


def _lease(config: RunnableConfig) -> tuple[str | None, str | None]:
    conf = config.get("configurable", {})
    return conf.get("srt_run"), conf.get("srt_token")


@asynccontextmanager
async def fenced_session(
    sessions: async_sessionmaker[AsyncSession],
    config: RunnableConfig,
    variant: str,
) -> AsyncIterator[AsyncSession]:
    _, tenant_id, workspace_id, _ = _scope(config)
    run, token = _lease(config)
    async with sessions() as session, session.begin():
        values = {"tenant_id": str(tenant_id), "workspace_id": str(workspace_id)}
        if variant == "fused" and run:
            row = (
                await session.execute(sa.text(_BIND_FUSED), {**values, "run": run, "token": token})
            ).one()
            if not row.held:
                STATS["fence_rejected"] += 1
                raise LeaseLostError(f"checkpoint write of {run} after the lease moved")
        else:
            (await session.execute(sa.text(_BIND), values)).first()
            if variant == "select" and run:
                held = (
                    await session.execute(sa.text(_FENCE), {"run": run, "token": token})
                ).first()
                if held is None:
                    STATS["fence_rejected"] += 1
                    raise LeaseLostError(f"checkpoint write of {run} after the lease moved")
        yield session


def _next_config(config: RunnableConfig, checkpoint_id: str) -> RunnableConfig:
    # Every configurable key goes back, the lease's included, so the fence
    # stays armed on the next write of the run.
    conf = dict(config.get("configurable", {}))
    conf["checkpoint_id"] = checkpoint_id
    return cast(RunnableConfig, {"configurable": conf})


class FencedSaver(SqlAlchemyCheckpointSaver):
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        serde: SerializerProtocol,
        variant: str = "fused",
    ) -> None:
        super().__init__(sessions, serde)
        self.variant = variant

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id, tenant_id, workspace_id, ns = _scope(config)
        parent_id = config.get("configurable", {}).get("checkpoint_id")
        type_cp, blob_cp = self.serde.dumps_typed(checkpoint)
        _, blob_md = self.serde.dumps_typed(dict(metadata))
        STATS["aput"] += 1
        async with fenced_session(self._session_factory, config, self.variant) as session:
            statement = sa.dialects.postgresql.insert(run_checkpoints).values(
                thread_id=thread_id,
                checkpoint_ns=ns,
                checkpoint_id=checkpoint["id"],
                parent_checkpoint_id=str(parent_id) if parent_id else None,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                type=type_cp,
                checkpoint=blob_cp,
                metadata=blob_md,
                created_at=sa.func.now(),
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=_CHECKPOINT_KEY,
                    set_={
                        "parent_checkpoint_id": statement.excluded.parent_checkpoint_id,
                        "type": statement.excluded.type,
                        "checkpoint": statement.excluded.checkpoint,
                        "metadata": statement.excluded.metadata,
                    },
                )
            )
        return _next_config(config, checkpoint["id"])

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, tenant_id, workspace_id, ns = _scope(config)
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        STATS["aput_writes"] += 1
        async with fenced_session(self._session_factory, config, self.variant) as session:
            for position, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, position)
                type_w, blob_w = self.serde.dumps_typed(value)
                statement = sa.dialects.postgresql.insert(run_checkpoint_writes).values(
                    thread_id=thread_id,
                    checkpoint_ns=ns,
                    checkpoint_id=str(checkpoint_id),
                    task_id=task_id,
                    idx=idx,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    channel=channel,
                    type=type_w,
                    value=blob_w,
                    task_path=task_path,
                )
                if idx < 0:
                    statement = statement.on_conflict_do_update(
                        index_elements=_WRITE_KEY,
                        set_={
                            "channel": statement.excluded.channel,
                            "type": statement.excluded.type,
                            "value": statement.excluded.value,
                            "task_path": statement.excluded.task_path,
                        },
                    )
                else:
                    statement = statement.on_conflict_do_nothing()
                await session.execute(statement)


# ------------------------------------------------------------ blob saver --


class BlobSaver(BaseCheckpointSaver[str]):
    """Blob per channel version (the shape of langgraph-checkpoint-postgres),
    on the spike's `srt.cp*` tables under RLS, with the same fence."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        serde: SerializerProtocol,
        variant: str = "fused",
        prune_writes: bool = False,
    ) -> None:
        super().__init__(serde=serde)
        self.sessions = sessions
        self.variant = variant
        # The writes of a checkpoint are folded into the next one's blobs; a
        # resume reads only the newest, so the parent's writes can go (T6).
        self.prune_writes = prune_writes

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id, tenant_id, workspace_id, ns = _scope(config)
        wanted = get_checkpoint_id(config)
        async with fenced_session(self.sessions, config, "none") as session:
            query = (
                "SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata FROM srt.cp"
                " WHERE thread_id = :t AND checkpoint_ns = :ns"
                + (" AND checkpoint_id = :id" if wanted else "")
                + " ORDER BY checkpoint_id DESC LIMIT 1"
            )
            row = (
                await session.execute(sa.text(query), {"t": thread_id, "ns": ns, "id": wanted})
            ).first()
            if row is None:
                return None
            checkpoint = self.serde.loads_typed((row.type, row.checkpoint))
            versions = checkpoint.get("channel_versions", {})
            values: dict[str, Any] = {}
            if versions:
                blobs = (
                    await session.execute(
                        sa.text(
                            "SELECT b.channel, b.type, b.blob FROM srt.cp_blobs b"
                            " JOIN unnest(CAST(:channels AS text[]), CAST(:versions AS text[]))"
                            " AS v(channel, version) ON b.channel = v.channel"
                            " AND b.version = v.version"
                            " WHERE b.thread_id = :t AND b.checkpoint_ns = :ns"
                        ),
                        {
                            "t": thread_id,
                            "ns": ns,
                            "channels": list(versions),
                            "versions": [str(v) for v in versions.values()],
                        },
                    )
                ).all()
                for blob in blobs:
                    if blob.type != "empty":
                        values[blob.channel] = self.serde.loads_typed((blob.type, blob.blob))
            checkpoint = {**checkpoint, "channel_values": values}
            writes = (
                await session.execute(
                    sa.text(
                        "SELECT task_id, channel, type, blob FROM srt.cp_writes"
                        " WHERE thread_id = :t AND checkpoint_ns = :ns AND checkpoint_id = :id"
                        " ORDER BY task_id, idx"
                    ),
                    {"t": thread_id, "ns": ns, "id": row.checkpoint_id},
                )
            ).all()
            metadata = self.serde.loads_typed((row.type, row.metadata))
        base = {
            "thread_id": str(thread_id),
            "checkpoint_ns": ns,
            "tenant_id": str(tenant_id),
            "workspace_id": str(workspace_id),
        }
        return CheckpointTuple(
            config=cast(
                RunnableConfig, {"configurable": {**base, "checkpoint_id": row.checkpoint_id}}
            ),
            checkpoint=cast(Checkpoint, checkpoint),
            metadata=metadata,
            parent_config=(
                cast(
                    RunnableConfig,
                    {"configurable": {**base, "checkpoint_id": row.parent_checkpoint_id}},
                )
                if row.parent_checkpoint_id
                else None
            ),
            pending_writes=[
                (w.task_id, w.channel, self.serde.loads_typed((w.type, w.blob))) for w in writes
            ],
        )

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        if config is None:
            return
        found = await self.aget_tuple(config)
        if found is not None:
            yield found

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread_id, tenant_id, workspace_id, ns = _scope(config)
        parent_id = config.get("configurable", {}).get("checkpoint_id")
        values = checkpoint.get("channel_values", {})
        bare = {**checkpoint, "channel_values": {}}
        type_cp, blob_cp = self.serde.dumps_typed(bare)
        _, blob_md = self.serde.dumps_typed(dict(metadata))
        blobs = []
        for channel, version in new_versions.items():
            if channel in values:
                kind, blob = self.serde.dumps_typed(values[channel])
            else:
                kind, blob = "empty", b""
            blobs.append(
                {
                    "t": thread_id,
                    "ns": ns,
                    "channel": channel,
                    "version": str(version),
                    "tenant": tenant_id,
                    "type": kind,
                    "blob": blob,
                }
            )
        STATS["aput"] += 1
        async with fenced_session(self.sessions, config, self.variant) as session:
            if blobs:
                await session.execute(
                    sa.text(
                        "INSERT INTO srt.cp_blobs (thread_id, checkpoint_ns, channel, version,"
                        " tenant_id, type, blob) VALUES (:t, :ns, :channel, :version, :tenant,"
                        " :type, :blob) ON CONFLICT DO NOTHING"
                    ),
                    blobs,
                )
            await session.execute(
                sa.text(
                    "INSERT INTO srt.cp (thread_id, checkpoint_ns, checkpoint_id,"
                    " parent_checkpoint_id, tenant_id, workspace_id, type, checkpoint, metadata)"
                    " VALUES (:t, :ns, :id, :parent, :tenant, :ws, :type, :cp, :md)"
                    " ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO UPDATE"
                    " SET checkpoint = EXCLUDED.checkpoint, metadata = EXCLUDED.metadata"
                ),
                {
                    "t": thread_id,
                    "ns": ns,
                    "id": checkpoint["id"],
                    "parent": str(parent_id) if parent_id else None,
                    "tenant": tenant_id,
                    "ws": workspace_id,
                    "type": type_cp,
                    "cp": blob_cp,
                    "md": blob_md,
                },
            )
            if self.prune_writes and parent_id:
                await session.execute(
                    sa.text(
                        "DELETE FROM srt.cp_writes WHERE thread_id = :t AND checkpoint_ns = :ns"
                        " AND checkpoint_id = :p"
                    ),
                    {"t": thread_id, "ns": ns, "p": str(parent_id)},
                )
        return _next_config(config, checkpoint["id"])

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, tenant_id, _, ns = _scope(config)
        checkpoint_id = str(config.get("configurable", {}).get("checkpoint_id"))
        rows = []
        for position, (channel, value) in enumerate(writes):
            kind, blob = self.serde.dumps_typed(value)
            rows.append(
                {
                    "t": thread_id,
                    "ns": ns,
                    "id": checkpoint_id,
                    "task": task_id,
                    "idx": WRITES_IDX_MAP.get(channel, position),
                    "tenant": tenant_id,
                    "channel": channel,
                    "type": kind,
                    "blob": blob,
                    "path": task_path,
                }
            )
        if not rows:
            return
        STATS["aput_writes"] += 1
        async with fenced_session(self.sessions, config, self.variant) as session:
            await session.execute(
                sa.text(
                    "INSERT INTO srt.cp_writes (thread_id, checkpoint_ns, checkpoint_id, task_id,"
                    " idx, tenant_id, channel, type, blob, task_path) VALUES (:t, :ns, :id, :task,"
                    " :idx, :tenant, :channel, :type, :blob, :path)"
                    " ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)"
                    " DO UPDATE SET channel = EXCLUDED.channel, type = EXCLUDED.type,"
                    " blob = EXCLUDED.blob"
                ),
                rows,
            )

    def get_next_version(self, current: str | None, channel: None) -> str:
        number = int(str(current).split(".")[0]) + 1 if current is not None else 1
        return f"{number:032}.{uuid.uuid4().hex[:8]}"
