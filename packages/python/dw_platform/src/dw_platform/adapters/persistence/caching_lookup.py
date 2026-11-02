"""Cache the membership lookup that builds every request's AccessContext.

``find_access`` runs several queries and fires on every authenticated request —
the largest per-request database cost. This wraps it: the resolved access (or a
"no membership" negative) is cached under
``ml:{tenant}:{version}:{workspace}:{issuer}:{subject}`` for a short TTL, so a
burst of requests from one signed-in user hits the database once per access
version.

Correctness rests on the version (tenant-rbac R4.1): `platform.tenant_access_versions`
is bumped by the database itself on every write to the tables that feed
authorization (roles, their privileges, assignments, memberships, company
members, the tenant, its plan), whoever writes — an API route, a lane, an
import or raw SQL. Each request reads the current version first (one key read),
so the first request after a commit misses and rebuilds. A tenant with no
version row (offboarded) is read straight from PostgreSQL and never cached
(R4.2). The TTL only bounds how long a superseded entry occupies memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from dw_platform.application.access_context import Grant
from dw_platform.application.cache import CachePort, membership_cache_key
from dw_platform.application.identity import MembershipAccess, VersionedMembershipLookupPort

# Short enough that a superseded entry does not linger, long enough to absorb a
# page's burst of requests.
DEFAULT_TTL_SECONDS = 30
_NEGATIVE = "\x00"  # sentinel: "looked up, no membership" — cached to spare the DB


def _serialize(access: MembershipAccess) -> str:
    return json.dumps(
        {
            "tenant_id": str(access.tenant_id),
            "workspace_id": str(access.workspace_id),
            "principal_id": str(access.principal_id),
            "roles": sorted(access.roles),
            "scopes": sorted(access.scopes),
            "groups": sorted(access.groups),
            "clearance": access.clearance,
            "plan_id": access.plan_id,
            "feature_flags": sorted(access.feature_flags),
            "record_visibility": access.record_visibility,
            "max_autonomy_level": access.max_autonomy_level,
            "visible_owners": (
                None
                if access.visible_owners is None
                else sorted(str(u) for u in access.visible_owners)
            ),
            "grants": [[g.key, g.depth, str(g.anchor_workspace_id)] for g in access.grants],
            "access_version": access.access_version,
        }
    )


def _deserialize(raw: str, version: int) -> MembershipAccess | None:
    """The cached access, or `None` for an entry this code cannot read whole or
    that was written at another access version.

    The cache outlives a deploy by up to its TTL, so entries written by the
    previous version are read for real after every release. Such an entry is
    missing whatever fields that version did not have — and there is no safe
    value to invent for an authorization fact. `record_visibility` defaulted to
    `open` here, which is the widest setting a tenant has: every restricted
    tenant read as unrestricted for the first thirty seconds after a deploy.

    So nothing is defaulted (R4.2). Every field is read with `[]`, a missing one
    raises `KeyError`, and the caller treats that as a miss and asks the
    database. An entry whose `access_version` is not the one its key names is a
    miss too, so a key and its body cannot disagree about which state they hold.

    Reading them all this way is also what keeps the rule from rotting: a field
    added to `_serialize` later becomes required here automatically, with no
    second list to remember to update.
    """
    data = json.loads(raw)
    try:
        if data["access_version"] != version:
            return None
        return MembershipAccess(
            tenant_id=UUID(data["tenant_id"]),
            workspace_id=UUID(data["workspace_id"]),
            principal_id=UUID(data["principal_id"]),
            roles=frozenset(data["roles"]),
            scopes=frozenset(data["scopes"]),
            groups=frozenset(data["groups"]),
            clearance=data["clearance"],
            plan_id=data["plan_id"],
            feature_flags=frozenset(data["feature_flags"]),
            record_visibility=data["record_visibility"],
            max_autonomy_level=data["max_autonomy_level"],
            visible_owners=(
                None
                if data["visible_owners"] is None
                else frozenset(UUID(u) for u in data["visible_owners"])
            ),
            grants=tuple(
                Grant(key=key, depth=depth, anchor_workspace_id=UUID(anchor))
                for key, depth, anchor in data["grants"]
            ),
            access_version=data["access_version"],
        )
    except KeyError:
        # Only the subscripts above raise this; `MembershipAccess` and `UUID` do
        # not. Narrow on purpose — a malformed value is still a real error.
        return None


@dataclass(frozen=True)
class CachingMembershipLookup:
    """Implements ``MembershipLookupPort`` in front of another one."""

    inner: VersionedMembershipLookupPort
    cache: CachePort
    ttl_seconds: int = DEFAULT_TTL_SECONDS

    async def find_access(
        self, subject: str, issuer: str, tenant_id: UUID, workspace_id: UUID
    ) -> MembershipAccess | None:
        version = await self.inner.access_version(tenant_id)
        if version is None:
            # No version to key by: read the source, write nothing (R4.2).
            return await self.inner.find_access(subject, issuer, tenant_id, workspace_id)
        key = membership_cache_key(tenant_id, version, workspace_id, issuer, subject)
        cached = await self.cache.get(key)
        if cached == _NEGATIVE:
            return None
        if cached is not None:
            hit = _deserialize(cached, version)
            if hit is not None:
                return hit
            # Written by an older deploy. Fall through and rewrite it rather than
            # read an authorization fact that is not there.

        access = await self.inner.find_access(subject, issuer, tenant_id, workspace_id)
        if access is None:
            # Read at a version no older than `version`: safe under its key.
            await self.cache.set(key, _NEGATIVE, ttl_seconds=self.ttl_seconds)
            return None
        if access.access_version is not None:
            # Under the version the data was read at, which may be newer than
            # the one this request started from; never under an older one.
            await self.cache.set(
                membership_cache_key(
                    tenant_id, access.access_version, workspace_id, issuer, subject
                ),
                _serialize(access),
                ttl_seconds=self.ttl_seconds,
            )
        return access
