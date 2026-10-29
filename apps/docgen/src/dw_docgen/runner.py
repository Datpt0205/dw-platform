"""Runs one shell command under the containment budget and returns what it said.

The budget has three parts and each stops a different failure:

* `ulimit` in the shell, before the command runs, bounds CPU, address space,
  open files, forks and file size. A memory bomb or a fork bomb dies here.
* A wall-clock deadline in the parent, then `SIGKILL` to the whole process
  group. A script that sleeps forever, or one whose child outlives it, dies
  here.
* An output cap on the way back. A script printing an endless stream cannot
  make the caller allocate without bound.

The limits are set by the shell rather than by `preexec_fn` on purpose. This
service answers HTTP, so the process running it has threads, and `preexec_fn`
runs arbitrary Python between `fork` and `exec` — documented as unsafe with
threads, and the failure is a hang rather than an error. `ulimit` is applied by
the child shell itself, after `exec`, so no such window exists. It is also
irreversible: a process without privilege cannot raise a limit it has lowered,
so the command it prefixes cannot undo it.

Combined output goes to a temporary file rather than a pipe: a pipe makes the
parent's memory the limit, and the parent is the trusted side. That file lives
under the service's own scratch directory on the sandbox tmpfs, because the
container's root filesystem is read-only and there is no `/tmp` to fall back to.
It is unlinked as it is created, so the command whose output it holds has no
name to reach it by.

With sessions isolated (ADR 0025) the command runs under the session's own uid
with `umask 077`, and afterwards everything of that uid is killed - not only the
process group, which `setsid` leaves - and what it left in the shared temporary
directories is purged, so its uid can be handed to another tenant clean.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from dw_docgen import identity
from dw_docgen.settings import DocgenSettings

logger = logging.getLogger(__name__)

# The shell reports a signalled child as 128 + signal number; SIGKILL is 9.
SIGKILL_EXIT_CODE = 137
# Distinct from anything a document script would plausibly return, so "the
# sandbox refused to run unprotected" is never read as "the script failed".
LIMITS_UNAVAILABLE_EXIT_CODE = 97

# How many SIGKILL rounds a process group gets before the request gives up on
# it. Ten covers a fork bomb with room to spare - each round strictly shrinks
# the group once `ulimit -u` is saturated - while capping the worst case at
# half a second, which a caller does not notice and a wedged process cannot
# extend.
_KILL_ROUNDS = 10
# Long enough for the kernel to reap what the last round killed, short enough
# that ten of them are not a pause.
_KILL_ROUND_SECONDS = 0.05


@dataclass(frozen=True)
class CommandResult:
    output: str
    exit_code: int | None
    truncated: bool
    timed_out: bool


def limit_preamble(settings: DocgenSettings) -> str:
    """The shell prefix that caps the command, or `""` where it cannot apply.

    Fails closed: if any limit cannot be set the command never runs. A sandbox
    that silently drops its own containment is worse than one that errors,
    because the error is visible and the drop is not.
    """
    if not settings.enforce_limits:
        return ""
    limits = " && ".join(
        (
            f"ulimit -t {settings.cpu_seconds}",
            f"ulimit -v {settings.address_space_mb * 1024}",  # ulimit -v counts kilobytes
            f"ulimit -n {settings.max_open_files}",
            f"ulimit -u {settings.max_processes}",
            f"ulimit -f {settings.max_file_bytes // 512}",  # ulimit -f counts 512-byte blocks
            "ulimit -c 0",
        )
    )
    refusal = (
        "echo 'sandbox: resource limits unavailable, refusing to run' >&2; "
        f"exit {LIMITS_UNAVAILABLE_EXIT_CODE}"
    )
    return f"{{ {limits}; }} || {{ {refusal}; }}\n"


def run_command(
    command: str,
    *,
    cwd: Path,
    sink_dir: Path,
    settings: DocgenSettings,
    timeout_seconds: int,
    uid: int | None,
) -> CommandResult:
    """Execute `command` with `cwd` as its working directory, under `uid`.

    `uid` is None only where sessions are not isolated; it has no default, so a
    caller states which it is.
    """
    who = identity.child_identity(uid)
    with tempfile.TemporaryFile(dir=sink_dir) as sink:
        # A shell is what this service exists to offer. The boundary is the
        # container it runs in, not the absence of one.
        process = subprocess.Popen(  # nosec B602
            limit_preamble(settings) + command,
            shell=True,
            cwd=str(cwd),
            stdout=sink,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=_child_environment(cwd),
            # `executable` picks the shell that runs the command string; on
            # Windows there is none to pick and `cmd.exe` is used, which is a
            # tests-only path.
            executable=settings.shell_path if sys.platform != "win32" else None,
            # POSIX: its own session, so the whole tree can be killed by group.
            start_new_session=sys.platform != "win32",
            user=who.user,
            group=who.group,
            extra_groups=who.extra_groups,
            # Nothing a session writes outside its 0700 directory is readable
            # by another uid; -1 is Popen's "leave it".
            umask=0o077 if uid is not None else -1,
        )
        group = _process_group(process)
        timed_out = False
        try:
            exit_code: int | None = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = SIGKILL_EXIT_CODE
        finally:
            # Unconditionally, not only on timeout. A command that RETURNS can
            # still leave children behind - `cmd &` is one line, and a fork bomb
            # exits 0 while its descendants keep running. Those survivors
            # outlive the session, hold the container's process budget and make
            # every later command fail with "Resource temporarily unavailable".
            # Measured, not theorised: it is what the image tests hit first.
            if uid is None:
                _kill_group(group, process)
            else:
                _kill_uid(uid, process, settings)
        output, truncated = _read_capped(sink, settings.max_output_bytes)

    if timed_out:
        output += f"\n[killed after {timeout_seconds}s]"
    return CommandResult(
        output=output, exit_code=exit_code, truncated=truncated, timed_out=timed_out
    )


def _child_environment(cwd: Path) -> dict[str, str]:
    """A deliberately bare environment.

    The parent's environment is not inherited: it is how a service token or a
    connection string would reach code the model wrote. What remains is what an
    interpreter needs to start and find its own working directory.
    """
    keep = ("PATH", "LANG", "LC_ALL", "PYTHONPATH", "SYSTEMROOT")
    env = {name: os.environ[name] for name in keep if name in os.environ}
    env["PWD"] = str(cwd)
    # `HOME` and `TMPDIR` point at the session, not at a directory every session
    # shares. LibreOffice writes a user profile under `HOME` on first run and
    # brandkit resolves its global profile store from it; both would otherwise
    # be one customer's state left where the next session looks.
    env["HOME"] = str(cwd)
    env["TMPDIR"] = str(cwd)
    # Nothing reads the sandbox's stdout progressively, and a buffered traceback
    # that never flushes is a bug report nobody receives.
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _process_group(process: subprocess.Popen[bytes]) -> int | None:
    """The command's process group, read before it can exit.

    Read up front because after `wait()` reaps the leader its id is free to be
    reused, and killing a recycled group would kill something else.
    """
    if sys.platform == "win32":
        # No process groups to read; `_kill_group` falls back to the leader.
        return None
    try:
        return os.getpgid(process.pid)
    except OSError:
        # Already gone. Nothing to signal, and nothing it could have started.
        return None


def _killpg_until_empty(group: int) -> bool:
    """SIGKILL the group until nothing is left in it. True if it emptied.

    One `killpg` is not enough and the reason is a race, not a missing flag. The
    kernel walks the group delivering the signal; a member that forks while the
    walk is still ahead of it produces a child the walk never reaches. Against a
    fork bomb that walk never wins in a single pass, and the survivors then sit
    on the container's process budget for good — which is how
    `test_a_fork_bomb_leaves_the_container_usable` passed its own assertion
    while every test after it failed with "Resource temporarily unavailable".

    Repeating converges because of the very limit that makes the symptom:
    `ulimit -u` is already saturated by then, so the survivors cannot fork
    either. Each round strictly shrinks the group.

    Bounded, because a request must answer even against something unkillable —
    a process wedged in uninterruptible sleep does not die for SIGKILL, and
    looping on it forever would trade one stuck session for a stuck service.
    """
    for _ in range(_KILL_ROUNDS):
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            # The group is empty. The ordinary case on the first round: the
            # command finished and started nothing that outlived it.
            return True
        except OSError:
            logger.warning("could not kill sandbox process group %s", group, exc_info=True)
            return False
        time.sleep(_KILL_ROUND_SECONDS)
    return False


def _kill_group(group: int | None, process: subprocess.Popen[bytes]) -> None:
    """Kill the command and everything it started.

    `soffice` daemonises and a backgrounded job outlives the shell that started
    it, so signalling only the leader leaves the next session a busy container.
    """
    if sys.platform == "win32":
        # No process groups to signal; the shell dies and its children are
        # the developer's problem, because this path is tests only.
        process.kill()
    elif group is not None and not _killpg_until_empty(group):
        logger.error("sandbox process group %s outlived %d SIGKILL rounds", group, _KILL_ROUNDS)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.error("sandbox process %s survived SIGKILL", process.pid)


def _kill_uid(uid: int, process: subprocess.Popen[bytes], settings: DocgenSettings) -> None:
    """Kill every process of the session's uid, then purge what it left.

    Neither failure stops the reply: the command already ran. Both leave the
    uid unusable instead - a survivor keeps it out of the pool and refuses the
    session's next request, and a failed purge is retried before the uid is
    handed out, which skips it while it still fails.
    """
    # The shell itself is this process's child: killed, it stays a zombie until
    # it is waited for, and a zombie is still a process of the uid. Only a shell
    # still running (the timeout) needs this first signal; one that returned was
    # reaped by `wait`, and `kill_all` spawns nothing when no process is left -
    # the ordinary case, and a helper process saved on every command.
    if process.poll() is None:
        identity.signal_all(uid)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.error("sandbox process %s survived SIGKILL", process.pid)
    if not identity.kill_all(uid):
        logger.error("uid %s outlived %d SIGKILL rounds", uid, identity.KILL_ROUNDS)
    try:
        identity.purge(uid, settings.shared_temp_dirs)
    except OSError:
        logger.error("could not purge uid %s after its command", uid, exc_info=True)


def _read_capped(sink: IO[bytes], limit: int) -> tuple[str, bool]:
    """Read at most `limit` bytes of combined output, decoded leniently."""
    sink.seek(0)
    data = sink.read(limit + 1)
    truncated = len(data) > limit
    return data[:limit].decode("utf-8", errors="replace"), truncated
