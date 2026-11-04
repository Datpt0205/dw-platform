"""The credential broker: tenant secrets in AES-256-GCM envelopes under the
tenant's key (connections-and-vault R1; ADR-0115 decision 1).

Each write draws a fresh data key from `KmsPort`, wrapped by the tenant key
`tenant-<tenant_id>`, and seals the value under an AAD that binds the caller's
tenant, the subject's owning workspace, the subject, the field and the secret
version, so an envelope copied to another row, field, version, subject,
workspace or tenant does not open (R1.4). `kek_version` is not in the AAD: a
rewrap changes only the wrapped data key.

The rows sit behind the database's one-way door (`platform.put_secret`,
`platform.open_secret`, `platform.secret_status`), reached through
`SecretEnvelopeDoorPort` on the caller's own transaction, so a secret is written
in the transaction that writes its subject. `dw_app` cannot read the table.

What this module never does: log, raise or audit a value. A `Secret` masks
itself; every error and audit row here carries identifiers only (R1.2).
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from dw_kernel.errors import (
    DomainError,
    DWError,
    ErrorCode,
    InfrastructureError,
    NotFoundError,
)
from dw_kernel.ids import TenantId, UserId, WorkspaceId
from dw_kernel.ports import IdGenerator, UtcClock
from dw_kernel.secret import Secret
from dw_platform.application.access_context import AccessContext
from dw_platform.application.decision_gate import ScopedAuditPort
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.audit import AuditEvent, lane_audit_event, system_actor

logger = logging.getLogger(__name__)

ALG = "aes-256-gcm"
AAD_PREFIX = "dw.secret.v1"
# The subject columns of `platform.secret_envelopes`, each `<kind>_id`; a later
# subject (workflow-triggers/02's `inbound_endpoint`) adds its kind here, its
# column in its migration and its owner lookup in the door adapter.
SUBJECT_KINDS = frozenset({"connection"})
# The table's CHECK: also keeps `|` out of the AAD.
_FIELD = re.compile(r"[a-z][a-z0-9_]{0,62}")
_NONCE_BYTES = 12
_TAG_BYTES = 16
# `ck_secret_envelopes_ciphertext`: the sealed value with its tag.
MAX_SECRET_BYTES = 65536 - _TAG_BYTES

KEY_MISMATCH = "secret.key_mismatch"


class KmsUnavailableError(InfrastructureError):
    """The key service did not answer; nothing falls back (R2.4)."""

    def __init__(self) -> None:
        super().__init__(
            "the key service is unavailable", details={"reason_code": "kms_unavailable"}
        )


class CredentialRevokedError(DWError):
    """No version of the field may be opened: revoked, replaced or missing (R1.10)."""

    code = ErrorCode.CONFLICT

    def __init__(self, subject: SecretSubject, secret_field: str) -> None:
        super().__init__(
            "the credential is revoked",
            details={
                "reason_code": "credential_revoked",
                "subject_kind": subject.kind,
                "subject_id": str(subject.id),
                "field": secret_field,
            },
        )


class SecretKeyMismatchError(DWError):
    """A row names another tenant's key: refused before any decryption (R1.5)."""

    code = ErrorCode.INTERNAL

    def __init__(self) -> None:
        super().__init__(
            "the secret is not under this company's key",
            details={"reason_code": "secret_key_mismatch"},
        )


class SecretUnreadableError(DWError):
    """The envelope does not open under its binding, or its key does not unwrap (R1.4)."""

    code = ErrorCode.INTERNAL

    def __init__(self) -> None:
        super().__init__(
            "the secret envelope does not open", details={"reason_code": "secret_unreadable"}
        )


@dataclass(frozen=True, slots=True)
class SecretSubject:
    """What a secret belongs to: a subject column's kind and the row's id."""

    kind: str
    id: uuid.UUID

    def __post_init__(self) -> None:
        if self.kind not in SUBJECT_KINDS:
            raise DomainError(
                "not a secret subject", details={"reason_code": "secret_subject_unknown"}
            )


@dataclass(frozen=True, slots=True)
class SecretCaller:
    """Whose key is used and who is audited: a person, or a lane as itself (ADR-0011)."""

    tenant_id: uuid.UUID
    actor_id: uuid.UUID
    lane: str | None = None

    @classmethod
    def person(cls, context: AccessContext) -> SecretCaller:
        return cls(tenant_id=context.tenant_id, actor_id=context.principal_id)

    @classmethod
    def of_lane(cls, lane: str, tenant_id: uuid.UUID) -> SecretCaller:
        return cls(tenant_id=tenant_id, actor_id=system_actor(lane).value, lane=lane)


@dataclass(frozen=True, slots=True)
class WrappedKey:
    """A data key as the tenant key wrapped it, and that key's version."""

    wrapped: bytes
    kek_version: int


@dataclass(frozen=True, slots=True)
class DataKey:
    plaintext: bytes = field(repr=False)
    wrapped: WrappedKey


class KmsPort(Protocol):
    """The tenant keys (ADR-0115 decision 1). `ensure_tenant_key` and
    `destroy_tenant_key` arrive with OpenBao and offboarding's shredding
    (ticket 06); `rewrap` is the 90-day rotation's step."""

    async def generate_data_key(self, kek_ref: str) -> DataKey: ...

    async def decrypt_data_key(self, kek_ref: str, key: WrappedKey) -> bytes: ...

    async def rewrap(self, kek_ref: str, key: WrappedKey) -> WrappedKey: ...


@dataclass(frozen=True, slots=True)
class Envelope:
    """One row of `platform.secret_envelopes`, as the door writes and returns it."""

    secret_version: int
    alg: str
    nonce: bytes
    kek_ref: str
    key: WrappedKey
    ciphertext: bytes


@dataclass(frozen=True, slots=True)
class SecretVersionStatus:
    secret_version: int
    revoked_at: datetime | None
    replaced_at: datetime | None


class SecretEnvelopeDoorPort(Protocol):
    """The database door on the caller's transaction, under its tenant scope."""

    async def owning_workspace(self, subject: SecretSubject) -> uuid.UUID | None:
        """The subject's owning workspace, None when this tenant has no such subject."""
        ...

    async def status(
        self, subject: SecretSubject, secret_field: str
    ) -> Sequence[SecretVersionStatus]: ...

    async def put(self, subject: SecretSubject, secret_field: str, envelope: Envelope) -> None:
        """Raises `ConflictError` when the version is already taken."""
        ...

    async def open(
        self, subject: SecretSubject, secret_field: str, secret_version: int | None
    ) -> Envelope | None:
        """The version named, or the latest; None when it is revoked or missing."""
        ...


@dataclass(frozen=True, slots=True)
class OpenedSecret:
    secret_version: int
    value: Secret


def kek_ref_for(tenant_id: uuid.UUID) -> str:
    """The tenant key's name, from the caller's tenant, never from a row."""
    return f"tenant-{tenant_id}"


def secret_aad(
    tenant_id: uuid.UUID,
    owning_workspace_id: uuid.UUID,
    subject: SecretSubject,
    secret_field: str,
    secret_version: int,
) -> bytes:
    return (
        f"{AAD_PREFIX}|{tenant_id}|{owning_workspace_id}|{subject.kind}:{subject.id}"
        f"|{secret_field}|{secret_version}"
    ).encode()


def _checked_field(secret_field: str) -> str:
    if not _FIELD.fullmatch(secret_field):
        raise DomainError(
            "not a secret field name", details={"reason_code": "secret_field_invalid"}
        )
    return secret_field


@dataclass(frozen=True)
class SecretStore:
    """The one place a tenant secret is sealed or opened."""

    kms: KmsPort
    audit: ScopedAuditPort
    clock: UtcClock
    id_generator: IdGenerator

    async def put(
        self,
        door: SecretEnvelopeDoorPort,
        caller: SecretCaller,
        subject: SecretSubject,
        secret_field: str,
        value: Secret,
    ) -> int:
        """Seal `value` as the field's next version; the earlier ones are
        replaced in the same transaction (R1.9). Returns the version written."""
        _checked_field(secret_field)
        plaintext = value.reveal().encode()
        if len(plaintext) > MAX_SECRET_BYTES:
            raise DomainError(
                "the secret is too large",
                details={"reason_code": "secret_too_large", "max_bytes": MAX_SECRET_BYTES},
            )
        workspace = await door.owning_workspace(subject)
        if workspace is None:
            raise NotFoundError("no such subject", details={"subject_kind": subject.kind})
        held = await door.status(subject, secret_field)
        # The number goes into the AAD before the row exists; a concurrent
        # write of the same number is refused by the UNIQUE (ConflictError),
        # never retried here.
        version = max((v.secret_version for v in held), default=0) + 1
        kek_ref = kek_ref_for(caller.tenant_id)
        data_key = await self.kms.generate_data_key(kek_ref)
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(data_key.plaintext).encrypt(
            nonce,
            plaintext,
            secret_aad(caller.tenant_id, workspace, subject, secret_field, version),
        )
        await door.put(
            subject,
            secret_field,
            Envelope(
                secret_version=version,
                alg=ALG,
                nonce=nonce,
                kek_ref=kek_ref,
                key=data_key.wrapped,
                ciphertext=ciphertext,
            ),
        )
        logger.info(
            "secret written",
            extra={
                "subject_kind": subject.kind,
                "subject_id": str(subject.id),
                "field": secret_field,
                "secret_version": version,
            },
        )
        return version

    async def open(
        self,
        door: SecretEnvelopeDoorPort,
        caller: SecretCaller,
        subject: SecretSubject,
        secret_field: str,
        *,
        secret_version: int | None = None,
    ) -> OpenedSecret:
        """The latest version not revoked, or the one named (a signing secret's
        overlap); `CredentialRevokedError` when there is none (R1.10, R1.14)."""
        _checked_field(secret_field)
        workspace = await door.owning_workspace(subject)
        envelope = (
            None if workspace is None else await door.open(subject, secret_field, secret_version)
        )
        if workspace is None or envelope is None:
            raise CredentialRevokedError(subject, secret_field)
        if envelope.kek_ref != kek_ref_for(caller.tenant_id):
            await self._audit_key_mismatch(caller, workspace, subject, secret_field, envelope)
            raise SecretKeyMismatchError()
        if envelope.alg != ALG:
            raise SecretUnreadableError()
        data_key = await self.kms.decrypt_data_key(envelope.kek_ref, envelope.key)
        aad = secret_aad(
            caller.tenant_id, workspace, subject, secret_field, envelope.secret_version
        )
        try:
            plaintext = AESGCM(data_key).decrypt(envelope.nonce, envelope.ciphertext, aad)
        except InvalidTag:
            raise SecretUnreadableError() from None
        logger.debug(
            "secret opened",
            extra={
                "subject_kind": subject.kind,
                "subject_id": str(subject.id),
                "field": secret_field,
                "secret_version": envelope.secret_version,
            },
        )
        return OpenedSecret(
            secret_version=envelope.secret_version, value=Secret(plaintext.decode())
        )

    async def _audit_key_mismatch(
        self,
        caller: SecretCaller,
        workspace: uuid.UUID,
        subject: SecretSubject,
        secret_field: str,
        envelope: Envelope,
    ) -> None:
        """In its own transaction, so the row stays when the caller's rolls
        back; never the row's `kek_ref`, which names another tenant (R1.5)."""
        details: dict[str, object] = {
            "subject_kind": subject.kind,
            "subject_id": str(subject.id),
            "field": secret_field,
            "secret_version": envelope.secret_version,
        }
        event_id = self.id_generator.new_uuid()
        tenant, owner, now = TenantId(caller.tenant_id), WorkspaceId(workspace), self.clock.now()
        resource_id = str(subject.id)
        event = (
            lane_audit_event(
                lane=caller.lane,
                event_id=event_id,
                tenant_id=tenant,
                workspace_id=owner,
                action=KEY_MISMATCH,
                resource_type=subject.kind,
                resource_id=resource_id,
                occurred_at=now,
                details=details,
            )
            if caller.lane is not None
            else AuditEvent(
                id=event_id,
                tenant_id=tenant,
                workspace_id=owner,
                actor_id=UserId(caller.actor_id),
                action=KEY_MISMATCH,
                resource_type=subject.kind,
                resource_id=resource_id,
                occurred_at=now,
                details=details,
            )
        )
        await self.audit.append(
            WorkScope(tenant_id=caller.tenant_id, workspace_id=workspace), event
        )
