"""Spike S-RT of discovery 14: LangGraph running the step tree, measured.

    DW_TEST_DB_SUFFIX=_lane2 uv run python tests/spike/srt/run_srt.py setup
    DW_TEST_DB_SUFFIX=_lane2 uv run python tests/spike/srt/run_srt.py measure t1 --out <dir>
    DW_TEST_DB_SUFFIX=_lane2 uv run python tests/spike/srt/run_srt.py measure all --out <dir>

`worker` is the entry the harness starts each worker process with. Nothing here
runs in CI: `tests/spike` is outside pytest's `testpaths`, and its tests carry
the `integration` marker and need this database (see `test_srt.py`).
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _worker(argv: list[str]) -> int:
    from srtlib.db import urls
    from srtlib.lane import Settings, Worker

    parser = argparse.ArgumentParser("worker")
    parser.add_argument("--id", required=True)
    parser.add_argument("--log")
    parser.add_argument("--lot", type=int, default=8)
    parser.add_argument("--lease", type=float, default=60.0)
    parser.add_argument("--heartbeat", type=float, default=15.0)
    parser.add_argument("--reaper", type=float, default=5.0)
    parser.add_argument("--poll", type=float, default=1.0)
    parser.add_argument("--fence", default="fused")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--cancel", default="notify")
    parser.add_argument("--recursion-limit", type=int, default=10_000)
    parser.add_argument("--durability", default="sync")
    parser.add_argument("--only-run")
    parser.add_argument("--pool", type=int, default=10)
    parser.add_argument("--max-concurrency", type=int, default=10)
    parser.add_argument("--no-dispatch-log", action="store_true")
    parser.add_argument("--seconds", type=float)
    args = parser.parse_args(argv)
    found = urls()
    settings = Settings(
        worker=args.id,
        app_url=found.app,
        provider_url=found.migrator,
        lot=args.lot,
        lease=args.lease,
        heartbeat=args.heartbeat,
        reaper=args.reaper,
        poll=args.poll,
        fence=args.fence,
        notify=not args.no_notify,
        cancel=args.cancel,
        recursion_limit=args.recursion_limit,
        durability=args.durability,
        only_run=args.only_run,
        pool=args.pool,
        max_concurrency=args.max_concurrency,
        dispatch_log=not args.no_dispatch_log,
        log_path=args.log,
    )

    async def main() -> None:
        import time

        worker = Worker(settings)
        loop = asyncio.get_running_loop()

        def stop(*_: object) -> None:
            worker.stopping = True
            worker.wake.set()

        if sys.platform == "win32":
            signal.signal(signal.SIGBREAK, lambda *_: loop.call_soon_threadsafe(stop))
        else:
            loop.add_signal_handler(signal.SIGTERM, stop)
        until = time.time() + args.seconds if args.seconds else None
        await worker.run(until)

    asyncio.run(main())
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    command, rest = argv[0], argv[1:]
    if command == "worker":
        return _worker(rest)
    if command == "setup":
        from srtlib import db

        print(db.create(migrate="--schema-only" not in rest))
        return 0
    if command == "measure":
        from srtlib.measure import main as measure

        return measure(rest)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
