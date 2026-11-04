"""Records-storage measurement of custom-objects ticket 01 (FOG-41, FOG-55).

    uv run python scripts/bench_records_storage.py --scale smoke --variants all
    uv run python scripts/bench_records_storage.py --scale d12 --variants all  # reference host

Runs on its own PostgreSQL container (default `dwbench-postgres` on 127.0.0.1:25442,
the compose image by digest, the prod overlay's memory limit), never on the
cluster other lanes test on, because the cold run restarts it. Exit 0 means every
cell of the matrix has its numbers at both moduli and the CO27 self-check saw HOT
updates; a missed threshold is a "trượt" row, not a failure. The report goes to
`--out` (default: a timestamped directory under the system temp directory).

The code lives in `scripts/bench_records_storage/records_bench/` with the DDL of
every variant; record-access/01 adds its policy variants there.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).with_suffix("")))

if __name__ == "__main__":
    raise SystemExit(importlib.import_module("records_bench.run").main(sys.argv[1:]))
