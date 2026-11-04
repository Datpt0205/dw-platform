"""code-sandbox 01: gVisor `runsc` (systrap) under a rootless Docker engine, measured.

    bash tests/spike/sandbox/setup_rootless.sh
    uv run python tests/spike/sandbox/harness.py measure --where ci     # results-ci.json
    DW_SANDBOX_SPIKE=1 uv run python -m pytest tests/spike/sandbox      # R1.2-R1.4

`measure` writes the ten rows of R1.1 (ticket 01 step 2) and, on GitHub
Actions, prints one `::notice` per row, so the table is readable from the
check run's public annotations. The tests in `test_runsc_spike.py` hold the
thresholds of steps 3 to 5. Both call the procedures below, which own every
threshold, so a number in the table and a verdict of a test cannot disagree.

The Docker CLI is driven through `subprocess`, never an SDK. Every measured
container runs the image setup_rootless.sh built, with CAPPED_FLAGS (the
`py-small` profile of ADR-0119 (Proposed) decision 3), carries the label
`dw.spike=1` and is removed after its measurement. Nothing here is collected
by CI's pytest runs: `tests/spike` is outside `testpaths`.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import platform
import queue
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Any

IMAGE = "dw-sandbox-spike:1"
RUNTIME = "runsc-dw"
LABEL = "dw.spike=1"

# The `py-small` profile, ADR-0119 (Proposed) decision 3. Ticket 01 step 7
# mutates three of these; keep each flag on its own line.
CAPPED_FLAGS: tuple[str, ...] = (
    "--runtime=runsc-dw",
    "--network=none",
    "--cpus=0.5",
    "--memory=256m",
    "--memory-swap=256m",
    "--pids-limit=64",
    "--read-only",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges:true",
    "--user=10001",
    "--tmpfs=/work:rw,noexec,nosuid,nodev,size=64m",
    "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m",
    f"--label={LABEL}",
)

# Not a cap of the profile under test: what row 2 measures beside it. gVisor
# enforces RLIMIT_NPROC inside the guest, so the guest stops at 64 processes
# while a roomier host pids.max stays a backstop for the sandbox's own threads
# (measured in a local rig on both engines; CI records it in row 2).
PIDS_REMEDY_FLAGS: tuple[str, ...] = (
    *("--pids-limit=512" if flag.startswith("--pids-limit") else flag for flag in CAPPED_FLAGS),
    "--ulimit=nproc=64:64",
)

# Thresholds, ticket 01 steps 3 and 4.
CPU_RATIO_MAX = 0.55
BUSY_SECONDS = 10
MEMORY_CAP_BYTES = 268_435_456
MEMORY_PEAK_MAX = MEMORY_CAP_BYTES * 1.05
MEMORY_BOMB_MIB = 512
MEMORY_STEP_MIB = 16
MEMORY_DEADLINE_SECONDS = 30
PIDS_CAP = 64
FORK_BOMB_SECONDS = 10
PROBES = 10
PROBE_DEADLINE_SECONDS = 5.0
INFO_DEADLINE_SECONDS = 2.0
REAPER_GRACE_SECONDS = 10
LATENCY_RUNS = 20
PANDAS_ROWS = 100_000
PY_SMALL_TIMEOUT_SECONDS = 30
STDIN_PAYLOAD_BYTES = 1 << 20

PASS = "đạt"
FAIL = "không đạt"
NOT_APPLICABLE = "không áp dụng"

ROOTFUL_SOCKET = "/var/run/docker.sock"
CGROUP_ROOT = Path("/sys/fs/cgroup")
DELEGATED = ("cpu", "cpuset", "io", "memory", "pids")


class HarnessError(RuntimeError):
    """A measurement could not be taken; the message says what the engine answered."""


# ----------------------------------------------------------------- engine --


def engine_host() -> str | None:
    """The engine under test: DW_SPIKE_DOCKER_HOST (the rootful fallback sets it
    to /var/run/docker.sock), else the rootless engine's per-user socket that
    setup_rootless.sh creates. None (Docker's own default) where there is no
    uid, so a Windows checkout asks Docker Desktop, which has no `runsc-dw`."""
    explicit = os.environ.get("DW_SPIKE_DOCKER_HOST")
    if explicit:
        return explicit
    getuid: Callable[[], int] | None = getattr(os, "getuid", None)
    return None if getuid is None else f"unix:///run/user/{getuid()}/docker.sock"


@dataclass(frozen=True)
class Engine:
    host: str | None

    @classmethod
    def under_test(cls) -> Engine:
        return cls(engine_host())

    def cli(self, *args: str) -> list[str]:
        return ["docker", *(["--host", self.host] if self.host else []), *args]

    def run(
        self, *args: str, stdin: bytes | None = None, timeout: float = 120
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            self.cli(*args), input=stdin, capture_output=True, timeout=timeout, check=False
        )

    def ok(self, *args: str, timeout: float = 120) -> str:
        done = self.run(*args, timeout=timeout)
        if done.returncode != 0:
            raise HarnessError(f"docker {' '.join(args[:3])}: {_tail(done.stderr)}")
        return done.stdout.decode(errors="replace")

    def info(self) -> dict[str, Any]:
        found: dict[str, Any] = json.loads(self.ok("info", "--format", "{{json .}}", timeout=30))
        return found

    def missing_runtime(self) -> str | None:
        """Why this engine cannot run the spike, or None when it lists `runsc-dw`."""
        try:
            runtimes = self.info().get("Runtimes") or {}
        except (HarnessError, OSError, subprocess.TimeoutExpired, ValueError) as error:
            return f"no engine at {self.host or 'the default context'}: {error}"
        if RUNTIME not in runtimes:
            return (
                f"the engine at {self.host or 'the default context'} has no runtime {RUNTIME} "
                f"(it has {sorted(runtimes)}); run tests/spike/sandbox/setup_rootless.sh"
            )
        return None

    def is_rootless(self) -> bool:
        """The engine reports `name=rootless`; False when it cannot be asked."""
        try:
            options = self.info().get("SecurityOptions") or []
        except (HarnessError, OSError, subprocess.TimeoutExpired, ValueError):
            return False
        return any("name=rootless" in option for option in options)

    def inspect(self, ref: str) -> dict[str, Any]:
        found: list[dict[str, Any]] = json.loads(self.ok("inspect", ref, timeout=30))
        return found[0]

    def labelled(self, *, running_only: bool = False) -> list[str]:
        args = ["ps", "-q", "--no-trunc", "--filter", f"label={LABEL}"]
        if not running_only:
            args.insert(1, "-a")
        return self.ok(*args, timeout=30).split()

    def remove(self, *refs: str) -> None:
        if refs:
            self.run("rm", "-f", *refs, timeout=60)

    def reap(self) -> list[str]:
        """Removes every `dw.spike=1` container; returns the ids it removed."""
        found = self.labelled()
        self.remove(*found)
        return found

    def try_reap(self) -> None:
        """reap() where an engine that does not answer must not stop the caller:
        the table still gets its ten rows, each saying what failed."""
        with contextlib.suppress(HarnessError, OSError, subprocess.TimeoutExpired):
            self.reap()


def _tail(data: bytes | str | None, limit: int = 600) -> str:
    text = data.decode(errors="replace") if isinstance(data, bytes) else (data or "")
    text = text.strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def _name(purpose: str) -> str:
    return f"dw-spike-{purpose}-{uuid.uuid4().hex[:8]}"


def run_once(
    engine: Engine,
    script: str,
    *,
    flags: Sequence[str] = CAPPED_FLAGS,
    extra: Sequence[str] = (),
    stdin: bytes | None = None,
    timeout: float = 120,
) -> tuple[subprocess.CompletedProcess[bytes], float]:
    """`docker run --rm` of one script; the result and its wall seconds."""
    args = ["run", "--rm", *(["-i"] if stdin is not None else []), *flags, *extra]
    started = time.perf_counter()
    done = engine.run(*args, IMAGE, "python", "-c", script, stdin=stdin, timeout=timeout)
    return done, time.perf_counter() - started


# -------------------------------------------------------------- live runs --


class Live:
    """A container started with `docker run -i`, held open on its stdin so its
    cgroup can be read after its result and before it is removed (ADR-0119
    (Proposed) decision 5)."""

    def __init__(self, engine: Engine, script: str, flags: Sequence[str], purpose: str) -> None:
        self.engine = engine
        self.name = _name(purpose)
        self._dir = tempfile.mkdtemp(prefix="dw-spike-")
        self._cidfile = Path(self._dir) / "cid"
        self._stderr: IO[bytes] = (Path(self._dir) / "stderr").open("w+b")
        self._lines: queue.Queue[str | None] = queue.Queue()
        self.proc = subprocess.Popen(
            engine.cli(
                "run",
                "-i",
                f"--cidfile={self._cidfile}",
                f"--name={self.name}",
                *flags,
                IMAGE,
                "python",
                "-c",
                script,
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
        )
        threading.Thread(target=self._read, daemon=True).start()
        self.id = self._await_id()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            self._lines.put(raw.decode(errors="replace").rstrip("\n"))
        self._lines.put(None)

    def _await_id(self, timeout: float = 60) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with contextlib.suppress(OSError):
                text = self._cidfile.read_text().strip()
                if text:
                    return text
            if self.proc.poll() is not None:
                raise HarnessError(f"docker run exited {self.proc.returncode}: {self.stderr()}")
            time.sleep(0.05)
        raise HarnessError(f"no container id after {timeout} s: {self.stderr()}")

    def stderr(self) -> str:
        self._stderr.flush()
        self._stderr.seek(0)
        return _tail(self._stderr.read())

    def expect(self, prefix: str, timeout: float) -> str:
        """The first stdout line starting with `prefix`; HarnessError on exit or timeout."""
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise HarnessError(f"no {prefix!r} from {self.name} in {timeout} s")
            try:
                line = self._lines.get(timeout=left)
            except queue.Empty:
                continue
            if line is None:
                self._lines.put(None)
                code = self.proc.wait()
                raise HarnessError(
                    f"{self.name} ended before {prefix!r} (exit {code}): {self.stderr()}"
                )
            if line.startswith(prefix):
                return line

    def send(self, data: bytes) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def close_stdin(self) -> None:
        with contextlib.suppress(OSError):
            assert self.proc.stdin is not None
            self.proc.stdin.close()

    def wait(self, timeout: float) -> int | None:
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def cgroup(self) -> Path | None:
        return cgroup_dir(self.engine, self.id)

    def destroy(self) -> None:
        self.close_stdin()
        self.engine.remove(self.id)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.proc.wait(timeout=30)
        if self.proc.poll() is None:
            self.proc.kill()
        self._stderr.close()
        shutil.rmtree(self._dir, ignore_errors=True)


@contextlib.contextmanager
def live(
    engine: Engine, script: str, *, purpose: str, flags: Sequence[str] = CAPPED_FLAGS
) -> Iterator[Live]:
    container = Live(engine, script, flags, purpose)
    try:
        yield container
    finally:
        container.destroy()


# ----------------------------------------------------------------- cgroup --


def cgroup_dir(engine: Engine, container_id: str) -> Path | None:
    """The container's cgroup on the host: where its init process (for runsc,
    the sandbox) lives, when that path names the container; else a directory
    named for the container anywhere under the hierarchy."""
    pid = engine.inspect(container_id).get("State", {}).get("Pid") or 0
    if pid:
        with contextlib.suppress(OSError):
            for line in Path(f"/proc/{pid}/cgroup").read_text().splitlines():
                if line.startswith("0::"):
                    found = CGROUP_ROOT / line[3:].lstrip("/")
                    if container_id in str(found) and found.is_dir():
                        return found
    for parent, dirs, _ in os.walk(CGROUP_ROOT):
        for name in dirs:
            if container_id in name:
                return Path(parent) / name
    return None


def init_pid(engine: Engine, container_id: str) -> int:
    """The host pid of the container's init: for runsc, the sandbox process."""
    return int(engine.inspect(container_id).get("State", {}).get("Pid") or 0)


def sandbox_cgroup(engine: Engine, container_id: str) -> str:
    """Where the container's init process sits, whatever it is named: the
    evidence when cgroup_dir finds nothing (runsc with --ignore-cgroups leaves
    the sandbox in the engine's own cgroup)."""
    pid = init_pid(engine, container_id)
    try:
        return Path(f"/proc/{pid}/cgroup").read_text().strip()
    except OSError as error:
        return f"pid {pid}: {error}"


def tree_cpu_usec(root: int) -> int:
    """Host CPU time of a process and every descendant (the runsc sandbox and
    its systrap stubs), from /proc/<pid>/stat: the measurement when there is no
    container cgroup to read cpu.stat from."""
    parents: dict[int, int] = {}
    times: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        fields = stat[stat.rindex(")") + 2 :].split()
        pid = int(entry.name)
        parents[pid] = int(fields[1])
        times[pid] = sum(int(value) for value in fields[11:15])
    tree = {root}
    grew = True
    while grew:
        grew = False
        for pid, parent in parents.items():
            if parent in tree and pid not in tree:
                tree.add(pid)
                grew = True
    ticks = sum(times.get(pid, 0) for pid in tree)
    return ticks * 1_000_000 // os.sysconf("SC_CLK_TCK")


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _int(path: Path) -> int | None:
    text = _read(path)
    return int(text) if text is not None and text.isdigit() else None


@dataclass
class CgroupReading:
    path: str
    memory_peak: int | None
    memory_current: int | None
    memory_max: str | None
    usage_usec: int | None
    cpu_max: str | None
    pids_current: int | None
    pids_peak: int | None
    pids_max: str | None


def read_cgroup(path: Path) -> CgroupReading:
    usage = None
    stat = _read(path / "cpu.stat")
    if stat:
        for line in stat.splitlines():
            key, _, value = line.partition(" ")
            if key == "usage_usec" and value.isdigit():
                usage = int(value)
    return CgroupReading(
        path=str(path),
        memory_peak=_int(path / "memory.peak"),
        memory_current=_int(path / "memory.current"),
        memory_max=_read(path / "memory.max"),
        usage_usec=usage,
        cpu_max=_read(path / "cpu.max"),
        pids_current=_int(path / "pids.current"),
        pids_peak=_int(path / "pids.peak"),
        pids_max=_read(path / "pids.max"),
    )


class Sampler:
    """Polls a cgroup until stopped, keeping the highest memory.peak and
    pids.peak seen: a container killed for memory takes its cgroup with it, so
    the last reading before that is the measurement."""

    def __init__(self, path: Path | None, interval: float = 0.1) -> None:
        self.path = path
        self.interval = interval
        self.memory_peak: int | None = None
        self.pids_peak: int | None = None
        self.pids_current_max: int | None = None
        self.last: CgroupReading | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> Sampler:
        if self.path is not None:
            self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        assert self.path is not None
        while not self._stop.is_set():
            reading = read_cgroup(self.path)
            if reading.memory_peak is not None or reading.usage_usec is not None:
                self.last = reading
                self.memory_peak = _max(self.memory_peak, reading.memory_peak)
                self.pids_peak = _max(self.pids_peak, reading.pids_peak)
                self.pids_current_max = _max(self.pids_current_max, reading.pids_current)
            self._stop.wait(self.interval)


def _max(a: int | None, b: int | None) -> int | None:
    return b if a is None else a if b is None else max(a, b)


# ------------------------------------------------------- container scripts --

CPU_BURN = f"""
import os, sys, time
print("start", flush=True)
end = time.monotonic() + {BUSY_SECONDS}
children = []
for _ in range(2):
    pid = os.fork()
    if pid == 0:
        while time.monotonic() < end:
            pass
        os._exit(0)
    children.append(pid)
for pid in children:
    os.waitpid(pid, 0)
print("done", flush=True)
sys.stdin.read()
"""

MEMORY_BOMB = f"""
import sys, time
blocks = []
print("start", flush=True)
for step in range({MEMORY_BOMB_MIB // MEMORY_STEP_MIB}):
    blocks.append(bytearray(b"\\x01") * ({MEMORY_STEP_MIB} << 20))
    print(f"allocated {{(step + 1) * {MEMORY_STEP_MIB}}}", flush=True)
    time.sleep(0.05)
print("survived", flush=True)
sys.stdin.read()
"""

# Counts processes from /proc inside the guest every 0.5 s while a shell fork
# bomb runs, printing each sample as it is taken: a bomb the caps do not stop
# can take the sandbox down with it (measured: systrap could not clone another
# stub thread and the sentry panicked, exit 2), and the samples taken until
# then are the measurement. Then it kills every process of the uid (pid 1 is
# spared), reaps what was reparented to it, and holds on stdin so the host can
# read pids.peak before removal. The bomb gets none of our stdio.
FORK_BOMB = """
import os, signal, subprocess, sys, time

def count():
    return sum(1 for name in os.listdir("/proc") if name.isdigit())

def reap():
    while True:
        try:
            if os.waitpid(-1, os.WNOHANG)[0] == 0:
                return
        except ChildProcessError:
            return

quiet = subprocess.DEVNULL
bomb = ["/bin/sh", "-c", "b() {{ b | b & }}; b"]
subprocess.Popen(bomb, stdin=quiet, stdout=quiet, stderr=quiet)
print("start", flush=True)
end = time.monotonic() + {seconds}
while time.monotonic() < end:
    print("sample", count(), flush=True)
    time.sleep(0.5)
for _ in range(200):
    try:
        os.kill(-1, signal.SIGKILL)
    except OSError:
        pass
    reap()
    if count() == 1:
        break
    time.sleep(0.05)
print("result", count(), flush=True)
sys.stdin.read()
"""

HOLD = """
import sys, time
print("ready", flush=True)
time.sleep(300)
"""

ECHO_ONE_LINE = """
import sys
print("ready", flush=True)
line = sys.stdin.readline()
print("echo " + line.strip(), flush=True)
"""

STATS_LOAD = """
import sys, time
block = bytearray(b"\\x01") * (64 << 20)
end = time.monotonic() + 1
while time.monotonic() < end:
    pass
print("ready", flush=True)
sys.stdin.read()
"""

NOEXEC = """
import os, shutil, subprocess
for directory in ("/work", "/tmp"):
    target = os.path.join(directory, "t")
    shutil.copy("/bin/true", target)
    os.chmod(target, 0o755)
    try:
        subprocess.run([target], check=False)
        print(directory, "executed")
    except PermissionError:
        print(directory, "denied")
"""

PANDAS = f"""
import json, time
started = time.perf_counter()
import numpy, pandas
imported = time.perf_counter()
values = numpy.random.default_rng(0).random(({PANDAS_ROWS}, 4))
frame = pandas.DataFrame(values, columns=list("abcd"))
summary = frame.describe()
described = time.perf_counter()
print(json.dumps({{
    "pandas": pandas.__version__,
    "numpy": numpy.__version__,
    "import_s": round(imported - started, 3),
    "describe_s": round(described - imported, 3),
    "count": int(summary.loc["count", "a"]),
}}))
"""

DMESG = """
import subprocess, sys
found = subprocess.run(["dmesg"], capture_output=True, text=True)
print(found.stdout + found.stderr)
print("dmesg-end", flush=True)
sys.stdin.read()
"""


# ------------------------------------------------------------ procedures --


@dataclass
class CpuResult:
    ratio: float
    usage_usec: int
    wall_seconds: float
    source: str
    cgroup: str
    cpu_max: str | None


def measure_cpu(engine: Engine, flags: Sequence[str] = CAPPED_FLAGS) -> CpuResult:
    """Two busy processes for BUSY_SECONDS: host CPU time over wall time (CS1)."""
    with live(engine, CPU_BURN, purpose="cpu", flags=flags) as box:
        box.expect("start", timeout=60)
        path = box.cgroup()
        pid = init_pid(engine, box.id)

        def usage() -> int | None:
            return read_cgroup(path).usage_usec if path else tree_cpu_usec(pid)

        before = usage()
        started = time.monotonic()
        box.expect("done", timeout=BUSY_SECONDS * 6)
        wall = time.monotonic() - started
        after = usage()
        if before is None or after is None:
            raise HarnessError(f"cpu.stat unreadable under {path}")
        return CpuResult(
            ratio=round((after - before) / 1e6 / wall, 3),
            usage_usec=after - before,
            wall_seconds=round(wall, 2),
            source="cgroup cpu.stat" if path else "sandbox process tree: no container cgroup",
            cgroup=str(path) if path else sandbox_cgroup(engine, box.id),
            cpu_max=read_cgroup(path).cpu_max if path else None,
        )


@dataclass
class MemoryResult:
    oom_killed: bool
    exit_code: int | None
    seconds: float
    allocated_mib: int
    peak_bytes: int | None
    memory_max: str | None
    cgroup: str

    @property
    def held(self) -> bool:
        return (
            (self.oom_killed or self.exit_code == 137)
            and self.seconds <= MEMORY_DEADLINE_SECONDS
            and self.peak_bytes is not None
            and self.peak_bytes <= MEMORY_PEAK_MAX
        )


def measure_memory(engine: Engine, flags: Sequence[str] = CAPPED_FLAGS) -> MemoryResult:
    """512 MiB in 16 MiB steps: killed within 30 s, memory.peak within the cap (CS1)."""
    with live(engine, MEMORY_BOMB, purpose="memory", flags=flags) as box:
        box.expect("start", timeout=60)
        started = time.monotonic()
        path = box.cgroup()
        where = str(path) if path else sandbox_cgroup(engine, box.id)
        allocated = 0
        with Sampler(path) as sampler:
            deadline = started + MEMORY_DEADLINE_SECONDS + 15
            while time.monotonic() < deadline:
                try:
                    line = box.expect("", timeout=max(0.1, deadline - time.monotonic()))
                except HarnessError:
                    break
                if line.startswith("allocated "):
                    allocated = int(line.split()[1])
                elif line == "survived":
                    break
            box.wait(timeout=5)
            seconds = time.monotonic() - started
        state = engine.inspect(box.id).get("State", {})
        running = bool(state.get("Running"))
        return MemoryResult(
            oom_killed=bool(state.get("OOMKilled")),
            exit_code=None if running else int(state.get("ExitCode", -1)),
            seconds=round(seconds, 2),
            allocated_mib=allocated,
            peak_bytes=sampler.memory_peak,
            memory_max=sampler.last.memory_max if sampler.last else None,
            cgroup=where,
        )


@dataclass
class ForkBombResult:
    max_inside: int
    samples: list[int]
    after_kill: int | None
    sandbox_exit: int | None
    pids_peak_host: int | None
    pids_current_max_host: int | None
    pids_max_host: str | None
    cgroup: str

    @property
    def held(self) -> bool:
        """Never more than the cap inside, and the sandbox outlived its bomb."""
        return bool(self.samples) and self.max_inside <= PIDS_CAP and self.sandbox_exit is None


def measure_fork_bomb(
    engine: Engine, flags: Sequence[str] = CAPPED_FLAGS, seconds: int = FORK_BOMB_SECONDS
) -> ForkBombResult:
    """A shell fork bomb for `seconds`; processes counted inside the guest every
    0.5 s, and the host cgroup's pids.peak recorded beside them (CS1)."""
    with live(engine, FORK_BOMB.format(seconds=seconds), purpose="forkbomb", flags=flags) as box:
        box.expect("start", timeout=60)
        path = box.cgroup()
        where = str(path) if path else sandbox_cgroup(engine, box.id)
        samples: list[int] = []
        after_kill = None
        with Sampler(path, interval=0.25) as sampler:
            deadline = time.monotonic() + seconds + 60
            with contextlib.suppress(HarnessError):
                while time.monotonic() < deadline:
                    line = box.expect("", timeout=max(0.1, deadline - time.monotonic()))
                    if line.startswith("sample "):
                        samples.append(int(line.split()[1]))
                    elif line.startswith("result "):
                        after_kill = int(line.split()[1])
                        break
        state = engine.inspect(box.id).get("State", {})
        return ForkBombResult(
            max_inside=max(samples or [0]),
            samples=samples,
            after_kill=after_kill,
            sandbox_exit=None if state.get("Running") else int(state.get("ExitCode", -1)),
            pids_peak_host=sampler.pids_peak,
            pids_current_max_host=sampler.pids_current_max,
            pids_max_host=sampler.last.pids_max if sampler.last else None,
            cgroup=where,
        )


@dataclass
class Probe:
    seconds: float
    output: str

    @property
    def ok(self) -> bool:
        return self.output == "1" and self.seconds <= PROBE_DEADLINE_SECONDS


@dataclass
class ServingResult:
    probes: list[Probe]
    info_seconds: float
    memory_bombs_started: int
    fork_bomb_alive_at_end: bool

    @property
    def held(self) -> bool:
        return all(p.ok for p in self.probes) and self.info_seconds <= INFO_DEADLINE_SECONDS


def measure_serving_during_bombs(engine: Engine) -> ServingResult:
    """R1.3: while a fork bomb and back-to-back memory bombs run, a second
    `runsc-dw` container prints 1 every second, ten times; then `docker info`
    answers once the bombs are removed."""
    stop = threading.Event()
    bombs: list[str] = []
    started = 0

    def memory_bombs() -> None:
        nonlocal started
        while not stop.is_set():
            name = _name("membomb")
            bombs.append(name)
            started += 1
            engine.run(
                "run",
                "--rm",
                f"--name={name}",
                *CAPPED_FLAGS,
                IMAGE,
                "python",
                "-c",
                MEMORY_BOMB,
                timeout=MEMORY_DEADLINE_SECONDS + 30,
            )

    seconds = PROBES * 3 + 30
    with live(engine, FORK_BOMB.format(seconds=seconds), purpose="forkbomb-serving") as fork:
        fork.expect("start", timeout=60)
        worker = threading.Thread(target=memory_bombs, daemon=True)
        worker.start()
        time.sleep(2)
        probes: list[Probe] = []
        for _ in range(PROBES):
            tick = time.monotonic()
            try:
                done, wall = run_once(engine, "print(1)", timeout=60)
                probes.append(Probe(round(wall, 3), done.stdout.decode(errors="replace").strip()))
            except subprocess.TimeoutExpired:
                probes.append(Probe(60.0, "timeout"))
            time.sleep(max(0.0, 1 - (time.monotonic() - tick)))
        alive = bool(engine.inspect(fork.id).get("State", {}).get("Running"))
        stop.set()
        engine.remove(*bombs)
    worker.join(timeout=60)
    engine.remove(*bombs)
    began = time.perf_counter()
    engine.run("info", timeout=60)
    return ServingResult(probes, round(time.perf_counter() - began, 3), started, alive)


@dataclass
class RuntimeResult:
    host_config_runtime: str
    dmesg: str

    @property
    def is_gvisor(self) -> bool:
        return "gVisor" in self.dmesg


def measure_runtime(engine: Engine, flags: Sequence[str] = CAPPED_FLAGS) -> RuntimeResult:
    """CS2: what the engine says it ran, and what the kernel inside says it is.
    `HostConfig.Runtime` only repeats the request, so `dmesg` is the evidence."""
    with live(engine, DMESG, purpose="runtime", flags=flags) as box:
        lines: list[str] = []
        while not lines or lines[-1] != "dmesg-end":
            lines.append(box.expect("", timeout=60))
        runtime = str(box.engine.inspect(box.id).get("HostConfig", {}).get("Runtime", ""))
    return RuntimeResult(runtime, "\n".join(lines))


# ------------------------------------------------------------ the ten rows --


@dataclass
class Outcome:
    measured: dict[str, Any]
    unit: str
    status: str
    reason: str


@dataclass
class Row:
    n: int
    item: str
    measured: dict[str, Any]
    unit: str
    status: str
    reason: str


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest rank: with 20 samples, P95 is the 19th smallest."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def row_delegation(engine: Engine) -> Outcome:
    uid = os.getuid()
    path = CGROUP_ROOT / f"user.slice/user-{uid}.slice/user@{uid}.service/cgroup.controllers"
    text = _read(path)
    have = set((text or "").split())
    missing = [c for c in DELEGATED if c not in have]
    return Outcome(
        {"path": str(path), "controllers": text, "missing": missing},
        "controllers",
        PASS if text is not None and not missing else FAIL,
        "all five delegated"
        if text is not None and not missing
        else f"missing {missing}"
        if text is not None
        else f"{path} unreadable",
    )


def row_fork_bomb(engine: Engine) -> Outcome:
    found = measure_fork_bomb(engine)
    died = "" if found.sandbox_exit is None else f"; the sandbox died, exit {found.sandbox_exit}"
    engine.reap()
    remedy = measure_fork_bomb(engine, flags=PIDS_REMEDY_FLAGS)
    return Outcome(
        asdict(found) | {"with_ulimit_nproc_64_and_pids_limit_512": asdict(remedy)},
        "processes counted in the guest's /proc; host pids.peak beside",
        PASS if found.held else FAIL,
        f"at most {found.max_inside} processes inside (cap {PIDS_CAP}){died}; "
        f"host pids.peak {found.pids_peak_host}, gVisor guest tasks are not host processes; "
        f"with --ulimit=nproc=64:64 and --pids-limit=512 at most {remedy.max_inside} inside, "
        + ("the sandbox survived" if remedy.sandbox_exit is None else "the sandbox died"),
    )


def row_stats_vs_cgroup(engine: Engine) -> Outcome:
    with live(engine, STATS_LOAD, purpose="stats") as box:
        box.expect("ready", timeout=60)
        path = box.cgroup()
        stats = json.loads(engine.ok("stats", "--no-stream", "--format", "{{json .}}", box.id))
        reading = read_cgroup(path) if path else None
        where = sandbox_cgroup(engine, box.id)
    measured = {
        "docker_stats_mem_usage": stats.get("MemUsage"),
        "docker_stats_cpu_perc": stats.get("CPUPerc"),
        "docker_stats_pids": stats.get("PIDs"),
        "cgroup": asdict(reading) if reading else None,
        "sandbox_cgroup": where,
    }
    peak = reading.memory_peak if reading else None
    usage = reading.usage_usec if reading else None
    held = peak is not None and usage is not None and peak >= 64 << 20
    return Outcome(
        measured,
        "bytes, usec",
        PASS if held else FAIL,
        f"memory.peak {peak} B holds the 64 MiB the guest touched; usage_usec {usage}"
        if held
        else f"no container cgroup to read: the sandbox sits in {where}"
        if reading is None
        else f"cgroup readings incomplete (memory.peak {peak}, usage_usec {usage})",
    )


def row_stdin_log_driver_none(engine: Engine) -> Outcome:
    payload = os.urandom(STDIN_PAYLOAD_BYTES)
    done, wall = run_once(
        engine,
        "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
        extra=("--log-driver=none",),
        stdin=payload,
    )
    same = done.returncode == 0 and done.stdout == payload
    return Outcome(
        {
            "sent_bytes": len(payload),
            "received_bytes": len(done.stdout),
            "sha256_sent": hashlib.sha256(payload).hexdigest(),
            "sha256_received": hashlib.sha256(done.stdout).hexdigest(),
            "exit_code": done.returncode,
            "seconds": round(wall, 3),
            "stderr": _tail(done.stderr, 300),
        },
        "bytes",
        PASS if same else FAIL,
        "returned intact on stdout"
        if same
        else f"stdout differs from the payload (exit {done.returncode}: {_tail(done.stderr, 200)})",
    )


def row_tmpfs_noexec(engine: Engine) -> Outcome:
    done, _ = run_once(engine, NOEXEC)
    lines = done.stdout.decode(errors="replace").split("\n")
    verdicts = dict(line.split(" ", 1) for line in lines if " " in line)
    denied = done.returncode == 0 and verdicts == {"/work": "denied", "/tmp": "denied"}
    return Outcome(
        {"verdicts": verdicts, "exit_code": done.returncode, "stderr": _tail(done.stderr, 300)},
        "outcome",
        PASS if denied else FAIL,
        "both refused with EACCES"
        if denied
        else f"not refused: {verdicts} (exit {done.returncode}: {_tail(done.stderr, 200)})",
    )


def row_latency(engine: Engine) -> Outcome:
    cold: list[float] = []
    for _ in range(LATENCY_RUNS):
        started = time.perf_counter()
        done = engine.run("run", "--rm", *CAPPED_FLAGS, IMAGE, "true", timeout=60)
        if done.returncode != 0:
            raise HarnessError(f"cold run failed: {_tail(done.stderr)}")
        cold.append((time.perf_counter() - started) * 1000)
    warm: list[float] = []
    for _ in range(LATENCY_RUNS):
        with live(engine, ECHO_ONE_LINE, purpose="warm") as box:
            box.expect("ready", timeout=60)
            started = time.perf_counter()
            box.send(b"ping\n")
            box.expect("echo ping", timeout=30)
            warm.append((time.perf_counter() - started) * 1000)
    measured = {
        "cold_p50_ms": round(statistics.median(cold), 1),
        "cold_p95_ms": round(percentile(cold, 0.95), 1),
        "warm_p50_ms": round(statistics.median(warm), 1),
        "warm_p95_ms": round(percentile(warm, 0.95), 1),
        "runs_each": LATENCY_RUNS,
    }
    return Outcome(
        measured,
        "ms",
        PASS,
        "measured; no threshold in R1.1, the ADR estimated a cold start of 0.5 to 1.5 s",
    )


def row_pandas(engine: Engine) -> Outcome:
    done, wall = run_once(engine, PANDAS, timeout=PY_SMALL_TIMEOUT_SECONDS + 60)
    found: dict[str, Any] = {}
    with contextlib.suppress(ValueError):
        found = json.loads((done.stdout.decode(errors="replace").strip() or "{}").splitlines()[-1])
    found |= {"wall_s": round(wall, 2), "exit_code": done.returncode}
    if done.returncode != 0:
        found["stderr"] = _tail(done.stderr, 400)
    held = (
        done.returncode == 0
        and found.get("count") == PANDAS_ROWS
        and wall <= PY_SMALL_TIMEOUT_SECONDS
    )
    return Outcome(
        found,
        "s",
        PASS if held else FAIL,
        f"done in {wall:.1f} s of the {PY_SMALL_TIMEOUT_SECONDS} s py-small allows"
        if held
        else f"exit {done.returncode} after {wall:.1f} s: {_tail(done.stderr, 200)}",
    )


def runsc_processes() -> list[str]:
    """Host processes whose name or argv[0] is gVisor's (runsc, its gofer and
    sandbox, the sentry binary of the split release layout)."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
            argv0 = (entry / "cmdline").read_bytes().split(b"\0", 1)[0].decode(errors="replace")
        except OSError:
            continue
        names = (comm, os.path.basename(argv0))
        if any("runsc" in name or "gvisor" in name for name in names):
            found.append(f"{entry.name} {comm} {argv0}")
    return found


def row_reaper(engine: Engine) -> Outcome:
    holder = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "hold", "3"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert holder.stdout is not None
    line = holder.stdout.readline().decode(errors="replace").strip()
    if not line.startswith("held "):
        holder.kill()
        raise HarnessError(f"holder did not start its containers: {line}")
    os.kill(holder.pid, signal.SIGKILL)
    holder.wait()
    survivors = engine.labelled(running_only=True)
    started = time.perf_counter()
    engine.remove(*engine.labelled())
    reap_seconds = time.perf_counter() - started
    left = engine.labelled()
    deadline = time.monotonic() + REAPER_GRACE_SECONDS
    processes = runsc_processes()
    while processes and time.monotonic() < deadline:
        time.sleep(0.5)
        processes = runsc_processes()
    clean = not left and not processes
    return Outcome(
        {
            "running_after_kill": len(survivors),
            "reap_seconds": round(reap_seconds, 2),
            "containers_left": left,
            "runsc_processes_after_grace": processes,
            "grace_s": REAPER_GRACE_SECONDS,
        },
        "containers, processes",
        PASS if clean else FAIL,
        f"{len(survivors)} outlived the harness; docker rm -f by label left none, "
        f"and no runsc process after {REAPER_GRACE_SECONDS} s"
        if clean
        else f"left {left} and processes {processes}",
    )


def row_beside_rootful(engine: Engine) -> Outcome:
    rootful = Engine(f"unix://{ROOTFUL_SOCKET}")
    if not Path(ROOTFUL_SOCKET).exists():
        return Outcome({}, "", NOT_APPLICABLE, f"no rootful daemon at {ROOTFUL_SOCKET}")
    if rootful.run("version", timeout=30).returncode != 0:
        return Outcome({}, "", NOT_APPLICABLE, "rootful daemon not reachable by this user")
    labels = engine.inspect(IMAGE).get("Config", {}).get("Labels") or {}
    base = str(labels.get("dw.spike.base", ""))
    rootful.ok("pull", "--quiet", base, timeout=600)
    one = two = ""
    try:
        one = rootful.ok(
            "run",
            "-d",
            "--rm",
            f"--label={LABEL}",
            "--network=none",
            base,
            "python",
            "-c",
            "import time; time.sleep(60)",
        ).strip()
        two = engine.ok(
            "run", "-d", "--rm", *CAPPED_FLAGS, IMAGE, "python", "-c", "import time; time.sleep(60)"
        ).strip()
        both = bool(rootful.inspect(one)["State"]["Running"]) and bool(
            engine.inspect(two)["State"]["Running"]
        )
        rootful_runtime = rootful.inspect(one)["HostConfig"]["Runtime"]
    finally:
        rootful.remove(*[c for c in (one,) if c])
        engine.remove(*[c for c in (two,) if c])
    socket = (engine.host or "").removeprefix("unix://")
    owner = os.stat(socket).st_uid if socket else -1
    rootless = engine.is_rootless()
    held = both and owner not in (0, -1) and rootless
    return Outcome(
        {
            "both_running_at_once": both,
            "rootful_runtime": rootful_runtime,
            "rootless_socket": socket,
            "rootless_socket_owner_uid": owner,
            "rootless_security_option": rootless,
        },
        "",
        PASS if held else FAIL,
        f"both ran at once; the rootless socket belongs to uid {owner}" if held else "see measured",
    )


def row_kvm(engine: Engine) -> Outcome:
    kvm = Path("/dev/kvm")
    exists = kvm.exists()
    usable = exists and os.access(kvm, os.R_OK | os.W_OK)
    return Outcome(
        {"exists": exists, "read_write_for_this_user": usable},
        "",
        NOT_APPLICABLE,
        "recorded only: systrap needs no KVM; on the target host it is an operator's "
        "question (ticket 02)",
    )


# The ten rows of R1.1 in the ticket's order (step 2): the row number is the
# position here, and the item text is the one name of what each row measures.
ROWS: tuple[tuple[str, Callable[[Engine], Outcome]], ...] = (
    ("cgroup v2 delegation to user@<uid>.service", row_delegation),
    ("fork bomb under runsc (--pids-limit=64)", row_fork_bomb),
    (
        "docker stats beside memory.peak and cpu.stat usage_usec, read before removal",
        row_stats_vs_cgroup,
    ),
    ("--log-driver none with stdin: 1 MiB through docker run -i", row_stdin_log_driver_none),
    ("tmpfs noexec: executing a file just written to /work and /tmp", row_tmpfs_noexec),
    (
        "latency: cold (docker run --rm ... true) and warm (stdin into a started container)",
        row_latency,
    ),
    (f"pandas: import and describe() on {PANDAS_ROWS} rows within py-small", row_pandas),
    ("reaper after kill -9 of the harness holding three containers", row_reaper),
    ("rootless engine beside the runner's rootful daemon", row_beside_rootful),
    ("/dev/kvm", row_kvm),
)


def measure_row(engine: Engine, n: int) -> Row:
    """Row `n` (1-based). A measurement that raises is a row that did not pass,
    carrying the error, never a missing row."""
    item, function = ROWS[n - 1]
    try:
        outcome = function(engine)
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        outcome = Outcome({"error": message}, "", FAIL, _tail(message))
    finally:
        engine.try_reap()
    return Row(n, item, outcome.measured, outcome.unit, outcome.status, outcome.reason)


def versions(engine: Engine) -> dict[str, Any]:
    found: dict[str, Any] = {
        "kernel": platform.release(),
        # GitHub's runner image names these variables in mixed case.
        "runner_image": os.environ.get("ImageOS"),  # noqa: SIM112
        "runner_image_version": os.environ.get("ImageVersion"),  # noqa: SIM112
        # 0 where setup_rootless.sh had to lift AppArmor's restriction (its step 2).
        "apparmor_restrict_unprivileged_userns": _read(
            Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
        ),
    }
    with contextlib.suppress(HarnessError, OSError, subprocess.TimeoutExpired, ValueError):
        info = engine.info()
        found["rootless_engine"] = info.get("ServerVersion")
        found["cgroup"] = f"v{info.get('CgroupVersion')} {info.get('CgroupDriver')}"
        runtime = (info.get("Runtimes") or {}).get(RUNTIME) or {}
        path = runtime.get("path")
        # Path and arguments only: the engine also reports runsc's whole feature
        # list, which alone overflows the 4096 characters an annotation keeps.
        found["runtime"] = {"path": path, "runtimeArgs": runtime.get("runtimeArgs")}
        if path:
            found["runsc"] = _tail(
                subprocess.run(
                    [path, "--version"], capture_output=True, timeout=30, check=False
                ).stdout
            )
        image = engine.inspect(IMAGE)
        found["image_id"] = image.get("Id")
        found["image_labels"] = (image.get("Config") or {}).get("Labels")
    with contextlib.suppress(HarnessError, OSError, subprocess.TimeoutExpired, ValueError):
        found["rootful_engine"] = Engine(f"unix://{ROOTFUL_SOCKET}").info().get("ServerVersion")
    return found


def measure(engine: Engine, where: str) -> dict[str, Any]:
    engine.try_reap()
    rows = [measure_row(engine, n) for n in range(1, len(ROWS) + 1)]
    return {
        "where": where,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "versions": versions(engine),
        "rows": [asdict(row) for row in rows],
    }


# ------------------------------------------------------------ annotations --


def workflow_command(kind: str, title: str, message: str) -> str:
    """One GitHub workflow command line (`::notice`, `::error`), escaped as the
    runner requires: % CR LF in the message; also : and , in the title."""

    def data(text: str) -> str:
        return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    def prop(text: str) -> str:
        return data(text).replace(":", "%3A").replace(",", "%2C")

    return f"::{kind} title={prop(title)}::{data(message)}"


def annotate(results: Mapping[str, Any]) -> list[str]:
    """Exactly one notice per row (GitHub keeps ten per step), plus an error
    for each row that did not pass."""
    lines = []
    for row in results["rows"]:
        lines.append(
            workflow_command(
                "notice", f"sandbox-spike R1.1 row {row['n']}", json.dumps(row, ensure_ascii=False)
            )
        )
    for row in results["rows"]:
        if row["status"] == FAIL:
            lines.append(
                workflow_command(
                    "error", f"sandbox-spike R1.1 row {row['n']} failed", row["reason"]
                )
            )
    return lines


# -------------------------------------------------------------------- cli --


def _hold(count: int) -> int:
    """Row 8's victim: starts `count` containers, says so, and waits to be killed."""
    engine = Engine.under_test()
    procs = []
    for _ in range(count):
        proc = subprocess.Popen(
            engine.cli(
                "run", f"--name={_name('hold')}", *CAPPED_FLAGS, IMAGE, "python", "-c", HOLD
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert proc.stdout is not None
        if proc.stdout.readline().decode().strip() != "ready":
            print("failed to start a held container", flush=True)
            return 1
        procs.append(proc)
    print(f"held {len(procs)}", flush=True)
    time.sleep(3600)
    return 0


# GitHub keeps the first 4096 characters of an annotation; the end of a failed
# log is what explains it, so the tail is cut to fit before it is sent.
ANNOTATION_CHARS = 3500


def _annotate_log(title: str, path: Path, lines: int) -> int:
    text = path.read_text(errors="replace") if path.exists() else f"{path} missing"
    tail = "\n".join(text.splitlines()[-lines:])[-ANNOTATION_CHARS:]
    print(workflow_command("error", title, tail))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure", help="the ten rows of R1.1, to results-<where>.json")
    m.add_argument("--where", required=True, help="ci or host")
    m.add_argument("--out", type=Path)
    h = sub.add_parser("hold", help="internal: row 8's harness to be killed")
    h.add_argument("count", type=int)
    a = sub.add_parser("annotate-log", help="a log's tail as one ::error annotation")
    a.add_argument("--title", required=True)
    a.add_argument("--lines", type=int, default=40)
    a.add_argument("path", type=Path)
    sub.add_parser("versions", help="the pins and versions measured, as one ::notice")
    args = parser.parse_args(argv)
    if args.command == "hold":
        return _hold(args.count)
    if args.command == "annotate-log":
        return _annotate_log(args.title, args.path, args.lines)
    if args.command == "versions":
        found = json.dumps(versions(Engine.under_test()), ensure_ascii=False)
        print(workflow_command("notice", "sandbox-spike versions", found))
        return 0
    # The statuses are Vietnamese; a Windows console is cp1252 by default.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    results = measure(Engine.under_test(), args.where)
    out: Path = args.out or Path(f"results-{args.where}.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in results["rows"]:
        print(f"{row['n']:>2} {row['status']:<14} {row['item']}: {row['reason']}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for line in annotate(results):
            print(line, flush=True)
    complete = len(results["rows"]) == len(ROWS) and all(r["status"] for r in results["rows"])
    return 0 if complete else 2


if __name__ == "__main__":
    sys.exit(main())
