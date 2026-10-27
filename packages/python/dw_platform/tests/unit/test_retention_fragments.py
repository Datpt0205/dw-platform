"""One retention fragment per store, read only from its own file (spec R5.6, R5.13, R5.14).

The pinned set is under `configs/policies/retention.d/`; these build their own
sets in a temporary directory, so each test plants exactly the defect it names.
That a fragment's name is a real table is asked of `pg_class`, in
`tests/integration/test_retention_terms.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts.release_manifest import build_manifest, fragment_set_checksum

from dw_platform.adapters.persistence.partition_maintenance import AUDIT_EVENTS
from dw_platform.retention_policy import (
    RETENTION_FRAGMENTS_DIR,
    RETENTION_POLICY_PATH,
    RetentionPurgerRegistry,
    load_retention_fragments,
    load_retention_policy,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]
AUDIT_FRAGMENT = "days: 1095\npurger: drop_partition\nenforced: true\ndescription: Nhật ký\n"


def _fragments(tmp_path: Path, **files: str) -> Path:
    directory = tmp_path / "retention.d"
    directory.mkdir()
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    return directory


def test_the_pinned_set_gives_the_audit_log_three_years() -> None:
    """Moved from `audit.tables.audit_events` of `retention@1.7.0` unchanged."""
    term = load_retention_policy().term(AUDIT_EVENTS)
    assert term is not None and (term.days, term.enforced) == (1095, True)


def test_the_policy_reads_a_term_only_from_its_own_fragment(tmp_path: Path) -> None:
    """R5.13: no fragment, no term — not the one the versioned file once held,
    which is how the provisional mapping to `retention@1.7.0` answered."""
    without = load_retention_policy(RETENTION_POLICY_PATH, _fragments(tmp_path))
    assert without.term(AUDIT_EVENTS) is None
    assert without.store_cutoff(AUDIT_EVENTS, now=datetime.now(UTC)) is None


def test_two_tables_of_one_name_in_two_schemas_keep_their_own_terms(tmp_path: Path) -> None:
    """R5.6: the key carries the schema, so `platform.x` and `studio.x` never collide."""
    directory = _fragments(
        tmp_path,
        **{
            "platform.events.yaml": AUDIT_FRAGMENT,
            "studio.events.yaml": AUDIT_FRAGMENT.replace("1095", "30"),
        },
    )
    policy = load_retention_policy(RETENTION_POLICY_PATH, directory)
    platform, studio = policy.term("platform.events"), policy.term("studio.events")
    assert platform is not None and platform.days == 1095
    assert studio is not None and studio.days == 30


def test_a_fragment_named_without_its_schema_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"audit_events\.yaml"):
        load_retention_fragments(_fragments(tmp_path, **{"audit_events.yaml": AUDIT_FRAGMENT}))


@pytest.mark.parametrize(
    ("text", "names"),
    [
        (AUDIT_FRAGMENT + "owner: platform\n", "owner"),
        # H-31: a store that never expires has no purger, and only it.
        (
            AUDIT_FRAGMENT.replace("1095", "indefinite").replace("drop_partition", "row_delete"),
            "indefinite",
        ),
        (AUDIT_FRAGMENT.replace("1095", "null").replace("drop_partition", "none"), "indefinite"),
        (AUDIT_FRAGMENT.replace("1095", "0"), "positive"),
        (AUDIT_FRAGMENT.replace("1095", "true"), "days"),
        (AUDIT_FRAGMENT.replace("drop_partition", "truncate"), "purger"),
    ],
    ids=[
        "extra key",
        "indefinite with a purger",
        "null without one",
        "zero",
        "bool",
        "unknown purger",
    ],
)
def test_a_malformed_fragment_is_refused_naming_its_file_and_the_fault(
    tmp_path: Path, text: str, names: str
) -> None:
    with pytest.raises(ValueError, match=r"platform.audit_events.yaml") as refused:
        load_retention_fragments(_fragments(tmp_path, **{"platform.audit_events.yaml": text}))
    assert names in str(refused.value)


def test_a_store_that_never_expires_has_no_term(tmp_path: Path) -> None:
    text = AUDIT_FRAGMENT.replace("1095", "indefinite").replace("drop_partition", "none")
    directory = _fragments(tmp_path, **{"platform.kept.yaml": text})
    assert load_retention_policy(RETENTION_POLICY_PATH, directory).term("platform.kept") is None


def test_the_versioned_file_may_not_carry_a_store(tmp_path: Path) -> None:
    carrying = tmp_path / "retention@9.9.9.yaml"
    carrying.write_text(
        RETENTION_POLICY_PATH.read_text(encoding="utf-8") + "\nstores: {}\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="fragment"):
        load_retention_policy(carrying, RETENTION_FRAGMENTS_DIR)


def test_the_set_checksum_follows_names_and_content_not_listing_order(tmp_path: Path) -> None:
    """R5.14. Hashing in the order the filesystem lists files would make two
    machines disagree about one set; the name is hashed because it is the key."""
    base = _fragments(tmp_path, **{"platform.a.yaml": AUDIT_FRAGMENT, "platform.b.yaml": "x"})
    checksum = fragment_set_checksum(base)
    (base / "platform.b.yaml").write_text("x", encoding="utf-8")
    assert fragment_set_checksum(base) == checksum
    (base / "platform.b.yaml").rename(base / "platform.c.yaml")
    assert fragment_set_checksum(base) != checksum
    (base / "platform.c.yaml").rename(base / "platform.b.yaml")
    (base / "platform.a.yaml").write_text(AUDIT_FRAGMENT.replace("1095", "1096"), "utf-8")
    assert fragment_set_checksum(base) != checksum


def test_the_committed_manifest_pins_the_fragment_set_as_it_is_now() -> None:
    """What `make release-manifest-check` turns on: a fragment edited without
    regenerating the manifest leaves this checksum behind the set."""
    committed = json.loads(
        (REPO_ROOT / "contracts" / "release" / "manifest.json").read_text("utf-8")
    )
    (entry,) = [p for p in committed["policies"] if p["policy_id"] == "retention.d"]
    assert entry["checksum"] == fragment_set_checksum(RETENTION_FRAGMENTS_DIR)
    built = {p["policy_id"]: p for p in build_manifest()["policies"]}
    assert built["retention.d"] == entry
    assert "retention" in built and built["retention"]["version"] == "1.8.0"


async def _purge() -> None: ...


def test_the_purger_registry_refuses_a_second_purger_and_a_late_one() -> None:
    """H-35: two purgers of one store are two answers to how long it is kept."""
    registry = RetentionPurgerRegistry({"platform.a": _purge})
    with pytest.raises(ValueError, match=r"platform.a"):
        registry.register("platform.a", _purge)
    registry.freeze()
    with pytest.raises(RuntimeError, match="frozen"):
        registry.register("platform.b", _purge)
    assert list(registry.all()) == ["platform.a"]
