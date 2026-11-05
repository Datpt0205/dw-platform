"""The transaction of an authenticated Studio request (record-access ticket 03,
step 5; ADR-0105 decisions 4 and 6).

The one module that binds the actor kind `user`: it opens a transaction bound
to the caller's tenant and principal (`bind_tenant`), binds `user` (`bind_actor`)
and calls the reach door `studio.ensure_principal_scope()`, all before the first
statement the caller runs, so the record policies decide with the caller's
current reach. Every transaction of a request opens here; RecordService
(custom-objects/03) takes it as its transaction factory. A session opened any
other way (a run's, a support context's, another package's adapter) carries no
actor kind and reads no Studio record until record-access/04 binds it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_platform.adapters.persistence.tenant_session import TenantScope, bind_actor, bind_tenant
from dw_platform.application.access_context import AccessContext

_REACH_DOOR = text("SELECT studio.ensure_principal_scope()")


@asynccontextmanager
async def user_session(
    session_factory: async_sessionmaker[AsyncSession], context: AccessContext
) -> AsyncIterator[AsyncSession]:
    """A session inside one transaction of ``context``'s request, bound to its
    tenant, principal and the actor kind `user`, the caller's reach row made
    valid. Commits on a clean exit, rolls back on an exception."""
    async with session_factory() as session, session.begin():
        await bind_tenant(session, TenantScope.from_access_context(context))
        await bind_actor(session, "user")
        (await session.execute(_REACH_DOOR)).first()
        yield session
