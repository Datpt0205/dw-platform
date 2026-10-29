"""The uid a session's shell runs as, and how nothing of it outlives a command.

ADR 0025: every session's shell runs under a uid of its own from a fixed pool,
so the kernel, not this service, keeps one tenant's drafts from another. Two
facts make a uid safe to hand to the next session, and this module owns both:

* no process of it is alive. `kill -9 -1` run under the uid reaches every
  process the uid owns, including one that `setsid` moved out of the command's
  process group, where a group kill never looks;
* nothing it wrote outside its session directory is left. `/tmp`, `/dev/shm`
  and `/dev/mqueue` are world-writable, and SysV IPC objects are not files at
  all, so each is purged of the uid's entries.

Everything here runs from the service, which holds `SETUID`/`SETGID` for exactly
this. A command started under another uid holds no capability: changing from
uid 0 to a non-zero uid clears them, measured on the image (`CapEff` 0).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Ten rounds of 50ms: what `runner` gives a process group, for the same reason.
# Each round strictly shrinks what is left once `ulimit -u` is saturated, and a
# process wedged in uninterruptible sleep must not stall the request forever.
KILL_ROUNDS = 10
_KILL_ROUND_SECONDS = 0.05

_PROC = Path("/proc")


@dataclass(frozen=True)
class ChildIdentity:
    """Who a child process starts as: `Popen`'s `user`, `group` and `extra_groups`.

    Applied by CPython's `_posixsubprocess` between fork and exec in C, so this
    is not `preexec_fn` and is safe from a threaded server. All None - `Popen`'s
    defaults - means "as this process".
    """

    user: int | None = None
    group: int | None = None
    extra_groups: list[int] | None = None


def child_identity(uid: int | None) -> ChildIdentity:
    """Start under `uid` with no supplementary group; unchanged for None.

    Also unchanged when `uid` is already ours: `setgroups` would need
    `CAP_SETGID` for no change, which a test runner does not have.
    """
    if uid is None or (hasattr(os, "geteuid") and os.geteuid() == uid):
        return ChildIdentity()
    return ChildIdentity(user=uid, group=uid, extra_groups=[])


def run_as(uid: int, argv: list[str]) -> int:
    """Run `argv` under `uid` with an empty environment; return its exit code."""
    who = child_identity(uid)
    completed = subprocess.run(
        argv,
        env={"PATH": "/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
        user=who.user,
        group=who.group,
        extra_groups=who.extra_groups,
    )
    return completed.returncode


def process_owners() -> set[int]:
    """The uid of every process alive in this container, zombies included.

    Empty where there is no `/proc` (Windows, unit tests only): there is
    nothing to look at there, and nothing runs under a pool uid either.
    """
    owners: set[int] = set()
    if not _PROC.is_dir():
        return owners
    for entry in _PROC.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            owners.add(entry.stat().st_uid)
        except FileNotFoundError:
            continue  # exited between the listing and the stat
    return owners


def kill_all(uid: int) -> bool:
    """SIGKILL every process of `uid` until none is left. True if none is.

    The helper that sends the signal runs under `uid` itself, so `-1` means
    "every process this uid may signal" - exactly the uid's own, never the
    service's - and the kernel spares the sender. It is gone by the time the
    next round looks, because `run_as` waits for it.
    """
    for _ in range(KILL_ROUNDS):
        if uid not in process_owners():
            return True
        signal_all(uid)
        time.sleep(_KILL_ROUND_SECONDS)
    return uid not in process_owners()


def signal_all(uid: int) -> None:
    """One SIGKILL to every process of `uid`, without waiting to see them go."""
    run_as(uid, ["/bin/bash", "-c", "kill -9 -1"])


def purge(uid: int, temp_dirs: Iterable[str]) -> None:
    """Remove what `uid` left outside its session directory. Raises `OSError`.

    Raising rather than logging is the point: the caller decides whether a uid
    that could not be cleaned is handed out, and the answer is no.
    """
    for directory in temp_dirs:
        _purge_directory(uid, Path(directory))
    _purge_ipc(uid)


def _purge_directory(uid: int, directory: Path) -> None:
    try:
        entries = list(os.scandir(directory))
    except FileNotFoundError:
        return  # not every host has `/dev/mqueue`; nothing can be left in it
    for entry in entries:
        if entry.stat(follow_symlinks=False).st_uid != uid:
            continue
        if entry.is_dir(follow_symlinks=False):
            shutil.rmtree(entry.path)
        else:
            os.unlink(entry.path)


# `/proc/sysvipc/<file>`, the `ipcrm` flag that removes one of its ids, and the
# header of the id column (the uid column is named `uid` in all three).
_IPC_KINDS = (("shm", "-m", "shmid"), ("msg", "-q", "msqid"), ("sem", "-s", "semid"))


def _purge_ipc(uid: int) -> None:
    """Remove every SysV shared memory segment, message queue and semaphore set
    owned by `uid`, by id, under the uid itself.

    Not `ipcrm --all`: it exits 1 as soon as any object of another uid exists,
    which is the ordinary case here (measured on the image, 2026-10-29), so its
    exit code could not tell a failed purge from a busy container.
    """
    argv = ["ipcrm"]
    for kind, flag, id_column in _IPC_KINDS:
        for ipc_id in _ipc_ids(_PROC / "sysvipc" / kind, id_column, uid):
            argv += [flag, ipc_id]
    if len(argv) == 1:
        return
    if run_as(uid, argv) != 0:
        msg = f"ipcrm failed for uid {uid}"
        raise OSError(msg)


def _ipc_ids(table: Path, id_column: str, uid: int) -> list[str]:
    try:
        header, *rows = table.read_text(encoding="ascii").splitlines()
    except FileNotFoundError:
        return []  # no SysV IPC on this kernel, or no /proc at all
    columns = header.split()
    at_id, at_uid = columns.index(id_column), columns.index("uid")
    return [fields[at_id] for fields in (row.split() for row in rows) if int(fields[at_uid]) == uid]
