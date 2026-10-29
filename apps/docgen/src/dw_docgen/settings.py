"""Every environment knob the sandbox service reads, in one place.

The numbers below are the containment budget. They are deliberately small: this
service exists to run code an LLM wrote from text a customer supplied, so the
question each limit answers is "what does a hostile script get?", not "what is
comfortable?".
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

MEGABYTE = 1024 * 1024


class DocgenSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DW_DOCGEN_", extra="ignore")

    # tmpfs in the container, a real directory in tests. Everything a session
    # touches lives under `<root>/<session id>` and is wiped when it is released.
    root: str = "/work"

    # Empty means unauthenticated, which is only defensible because the service
    # is published on no network but `dw-sandbox`, whose only other member is the
    # forwarder. Setting it is one env var and stops a compromised sibling
    # container from getting a free shell.
    token: str = ""

    # bash, not `/bin/sh`. On Debian `/bin/sh` is dash, whose `ulimit` has no
    # `-u`, so the process cap could not be set and the fail-closed preamble
    # refused every command. Both shells are in the image; only one can express
    # the whole budget.
    shell_path: str = "/bin/bash"

    # One command at a time, and with sessions isolated nothing else is allowed
    # (`main` refuses to start): the file routes write with DAC_OVERRIDE, and the
    # one semaphore is what keeps a session's own process from swapping a path
    # component for a symlink under them (ADR 0025, decision 4).
    max_concurrency: int = 1

    # The pool of uids a session's shell runs under, one per live session
    # (ADR 0025). The image carries a `passwd` entry `dws<n>` for each, and
    # `main` refuses to start when one is missing, so this and the Dockerfile
    # cannot drift quietly. Well above every system and image uid, so no pool
    # uid is anything but a session.
    session_uid_base: int = Field(default=20000, ge=10000)
    session_uid_count: int = Field(default=1024, ge=1)

    # World-writable places outside `/work` where a session can leave something
    # behind for whoever gets its uid next. Each is purged of the uid's entries
    # after its command and before the uid is handed out.
    shared_temp_dirs: tuple[str, ...] = ("/tmp", "/dev/shm", "/dev/mqueue")

    # A brandkit generate over a large template measures in single-digit seconds;
    # a LibreOffice PDF conversion in tens. 120s leaves headroom for both and
    # still bounds a hung script to two minutes.
    default_timeout_seconds: int = 120
    max_timeout_seconds: int = 300

    # CPU seconds, not wall seconds: a script that sleeps is cheap, a script that
    # spins is not. Set above the wall timeout so the wall clock is the usual
    # stop and this is the backstop for a fork that outlives its parent.
    cpu_seconds: int = 180
    # LibreOffice alone maps ~500MB of address space on a first run. 2GB fits it
    # plus a python-docx tree over a large template; a memory bomb dies here.
    address_space_mb: int = 2048
    max_open_files: int = 512
    # Per-uid, not per-process: with serial execution this caps the whole
    # container's fork rate, which is the point — it stops a fork bomb.
    max_processes: int = 256
    # Caps any single file the script writes, the captured output included. A
    # 200-page docx with images stays well inside it.
    max_file_bytes: int = 64 * MEGABYTE

    # What comes back to the model. Beyond this the tail is dropped and the
    # response is flagged truncated, the same contract deepagents' own sandboxes
    # offer.
    max_output_bytes: int = 512 * 1024

    # One upload batch. The largest legitimate payload is a template shell plus
    # its profile, which is a few megabytes.
    max_upload_bytes: int = 32 * MEGABYTE
    max_download_bytes: int = 32 * MEGABYTE
    max_files_per_batch: int = 64

    # A session left behind by a crashed run is swept rather than kept forever;
    # tmpfs is RAM and an abandoned workdir is both a leak and a disclosure.
    session_ttl_seconds: int = 3600

    @property
    def session_uids(self) -> range:
        return range(self.session_uid_base, self.session_uid_base + self.session_uid_count)

    @property
    def enforce_limits(self) -> bool:
        """Whether `setrlimit` is available.

        False on Windows, where the service runs only under unit tests. The
        container is Linux, so the limits are always on where they matter, and
        `main` logs loudly when they are not.
        """
        return os.name == "posix"


@lru_cache(maxsize=1)
def get_settings() -> DocgenSettings:
    return DocgenSettings()
