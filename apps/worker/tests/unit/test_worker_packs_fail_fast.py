"""wf-lite R3.5 (WFL6): a bad workflow under `configs/packs` stops the worker
before it registers any lane, naming the file."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from test_worker import bare_settings

from dw_agent_runtime.wflite.catalog import load_yaml
from dw_kernel.errors import ConfigError
from dw_worker import main

pytestmark = pytest.mark.unit

FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "packages/python/dw_agent_runtime/tests/fixtures/packs/sample"
)


def test_a_bad_pack_stops_the_worker_and_names_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configs = tmp_path / "configs"
    (configs / "tools").mkdir(parents=True)
    pack = configs / "packs" / "sample"
    shutil.copytree(FIXTURE, pack)
    path = pack / "workflows" / "sample@1.0.0.yaml"
    document = load_yaml(path.read_text(encoding="utf-8"))
    del document["steps"][3]["config"]["default"]
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    monkeypatch.setattr(main, "CONFIGS", configs)
    with pytest.raises(ConfigError) as refused:
        main.build_registry(bare_settings())
    assert "sample@1.0.0.yaml" in refused.value.message
    assert "wf.router_not_total" in refused.value.message
