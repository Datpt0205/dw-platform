"""The price book file, and the startup check both composition roots run.

Pinned by file name like every versioned artifact (`price_book@<semver>.yaml`);
`scripts/release_manifest.py` pins its id, version and sha256.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Final

import yaml

from dw_agent_runtime.model.profiles import ModelProfile, ModelProfileRegistry
from dw_kernel.errors import ConfigError
from dw_usage.application.coverage import require_paid_routes_priced
from dw_usage.domain.pricing import PriceBook, price_book_from_document

__all__ = ["PRICE_BOOK_PATH", "enforce_price_coverage", "load_price_book", "platform_profiles"]

# The image sets DW_REPO_ROOT=/app and ships `configs/` there; in a checkout the
# root is six levels up from this file.
_REPO_ROOT = Path(os.environ.get("DW_REPO_ROOT", str(Path(__file__).resolve().parents[6])))
PRICE_BOOK_PATH: Final = _REPO_ROOT / "configs" / "pricing" / "price_book@1.1.0.yaml"


def load_price_book(path: Path = PRICE_BOOK_PATH) -> PriceBook:
    """The book, or `ConfigError` naming the file: a bad edit stops the process."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"price book {path.name} unreadable: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError(f"price book {path.name} is not a mapping")
    try:
        book = price_book_from_document(document)
    except ConfigError as exc:
        raise ConfigError(f"price book {path.name}: {exc.message}", details=exc.details) from exc
    expected = path.stem.partition("@")[2]
    if expected and expected != book.version:
        raise ConfigError(f"price book {path.name} says version {book.version}")
    return book


def platform_profiles(directory: Path) -> list[ModelProfile]:
    """The platform layer's model profiles, parsed by the registry's own loader."""
    return [ModelProfileRegistry().load_file(path) for path in sorted(directory.glob("*.yaml"))]


def enforce_price_coverage(
    book: PriceBook, profiles_dir: Path, *, at: datetime, is_deployed: bool
) -> None:
    """R2.3, as both processes run it before serving: a deployed profile with a
    paid route the book does not price at `at` does not start."""
    require_paid_routes_priced(platform_profiles(profiles_dir), book, at, is_deployed=is_deployed)
