"""The rules and the judgement of `scripts/verify_compose_policy.py`
(studio-skeleton R8; SKEL16, SKEL17), on hand-built rendered models.

`scripts/test_compose_policy.sh` plants each defect in real compose files and
reads what `docker compose config` renders; these run the same rules without
Docker, one defect each on a probe service that passes every rule, so a rule
removed or loosened turns its own case red (and `mutations/04.yaml` can say so).
"""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts import verify_compose_policy as policy
from scripts.verify_compose_policy import (
    COMBINATIONS,
    EXCEPTIONS,
    RULES,
    Rendered,
    Waiver,
    adr_admits,
    judge,
    parse_ci,
    violations,
)

pytestmark = pytest.mark.unit

PROBE = "probe-svc"
PINNED = "alpine:3.20.10@sha256:" + "d" * 64

CI_TEXT = """
jobs:
  contracts:
    steps:
      - run: |
          docker compose --env-file .env -f x.yml --profile probe-svc config -q
          docker compose --env-file .env -f x.yml \\
            --profile probe-svc up -d --wait probe-svc
  containers:
    steps:
      - run: |
          for image in dw-api:local dw-probe:local; do
            ./trivy image "$image"
          done
          pinned=$(grep -hoE 'image: *[^ ]+@sha256:[0-9a-f]{64}' infra/compose/*.yml \\
            | sort -u)
          for image in $pinned; do
            ./trivy image "$image"
          done
"""


def _probe() -> dict[str, Any]:
    return {
        "image": PINNED,
        "profiles": [PROBE],
        "networks": {"probe-net": None},
        "healthcheck": {"test": ["CMD-SHELL", "exit 0"]},
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "init": True,
        "user": "1000:1000",
        "mem_limit": "67108864",
        "pids_limit": 64,
        "deploy": {"resources": {"limits": {"memory": "67108864"}}},
    }


def _rendered(
    probe: dict[str, Any],
    *,
    others: dict[str, Any] | None = None,
    per_combo: dict[str, dict[str, Any]] | None = None,
    ci: str = CI_TEXT,
) -> Rendered:
    networks = {
        "probe-net": {"name": "p_probe-net", "internal": True},
        "dw-internal": {"name": "p_dw-internal", "internal": True},
        "open": {"name": "p_open"},
    }
    models = {}
    for combo in COMBINATIONS:
        spec = copy.deepcopy(probe)
        spec.update((per_combo or {}).get(combo, {}))
        spec = {k: v for k, v in spec.items() if v is not None}
        services = {PROBE: spec, **copy.deepcopy(others or {})}
        models[combo] = {"networks": networks, "services": services}
    return Rendered(models, parse_ci(ci))


def _probe_rules(rendered: Rendered) -> set[str]:
    return {rule for service, rule in violations(rendered) if service == PROBE}


def _without(**removed: None) -> dict[str, Any]:
    probe = _probe()
    for key in removed:
        probe.pop(key)
    return probe


def _with(**changed: Any) -> dict[str, Any]:
    return {**_probe(), **changed}


def test_the_probe_passes_every_rule() -> None:
    assert _probe_rules(_rendered(_probe())) == set()


# One defect each; the probe must break exactly the rule named, nothing else.
DEFECTS: list[tuple[str, dict[str, Any]]] = [
    ("dw-internal", _with(networks={"dw-internal": None})),
    ("internal-network", _with(networks={"open": None})),
    ("internal-network", _without(networks=None)),
    ("digest", _with(image="alpine:3.20")),
    ("digest", _with(image="alpine@sha256:" + "d" * 64)),
    ("ports", _with(ports=[{"target": 80, "published": "8080"}])),
    ("healthcheck", _without(healthcheck=None)),
    ("healthcheck", _with(healthcheck={"disable": True})),
    ("healthcheck", _with(healthcheck={"test": ["CMD-SHELL", "exit 0"], "disable": True})),
    ("read_only", _without(read_only=None)),
    ("cap_drop", _with(cap_drop=["NET_RAW"])),
    ("no-new-privileges", _with(security_opt=["seccomp:unconfined"])),
    ("init", _without(init=None)),
    ("user", _without(user=None)),
    ("user", _with(user="0:0")),
    ("user", _with(user="root")),
    ("mem_limit", _without(mem_limit=None)),
    ("pids_limit", _with(pids_limit=-1)),
    ("network_mode", _with(network_mode="service:qdrant", networks=None)),
    ("network_mode", _with(network_mode="host", networks=None)),
    ("privileged", _with(privileged=True)),
    ("cap_add", _with(cap_add=["NET_ADMIN"])),
    ("pid-host", _with(pid="host")),
    ("ipc-host", _with(ipc="host")),
    (
        "docker-socket",
        _with(
            volumes=[
                {"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock"}
            ]
        ),
    ),
    ("profile", _with(profiles=["full"])),
]


@pytest.mark.parametrize(
    ("rule", "probe"), DEFECTS, ids=[f"{r}-{i}" for i, (r, _) in enumerate(DEFECTS)]
)
def test_each_defect_breaks_its_own_rule(rule: str, probe: dict[str, Any]) -> None:
    probe = {k: v for k, v in probe.items() if v is not None}
    assert _probe_rules(_rendered(probe)) == {rule}


def test_an_alias_of_dw_internal_is_dw_internal() -> None:
    rendered = _rendered(_with(networks={"backdoor": None}))
    for model in rendered.models.values():
        model["networks"]["backdoor"] = {"name": "p_dw-internal", "internal": True}
    assert "dw-internal" in _probe_rules(rendered)


def test_sharing_a_network_with_an_undeclared_caller_is_red(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    others = {"api": {"networks": {"probe-net": None}}}
    assert "internal-network" in _probe_rules(_rendered(_probe(), others=others))
    monkeypatch.setitem(policy.CALLERS, PROBE, frozenset({"api"}))
    assert "internal-network" not in _probe_rules(_rendered(_probe(), others=others))


def test_ports_only_in_the_dev_overlay_pass() -> None:
    ports = [{"target": 80, "published": "8080"}]
    assert _probe_rules(_rendered(_probe(), per_combo={"dev": {"ports": ports}})) == set()
    assert _probe_rules(_rendered(_probe(), per_combo={"host": {"ports": ports}})) == {"ports"}


def test_deploy_memory_is_required_in_uat_and_in_prod_each() -> None:
    no_deploy = {"deploy": None}
    assert _probe_rules(_rendered(_probe(), per_combo={"prod": no_deploy})) == {"deploy-resources"}
    assert _probe_rules(_rendered(_probe(), per_combo={"uat": no_deploy})) == {"deploy-resources"}
    assert _probe_rules(_rendered(_probe(), per_combo={"base": no_deploy})) == set()


def _built(tmp_path: Path, dockerfile: str, image: str = "dw-probe:local") -> dict[str, Any]:
    (tmp_path / "probe.Dockerfile").write_text(dockerfile, encoding="utf-8")
    return _with(image=image, build={"context": str(tmp_path), "dockerfile": "probe.Dockerfile"})


def test_a_built_image_needs_every_from_pinned(tmp_path: Path) -> None:
    pinned = f"FROM {PINNED} AS builder\nRUN true\nFROM builder AS runtime\nFROM scratch\n"
    assert _probe_rules(_rendered(_built(tmp_path, pinned))) == set()
    unpinned = f"FROM {PINNED} AS builder\nFROM python:3.12-slim AS runtime\n"
    assert _probe_rules(_rendered(_built(tmp_path, unpinned))) == {"digest"}


def test_from_an_arg_reads_its_default(tmp_path: Path) -> None:
    pinned = f"ARG BASE={PINNED}\nFROM ${{BASE}}\n"
    assert _probe_rules(_rendered(_built(tmp_path, pinned))) == set()
    unpinned = "ARG BASE=alpine:3.20\nFROM $BASE\n"
    assert _probe_rules(_rendered(_built(tmp_path, unpinned))) == {"digest"}


def test_a_missing_dockerfile_is_unpinned(tmp_path: Path) -> None:
    probe = _with(image="dw-probe:local", build={"context": str(tmp_path / "gone")})
    assert _probe_rules(_rendered(probe)) == {"digest"}


def test_ci_config_and_smoke_lines_are_required() -> None:
    no_config = CI_TEXT.replace("--profile probe-svc config -q", "--profile other config -q")
    assert _probe_rules(_rendered(_probe(), ci=no_config)) == {"ci-config"}
    no_wait = CI_TEXT.replace("up -d --wait probe-svc", "up -d --wait postgres")
    assert _probe_rules(_rendered(_probe(), ci=no_wait)) == {"ci-smoke"}
    commented = CI_TEXT.replace(
        "          docker compose --env-file .env -f x.yml --profile probe-svc config -q",
        "          # docker compose --env-file .env -f x.yml --profile probe-svc config -q",
    )
    assert _probe_rules(_rendered(_probe(), ci=commented)) == {"ci-config"}


def test_ci_trivy_reads_the_list_for_built_and_the_grep_for_pulled(tmp_path: Path) -> None:
    built = _built(tmp_path, f"FROM {PINNED}\n")
    unlisted = CI_TEXT.replace("dw-api:local dw-probe:local", "dw-api:local")
    assert _probe_rules(_rendered(built, ci=unlisted)) == {"ci-trivy"}
    assert _probe_rules(_rendered(_probe(), ci=unlisted)) == set()
    no_grep = CI_TEXT.replace(
        "grep -hoE 'image: *[^ ]+@sha256:[0-9a-f]{64}' infra/compose/*.yml", "true"
    )
    assert _probe_rules(_rendered(_probe(), ci=no_grep)) == {"ci-trivy"}


# ------------------------------------------------------------ the judgement --


def _never(_adr: str | None, _service: str, _rule: str) -> bool:
    return False


def test_a_violation_without_an_exception_line_is_red() -> None:
    assert judge({(PROBE, "read_only")}, set(), {}, _never) == [f"violation {PROBE} read_only"]


def test_an_exception_line_for_a_base_violation_is_enough() -> None:
    found = {("postgres", "read_only")}
    assert judge(found, found, {"read_only": {"postgres": "old"}}, _never) == []


def test_an_exception_that_no_longer_matches_is_stale() -> None:
    assert judge(set(), set(), {"read_only": {"docgen-gateway": "x"}}, _never) == [
        "stale-exception docgen-gateway read_only"
    ]


def test_an_exception_outside_the_base_set_needs_an_adr() -> None:
    found = {("postgres", "privileged")}
    lines = {"privileged": {"postgres": "x"}}
    assert judge(found, set(), lines, _never) == ["exception-needs-adr postgres privileged"]
    admitted = {"privileged": {"postgres": Waiver("x", adr="docs/adr/9999.md")}}
    seen: list[tuple[str | None, str, str]] = []

    def admits(adr: str | None, service: str, rule: str) -> bool:
        seen.append((adr, service, rule))
        return True

    assert judge(found, set(), admitted, admits) == []
    assert seen == [("docs/adr/9999.md", "postgres", "privileged")]


def test_an_exception_for_an_unknown_rule_is_red() -> None:
    assert judge(set(), set(), {"readonly": {"x": "y"}}, _never) == ["unknown-rule x readonly"]


def test_the_shipped_table_names_only_known_rules() -> None:
    assert set(EXCEPTIONS) <= set(RULES)


def _adr(tmp_path: Path, status: str, body: str) -> str:
    (tmp_path / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "adr" / "9999-probe.md").write_text(
        f"---\nstatus: {status}\ndate: 2026-11-05\n---\n\n# 9999. Probe\n\n{body}\n",
        encoding="utf-8",
    )
    return "docs/adr/9999-probe.md"


def test_an_accepted_adr_naming_both_in_backticks_admits(tmp_path: Path) -> None:
    adr = _adr(tmp_path, "Accepted (Đạt, 2026-11-05)", "`probe-svc` may leave `internal-network`.")
    assert adr_admits(tmp_path, adr, PROBE, "internal-network")


@pytest.mark.parametrize(
    ("status", "body"),
    [
        ("Proposed", "`probe-svc` may leave `internal-network`."),
        ("Accepted", "`other-svc` may leave `internal-network`."),
        ("Accepted", "probe-svc may leave internal-network."),
        ("Accepted", "probe-svc may leave `internal-network`."),
        ("Accepted", "`probe-svc` may leave internal-network."),
        ("Accepted", "`probe-svc` may leave the network."),
    ],
)
def test_an_adr_that_does_not_name_both_or_is_not_accepted_does_not(
    tmp_path: Path, status: str, body: str
) -> None:
    adr = _adr(tmp_path, status, body)
    assert not adr_admits(tmp_path, adr, PROBE, "internal-network")


def test_an_adr_outside_docs_adr_does_not_admit(tmp_path: Path) -> None:
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "x.md").write_text(
        "---\nstatus: Accepted\n---\n`probe-svc` `internal-network`\n", encoding="utf-8"
    )
    assert not adr_admits(tmp_path, "x.md", PROBE, "internal-network")
    assert not adr_admits(tmp_path, None, PROBE, "internal-network")


# ---------------------------------------------- what the check refuses to see --


def test_a_missing_base_commit_is_named(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    why = policy.extract_base(repo, tmp_path / "into")
    assert why is not None
    assert why.startswith(f"BASE_SHA {policy.BASE_SHA} is not in")


def _fake_compose(
    monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str, stderr: str = ""
) -> list[dict[str, str]]:
    envs: list[dict[str, str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        envs.append(kwargs["env"])
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    monkeypatch.setattr(subprocess, "run", run)
    return envs


def _compose_tree(tmp_path: Path) -> Path:
    (tmp_path / "infra" / "compose").mkdir(parents=True, exist_ok=True)
    (tmp_path / "infra" / "compose" / "docker-compose.yml").write_text(
        "services:\n  a:\n    environment:\n      K: ${QDRANT_API_KEY:?}\n", encoding="utf-8"
    )
    (tmp_path / ".env.example").write_text("REDIS_PASSWORD=change-me\n", encoding="utf-8")
    return tmp_path


def test_a_combination_that_fails_is_a_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_compose(monkeypatch, 1, "", "required variable X is missing a value")
    result = policy.render(_compose_tree(tmp_path), "prod")
    assert result == (
        "combination prod (docker-compose.yml + docker-compose.prod.yml) did not render:"
        " required variable X is missing a value"
    )


def test_a_combination_with_no_service_is_a_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_compose(monkeypatch, 0, '{"services": {}}')
    result = policy.render(_compose_tree(tmp_path), "uat")
    assert (
        result
        == "combination uat (docker-compose.yml + docker-compose.uat.yml) rendered no services"
    )


def test_compose_never_sees_the_callers_own_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("QDRANT_API_KEY", "a-real-key")
    monkeypatch.setenv("REDIS_PASSWORD", "a-real-password")
    monkeypatch.setenv("COMPOSE_PROFILES", "full")
    envs = _fake_compose(monkeypatch, 0, '{"services": {"a": {}}}')
    policy.render(_compose_tree(tmp_path), "dev")
    (env,) = envs
    assert env["QDRANT_API_KEY"] == "ci"  # the dev placeholder, not the caller's key
    assert "REDIS_PASSWORD" not in env or env["REDIS_PASSWORD"] == "ci"
    assert "COMPOSE_PROFILES" not in env
    policy.render(_compose_tree(tmp_path), "base")
    assert "QDRANT_API_KEY" not in envs[1]
    assert "REDIS_PASSWORD" not in envs[1]
