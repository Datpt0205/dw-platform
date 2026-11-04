"""`KmsPort` implementations chosen by `DW_KMS_PROVIDER` (connections-and-vault
R2.2, R2.4; ADR-0115 decision 1).

- `none`, the default: every call fails with `kms_unavailable`. Nothing falls
  back to `LocalDevKms` or to a plain value, so a deployment that forgot to
  configure a key service stores no secret rather than a weak one.
- `local`: `LocalDevKms`, a development key service. Each tenant key version is
  derived by HKDF-SHA256 from `DW_LOCAL_KMS_MASTER_KEY` (base64 of at least 32
  bytes, generated on the developer's machine), and data keys are wrapped with
  AES key wrap (RFC 3394). Refused in every deployed profile by
  `check_kms_settings`.

OpenBao Transit, the deployed provider, is ticket 06's (`openbao`).
"""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass, field
from typing import Literal

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap, aes_key_wrap

from dw_platform.application.secrets import (
    DataKey,
    KmsPort,
    KmsUnavailableError,
    SecretUnreadableError,
    WrappedKey,
)

KmsProvider = Literal["none", "local"]
MIN_MASTER_KEY_BYTES = 32
_DATA_KEY_BYTES = 32
_KEK_INFO = "dw.kms.local.v1"


def decode_local_master_key(encoded: str) -> bytes:
    """`DW_LOCAL_KMS_MASTER_KEY` as bytes; a missing, malformed or short key
    refuses to start, in every profile."""
    try:
        key = base64.b64decode(encoded.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise RuntimeError("DW_LOCAL_KMS_MASTER_KEY must be base64") from None
    if len(key) < MIN_MASTER_KEY_BYTES:
        raise RuntimeError(
            f"DW_LOCAL_KMS_MASTER_KEY must decode to at least {MIN_MASTER_KEY_BYTES} bytes"
        )
    return key


def check_kms_settings(
    provider: KmsProvider, local_master_key: str, *, deployed: bool, profile: str
) -> None:
    """What the api and the worker each refuse at startup (R2.2)."""
    if provider == "local":
        if deployed:
            raise RuntimeError(f"DW_KMS_PROVIDER=local is forbidden in the {profile} profile")
        decode_local_master_key(local_master_key)


@dataclass(frozen=True)
class LocalDevKms:
    """Tenant keys derived from one development master key.

    `current_version` is the tenant key version new data keys are wrapped
    under; a key wrapped under an earlier version still unwraps, and `rewrap`
    moves it to the current one, as OpenBao's rotation does.
    """

    master_key: bytes = field(repr=False)
    current_version: int = 1

    def __post_init__(self) -> None:
        if len(self.master_key) < MIN_MASTER_KEY_BYTES:
            raise RuntimeError(f"a local master key is at least {MIN_MASTER_KEY_BYTES} bytes")
        if self.current_version < 1:
            raise ValueError("a key version starts at 1")

    def _kek(self, kek_ref: str, version: int) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=f"{_KEK_INFO}|{kek_ref}|{version}".encode(),
        ).derive(self.master_key)

    async def generate_data_key(self, kek_ref: str) -> DataKey:
        plaintext = os.urandom(_DATA_KEY_BYTES)
        wrapped = aes_key_wrap(self._kek(kek_ref, self.current_version), plaintext)
        return DataKey(plaintext=plaintext, wrapped=WrappedKey(wrapped, self.current_version))

    async def decrypt_data_key(self, kek_ref: str, key: WrappedKey) -> bytes:
        if not 1 <= key.kek_version <= self.current_version:
            raise SecretUnreadableError()
        try:
            return aes_key_unwrap(self._kek(kek_ref, key.kek_version), key.wrapped)
        except InvalidUnwrap:
            raise SecretUnreadableError() from None

    async def rewrap(self, kek_ref: str, key: WrappedKey) -> WrappedKey:
        plaintext = await self.decrypt_data_key(kek_ref, key)
        wrapped = aes_key_wrap(self._kek(kek_ref, self.current_version), plaintext)
        return WrappedKey(wrapped, self.current_version)


class UnavailableKms:
    """`DW_KMS_PROVIDER=none`: no key service, so no secret is sealed or opened."""

    async def generate_data_key(self, kek_ref: str) -> DataKey:
        raise KmsUnavailableError()

    async def decrypt_data_key(self, kek_ref: str, key: WrappedKey) -> bytes:
        raise KmsUnavailableError()

    async def rewrap(self, kek_ref: str, key: WrappedKey) -> WrappedKey:
        raise KmsUnavailableError()


def build_kms(provider: KmsProvider, local_master_key: str) -> KmsPort:
    """The composition roots' one way to a `KmsPort`."""
    if provider == "local":
        return LocalDevKms(decode_local_master_key(local_master_key))
    return UnavailableKms()
