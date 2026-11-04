"""The API's key service settings (connections-and-vault R2.2, CV5).

`DW_KMS_PROVIDER` defaults to `none`; `local`, the development key service, is
refused in a deployed profile and needs a master key of at least 32 bytes in
every profile. `validate_for_profile` is what refuses, before the container is
built (`bootstrap/wiring.py`).
"""

from __future__ import annotations

import base64

import pytest
from pydantic import SecretStr
from test_dev_endpoints import deployed_settings

from dw_api.settings import ApiSettings

pytestmark = pytest.mark.unit

MASTER_B64 = base64.b64encode(bytes(range(32))).decode()


@pytest.mark.parametrize("profile", ["uat", "production"])
def test_a_deployed_api_refuses_the_local_key_service(profile: str) -> None:
    settings = deployed_settings(profile).model_copy(
        update={"kms_provider": "local", "local_kms_master_key": SecretStr(MASTER_B64)}
    )
    with pytest.raises(RuntimeError, match="DW_KMS_PROVIDER=local is forbidden"):
        settings.validate_for_profile()
    # The control: the same settings with no key service start.
    deployed_settings(profile).validate_for_profile()


def test_the_default_is_no_key_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DW_KMS_PROVIDER", raising=False)
    assert ApiSettings(profile="local").kms_provider == "none"


def test_the_setting_is_read_under_its_one_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DW_KMS_PROVIDER", "local")
    monkeypatch.setenv("DW_LOCAL_KMS_MASTER_KEY", MASTER_B64)
    settings = ApiSettings(profile="local")
    assert settings.kms_provider == "local"
    settings.validate_for_profile()


@pytest.mark.parametrize(
    "key", ["", base64.b64encode(bytes(31)).decode()], ids=["empty", "31 bytes"]
)
def test_a_local_key_service_without_a_full_master_key_does_not_start(key: str) -> None:
    settings = ApiSettings(
        profile="local", kms_provider="local", local_kms_master_key=SecretStr(key)
    )
    with pytest.raises(RuntimeError, match="DW_LOCAL_KMS_MASTER_KEY"):
        settings.validate_for_profile()


def test_the_master_key_never_prints() -> None:
    settings = ApiSettings(
        profile="local", kms_provider="local", local_kms_master_key=SecretStr(MASTER_B64)
    )
    assert MASTER_B64 not in repr(settings)
    assert MASTER_B64 not in str(settings.model_dump())
