"""`SecretStore` over an in-memory door (connections-and-vault R1.2, R1.4, R1.5, R2.2).

The door here keeps the contract `SqlSecretEnvelopes` keeps over the database
(`test_secret_vault.py` runs the same questions against Postgres): the latest
version not revoked or the one named, None when it is revoked or missing, and a
`ConflictError` for a version already taken. What this file adds is what only
the broker decides: the AAD, the `kek_ref` comparison before any key is asked
for, the audit of a mismatch, and that no value reaches a log, an error or an
audit row.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest

from dw_kernel.errors import ConflictError, DWError
from dw_kernel.ports import FixedClock, Uuid4Generator
from dw_kernel.secret import Secret
from dw_platform.adapters.kms import LocalDevKms, UnavailableKms
from dw_platform.application.secrets import (
    CredentialRevokedError,
    DataKey,
    Envelope,
    KmsUnavailableError,
    SecretCaller,
    SecretKeyMismatchError,
    SecretStore,
    SecretSubject,
    SecretUnreadableError,
    SecretVersionStatus,
    WrappedKey,
    kek_ref_for,
    secret_aad,
)
from dw_platform.application.work_queue import WorkScope
from dw_platform.domain.audit import AuditEvent, system_actor

pytestmark = pytest.mark.unit

CANARY = "canary-5d1e-không-được-lộ-ra-ngoài"
MASTER = bytes(range(32))
NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
TENANT_A, TENANT_B = uuid.UUID(int=0xA00), uuid.UUID(int=0xB00)
WORKSPACE_A, WORKSPACE_B = uuid.UUID(int=0xA01), uuid.UUID(int=0xB01)
PERSON = uuid.UUID(int=0xA0F)


@dataclass
class _Row:
    envelope: Envelope
    revoked: bool = False


@dataclass
class FakeDoor:
    """One tenant's view of the envelopes, as `platform.open_secret` gives it."""

    owners: dict[uuid.UUID, uuid.UUID]
    rows: dict[tuple[uuid.UUID, str], list[_Row]] = field(default_factory=dict)

    async def owning_workspace(self, subject: SecretSubject) -> uuid.UUID | None:
        return self.owners.get(subject.id)

    async def status(
        self, subject: SecretSubject, secret_field: str
    ) -> Sequence[SecretVersionStatus]:
        return [
            SecretVersionStatus(row.envelope.secret_version, NOW if row.revoked else None, None)
            for row in self.rows.get((subject.id, secret_field), [])
        ]

    async def put(self, subject: SecretSubject, secret_field: str, envelope: Envelope) -> None:
        held = self.rows.setdefault((subject.id, secret_field), [])
        if any(row.envelope.secret_version == envelope.secret_version for row in held):
            raise ConflictError("taken", details={"reason_code": "secret_version_taken"})
        for row in held:
            row.revoked = True
        held.append(_Row(envelope))

    async def open(
        self, subject: SecretSubject, secret_field: str, secret_version: int | None
    ) -> Envelope | None:
        held = [
            row
            for row in self.rows.get((subject.id, secret_field), [])
            if secret_version is None or row.envelope.secret_version == secret_version
        ]
        if not held:
            return None
        latest = max(held, key=lambda row: row.envelope.secret_version)
        return None if latest.revoked else latest.envelope


@dataclass
class FakeAudit:
    written: list[tuple[WorkScope, AuditEvent]] = field(default_factory=list)

    async def append(self, scope: WorkScope, event: AuditEvent) -> None:
        self.written.append((scope, event))


@dataclass
class SpyKms:
    """Counts the calls a `LocalDevKms` answers."""

    inner: LocalDevKms
    calls: list[str] = field(default_factory=list)

    async def generate_data_key(self, kek_ref: str) -> DataKey:
        self.calls.append("generate")
        return await self.inner.generate_data_key(kek_ref)

    async def decrypt_data_key(self, kek_ref: str, key: WrappedKey) -> bytes:
        self.calls.append("decrypt")
        return await self.inner.decrypt_data_key(kek_ref, key)

    async def rewrap(self, kek_ref: str, key: WrappedKey) -> WrappedKey:
        self.calls.append("rewrap")
        return await self.inner.rewrap(kek_ref, key)


def _store(kms: object | None = None, audit: FakeAudit | None = None) -> SecretStore:
    return SecretStore(
        kms=kms or LocalDevKms(MASTER),  # type: ignore[arg-type]
        audit=audit or FakeAudit(),
        clock=FixedClock(NOW),
        id_generator=Uuid4Generator(),
    )


def _connection() -> SecretSubject:
    return SecretSubject("connection", uuid.uuid4())


PERSON_A = SecretCaller(tenant_id=TENANT_A, actor_id=PERSON)


async def test_a_value_written_opens_and_its_envelope_holds_no_plain_value() -> None:
    """R1.1, at the broker: one row per version, the earlier one untouched."""
    store, subject = _store(), _connection()
    door = FakeDoor({subject.id: WORKSPACE_A})
    assert await store.put(door, PERSON_A, subject, "api_key", Secret(CANARY)) == 1
    first = door.rows[(subject.id, "api_key")][0].envelope
    assert CANARY.encode() not in first.ciphertext
    assert first.kek_ref == kek_ref_for(TENANT_A)
    opened = await store.open(door, PERSON_A, subject, "api_key")
    assert (opened.secret_version, opened.value.reveal()) == (1, CANARY)

    assert await store.put(door, PERSON_A, subject, "api_key", Secret("second")) == 2
    assert door.rows[(subject.id, "api_key")][0].envelope == first
    opened = await store.open(door, PERSON_A, subject, "api_key")
    assert (opened.secret_version, opened.value.reveal()) == (2, "second")


async def test_no_value_reaches_a_log_an_error_or_an_audit_row(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R1.2 (CV4), the vault's layer: the canary is written, opened, refused
    three ways and audited once; it is in none of what those leave behind."""
    audit = FakeAudit()
    store, subject = _store(audit=audit), _connection()
    door = FakeDoor({subject.id: WORKSPACE_A})
    left: list[str] = []
    with caplog.at_level(logging.DEBUG):
        await store.put(door, PERSON_A, subject, "password", Secret(CANARY))
        opened = await store.open(door, PERSON_A, subject, "password")
        left += [repr(opened), str(opened), repr(opened.value), f"{opened.value}"]

        with pytest.raises(CredentialRevokedError) as revoked:
            await store.open(door, PERSON_A, subject, "password", secret_version=9)
        with pytest.raises(KmsUnavailableError) as unavailable:
            await _store(kms=UnavailableKms()).open(door, PERSON_A, subject, "password")
        [row] = door.rows[(subject.id, "password")]
        row.envelope = replace(row.envelope, kek_ref=kek_ref_for(TENANT_B))
        with pytest.raises(SecretKeyMismatchError) as mismatch:
            await store.open(door, PERSON_A, subject, "password")

    errors: list[DWError] = [revoked.value, unavailable.value, mismatch.value]
    assert [e.details["reason_code"] for e in errors] == [
        "credential_revoked",
        "kms_unavailable",
        "secret_key_mismatch",
    ]
    left += [str(e) for e in errors] + [json.dumps(e.details) for e in errors]
    [(_, event)] = audit.written
    left.append(json.dumps(event.details, default=str))
    left.append(caplog.text)
    left += [json.dumps(r.__dict__, default=str) for r in caplog.records]
    assert caplog.records, "the write and the open log their identifiers"
    for text in left:
        assert CANARY not in text


@pytest.mark.parametrize(
    "moved",
    ["another connection", "another field", "another version", "another workspace"],
)
async def test_an_envelope_opens_only_under_its_own_binding(moved: str) -> None:
    """R1.4 (CV1): the AAD binds tenant, owning workspace, subject, field and
    version, so a copy anywhere else does not open (the copy into another
    tenant is refused by `kek_ref` first, `test_secret_vault.py`)."""
    store, subject, other = _store(), _connection(), _connection()
    door = FakeDoor({subject.id: WORKSPACE_A, other.id: WORKSPACE_A})
    await store.put(door, PERSON_A, subject, "api_key", Secret(CANARY))
    envelope = door.rows[(subject.id, "api_key")][0].envelope

    if moved == "another connection":
        door.rows[(other.id, "api_key")] = [_Row(envelope)]
        target, target_field = other, "api_key"
    elif moved == "another field":
        door.rows[(subject.id, "password")] = [_Row(envelope)]
        target, target_field = subject, "password"
    elif moved == "another version":
        door.rows[(subject.id, "api_key")] = [_Row(replace(envelope, secret_version=2))]
        target, target_field = subject, "api_key"
    else:
        door.owners[subject.id] = WORKSPACE_B
        target, target_field = subject, "api_key"

    with pytest.raises(SecretUnreadableError) as refused:
        await store.open(door, PERSON_A, target, target_field)
    assert CANARY not in str(refused.value)


async def test_a_rewrapped_data_key_still_opens_the_envelope() -> None:
    """R1.4: a rewrap changes `wrapped_data_key` and `kek_version` only, and
    `kek_version` is not in the AAD."""
    store, subject = _store(), _connection()
    door = FakeDoor({subject.id: WORKSPACE_A})
    await store.put(door, PERSON_A, subject, "api_key", Secret(CANARY))
    [row] = door.rows[(subject.id, "api_key")]
    rotated = LocalDevKms(MASTER, current_version=2)
    moved = await rotated.rewrap(row.envelope.kek_ref, row.envelope.key)
    assert moved.kek_version == 2
    row.envelope = replace(row.envelope, key=moved)

    opened = await _store(kms=rotated).open(door, PERSON_A, subject, "api_key")
    assert opened.value.reveal() == CANARY


def test_the_aad_carries_no_key_version() -> None:
    subject = SecretSubject("connection", uuid.UUID(int=7))
    aad = secret_aad(TENANT_A, WORKSPACE_A, subject, "api_key", 3).decode()
    assert aad == f"dw.secret.v1|{TENANT_A}|{WORKSPACE_A}|connection:{subject.id}|api_key|3"


async def test_another_tenants_key_is_refused_before_any_key_is_asked_for() -> None:
    """R1.5 (CV3): no decryption is attempted, and the audit row names the
    person, the tenant of the context and the subject's workspace, never the
    row's `kek_ref`."""
    audit = FakeAudit()
    kms = SpyKms(LocalDevKms(MASTER))
    store, subject = _store(kms=kms, audit=audit), _connection()
    door = FakeDoor({subject.id: WORKSPACE_A})
    await store.put(door, PERSON_A, subject, "api_key", Secret(CANARY))
    [row] = door.rows[(subject.id, "api_key")]
    row.envelope = replace(row.envelope, kek_ref=kek_ref_for(TENANT_B))
    kms.calls.clear()

    with pytest.raises(SecretKeyMismatchError):
        await store.open(door, PERSON_A, subject, "api_key")

    assert kms.calls == []
    [(scope, event)] = audit.written
    assert scope == WorkScope(tenant_id=TENANT_A, workspace_id=WORKSPACE_A)
    assert event.action == "secret.key_mismatch"
    assert (event.tenant_id.value, event.workspace_id.value) == (TENANT_A, WORKSPACE_A)
    assert event.actor_id.value == PERSON
    assert event.details == {
        "subject_kind": "connection",
        "subject_id": str(subject.id),
        "field": "api_key",
        "secret_version": 1,
    }
    assert str(TENANT_B) not in json.dumps(event.details)


async def test_a_lane_that_meets_a_mismatch_audits_as_itself() -> None:
    """ADR-0011: a lane's call is audited as `system_actor(<lane>)`."""
    audit = FakeAudit()
    store, subject = _store(audit=audit), _connection()
    door = FakeDoor({subject.id: WORKSPACE_A})
    lane = SecretCaller.of_lane("credential_rewrap", TENANT_A)
    await store.put(door, lane, subject, "api_key", Secret(CANARY))
    [row] = door.rows[(subject.id, "api_key")]
    row.envelope = replace(row.envelope, kek_ref=kek_ref_for(TENANT_B))

    with pytest.raises(SecretKeyMismatchError):
        await store.open(door, lane, subject, "api_key")

    [(_, event)] = audit.written
    assert event.actor_id == system_actor("credential_rewrap")
    assert event.details["actor"] == "system:credential_rewrap"


async def test_without_a_key_service_nothing_is_sealed_or_opened() -> None:
    """R2.2 (CV5): `none` refuses the write before any row reaches the door."""
    store, subject = _store(kms=UnavailableKms()), _connection()
    door = FakeDoor({subject.id: WORKSPACE_A})
    with pytest.raises(KmsUnavailableError):
        await store.put(door, PERSON_A, subject, "api_key", Secret(CANARY))
    assert door.rows == {}


async def test_a_subject_this_tenant_does_not_hold_reads_as_revoked() -> None:
    """R1.5, R1.10: another tenant's subject is invisible under this tenant's
    RLS, so it answers as a missing credential, never as a different error."""
    store = _store()
    door = FakeDoor({})
    with pytest.raises(CredentialRevokedError):
        await store.open(door, PERSON_A, _connection(), "api_key")


async def test_a_version_taken_concurrently_is_a_conflict_and_not_retried() -> None:
    """Ticket MEDIUM (h): the number is in the AAD before the row exists."""

    @dataclass
    class RacingDoor(FakeDoor):
        async def status(
            self, subject: SecretSubject, secret_field: str
        ) -> Sequence[SecretVersionStatus]:
            return []  # both writers read "no version yet"

    store, subject = _store(), _connection()
    door = RacingDoor({subject.id: WORKSPACE_A})
    await store.put(door, PERSON_A, subject, "api_key", Secret("first"))
    with pytest.raises(ConflictError):
        await store.put(door, PERSON_A, subject, "api_key", Secret("second"))
    assert len(door.rows[(subject.id, "api_key")]) == 1


@pytest.mark.parametrize("bad", ["", "Api", "a|b", "1x", "x" * 64, "api key"])
async def test_a_field_name_outside_the_tables_check_is_refused(bad: str) -> None:
    """The table's CHECK, held here too, also keeps `|` out of the AAD."""
    store, subject = _store(), _connection()
    door = FakeDoor({subject.id: WORKSPACE_A})
    with pytest.raises(DWError, match="field"):
        await store.put(door, PERSON_A, subject, bad, Secret(CANARY))
    assert door.rows == {}


def test_a_local_master_key_never_prints() -> None:
    kms = LocalDevKms(MASTER)
    assert base64.b64encode(MASTER).decode() not in repr(kms)
    assert repr(MASTER) not in repr(kms)
