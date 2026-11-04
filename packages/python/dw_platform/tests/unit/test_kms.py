"""The key services `DW_KMS_PROVIDER` chooses (connections-and-vault R1.4, R2.2, R2.4)."""

from __future__ import annotations

import base64

import pytest

from dw_platform.adapters.kms import (
    LocalDevKms,
    UnavailableKms,
    build_kms,
    check_kms_settings,
    decode_local_master_key,
)
from dw_platform.application.secrets import KmsUnavailableError, SecretUnreadableError, WrappedKey

pytestmark = pytest.mark.unit

MASTER = bytes(range(32))
MASTER_B64 = base64.b64encode(MASTER).decode()
TENANT_A = "tenant-00000000-0000-0000-0000-00000000000a"
TENANT_B = "tenant-00000000-0000-0000-0000-00000000000b"


async def test_a_data_key_unwraps_under_its_tenant_key_only() -> None:
    kms = LocalDevKms(MASTER)
    key = await kms.generate_data_key(TENANT_A)
    assert len(key.plaintext) == 32
    assert key.wrapped.kek_version == 1
    assert await kms.decrypt_data_key(TENANT_A, key.wrapped) == key.plaintext
    with pytest.raises(SecretUnreadableError):
        await kms.decrypt_data_key(TENANT_B, key.wrapped)
    # Another master key is another key service.
    with pytest.raises(SecretUnreadableError):
        await LocalDevKms(bytes(32)).decrypt_data_key(TENANT_A, key.wrapped)
    # A data key that reaches a log line shows only its wrapped form.
    assert repr(key.plaintext) not in repr(key)


async def test_a_rewrap_moves_the_key_to_the_current_version_and_keeps_it() -> None:
    old = LocalDevKms(MASTER)
    key = await old.generate_data_key(TENANT_A)
    rotated = LocalDevKms(MASTER, current_version=2)
    moved = await rotated.rewrap(TENANT_A, key.wrapped)
    assert moved.kek_version == 2
    assert moved.wrapped != key.wrapped.wrapped
    assert await rotated.decrypt_data_key(TENANT_A, moved) == key.plaintext
    # The earlier version still unwraps; a version not yet reached does not.
    assert await rotated.decrypt_data_key(TENANT_A, key.wrapped) == key.plaintext
    with pytest.raises(SecretUnreadableError):
        await old.decrypt_data_key(TENANT_A, moved)
    with pytest.raises(SecretUnreadableError):
        await rotated.decrypt_data_key(TENANT_A, WrappedKey(moved.wrapped, 1))


async def test_none_refuses_every_call() -> None:
    kms = UnavailableKms()
    with pytest.raises(KmsUnavailableError) as raised:
        await kms.generate_data_key(TENANT_A)
    assert raised.value.details["reason_code"] == "kms_unavailable"
    with pytest.raises(KmsUnavailableError):
        await kms.decrypt_data_key(TENANT_A, WrappedKey(b"x" * 40, 1))
    with pytest.raises(KmsUnavailableError):
        await kms.rewrap(TENANT_A, WrappedKey(b"x" * 40, 1))


def test_none_never_falls_back_to_the_local_key_service() -> None:
    """R2.2: `none` with a perfectly good master key set is still `none`."""
    assert isinstance(build_kms("none", MASTER_B64), UnavailableKms)
    assert isinstance(build_kms("local", MASTER_B64), LocalDevKms)


@pytest.mark.parametrize(
    "encoded",
    ["", "   ", "not base64!", base64.b64encode(bytes(31)).decode()],
    ids=["empty", "blank", "malformed", "31 bytes"],
)
def test_a_missing_or_short_master_key_refuses_to_start(encoded: str) -> None:
    with pytest.raises(RuntimeError, match="DW_LOCAL_KMS_MASTER_KEY"):
        decode_local_master_key(encoded)
    with pytest.raises(RuntimeError, match="DW_LOCAL_KMS_MASTER_KEY"):
        build_kms("local", encoded)
    with pytest.raises(RuntimeError, match="DW_LOCAL_KMS_MASTER_KEY"):
        check_kms_settings("local", encoded, deployed=False, profile="local")


def test_the_local_key_service_is_refused_when_deployed() -> None:
    with pytest.raises(RuntimeError, match="DW_KMS_PROVIDER=local is forbidden in the uat"):
        check_kms_settings("local", MASTER_B64, deployed=True, profile="uat")
    check_kms_settings("local", MASTER_B64, deployed=False, profile="local")
    check_kms_settings("none", "", deployed=True, profile="production")
