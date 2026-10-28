"""SQL implementation of :class:`IdempotencyStorePort`.

Each call opens its own tenant-bound transaction and commits it, because the
guarantee only works if the reservation is visible to other requests *before*
the handler runs — see the port's docstring.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence import tables
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.access_context import AccessContext
from dw_platform.application.idempotency import (
    REPLAYED_HEADERS,
    RequestFingerprint,
    ReservedKey,
    StoredResponse,
)

_KEYS = tables.idempotency_keys


@dataclass(frozen=True)
class SqlIdempotencyStore:
    """Implements ``IdempotencyStorePort`` over ``platform.idempotency_keys``."""

    session_factory: async_sessionmaker[AsyncSession]

    async def reserve(
        self, context: AccessContext, *, key: str, fingerprint: RequestFingerprint
    ) -> uuid.UUID | ReservedKey:
        """Insert the reservation, or read back whoever got there first.

        ``ON CONFLICT DO NOTHING ... RETURNING`` is the primary key doing the
        mutual exclusion: one of two concurrent inserts returns a row and the
        other returns nothing, decided by the index rather than by a lock this
        code would have to remember to release. Catching the integrity error
        would be the same mechanism with an aborted transaction to clean up
        afterwards.

        The follow-up SELECT is safe under RLS precisely because ``tenant_id``
        leads the primary key: a conflict can only be with a row of this tenant,
        which this transaction can see. A key scoped any other way could collide
        with a row the policy hides, and then neither branch would be true.
        """
        async with tenant_session(
            self.session_factory, TenantScope.from_access_context(context)
        ) as session:
            token: uuid.UUID | None = (
                await session.execute(
                    pg_insert(_KEYS)
                    .values(
                        tenant_id=context.tenant_id,
                        idempotency_key=key,
                        workspace_id=fingerprint.workspace_id,
                        request_method=fingerprint.method,
                        request_path=fingerprint.path,
                        body_hash=fingerprint.body_hash,
                        caller_ref=fingerprint.caller_ref,
                        request_preconditions=fingerprint.preconditions,
                    )
                    .on_conflict_do_nothing(constraint="pk_idempotency_keys")
                    .returning(_KEYS.c.reservation_token)
                )
            ).scalar_one_or_none()
            if token is not None:
                return token

            row = (
                await session.execute(
                    sa.select(
                        _KEYS.c.workspace_id,
                        _KEYS.c.request_method,
                        _KEYS.c.request_path,
                        _KEYS.c.body_hash,
                        _KEYS.c.caller_ref,
                        _KEYS.c.request_preconditions,
                        _KEYS.c.response_status,
                        _KEYS.c.response_body,
                        _KEYS.c.response_headers,
                    ).where(
                        _KEYS.c.tenant_id == context.tenant_id,
                        _KEYS.c.idempotency_key == key,
                    )
                )
            ).one()

        stored = (
            StoredResponse(
                status_code=row.response_status,
                body=row.response_body,
                headers=dict(row.response_headers or {}),
            )
            if row.response_status is not None
            else None
        )
        return ReservedKey(
            fingerprint=RequestFingerprint(
                method=row.request_method,
                path=row.request_path,
                workspace_id=row.workspace_id,
                body_hash=row.body_hash,
                caller_ref=row.caller_ref,
                preconditions=row.request_preconditions,
            ),
            response=stored,
        )

    async def take_over(
        self,
        context: AccessContext,
        *,
        key: str,
        fingerprint: RequestFingerprint,
        older_than: datetime,
    ) -> uuid.UUID | None:
        """Re-stamp an abandoned reservation of the same caller onto this request.

        One UPDATE decides the race: several requests may find the same stale
        row, and only the one whose ``created_at`` predicate still holds when it
        takes the row lock updates anything. ``completed_at IS NULL`` is what
        keeps a stored response safe from being reopened, and ``caller_ref`` is
        what keeps another person's reservation theirs (R2.10). The new token
        fences the request that lost it out of ``complete`` and ``release``.
        """
        async with tenant_session(
            self.session_factory, TenantScope.from_access_context(context)
        ) as session:
            token: uuid.UUID | None = (
                await session.execute(
                    sa.update(_KEYS)
                    .where(
                        _KEYS.c.tenant_id == context.tenant_id,
                        _KEYS.c.idempotency_key == key,
                        _KEYS.c.caller_ref == fingerprint.caller_ref,
                        _KEYS.c.completed_at.is_(None),
                        _KEYS.c.created_at <= older_than,
                    )
                    .values(created_at=sa.func.now(), reservation_token=sa.func.gen_random_uuid())
                    .returning(_KEYS.c.reservation_token)
                )
            ).scalar_one_or_none()
        return token

    async def complete(
        self, context: AccessContext, *, key: str, token: uuid.UUID, response: StoredResponse
    ) -> None:
        async with tenant_session(
            self.session_factory, TenantScope.from_access_context(context)
        ) as session:
            await session.execute(
                sa.update(_KEYS)
                .where(
                    _KEYS.c.tenant_id == context.tenant_id,
                    _KEYS.c.idempotency_key == key,
                    # Only the holder of the reservation in force may write the
                    # response. A late completion from a request whose
                    # reservation was taken over must not overwrite the answer
                    # the client has already been given (R2.5).
                    _KEYS.c.reservation_token == token,
                    _KEYS.c.completed_at.is_(None),
                )
                .values(
                    response_status=response.status_code,
                    response_body=response.body,
                    response_headers={
                        name: value
                        for name, value in response.headers.items()
                        if name in REPLAYED_HEADERS
                    },
                    completed_at=sa.func.now(),
                )
            )

    async def release(self, context: AccessContext, *, key: str, token: uuid.UUID) -> None:
        async with tenant_session(
            self.session_factory, TenantScope.from_access_context(context)
        ) as session:
            await session.execute(
                sa.delete(_KEYS).where(
                    _KEYS.c.tenant_id == context.tenant_id,
                    _KEYS.c.idempotency_key == key,
                    # Same guard as ``complete``: releasing a key whose response
                    # is stored would throw away a successful reply, and
                    # releasing one taken over would free another request's.
                    _KEYS.c.reservation_token == token,
                    _KEYS.c.completed_at.is_(None),
                )
            )
