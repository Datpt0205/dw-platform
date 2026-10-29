"""Mutation check: break each control, run only the tests that guard it, expect red.

`reviewing-feature-security` asks every ticket to show that each control's test
can fail (failure-modes #3). Writing a fresh script per ticket cost more than
running it, and one of those scripts once silently did not mutate. So the
mutations are data, in a YAML file beside the ticket, and this one runner owns
how they are applied, isolated, verified and reported.

    uv run python scripts/mutate.py .claude/plans/<area>/<feature>/mutations/NN.yaml
    uv run python scripts/mutate.py <spec> --only "dir 0700"   # a subset by name
    uv run python scripts/mutate.py <spec> --jobs 8

The spec:

    images:                      # optional, for `runner: image:<name>`
      docgen:
        image: dw-docgen:local
        target: /app/.venv/lib/python3.12/site-packages/dw_docgen
        port: 8110               # the port the service listens on inside
        health: /health
        url_env: DW_DOCGEN_URL   # what the tests read to find the service
        args: [--read-only, --user, "0:0"]
        command: [uvicorn, dw_docgen.main:create_app, --factory, --host, 0.0.0.0]
    mutations:
      - name: dir 0700 -> 0755   # unique
        file: apps/docgen/src/dw_docgen/workspace.py
        old: "path.chmod(0o700)"     # must occur exactly once
        new: "path.chmod(0o755)"
        tests: [apps/docgen/tests/unit/test_isolation.py::test_x]
        runner: local            # local (default) | linux | image:<name>

How a mutation is isolated, so mutations can run side by side:

* A Python file under a `src/` directory is mutated in a COPY of its package,
  put first on `PYTHONPATH` (ahead of the editable install). Before its tests
  run, the runner asks Python which file it imports and refuses to report
  anything if that is not the copy: a mutation that does not reach the code
  under test proves nothing.
* Any other file (a migration, a config, a template) is mutated in place and
  restored, one at a time, after the parallel batch. A backup is written first;
  a run that finds a leftover backup restores it and stops.
* `runner: image:<name>` mounts the mutated package copy over the installed one
  in a fresh container per mutation, on its own host port, so no image is
  rebuilt for a mutation.
* `runner: linux` runs the tests in a Linux container as uid 1000, for tests a
  Windows machine skips. The container is kept between runs and rebuilt when
  `uv.lock` changes.

Integration tests share one database per package (`TEST_DB`), so anything under
`/integration/` that is not an image test runs serially; everything else runs in
parallel. Every group of tests also runs once unmutated: a control that is red
before any mutation makes every red after it meaningless, and is reported as such.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
BACKUP_SUFFIX = ".mutate-backup"
TEST_TIMEOUT_SECONDS = 600
LINUX_CONTAINER = "dw-mutate-linux"
LINUX_IMAGE = "python:3.12-slim-bookworm"
UV_IMAGE = "ghcr.io/astral-sh/uv:0.11.31"
# Docker on Git for Windows rewrites `/app/...` arguments into Windows paths.
DOCKER_ENV = {**os.environ, "MSYS_NO_PATHCONV": "1"}


@dataclass(frozen=True)
class Image:
    name: str
    image: str
    target: str
    port: int
    health: str
    url_env: str
    args: tuple[str, ...]
    command: tuple[str, ...]


@dataclass(frozen=True)
class Mutation:
    name: str
    file: Path
    old: str
    new: str
    tests: tuple[str, ...]
    runner: str

    @property
    def package(self) -> Path | None:
        """`<...>/src/<package>` for a Python file in a src layout, else None."""
        parts = self.file.relative_to(REPO).parts
        if self.file.suffix != ".py" or "src" not in parts:
            return None
        at = parts.index("src")
        return REPO.joinpath(*parts[: at + 2]) if len(parts) > at + 2 else None

    @property
    def group(self) -> Group:
        return (self.runner, self.tests, self.package)


# What one control run covers: the runner, the tests, and the package overlaid.
Group = tuple[str, tuple[str, ...], Path | None]


def is_serial(group: Group) -> bool:
    """In place (no package to overlay): nothing else may read the file
    meanwhile. Integration tests outside an image share one database."""
    runner, tests, package = group
    if package is None:
        return True
    return not runner.startswith("image:") and any("/integration/" in t for t in tests)


@dataclass
class Outcome:
    label: str
    verdict: str
    caught: bool
    detail: str = ""


@dataclass
class Spec:
    images: dict[str, Image] = field(default_factory=dict)
    mutations: list[Mutation] = field(default_factory=list)


def load(path: Path) -> Spec:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    images = {
        name: Image(
            name=name,
            image=body["image"],
            target=body["target"],
            port=int(body["port"]),
            health=body.get("health", "/health"),
            url_env=body["url_env"],
            args=tuple(str(a) for a in body.get("args", ())),
            command=tuple(str(a) for a in body.get("command", ())),
        )
        for name, body in (raw.get("images") or {}).items()
    }
    mutations = [
        Mutation(
            name=item["name"],
            file=REPO / item["file"],
            old=item["old"],
            new=item["new"],
            tests=tuple(item["tests"]),
            runner=item.get("runner", "local"),
        )
        for item in raw["mutations"]
    ]
    names = [m.name for m in mutations]
    if len(names) != len(set(names)):
        raise SystemExit("mutation names must be unique")
    for mutation in mutations:
        _check_applies(mutation)
        if mutation.runner.startswith("image:"):
            image = images.get(mutation.runner.removeprefix("image:"))
            if image is None:
                raise SystemExit(f"{mutation.name}: no image {mutation.runner!r} in the spec")
            if mutation.package is None or mutation.package.name != Path(image.target).name:
                raise SystemExit(f"{mutation.name}: its package does not match {image.target}")
    return Spec(images=images, mutations=mutations)


def _check_applies(mutation: Mutation) -> None:
    text = mutation.file.read_text(encoding="utf-8")
    count = text.count(mutation.old)
    if count != 1:
        raise SystemExit(
            f"{mutation.name}: `old` occurs {count} times in {mutation.file}, not once"
        )
    if mutation.old == mutation.new:
        raise SystemExit(f"{mutation.name}: `old` and `new` are the same")


# ------------------------------------------------------------ overlays --


def overlay(mutation: Mutation | None, package: Path, scratch: Path) -> Path:
    """A copy of `package` under `scratch`, with `mutation` applied if given."""
    copy = scratch / package.name
    shutil.copytree(package, copy, ignore=shutil.ignore_patterns("__pycache__"))
    if mutation is not None:
        target = copy / mutation.file.relative_to(package)
        text = target.read_text(encoding="utf-8")
        target.write_text(text.replace(mutation.old, mutation.new), encoding="utf-8", newline="\n")
    return scratch


def _imports_from(scratch: Path, package: Path) -> bool:
    """Whether Python with `scratch` first on its path imports the copy."""
    probe = subprocess.run(
        [sys.executable, "-c", f"import {package.name}; print({package.name}.__file__)"],
        env={**os.environ, "PYTHONPATH": str(scratch)},
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(probe.stdout.strip()).resolve().is_relative_to(scratch.resolve())


# ------------------------------------------------------------- runners --


def run_local(tests: tuple[str, ...], pythonpath: Path | None) -> int:
    env = dict(os.environ)
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    return _pytest([sys.executable, "-m", "pytest"], tests, env)


def _pytest(prefix: list[str], tests: tuple[str, ...], env: dict[str, str]) -> int:
    try:
        return subprocess.run(
            [*prefix, "-q", "-x", "-p", "no:cacheprovider", "-m", "", *tests],
            cwd=REPO,
            env=env,
            capture_output=True,
            timeout=TEST_TIMEOUT_SECONDS,
            check=False,
        ).returncode
    except subprocess.TimeoutExpired:
        return 124  # a hang is a failure the guarded code caused


class LinuxBox:
    """One long-lived Linux container with the locked dependencies installed."""

    def __init__(self) -> None:
        self._ready = False
        self._lock = threading.Lock()

    def ensure(self) -> None:
        with self._lock:
            if self._ready:
                return
            digest = hashlib.sha256((REPO / "uv.lock").read_bytes()).hexdigest()[:12]
            current = _docker(
                "inspect",
                "-f",
                '{{ index .Config.Labels "uv-lock" }}',
                LINUX_CONTAINER,
                check=False,
            )
            if current.strip() != digest:
                _docker("rm", "-f", LINUX_CONTAINER, check=False)
                _docker(
                    "run",
                    "-d",
                    "--name",
                    LINUX_CONTAINER,
                    "--label",
                    f"uv-lock={digest}",
                    "-v",
                    f"{REPO}:/repo:ro",
                    LINUX_IMAGE,
                    "sleep",
                    "infinity",
                )
                _docker("cp", _uv_binary(), f"{LINUX_CONTAINER}:/usr/local/bin/uv")
                _docker(
                    "exec",
                    "-w",
                    "/repo",
                    "-e",
                    "UV_PROJECT_ENVIRONMENT=/venv",
                    "-e",
                    "UV_CACHE_DIR=/uv-cache",
                    "-e",
                    "UV_LINK_MODE=copy",
                    LINUX_CONTAINER,
                    "uv",
                    "sync",
                    "--frozen",
                    "--all-packages",
                    "--no-install-workspace",
                )
                _docker("exec", LINUX_CONTAINER, "chmod", "-R", "a+rwX", "/venv")
            else:
                _docker("start", LINUX_CONTAINER)
            self._ready = True

    def run(self, tests: tuple[str, ...], scratch: Path | None, slot: str) -> int:
        self.ensure()
        sources = sorted(
            f"/repo/{p.relative_to(REPO).as_posix()}"
            for p in [*REPO.glob("packages/python/*/src"), *REPO.glob("apps/*/src")]
        )
        path = sources
        if scratch is not None:
            remote = f"/mut/{slot}"
            _docker("exec", LINUX_CONTAINER, "rm", "-rf", remote)
            _docker("exec", LINUX_CONTAINER, "mkdir", "-p", remote)
            for child in scratch.iterdir():
                _docker("cp", str(child), f"{LINUX_CONTAINER}:{remote}/{child.name}")
            _docker("exec", LINUX_CONTAINER, "chmod", "-R", "a+rX", "/mut")
            path = [remote, *sources]
        prefix = [
            "docker",
            "exec",
            "-u",
            "1000:1000",
            "-w",
            "/repo",
            "-e",
            "HOME=/tmp",
            "-e",
            f"PYTHONPATH={':'.join(path)}",
            LINUX_CONTAINER,
            "/venv/bin/python",
            "-m",
            "pytest",
        ]
        return _pytest(prefix, tests, DOCKER_ENV)


def _uv_binary() -> str:
    """The pinned uv, copied out of its image, so the box needs no network for it."""
    cached = Path(tempfile.gettempdir()) / "dw-mutate-uv"
    if not cached.exists():
        holder = _docker("create", UV_IMAGE, "/uv").strip()
        try:
            _docker("cp", f"{holder}:/uv", str(cached))
        finally:
            _docker("rm", holder, check=False)
    return str(cached)


def run_image(image: Image, tests: tuple[str, ...], scratch: Path, host_port: int) -> int:
    name = f"dw-mutate-{image.name}-{host_port}"
    _docker("rm", "-f", name, check=False)
    _docker(
        "run",
        "-d",
        "--name",
        name,
        *image.args,
        "-p",
        f"127.0.0.1:{host_port}:{image.port}",
        "-v",
        f"{scratch / Path(image.target).name}:{image.target}:ro",
        image.image,
        *image.command,
    )
    try:
        url = f"http://127.0.0.1:{host_port}"
        deadline = time.monotonic() + 60
        while True:
            try:
                urllib.request.urlopen(url + image.health, timeout=2)
                break
            except OSError:
                if time.monotonic() > deadline:
                    return -1
                time.sleep(0.5)
        return _pytest([sys.executable, "-m", "pytest"], tests, {**os.environ, image.url_env: url})
    finally:
        _docker("rm", "-f", name, check=False)


def _docker(*args: str, check: bool = True) -> str:
    done = subprocess.run(
        ["docker", *args], env=DOCKER_ENV, capture_output=True, text=True, check=False
    )
    if check and done.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args[:3])} failed: {done.stderr.strip()[-400:]}")
    return done.stdout


# ------------------------------------------------------------ the check --


class Check:
    def __init__(self, spec: Spec) -> None:
        self.spec = spec
        self.linux = LinuxBox()
        self._ports = iter(range(18200, 18999))
        self._port_lock = threading.Lock()

    def _port(self) -> int:
        with self._port_lock:
            return next(self._ports)

    def execute(self, mutation: Mutation | None, group: Group, slot: str) -> int:
        runner, tests, package = group
        with tempfile.TemporaryDirectory(prefix="mutate-") as tmp:
            scratch = overlay(mutation, package, Path(tmp)) if package is not None else None
            local = runner == "local"
            if (
                scratch is not None
                and package is not None
                and local
                and not _imports_from(scratch, package)
            ):
                return -2
            if runner == "local":
                return run_local(tests, scratch)
            if runner == "linux":
                return self.linux.run(tests, scratch, slot)
            image = self.spec.images[runner.removeprefix("image:")]
            if scratch is None:
                raise SystemExit(f"runner {runner} needs a package to mount")
            return run_image(image, tests, scratch, self._port())

    def control(self, indexed: tuple[int, Group]) -> Outcome:
        index, group = indexed
        code = self.execute(None, group, slot=f"control-{index}")
        label = f"control {group[0]} ({len(group[1])} tests)"
        return Outcome(label, "green" if code == 0 else f"RED ({code})", caught=code == 0)

    def mutate(self, mutation: Mutation, index: int) -> Outcome:
        if mutation.package is None:
            code = self._in_place(mutation)
        else:
            code = self.execute(mutation, mutation.group, slot=str(index))
        if code == -2:
            return Outcome(mutation.name, "DID NOT REACH THE CODE (import is not the copy)", False)
        if code == -1:
            return Outcome(mutation.name, "service did not start", False)
        if code == 0:
            return Outcome(mutation.name, "NOT CAUGHT", False)
        return Outcome(mutation.name, "red (caught)" if code != 124 else "red (timeout)", True)

    def _in_place(self, mutation: Mutation) -> int:
        backup = mutation.file.with_name(mutation.file.name + BACKUP_SUFFIX)
        original = mutation.file.read_bytes()
        backup.write_bytes(original)
        try:
            mutation.file.write_text(
                original.decode("utf-8").replace(mutation.old, mutation.new),
                encoding="utf-8",
                newline="\n",
            )
            if mutation.runner == "linux":
                return self.linux.run(mutation.tests, None, "in-place")
            return run_local(mutation.tests, None)
        finally:
            mutation.file.write_bytes(original)
            backup.unlink()


def _restore_leftovers() -> None:
    leftovers = [p for p in REPO.rglob(f"*{BACKUP_SUFFIX}") if ".venv" not in p.parts]
    for backup in leftovers:
        backup.replace(backup.with_name(backup.name.removesuffix(BACKUP_SUFFIX)))
    if leftovers:
        names = ", ".join(str(p.relative_to(REPO)) for p in leftovers)
        raise SystemExit(f"restored files an interrupted run left mutated: {names}; check git diff")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", type=Path)
    parser.add_argument(
        "--only", action="append", default=[], help="run mutations whose name contains this"
    )
    parser.add_argument("--jobs", type=int, default=max(2, (os.cpu_count() or 4) // 2))
    args = parser.parse_args()

    _restore_leftovers()
    spec = load(args.spec)
    chosen = [m for m in spec.mutations if not args.only or any(o in m.name for o in args.only)]
    if not chosen:
        raise SystemExit("no mutation matches")
    check = Check(spec)

    groups = list(enumerate(sorted({m.group for m in chosen}, key=str)))
    parallel = [m for m in chosen if not is_serial(m.group)]
    serial = [m for m in chosen if is_serial(m.group)]

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        controls = list(pool.map(check.control, [g for g in groups if not is_serial(g[1])]))
        controls += [check.control(g) for g in groups if is_serial(g[1])]
        results = list(pool.map(lambda pair: check.mutate(pair[1], pair[0]), enumerate(parallel)))
    results += [check.mutate(m, 1000 + i) for i, m in enumerate(serial)]

    for outcome in controls:
        print(f"{'ok ' if outcome.caught else 'BAD'} {outcome.label:44} -> {outcome.verdict}")
    width = max(len(m.name) for m in chosen)
    for outcome in results:
        print(f"{'ok ' if outcome.caught else 'BAD'} {outcome.label:{width}} -> {outcome.verdict}")
    caught = sum(o.caught for o in results)
    controls_green = all(c.caught for c in controls)
    print(
        f"{caught}/{len(results)} caught, controls {'green' if controls_green else 'RED'}, "
        f"{time.monotonic() - started:.0f}s with {args.jobs} jobs"
    )
    sys.exit(0 if caught == len(results) and controls_green else 1)


if __name__ == "__main__":
    main()
