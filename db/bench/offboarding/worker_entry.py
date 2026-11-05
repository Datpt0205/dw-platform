"""The worker process `bench_offboarding.py` starts in the container (discovery 09).

`head` runs `dw_worker.main` exactly as the image's CMD does. `spool` runs the
same process with one prototype swapped in: the lane's `_build_bundle` writes
each table's ndjson straight into a zip entry on a temporary file instead of
gathering every line in memory first. The swap is a module attribute replaced
before `main()` builds the lane, in this process only; no repository code
changes. Mounted read-only at `/bench`; not imported by anything else.
"""

from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from collections.abc import AsyncIterable
from typing import Any, Protocol


class _Batch(Protocol):
    @property
    def schema(self) -> str: ...
    @property
    def table(self) -> str: ...
    @property
    def rows(self) -> list[dict[str, Any]]: ...


async def spooled_bundle(
    batches: AsyncIterable[_Batch],
    artifact_blobs: dict[str, bytes],
    attachment_blobs: dict[str, bytes],
) -> bytes:
    """The head bundle's entries and bytes per line, one batch in memory at a
    time: the compressed zip is the only whole thing held, once, at the end."""
    from dw_worker.consumers.offboarding import _json_default

    seen: set[str] = set()
    with tempfile.TemporaryFile() as raw:
        with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as zf:
            current: str | None = None
            entry = None
            first = True
            async for batch in batches:
                name = f"tables/{batch.schema}.{batch.table}.ndjson"
                if name != current:
                    if name in seen:
                        raise RuntimeError(f"{name} arrived in two runs of batches")
                    if entry is not None:
                        entry.close()
                    seen.add(name)
                    entry = zf.open(name, "w", force_zip64=True)
                    current, first = name, True
                assert entry is not None
                for row in batch.rows:
                    line = json.dumps(row, default=_json_default, ensure_ascii=False)
                    entry.write((line if first else "\n" + line).encode("utf-8"))
                    first = False
            if entry is not None:
                entry.close()
            for key, data in artifact_blobs.items():
                zf.writestr(f"blobs/artifacts/{key}", data)
            for key, data in attachment_blobs.items():
                zf.writestr(f"blobs/attachments/{key}", data)
        raw.seek(0)
        return raw.read()


def main() -> None:
    variant = sys.argv[1] if len(sys.argv) > 1 else "head"
    if variant == "spool":
        import dw_worker.consumers.offboarding as lane

        lane._build_bundle = spooled_bundle
    elif variant != "head":
        raise SystemExit(f"unknown variant {variant!r}")
    from dw_worker.main import main as worker_main

    worker_main()


if __name__ == "__main__":
    main()
