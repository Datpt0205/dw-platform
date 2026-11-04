"""Compile time and memory of the graph caches at 10, 100 and 256 keys
(agent-builder ticket 01, step 4). Not a test: run it, read the table.

    uv run python packages/python/dw_agent_runtime/tests/prototype/measure_compile.py

Two paths, each in a cold process per (path, keys, mode):

* `studio`: `StudioGraphSource` builds the fixture agent (10 tools) per key,
  one version of the fixture per key, the keys split evenly over two
  companies, into its LRU of 256.
* `workflow`: the path a company's workflow version takes today:
  `TenantWorkflowGraphs.ensure` registers the version's graph in
  `GraphRegistry`, and the graph is compiled as the runner's `_graph` does
  into a plain dict standing in for `_compiled`, which nothing ever empties.

Two modes, because `tracemalloc` slows every allocation it records: `time`
reads compile time per key and the process's RSS before the first key and
after the last; `memory` reads what `tracemalloc` traced per key. Both then
add keys up to the 257th and report how many entries the cache still holds.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import ctypes
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import tracemalloc
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
LEVELS = (10, 100, 256)
OVERFLOW = 257
TENANTS = (uuid.UUID(int=0xA00), uuid.UUID(int=0xB00))
MIB = 1024 * 1024


def rss_bytes() -> int:
    """This process's resident set, from the OS (no third-party package)."""
    if os.name == "nt":

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel32: Any = getattr(ctypes, "windll").kernel32  # noqa: B009 - absent on Linux
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.K32GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(Counters),
            ctypes.c_ulong,
        ]
        if not kernel32.K32GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            raise OSError("GetProcessMemoryInfo failed")
        return int(counters.WorkingSetSize)
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("no RSS reading on this platform")


def studio_path() -> tuple[Callable[[int], None], Callable[[], int]]:
    from langgraph.checkpoint.memory import InMemorySaver
    from studio_agent_prototype import (
        AgentDocument,
        FixedRoutes,
        ProbedRunControl,
        StudioGraphSource,
        executor_over,
        register_tools,
    )

    from dw_agent_runtime.adapters.chat_model import MockChatModel
    from dw_agent_runtime.tools import ToolRegistry

    document = AgentDocument.load()
    registry = ToolRegistry()
    for tenant in TENANTS:
        register_tools(registry, document, tenant_id=tenant)
    source = StudioGraphSource(
        registry=registry,
        executor=executor_over(registry, ProbedRunControl([])),
        default_model=MockChatModel(responses=[], mock_reply=""),
        routes=FixedRoutes({document.profile_id: MockChatModel(responses=[], mock_reply="")}),
        checkpointer=InMemorySaver(),
    )

    def add(n: int) -> None:
        source.graph(TENANTS[n % 2], document.variant(n))

    return add, lambda: len(source.compiled)


def workflow_path() -> tuple[Callable[[int], None], Callable[[], int]]:
    from langgraph.checkpoint.memory import InMemorySaver
    from pydantic import BaseModel
    from studio_agent_prototype import ToolAnswer, ToolSpec, answer, definition_of

    from dw_agent_runtime.registry import GraphRegistry, WorkerRegistry
    from dw_agent_runtime.testing.wflite import InMemoryTenantVersions
    from dw_agent_runtime.tools import RegisteredTool, ToolRegistry, pydantic_behaviour
    from dw_agent_runtime.wflite.catalog import load_shipped_packs, workflow_sha256
    from dw_agent_runtime.wflite.compile import WfPorts
    from dw_agent_runtime.wflite.versions import TenantVersion, TenantWorkflowGraphs
    from dw_platform.application.work_queue import WorkScope

    packs = load_shipped_packs(REPO / "configs")
    pack = packs.workflow("lead_care", "1.0.0")
    assert pack is not None
    base = pack.document.model_dump(by_alias=True, exclude_none=True)
    versions = InMemoryTenantVersions()
    graphs = GraphRegistry()

    # The one port compilation reads: the input schema of the tool an
    # approval's lane sends with (`_proposal_schema`). The nodes close over
    # the others and use them only when they run.
    class EmailInput(BaseModel):
        to: str
        subject: str
        body: str

    tools = ToolRegistry()
    send = ToolSpec("email.send", "1.0.0", "Gửi thư.", ("to", "subject", "body"))
    tools.register(
        RegisteredTool(
            definition=definition_of(send).model_copy(update={"side_effect_level": "external"}),
            behaviour=pydantic_behaviour(EmailInput, ToolAnswer, answer),
        )
    )
    unused: Any = None
    ports = WfPorts(
        gateway=unused,
        executor=unused,
        tools=tools,
        gate=unused,
        queue=unused,
        workers=unused,
        clock=unused,
        recommendations={},
    )
    tenant_graphs = TenantWorkflowGraphs(
        catalog=packs,
        versions=versions,
        ports=ports,
        graphs=graphs,
        workers=WorkerRegistry(graph_registry=graphs),
    )
    saver = InMemorySaver()
    compiled: dict[tuple[str, str], Any] = {}  # `LangGraphWorkflowRunner._compiled`
    now = datetime.now(UTC)

    def add(n: int) -> None:
        tenant = TENANTS[n % 2]
        scope = WorkScope(tenant_id=tenant, workspace_id=uuid.UUID(int=tenant.int + 1))
        steps = copy.deepcopy(base["steps"])
        steps[0] = {**steps[0], "description": f"phiên bản {n}"}
        content = {**base, "steps": steps}
        sha = workflow_sha256(content)
        label = f"1.0.0+t{n + 1}"
        versions.put(
            scope,
            TenantVersion(
                dw_id=uuid.uuid4(),
                key="lead_care",
                version=label,
                content=content,
                content_sha256=sha,
                base_sha256=pack.sha256,
                author_ids=(uuid.uuid4(),),
                approved_by=uuid.uuid4(),
                approval_id=uuid.uuid4(),
                created_at=now,
            ),
        )
        run_version = f"{label}.{sha}"
        asyncio.run(
            tenant_graphs.ensure(
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                worker_id="dw:lead_care",
                worker_version=run_version,
            )
        )
        key = ("dw:lead_care", run_version)
        compiled[key] = graphs.resolve(*key)().compile(checkpointer=saver)

    return add, lambda: len(compiled)


PATHS = {"studio": studio_path, "workflow": workflow_path}


def measure(path: str, keys: int, mode: str) -> dict[str, Any]:
    add, held = PATHS[path]()
    gc.collect()
    result: dict[str, Any] = {"path": path, "keys": keys, "mode": mode}
    if mode == "time":
        before = rss_bytes()
        times: list[float] = []
        for n in range(keys):
            started = time.perf_counter()
            add(n)
            times.append((time.perf_counter() - started) * 1000)
        gc.collect()
        after = rss_bytes()
        cuts = statistics.quantiles(times, n=20, method="inclusive")
        result |= {
            "p50_ms": statistics.median(times),
            "p95_ms": cuts[18],
            "first_ms": times[0],
            "rss_before_mib": before / MIB,
            "rss_after_mib": after / MIB,
            "rss_growth_mib": (after - before) / MIB,
        }
    else:
        tracemalloc.start()
        start = tracemalloc.get_traced_memory()[0]
        for n in range(keys):
            add(n)
        gc.collect()
        traced = tracemalloc.get_traced_memory()[0] - start
        tracemalloc.stop()
        result |= {"traced_mib": traced / MIB, "per_key_mib": traced / keys / MIB}
    for n in range(keys, OVERFLOW):
        add(n)
    result["held_after_257"] = held()
    return result


def run_all(out: Path | None) -> None:
    rows: list[dict[str, Any]] = []
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(HERE), str(HERE.parent / "unit"), *sys.path]),
    }
    for path in PATHS:
        for keys in LEVELS:
            merged: dict[str, Any] = {}
            for mode in ("time", "memory"):
                done = subprocess.run(
                    [sys.executable, __file__, "--path", path, "--keys", str(keys), "--mode", mode],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                merged |= json.loads(done.stdout.strip().splitlines()[-1])
            rows.append(merged)
            print(json.dumps(merged), flush=True)
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO
    ).stdout.strip()
    machine = (
        f"{platform.system()} {platform.release()}, {platform.processor()},"
        f" Python {platform.python_version()}"
    )
    if out is not None:
        out.write_text(json.dumps({"commit": commit, "machine": machine, "rows": rows}, indent=2))
    print(f"commit {commit}; {machine}")
    print("| path | keys | P50 ms | P95 ms | RSS growth MiB | per key MiB | held after 257 |")
    for r in rows:
        print(
            f"| {r['path']} | {r['keys']} | {r['p50_ms']:.1f} | {r['p95_ms']:.1f} |"
            f" {r['rss_before_mib']:.0f} -> {r['rss_after_mib']:.0f} (+{r['rss_growth_mib']:.1f})"
            f" | {r['per_key_mib']:.3f} | {r['held_after_257']} |"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", choices=sorted(PATHS))
    parser.add_argument("--keys", type=int)
    parser.add_argument("--mode", choices=("time", "memory"))
    parser.add_argument("--out", type=Path, help="also write the rows as JSON here")
    args = parser.parse_args()
    if args.path is None:
        run_all(args.out)
        return
    print(json.dumps(measure(args.path, args.keys, args.mode)))


if __name__ == "__main__":
    main()
