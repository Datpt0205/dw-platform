"""The one advisory lock key of an object (ADR-0107 decisions 3, 5).

The publish hook takes `pg_advisory_xact_lock` on it, exclusive, while it
changes the definition and gives slots; RecordService (ticket 03) takes
`pg_advisory_xact_lock_shared` on the same key while it writes a record
against a snapshot of that definition. Two keys would not exclude each other
(gate HIGH 12, 3/11/2026), so this function is the only place it is made.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Final

_DOMAIN: Final = b"studio.object_lock/v1:"


def object_lock_key(tenant_id: uuid.UUID, object_id: uuid.UUID) -> int:
    """A signed 64-bit key for `pg_advisory_xact_lock(bigint)`, the same in
    every process: the tenant is in it, since an object's id travels to
    another tenant with a pack (ADR-0109 decision 1)."""
    digest = hashlib.sha256(_DOMAIN + tenant_id.bytes + object_id.bytes).digest()
    return int.from_bytes(digest[:8], "big", signed=True)
