"""The harness's own PostgreSQL container: never the cluster other lanes test on.

Same image and digest as `infra/compose/docker-compose.yml`, the same command
(`wal_level=logical`) and init script, and the prod overlay's 2 GB memory limit
(`infra/compose/docker-compose.prod.yml`), on its own host port and its own
volume (ticket 01 step 1). The cold run restarts it and drops the OS page cache
of the Docker VM through a privileged container of the same image.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
from dataclasses import dataclass

import asyncpg

from .db import REPO_ROOT, Endpoint

COMPOSE = REPO_ROOT / "infra" / "compose" / "docker-compose.yml"
PROD = REPO_ROOT / "infra" / "compose" / "docker-compose.prod.yml"


def compose_image() -> str:
    text = COMPOSE.read_text(encoding="utf-8")
    match = re.search(r"^  postgres:\n    image: (\S+)", text, re.MULTILINE)
    if not match:
        raise RuntimeError("no postgres image in docker-compose.yml")
    return match.group(1)


def prod_memory_limit() -> str:
    text = PROD.read_text(encoding="utf-8")
    match = re.search(r"^  postgres:\n(?:    .*\n)*?\s+memory: (\S+)", text, re.MULTILINE)
    if not match:
        raise RuntimeError("no postgres memory limit in docker-compose.prod.yml")
    return match.group(1)


def _docker(*args: str, check: bool = True, timeout: float = 120) -> str:
    done = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if check and done.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


@dataclass
class Container:
    name: str
    port: int
    endpoint: Endpoint
    created_here: bool = False

    @property
    def volume(self) -> str:
        return f"{self.name}-data"

    def exists(self) -> bool:
        return bool(_docker("ps", "-a", "-q", "--filter", f"name=^{self.name}$", check=False))

    def start(self) -> None:
        if self.exists():
            _docker("start", self.name)
            return
        init = REPO_ROOT / "infra" / "compose" / "init" / "init-databases.sh"
        ep = self.endpoint
        _docker(
            "run",
            "-d",
            "--name",
            self.name,
            "--memory",
            prod_memory_limit(),
            "-p",
            f"127.0.0.1:{self.port}:5432",
            "-v",
            f"{self.volume}:/var/lib/postgresql/data",
            "-v",
            f"{init.as_posix()}:/docker-entrypoint-initdb.d/10-init-databases.sh:ro",
            "-e",
            f"POSTGRES_USER={ep.admin_user}",
            "-e",
            f"POSTGRES_PASSWORD={ep.admin_password}",
            "-e",
            "POSTGRES_DB=postgres",
            "-e",
            f"DW_DB_MIGRATOR_PASSWORD={ep.migrator_password}",
            "-e",
            f"DW_DB_APP_PASSWORD={ep.app_password}",
            "-e",
            "DW_DB_AGENT_RO_PASSWORD=bench-agent-ro",
            "-e",
            "DW_DB_PROVISIONER_PASSWORD=bench-provisioner",
            "-e",
            "DW_DB_MONITOR_PASSWORD=bench-monitor",
            compose_image(),
            "postgres",
            "-c",
            "wal_level=logical",
            timeout=600,
        )
        self.created_here = True

    async def wait_ready(self, timeout_s: float = 120) -> None:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                conn = await self.endpoint.on("postgres").connect("admin", timeout=5)
                ok = await conn.fetchval("SELECT count(*) FROM pg_roles WHERE rolname = 'dw_app'")
                await conn.close()
                if ok:
                    return
            except (TimeoutError, OSError, asyncpg.PostgresError, asyncpg.InterfaceError):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError(f"{self.name} not ready after {timeout_s} s")
            await asyncio.sleep(1)

    async def restart_cold(self) -> None:
        """Restart PostgreSQL and drop the VM's page cache (gate MEDIUM (c))."""
        _docker("restart", self.name, timeout=180)
        _docker(
            "run",
            "--rm",
            "--privileged",
            "--entrypoint",
            "sh",
            compose_image(),
            "-c",
            "sync; echo 3 > /proc/sys/vm/drop_caches",
        )
        await self.wait_ready()

    def remove(self) -> None:
        _docker("rm", "-f", self.name, check=False)
        _docker("volume", "rm", "-f", self.volume, check=False)

    def describe(self) -> list[str]:
        image = _docker("inspect", "--format", "{{.Config.Image}}", self.name, check=False)
        memory = _docker("inspect", "--format", "{{.HostConfig.Memory}}", self.name, check=False)
        ncpu = _docker(
            "info",
            "--format",
            "{{.NCPU}} CPU, {{.MemTotal}} byte RAM, {{.OperatingSystem}}",
            check=False,
        )
        shm = _docker("exec", self.name, "df", "-h", "/dev/shm", check=False).splitlines()
        return [
            f"container {self.name}, cổng 127.0.0.1:{self.port}, volume {self.volume}",
            # Compose sets no shm_size, so the host has Docker's 64 MB too: a
            # parallel plan needing more dynamic shared memory fails there.
            f"/dev/shm: {shm[-1] if shm else '?'} (compose không đặt shm_size); mọi phiên của"
            " harness đặt max_parallel_maintenance_workers = 0, vì CREATE INDEX và VACUUM song"
            " song hỏi 64 MB bộ nhớ chia sẻ động và vỡ với 'could not resize shared memory"
            " segment' (autovacuum không bao giờ song song)",
            f"image {image}",
            f"giới hạn bộ nhớ {int(memory or 0) / 2**30:.1f} GiB (docker-compose.prod.yml)",
            f"Docker: {ncpu}",
        ]
