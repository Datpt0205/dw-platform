"""The two compose checks of `scripts/verify_invariants.py` (runtime-hardening
R8.3, R8.4; RH23, RH24): each is clean on the shipped files and goes red on a
copy with the one thing it guards broken."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from scripts.verify_invariants import (
    COMPOSE,
    check_exporter_connects_as_monitor,
    check_third_party_images_are_pinned,
)

pytestmark = pytest.mark.unit


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "compose"
    target.mkdir()
    for path in COMPOSE.glob("*.yml"):
        shutil.copy(path, target / path.name)
    return target


def test_the_shipped_compose_files_are_clean() -> None:
    assert check_third_party_images_are_pinned() == []
    assert check_exporter_connects_as_monitor() == []


def test_an_image_without_its_digest_is_red(tmp_path: Path) -> None:
    compose = _copy(tmp_path)
    base = compose / "docker-compose.yml"
    text = base.read_text(encoding="utf-8")
    pinned = next(line for line in text.splitlines() if "image: valkey/valkey:" in line)
    base.write_text(text.replace(pinned, pinned.split("@")[0], 1), encoding="utf-8")
    assert any("valkey/valkey" in v for v in check_third_party_images_are_pinned(compose))


def test_a_floating_tag_with_a_digest_is_red_too(tmp_path: Path) -> None:
    compose = _copy(tmp_path)
    (compose / "extra.yml").write_text(
        "services:\n  x:\n    image: alpine:latest@sha256:" + "a" * 64 + "\n", encoding="utf-8"
    )
    assert check_third_party_images_are_pinned(compose) != []


def test_the_exporter_connecting_as_the_app_is_red(tmp_path: Path) -> None:
    compose = _copy(tmp_path)
    base = compose / "docker-compose.yml"
    text = base.read_text(encoding="utf-8")
    base.write_text(
        text.replace(
            "postgresql://dw_monitor:${DW_DB_MONITOR_PASSWORD:?}",
            "postgresql://dw_app:${DW_DB_APP_PASSWORD:?}",
        ),
        encoding="utf-8",
    )
    assert check_exporter_connects_as_monitor(compose) != []
