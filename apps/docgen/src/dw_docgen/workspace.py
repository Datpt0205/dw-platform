"""Per-session directories and the containment rule for every path that crosses
the wire.

One container serves every session. Two things separate them, and this module
owns both: a session id maps to exactly one directory, and no path a caller
sends may resolve outside it (symlinks are resolved before the check, so a
script that plants `out -> /etc` cannot turn a later download into an arbitrary
file read); and, when sessions are isolated, each directory is mode 0700 and
owned by a uid of its own from a fixed pool, which is what keeps one session's
SHELL out of another's files (ADR 0025). The path check guards only the file
routes; the shell is stopped by the kernel or not at all.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
from collections.abc import Container
from pathlib import Path

from dw_docgen import identity

logger = logging.getLogger(__name__)

# Session ids come from the calling backend, not from the model, but they land
# in a filesystem path, so they are validated rather than trusted.
SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class InvalidSessionError(ValueError):
    """The session id could not be used as a directory name."""


class PathOutsideSessionError(ValueError):
    """A path resolved outside the session directory it was addressed to."""


class SessionPoolExhaustedError(RuntimeError):
    """Every uid of the pool belongs to a live session or is not yet clean."""


class SessionIsolationError(RuntimeError):
    """A session directory is owned by a uid outside the pool. Nothing runs."""


class SessionUncleanError(RuntimeError):
    """A process of the session's uid outlived its last command."""


class SessionWorkspace:
    """Resolves session ids and paths against a root directory.

    `uids` is the pool sessions run under; None only where sessions are not
    isolated, which `main` permits for a service that is not uid 0.
    """

    def __init__(
        self,
        root: Path,
        *,
        uids: range | None,
        shared_temp_dirs: tuple[str, ...] = (),
        session_ttl_seconds: int = 3600,
    ) -> None:
        self._root = root
        self._uids = uids
        self._shared_temp_dirs = shared_temp_dirs
        self._session_ttl_seconds = session_ttl_seconds
        # Every caller already holds the API's one semaphore; this keeps two
        # new sessions from ever taking one uid even if a caller does not.
        self._allocation = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def scratch_dir(self) -> Path:
        """The service's own directory under the root, created on demand.

        Dot-prefixed, which no session id can be, so it can never be mistaken
        for one - by the sweep or by anything else.
        """
        path = self._root / ".service"
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        # The service's own, never a session's: the shell gets the open file
        # descriptor of its output, never a path into here.
        path.chmod(0o700)
        return path

    def adopt_root(self) -> None:
        """Make the root what isolation assumes, before any session is served.

        0711 lets a shell enter its own directory without listing its
        neighbours, whose names carry their tenant. An entry owned by no pool
        uid is from before isolation or from a crash between `mkdir` and
        `chown`, and is readable by whoever guesses its name, so it goes.
        """
        if self._uids is None:
            return
        self._root.chmod(0o711)
        for child in self._root.iterdir():
            if child.name == ".service" or child.lstat().st_uid in self._uids:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()

    def session_dir(self, session_id: str, *, create: bool = True) -> Path:
        """The directory backing `session_id`, created on first use."""
        if not SESSION_ID.match(session_id):
            msg = (
                f"session id {session_id!r} is not usable as a directory name; "
                "use letters, digits, '-' and '_', up to 64 characters"
            )
            raise InvalidSessionError(msg)
        path = self._root / session_id
        if not create:
            return path
        if self._uids is None:
            path.mkdir(parents=True, exist_ok=True)
            return path
        with self._allocation:
            if not path.exists():
                uid = self._allocate()
                path.mkdir(mode=0o700)
                os.chown(path, uid, uid)
                path.chmod(0o700)
        return path

    def uid_of(self, session_id: str) -> int | None:
        """The uid the session's shell runs under; None when not isolated.

        Read from the directory's owner, the one place it is recorded. An owner
        outside the pool - root, the old shared uid - is refused rather than
        run as. A process of the uid still alive means the last command's kill
        did not converge, and between commands such a process could swap a
        path under the service's own file operations, so the session waits.
        """
        if self._uids is None:
            return None
        owner = self.session_dir(session_id, create=False).stat().st_uid
        if owner not in self._uids:
            msg = f"session {session_id!r} is owned by uid {owner}, outside the session pool"
            raise SessionIsolationError(msg)
        if owner in identity.process_owners():
            msg = f"session {session_id!r} still has a process from its last command"
            raise SessionUncleanError(msg)
        return owner

    def _allocate(self) -> int:
        """The lowest clean uid, sweeping stale sessions once before giving up."""
        uid = self._free_uid()
        if uid is None:
            self.sweep(older_than_seconds=self._session_ttl_seconds)
            uid = self._free_uid()
        if uid is None:
            msg = "every uid of the session pool is in use"
            raise SessionPoolExhaustedError(msg)
        return uid

    def _free_uid(self) -> int | None:
        """A uid no session directory owns, with no process alive, purged clean.

        A uid that cannot be purged is skipped, never handed out: its residue
        would be the next tenant's to read.
        """
        if self._uids is None:
            return None
        taken = {
            child.stat().st_uid for child in self._root.iterdir() if not child.name.startswith(".")
        } | identity.process_owners()
        for uid in self._uids:
            if uid in taken:
                continue
            try:
                identity.purge(uid, self._shared_temp_dirs)
            except OSError:
                logger.error("could not purge uid %s; it stays out of the pool", uid, exc_info=True)
                continue
            return uid
        return None

    def resolve(self, session_id: str, raw_path: str) -> Path:
        """Map a caller-supplied path onto a real path inside the session.

        Absolute paths are honoured when they already point inside the session
        directory; relative paths are taken against it. Anything else is refused
        rather than clamped, because silently relocating a write is how a script
        ends up believing it wrote a file it did not.
        """
        base = self.session_dir(session_id, create=False)
        candidate = Path(raw_path)
        target = candidate if candidate.is_absolute() else base / candidate
        # `resolve()` on a path that does not exist yet resolves the existing
        # prefix and appends the rest verbatim - what an upload to a new file
        # needs, and it still follows a symlinked parent, which is the escape
        # this check exists for.
        resolved = target.resolve()
        base_resolved = base.resolve()
        if resolved != base_resolved and base_resolved not in resolved.parents:
            msg = f"{raw_path!r} resolves outside the session workspace"
            raise PathOutsideSessionError(msg)
        return resolved

    def reset(self, session_id: str) -> None:
        """Delete everything the session wrote. Idempotent."""
        shutil.rmtree(self.session_dir(session_id, create=False), ignore_errors=True)

    def sweep(
        self,
        *,
        older_than_seconds: int,
        skip: Container[str] = (),
        now: float | None = None,
    ) -> list[str]:
        """Delete sessions untouched for `older_than_seconds`; return their ids.

        A run that crashes never calls `reset`, and the root is a tmpfs, so
        without this the container leaks RAM and keeps one customer's draft
        readable to the next session that goes looking. `skip` holds the sessions
        with a command in flight: a long run that only reads leaves its directory
        mtime untouched and would otherwise look abandoned.
        """
        if not self._root.exists():
            return []
        cutoff = (time.time() if now is None else now) - older_than_seconds
        swept: list[str] = []
        for child in self._root.iterdir():
            if child.name.startswith(".") or child.name in skip:
                continue
            if not child.is_dir() or child.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(child, ignore_errors=True)
            swept.append(child.name)
        return swept
