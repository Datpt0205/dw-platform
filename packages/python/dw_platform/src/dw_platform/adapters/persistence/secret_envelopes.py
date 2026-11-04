"""`SecretEnvelopeDoorPort` over the database's door functions (migration
70d8a4564454): `dw_app` holds no privilege on `platform.secret_envelopes`, so
every read and write is a call to `platform.put_secret`, `platform.open_secret`
or `platform.secret_status`, each narrowing by the transaction's
`app.tenant_id`. Runs on the caller's session, inside its transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dw_kernel.errors import ConflictError
from dw_platform.adapters.persistence.separation_of_duties import refusal
from dw_platform.application.secrets import (
    SUBJECT_KINDS,
    Envelope,
    SecretSubject,
    SecretVersionStatus,
    WrappedKey,
)

# Where each subject kind keeps its owning workspace, read under the caller's
# RLS; one entry per kind of `SUBJECT_KINDS` (checked at import).
_OWNING_WORKSPACE: Mapping[str, sa.TextClause] = MappingProxyType(
    {
        "connection": sa.text(
            "SELECT owning_workspace_id FROM platform.connections WHERE id = :id"
        ),
    }
)
if frozenset(_OWNING_WORKSPACE) != SUBJECT_KINDS:
    raise RuntimeError("every secret subject kind needs its owning-workspace lookup")

_PUT = sa.text(
    "SELECT platform.put_secret(:kind, :id, :field, :version, :alg, :nonce, :kek_ref,"
    " :kek_version, :wrapped_data_key, :ciphertext)"
)
_OPEN = sa.text(
    "SELECT secret_version, alg, nonce, kek_ref, kek_version, wrapped_data_key, ciphertext"
    " FROM platform.open_secret(:kind, :id, :field, :version)"
)
_STATUS = sa.text(
    "SELECT secret_version, revoked_at, replaced_at FROM platform.secret_status(:kind, :id, :field)"
)
_VERSION_TAKEN = "uq_secret_envelopes_tenant_id_connection_id_field_version"


@dataclass(frozen=True)
class SqlSecretEnvelopes:
    """Implements `SecretEnvelopeDoorPort` on a unit of work's open transaction."""

    session: AsyncSession

    async def owning_workspace(self, subject: SecretSubject) -> uuid.UUID | None:
        found = await self.session.scalar(_OWNING_WORKSPACE[subject.kind], {"id": subject.id})
        return found if isinstance(found, uuid.UUID) else None

    async def status(
        self, subject: SecretSubject, secret_field: str
    ) -> Sequence[SecretVersionStatus]:
        rows = await self.session.execute(
            _STATUS, {"kind": subject.kind, "id": subject.id, "field": secret_field}
        )
        return [
            SecretVersionStatus(
                secret_version=row.secret_version,
                revoked_at=row.revoked_at,
                replaced_at=row.replaced_at,
            )
            for row in rows
        ]

    async def put(self, subject: SecretSubject, secret_field: str, envelope: Envelope) -> None:
        try:
            await self.session.execute(
                _PUT,
                {
                    "kind": subject.kind,
                    "id": subject.id,
                    "field": secret_field,
                    "version": envelope.secret_version,
                    "alg": envelope.alg,
                    "nonce": envelope.nonce,
                    "kek_ref": envelope.kek_ref,
                    "kek_version": envelope.key.kek_version,
                    "wrapped_data_key": envelope.key.wrapped,
                    "ciphertext": envelope.ciphertext,
                },
            )
        except IntegrityError as exc:
            refused = refusal(exc)
            if refused is not None and refused[0] == _VERSION_TAKEN:
                # Another write took this version first; its AAD carries the
                # number, so it is not retried here.
                raise ConflictError(
                    "the secret was written concurrently",
                    details={"reason_code": "secret_version_taken"},
                ) from None
            raise

    async def open(
        self, subject: SecretSubject, secret_field: str, secret_version: int | None
    ) -> Envelope | None:
        row = (
            await self.session.execute(
                _OPEN,
                {
                    "kind": subject.kind,
                    "id": subject.id,
                    "field": secret_field,
                    "version": secret_version,
                },
            )
        ).first()
        if row is None:
            return None
        return Envelope(
            secret_version=row.secret_version,
            alg=row.alg,
            nonce=bytes(row.nonce),
            kek_ref=row.kek_ref,
            key=WrappedKey(bytes(row.wrapped_data_key), row.kek_version),
            ciphertext=bytes(row.ciphertext),
        )
