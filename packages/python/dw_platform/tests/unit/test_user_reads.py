"""Every read of `platform.users` in the persistence adapters, listed
(org-and-principals ticket 03 step 8, R7).

A service account is a `platform.users` row too, and it is no person: a list of
people, a sign-in or a candidate for a role that forgets `kind` shows it. Each
function of `dw_platform.adapters.persistence` that names the table either
filters people (`tables.HUMAN`, or `kind = 'human'` in its SQL) or is listed
below with why a service account may stand there. A new function that names
the table fails here until it does one or the other; a listed function that no
longer names it, or now filters, fails too, so the list does not rot.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PERSISTENCE = (
    Path(__file__).resolve().parents[2] / "src" / "dw_platform" / "adapters" / "persistence"
)

# (module, function) -> why a service account may be in what it reads.
NOT_A_LIST_OF_PEOPLE: dict[tuple[str, str], str] = {
    ("digital_workers_repo.py", "create"): "writes a DW's own service user",
    ("service_principals_repo.py", "create"): "writes a service account's own user",
    ("identity_provisioning.py", "bootstrap"): "reads back the user `_resolve_user` resolved",
    ("offboarding.py", "service_users_purge_step"): "the purge step of the service users",
    ("provisioning_repo.py", "_owner_user"): "finds or makes an owner by email; tenant_owner "
    "never reaches a service user (guard_service_principal_grants)",
    ("provisioning_repo.py", "find_user_by_email"): "the person an operator names by email; "
    "the same guard refuses the role to a service user",
    ("provisioning_repo.py", "list_operators"): "the operators' allowlist, joined by id",
    ("provisioning_repo.py", "list_support_staff"): "the support staff allowlist, joined by id",
    ("repositories.py", "list_page"): "a feedback row's author, joined by id",
    ("tenant_members.py", "invite"): "the person an invitation names by email",
    ("digital_workers_repo.py", "_STANDING"): "reports the kind; `is_person_in` and the DW "
    "service refuse a service user themselves",
}

_NEEDLES = ("tables.users", "platform.users")
_PEOPLE = ("tables.HUMAN", "kind = 'human'", 'kind == "human"', "u.kind = 'human'")


def _reads() -> dict[tuple[str, str], str]:
    """Every innermost function naming the table, with its source."""
    found: dict[tuple[str, str], str] = {}
    for path in sorted(PERSISTENCE.glob("*.py")):
        if path.name == "tables.py":
            continue
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            inner = {
                child
                for child in ast.walk(node)
                if child is not node and isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            }
            text = ast.get_source_segment(source, node) or ""
            for child in inner:
                text = text.replace(ast.get_source_segment(source, child) or "", "")
            if any(needle in text for needle in _NEEDLES):
                found[(path.name, node.name)] = text
        # A query held in a module constant is a read too.
        for statement in ast.parse(source).body:
            if isinstance(statement, ast.Assign | ast.AnnAssign):
                targets = (
                    statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                )
                text = ast.get_source_segment(source, statement) or ""
                for target in targets:
                    if isinstance(target, ast.Name) and any(n in text for n in _NEEDLES):
                        found[(path.name, target.id)] = text
    return found


def test_every_read_of_platform_users_filters_people_or_says_why_not() -> None:
    reads = _reads()
    unexplained = sorted(
        key
        for key, text in reads.items()
        if key not in NOT_A_LIST_OF_PEOPLE and not any(p in text for p in _PEOPLE)
    )
    assert unexplained == [], (
        "these read platform.users without filtering people; filter with tables.HUMAN"
        f" or list them with a reason: {unexplained}"
    )


def test_the_list_names_only_reads_that_exist_and_do_not_filter() -> None:
    reads = _reads()
    stale = sorted(
        key
        for key in NOT_A_LIST_OF_PEOPLE
        if key not in reads or any(p in reads[key] for p in _PEOPLE)
    )
    assert stale == [], f"listed but no longer an unfiltered read of platform.users: {stale}"


@pytest.mark.parametrize(
    ("module", "function"),
    [
        ("provisioning_repo.py", "list_users"),
        ("directory.py", "list_candidates"),
        ("membership_lookup.py", "find_access"),
        ("tenant_members.py", "list_members"),
    ],
)
def test_the_people_lists_filter_people(module: str, function: str) -> None:
    """R7.1, R7.2, R6.2: the reads the ticket names, by name."""
    text = _reads()[(module, function)]
    assert any(p in text for p in _PEOPLE), (module, function)
