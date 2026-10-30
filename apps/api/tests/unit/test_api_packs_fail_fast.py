"""wf-lite R3.5 (WFL6): a bad workflow under `configs/packs` stops the API at
construction, naming the file, and with or without a database."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from dw_agent_runtime.wflite.catalog import load_yaml
from dw_api.bootstrap import wiring
from dw_api.bootstrap.wiring import build_container
from dw_api.settings import ApiSettings
from dw_kernel.errors import ConfigError

pytestmark = pytest.mark.unit

FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "packages/python/dw_agent_runtime/tests/fixtures/packs/sample"
)


def _configs_with_a_bad_pack(tmp_path: Path) -> Path:
    configs = tmp_path / "configs"
    (configs / "tools").mkdir(parents=True)
    pack = configs / "packs" / "sample"
    shutil.copytree(FIXTURE, pack)
    path = pack / "workflows" / "sample@1.0.0.yaml"
    document = load_yaml(path.read_text(encoding="utf-8"))
    document["steps"].append({"id": "x", "type": "http.request@1", "config": {}})
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return configs


def test_a_bad_pack_stops_the_api_and_names_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wiring, "CONFIGS", _configs_with_a_bad_pack(tmp_path))
    with pytest.raises(ConfigError) as refused:
        build_container(ApiSettings(profile="test", dev_secret="x" * 32))
    assert "sample@1.0.0.yaml" in refused.value.message
    assert "wf.unknown_type" in refused.value.message


def test_the_shipped_packs_load() -> None:
    build_container(ApiSettings(profile="test", dev_secret="x" * 32))
