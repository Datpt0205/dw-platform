"""The compose policy a new service meets (studio-skeleton R8).

Usage: uv run python scripts/verify_compose_policy.py [--root TREE] [--base-repo REPO]
Exit 0 clean, 1 with one line per finding.

Every rule is read from the model compose itself renders, never from the YAML
text: `docker compose ... --profile '*' config --format json` for each of five
combinations (the base file alone, then with each of the uat, prod, host and dev
overlays). An overlay can add a service, a port or a network, and a rule that
read only the base file could not see what the overlay added (failure-modes #0).
A combination that does not render, or renders no service, is a finding in its
own right: a check that saw nothing must not read as a check that passed.

Each rule applies to every service not named in that rule's `EXCEPTIONS`.
`EXCEPTIONS` holds exactly what violated the rule at `BASE_SHA`, the commit
before this check existed; that set is computed here, by running the same rules
on the files `git archive BASE_SHA` returns, so the table cannot quietly grow.
Three kinds of finding, each line starting with its kind:

    violation <service> <rule>             a violation with no exception line
    stale-exception <service> <rule>       an exception for a service that no
                                           longer exists or no longer violates
    exception-needs-adr <service> <rule>   an exception the base commit does not
                                           justify, without an Accepted ADR that
                                           names the service and the rule in
                                           backticks

A new service therefore lands hardened, on a network of its own, pinned, with
no published port outside the dev overlay, with a profile of its own and wired
into CI - or with an Accepted ADR that says why not.

`--root` points the rules at another tree (the planted-defect tests run on a
copy); the base set is always read from `--base-repo`, by default the repository
this script sits in, which holds `BASE_SHA`.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, NamedTuple, cast

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# The parent of this check's first commit on main: what existed before the rule.
# Moving it forward re-bases every exception on newer files, so it moves only
# with a review that says why.
BASE_SHA = "b6f84334b22578ab06a1ed1255962de89217fca5"

COMPOSE_DIR = "infra/compose"
CI_FILE = ".github/workflows/ci.yml"
ENV_FILE = ".env.example"
ADR_DIR = "docs/adr"
# What the base tree needs to render and to be judged by the same rules.
BASE_PATHS = (COMPOSE_DIR, "infra/docker", CI_FILE, ENV_FILE)

# `:?` variables the overlays demand. dev: the variables the "Compose profiles
# validate" step of ci.yml sets for the same overlay; host: its three hostnames.
DEV_PLACEHOLDERS = {
    "QDRANT_API_KEY": "ci",
    "REDIS_PASSWORD": "ci",
    "KC_PUBLIC_HOSTNAME": "http://localhost:8686",
    "DW_KEYCLOAK_ISSUER": "http://localhost:8686/realms/dw",
    "DW_PUBLIC_WEB_URL": "http://localhost:23000",
    "NEXT_PUBLIC_API_BASE_URL": "http://localhost:28000",
    "NEXT_PUBLIC_CHAT_BASE_URL": "http://localhost:28100",
}
HOST_PLACEHOLDERS = {
    "DW_WEB_HOST": "web.invalid",
    "DW_API_HOST": "api.invalid",
    "DW_AUTH_HOST": "auth.invalid",
}


class Combination(NamedTuple):
    overlays: tuple[str, ...]
    placeholders: Mapping[str, str]


BASE_FILE = "docker-compose.yml"
COMBINATIONS: dict[str, Combination] = {
    "base": Combination((), {}),
    "uat": Combination(("docker-compose.uat.yml",), {}),
    "prod": Combination(("docker-compose.prod.yml",), {}),
    "host": Combination(("docker-compose.host.yml",), HOST_PLACEHOLDERS),
    "dev": Combination(("docker-compose.dev.yml",), DEV_PLACEHOLDERS),
}
# The only combination whose services may publish a port (R8.4).
PORTS_ALLOWED_IN = "dev"
# Where `deploy.resources.limits.memory` is required, each on its own (R8.5).
# Compose refuses a `mem_limit` or `pids_limit` that differs from the deploy
# limit (measured on Compose v5.6.0, 5/11/2026: "can't set distinct values"),
# so an overlay that sizes a service sets `memory` and `pids` there, and its
# `mem_limit` too when the size differs from the base file's.
DEPLOYED = ("uat", "prod")


class Waiver(NamedTuple):
    reason: str
    # A path under docs/adr/ of an Accepted ADR naming the service and the rule
    # in backticks. Required only for a pair the base commit did not violate.
    adr: str | None = None


PREDATES = "có trước luật, 23/10/2026"
UNPINNED_FROM = "FROM chưa ghim ở commit nền, ngoài runtime-hardening:R8.3"


def _waived(*services: str, reason: str = PREDATES) -> dict[str, str | Waiver]:
    return dict.fromkeys(services, reason)


# rule -> {service: reason}. Exactly the violations at BASE_SHA; a line outside
# that set needs a Waiver with an Accepted ADR (R8.10), and a line that no
# longer matches a violation is reported stale (R8.9).
EXCEPTIONS: dict[str, dict[str, str | Waiver]] = {
    "dw-internal": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "clickhouse",
        "docgen-gateway",
        "keycloak",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "qdrant",
        "s3",
        "s3-setup",
        "valkey",
        "web",
        "worker",
    ),
    "internal-network": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "caddy",
        "clickhouse",
        "docgen",
        "docgen-gateway",
        "keycloak",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "qdrant",
        "s3",
        "s3-setup",
        "valkey",
        "web",
        "worker",
    ),
    "digest": _waived(
        "api",
        "docgen",
        "docgen-gateway",
        "migrate",
        "web",
        "worker",
        reason=UNPINNED_FROM,
    ),
    "ports": _waived(
        "alertmanager",
        "api",
        "caddy",
        "docgen-gateway",
        "keycloak",
        "langfuse-web",
        "postgres",
        "prometheus",
        "qdrant",
        "s3",
        "valkey",
        "web",
    ),
    "healthcheck": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "caddy",
        "docgen",
        "docgen-gateway",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres-exporter",
        "prometheus",
        "s3-setup",
        "web",
        "worker",
    ),
    "read_only": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "clickhouse",
        "keycloak",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "qdrant",
        "s3",
        "s3-setup",
        "valkey",
        "web",
        "worker",
    ),
    "cap_drop": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "clickhouse",
        "keycloak",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "qdrant",
        "s3",
        "s3-setup",
        "valkey",
        "web",
        "worker",
    ),
    "no-new-privileges": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "clickhouse",
        "keycloak",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "qdrant",
        "s3",
        "s3-setup",
        "valkey",
        "web",
        "worker",
    ),
    "init": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "caddy",
        "clickhouse",
        "docgen-gateway",
        "keycloak",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "qdrant",
        "s3",
        "s3-setup",
        "valkey",
        "web",
        "worker",
    ),
    "user": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "caddy",
        "clickhouse",
        "docgen",
        "keycloak",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "qdrant",
        "s3",
        "s3-setup",
        "valkey",
        "web",
        "worker",
    ),
    "mem_limit": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "caddy",
        "clickhouse",
        "docgen-gateway",
        "keycloak",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "qdrant",
        "s3",
        "s3-setup",
        "valkey",
        "web",
        "worker",
    ),
    "pids_limit": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "caddy",
        "clickhouse",
        "docgen-gateway",
        "keycloak",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "qdrant",
        "s3",
        "s3-setup",
        "valkey",
        "web",
        "worker",
    ),
    "deploy-resources": _waived(
        "alertmanager",
        "alertmanager-config",
        "caddy",
        "clickhouse",
        "docgen",
        "docgen-gateway",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres-exporter",
        "prometheus",
        "s3-setup",
    ),
    "cap_add": _waived(
        "caddy",
        "docgen",
    ),
    "profile": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "caddy",
        "clickhouse",
        "docgen",
        "docgen-gateway",
        "keycloak",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "qdrant",
        "s3",
        "s3-setup",
        "valkey",
        "web",
        "worker",
    ),
    "ci-config": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "caddy",
        "clickhouse",
        "docgen",
        "docgen-gateway",
        "keycloak",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "qdrant",
        "s3",
        "s3-setup",
        "valkey",
        "web",
        "worker",
    ),
    "ci-smoke": _waived(
        "alertmanager",
        "alertmanager-config",
        "api",
        "caddy",
        "clickhouse",
        "docgen",
        "docgen-gateway",
        "keycloak",
        "langfuse-valkey",
        "langfuse-web",
        "langfuse-worker",
        "mailpit",
        "migrate",
        "postgres",
        "postgres-exporter",
        "prometheus",
        "qdrant",
        "s3",
        "s3-setup",
        "valkey",
        "web",
        "worker",
    ),
}

# service -> the services it may share a network with (R8.2). A line is
# reviewed in the ticket that adds the service it names.
CALLERS: dict[str, frozenset[str]] = {}


# --------------------------------------------------------------- the model --

Spec = dict[str, Any]
Model = dict[str, Any]


@dataclass(frozen=True)
class Ci:
    """What the rules read from ci.yml: the `docker compose` command lines, and
    the trivy step's image list and whether it still scans the pinned pulls."""

    commands: tuple[tuple[str, ...], ...]
    trivy_images: frozenset[str]
    trivy_scans_pinned_pulls: bool


@dataclass(frozen=True)
class Rendered:
    models: Mapping[str, Model]
    ci: Ci

    def services(self) -> set[str]:
        return {name for model in self.models.values() for name in model.get("services", {})}

    def appearances(self, service: str) -> Iterator[tuple[str, Model, Spec]]:
        for combo, model in self.models.items():
            spec = model.get("services", {}).get(service)
            if spec is not None:
                yield combo, model, spec


def _shell_line_tokens(text: str) -> Iterator[tuple[str, ...]]:
    """Each logical shell line (backslash continuations joined), as tokens."""
    for line in text.replace("\\\n", " ").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        tokens: list[str] = []
        for raw in stripped.replace('"', " ").replace("'", " ").split():
            tokens.extend(raw.split("=", 1) if raw.startswith("--profile=") else [raw])
        yield tuple(tokens)


def _is_compose(tokens: tuple[str, ...]) -> bool:
    return any(a == "docker" and b == "compose" for a, b in pairwise(tokens))


def parse_ci(text: str) -> Ci:
    commands = tuple(t for t in _shell_line_tokens(text) if _is_compose(t))
    images: set[str] = set()
    pinned = False
    workflow = yaml.safe_load(text) or {}
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            run = step.get("run") or ""
            if "trivy image" not in run:
                continue
            for listed in re.findall(r"for image in ([^;\n]+);", run):
                images.update(listed.split())
            pinned = pinned or any(
                "grep" in line and "@sha256:" in line and f"{COMPOSE_DIR}/*.yml" in line
                for line in run.splitlines()
            )
    return Ci(commands, frozenset(images), pinned)


# ------------------------------------------------------------------- rules --

Rule = Callable[[Rendered, str], bool]
"""True when the service violates the rule."""

_PIN_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def _pulled_pin_pattern() -> re.Pattern[str]:
    """`verify_invariants.py` owns what a pinned pulled image looks like (a
    version tag and its digest); this reads its pattern rather than a copy."""
    spec = importlib.util.spec_from_file_location(
        "_verify_invariants", Path(__file__).resolve().parent / "verify_invariants.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("scripts/verify_invariants.py is not importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(re.Pattern[str], module._PINNED)


_PULLED_PINNED = _pulled_pin_pattern()


def _each(violates: Callable[[Model, str, Spec], bool], combos: tuple[str, ...] = ()) -> Rule:
    """A rule held in every combination the service appears in (or the named ones)."""

    def rule(rendered: Rendered, service: str) -> bool:
        return any(
            violates(model, service, spec)
            for combo, model, spec in rendered.appearances(service)
            if not combos or combo in combos
        )

    return rule


def _networks(spec: Spec) -> list[str]:
    return list((spec.get("networks") or {}).keys())


def _network_name(model: Model, key: str) -> str:
    """The network docker creates, so an alias of dw-internal is still dw-internal."""
    return str((model.get("networks", {}).get(key) or {}).get("name") or key)


def _on_dw_internal(model: Model, _service: str, spec: Spec) -> bool:
    target = _network_name(model, "dw-internal")
    return any(_network_name(model, key) == target for key in _networks(spec))


def _network_not_private(model: Model, service: str, spec: Spec) -> bool:
    allowed = CALLERS.get(service, frozenset())
    if not _networks(spec) and not spec.get("network_mode"):
        # Compose renders `default` here; a model without it was not rendered.
        return True
    for key in _networks(spec):
        if (model.get("networks", {}).get(key) or {}).get("internal") is not True:
            return True
        name = _network_name(model, key)
        members = {
            other
            for other, other_spec in model.get("services", {}).items()
            if other != service
            and any(_network_name(model, k) == name for k in _networks(other_spec))
        }
        if members - allowed:
            return True
    return False


def _from_images(dockerfile: str) -> list[str]:
    """The pulled image of every FROM line: not an earlier stage, not scratch,
    with a global ARG's default substituted."""
    args: dict[str, str] = {}
    stages: set[str] = set()
    images: list[str] = []
    seen_from = False
    for line in dockerfile.replace("\\\n", " ").splitlines():
        words = line.split()
        if not words:
            continue
        keyword = words[0].upper()
        if keyword == "ARG" and not seen_from and len(words) > 1:
            name, _, default = words[1].partition("=")
            args[name] = default
        if keyword != "FROM":
            continue
        seen_from = True
        operands = [w for w in words[1:] if not w.startswith("--")]
        if not operands:
            images.append("")
            continue
        image = re.sub(r"\$\{?(\w+)\}?", lambda m: args.get(m.group(1), m.group(0)), operands[0])
        earlier_stage = image.lower() in stages
        if len(operands) >= 3 and operands[1].upper() == "AS":
            stages.add(operands[2].lower())
        if image.lower() == "scratch" or earlier_stage:
            continue
        images.append(image)
    return images


def _dockerfile_text(build: Spec) -> str | None:
    if build.get("dockerfile_inline"):
        return str(build["dockerfile_inline"])
    context = str(build.get("context") or "")
    if "://" in context or context.startswith("git@"):
        return None
    path = Path(context) / str(build.get("dockerfile") or "Dockerfile")
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _unpinned(_model: Model, _service: str, spec: Spec) -> bool:
    build = spec.get("build")
    if build is None:
        return not _PULLED_PINNED.match(str(spec.get("image") or ""))
    text = _dockerfile_text(build)
    if text is None:
        return True
    images = _from_images(text)
    return not images or not all(_PIN_DIGEST.search(image) for image in images)


def _publishes_ports(_model: Model, _service: str, spec: Spec) -> bool:
    return bool(spec.get("ports"))


def _no_healthcheck(_model: Model, _service: str, spec: Spec) -> bool:
    check = spec.get("healthcheck") or {}
    test = check.get("test") or []
    return not check or bool(check.get("disable")) or test in (["NONE"], "NONE") or not test


def _is_root(_model: Model, _service: str, spec: Spec) -> bool:
    user = str(spec.get("user") or "").strip()
    return user.split(":", 1)[0] in ("", "0", "root")


def _mounts_docker_socket(_model: Model, _service: str, spec: Spec) -> bool:
    for volume in spec.get("volumes") or []:
        ends = (
            (volume.get("source"), volume.get("target")) if isinstance(volume, dict) else (volume,)
        )
        if any("docker.sock" in str(end or "") for end in ends):
            return True
    return False


def _no_deploy_memory(rendered: Rendered, service: str) -> bool:
    for combo in DEPLOYED:
        spec = (rendered.models.get(combo) or {}).get("services", {}).get(service)
        memory = (((spec or {}).get("deploy") or {}).get("resources") or {}).get("limits") or {}
        if not memory.get("memory"):
            return True
    return False


def _profile_pair(tokens: tuple[str, ...], service: str) -> bool:
    return any(a == "--profile" and b == service for a, b in pairwise(tokens))


def _no_ci_config(rendered: Rendered, service: str) -> bool:
    return not any(
        _profile_pair(t, service) and "config" in t and "-q" in t for t in rendered.ci.commands
    )


def _waits_for(tokens: tuple[str, ...], service: str) -> bool:
    if "up" not in tokens or "--wait" not in tokens or not _profile_pair(tokens, service):
        return False
    up = tokens.index("up")
    return "--wait" in tokens[up:] and any(
        token == service and tokens[i - 1] != "--profile"
        for i, token in enumerate(tokens)
        if i > up
    )


def _no_ci_smoke(rendered: Rendered, service: str) -> bool:
    return not any(_waits_for(t, service) for t in rendered.ci.commands)


def _not_scanned(rendered: Rendered, service: str) -> bool:
    for _combo, _model, spec in rendered.appearances(service):
        if spec.get("build") is not None:
            if str(spec.get("image") or "") not in rendered.ci.trivy_images:
                return True
        elif not rendered.ci.trivy_scans_pinned_pulls:
            return True
    return False


RULES: dict[str, Rule] = {
    "dw-internal": _each(_on_dw_internal),
    "internal-network": _each(_network_not_private),
    "digest": _each(_unpinned),
    "ports": _each(_publishes_ports, tuple(c for c in COMBINATIONS if c != PORTS_ALLOWED_IN)),
    "healthcheck": _each(_no_healthcheck),
    "read_only": _each(lambda _m, _n, s: s.get("read_only") is not True),
    "cap_drop": _each(
        lambda _m, _n, s: "ALL" not in [str(c).upper() for c in s.get("cap_drop") or []]
    ),
    "no-new-privileges": _each(
        lambda _m, _n, s: "no-new-privileges:true" not in (s.get("security_opt") or [])
    ),
    "init": _each(lambda _m, _n, s: s.get("init") is not True),
    "user": _each(_is_root),
    "mem_limit": _each(lambda _m, _n, s: not s.get("mem_limit")),
    "pids_limit": _each(
        lambda _m, _n, s: not (isinstance(s.get("pids_limit"), int) and s["pids_limit"] > 0)
    ),
    "deploy-resources": _no_deploy_memory,
    "network_mode": _each(lambda _m, _n, s: bool(s.get("network_mode"))),
    "privileged": _each(lambda _m, _n, s: s.get("privileged") is True),
    "cap_add": _each(lambda _m, _n, s: bool(s.get("cap_add"))),
    "pid-host": _each(lambda _m, _n, s: s.get("pid") == "host"),
    "ipc-host": _each(lambda _m, _n, s: s.get("ipc") == "host"),
    "docker-socket": _each(_mounts_docker_socket),
    "profile": _each(lambda _m, n, s: n not in (s.get("profiles") or [])),
    "ci-config": _no_ci_config,
    "ci-smoke": _no_ci_smoke,
    "ci-trivy": _not_scanned,
}


def violations(rendered: Rendered) -> set[tuple[str, str]]:
    return {
        (service, name)
        for service in rendered.services()
        for name, rule in RULES.items()
        if rule(rendered, service)
    }


# ---------------------------------------------------------- the judgement --

_STATUS = re.compile(r"^status:\s*[\"']?(\w+)", re.M)


def adr_admits(root: Path, adr: str | None, service: str, rule: str) -> bool:
    """An Accepted ADR under docs/adr/ whose body names both in backticks.
    A substring does not count: `user` and `init` are in almost every ADR."""
    if not adr:
        return False
    adr_dir = (root / ADR_DIR).resolve()
    path = (root / adr).resolve()
    if adr_dir not in path.parents or not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False
    _, front, body = [*text.split("---", 2), "", ""][:3]
    status = _STATUS.search(front)
    return (
        status is not None
        and status.group(1) == "Accepted"
        and f"`{service}`" in body
        and f"`{rule}`" in body
    )


def judge(
    current: set[tuple[str, str]],
    base: set[tuple[str, str]],
    exceptions: Mapping[str, Mapping[str, str | Waiver]],
    admits: Callable[[str | None, str, str], bool],
) -> list[str]:
    findings = [
        f"violation {service} {rule}"
        for service, rule in current
        if service not in exceptions.get(rule, {})
    ]
    for rule, waived in exceptions.items():
        if rule not in RULES:
            findings.extend(f"unknown-rule {service} {rule}" for service in waived)
            continue
        for service, waiver in waived.items():
            if (service, rule) not in current:
                findings.append(f"stale-exception {service} {rule}")
            elif (service, rule) not in base:
                adr = waiver.adr if isinstance(waiver, Waiver) else None
                if not admits(adr, service, rule):
                    findings.append(f"exception-needs-adr {service} {rule}")
    return sorted(findings)


# --------------------------------------------------------------- rendering --

_INTERPOLATED = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")


def _hermetic_env(root: Path, placeholders: Mapping[str, str]) -> dict[str, str]:
    """The caller's environment without anything compose would interpolate, so
    a developer's own keys never shape (or leak into) the model judged."""
    names = set(
        _INTERPOLATED.findall(
            "".join(p.read_text(encoding="utf-8") for p in (root / COMPOSE_DIR).glob("*.yml"))
        )
    )
    env_example = root / ENV_FILE
    if env_example.is_file():
        names |= set(
            re.findall(
                r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", env_example.read_text(encoding="utf-8"), re.M
            )
        )
    env = {k: v for k, v in os.environ.items() if k not in names and not k.startswith("COMPOSE_")}
    return {**env, **placeholders}


def render(root: Path, combo: str) -> Model | str:
    """The model compose renders, or why there is none."""
    combination = COMBINATIONS[combo]
    files = [BASE_FILE, *combination.overlays]
    command = ["docker", "compose", "--env-file", str(root / ENV_FILE)]
    for name in files:
        command += ["-f", str(root / COMPOSE_DIR / name)]
    command += ["--profile", "*", "config", "--format", "json"]
    label = " + ".join(files)
    try:
        done = subprocess.run(
            command,
            cwd=root,
            env=_hermetic_env(root, combination.placeholders),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"combination {combo} ({label}) did not render: {error}"
    if done.returncode != 0:
        why = (done.stderr.strip().splitlines() or ["no output"])[-1]
        return f"combination {combo} ({label}) did not render: {why}"
    model = cast(Model, json.loads(done.stdout))
    if not model.get("services"):
        return f"combination {combo} ({label}) rendered no services"
    return model


def render_tree(root: Path) -> Rendered | list[str]:
    with ThreadPoolExecutor(max_workers=len(COMBINATIONS)) as pool:
        results = dict(
            zip(COMBINATIONS, pool.map(lambda c: render(root, c), COMBINATIONS), strict=True)
        )
    failures = [r for r in results.values() if isinstance(r, str)]
    if failures:
        return failures
    ci = parse_ci((root / CI_FILE).read_text(encoding="utf-8"))
    return Rendered({c: cast(Model, m) for c, m in results.items()}, ci)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)


def extract_base(repo: Path, into: Path) -> str | None:
    """The base commit's files under `into`, or why they could not be read."""
    if _git(repo, "cat-file", "-e", f"{BASE_SHA}^{{commit}}").returncode != 0:
        return (
            f"BASE_SHA {BASE_SHA} is not in {repo}; the check needs the full history"
            " (the CI job checks out with fetch-depth: 0)"
        )
    archive = _git(repo, "archive", "--format=tar", BASE_SHA, "--", *BASE_PATHS)
    if archive.returncode != 0:
        return f"git archive {BASE_SHA} failed: {archive.stderr.decode(errors='replace').strip()}"
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(into, filter="data")
    return None


def main(argv: list[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--root", type=Path, default=REPO_ROOT, help="the tree whose files are judged"
    )
    parser.add_argument(
        "--base-repo", type=Path, default=REPO_ROOT, help="the repository holding BASE_SHA"
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    with tempfile.TemporaryDirectory(prefix="compose-policy-base-") as scratch:
        base_root = Path(scratch)
        missing = extract_base(args.base_repo.resolve(), base_root)
        if missing:
            print(missing)
            return 1
        with ThreadPoolExecutor(max_workers=2) as pool:
            current_future = pool.submit(render_tree, root)
            base_future = pool.submit(render_tree, base_root)
            current, base = current_future.result(), base_future.result()
        if isinstance(base, list):
            print(*(f"{line} at BASE_SHA {BASE_SHA}" for line in base), sep="\n")
            return 1
        if isinstance(current, list):
            print(*current, sep="\n")
            return 1
        base_violations = violations(base)
    found = violations(current)
    findings = judge(
        found,
        base_violations,
        EXCEPTIONS,
        lambda adr, service, rule: adr_admits(root, adr, service, rule),
    )
    for line in findings:
        print(line)
    if findings:
        print(
            "\nA new service meets every rule, or its exception line names an Accepted"
            " ADR under docs/adr/ that names the service and the rule in backticks."
        )
        return 1
    waived = sum(len(v) for v in EXCEPTIONS.values())
    print(
        f"ok: {len(current.services())} services in {len(COMBINATIONS)} combinations,"
        f" {len(RULES)} rules, {waived} exceptions, each a violation at {BASE_SHA[:7]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
