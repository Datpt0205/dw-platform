"""Generate the pinned OTel GenAI snapshot (contracts/telemetry/genai-semconv@<sha12>.json).

The upstream half comes from the YAML of `open-telemetry/semantic-conventions-genai`
at `dw_observability.semconv.GENAI_SEMCONV_COMMIT`, fetched as that commit's
tarball, never from `semconv.py` — otherwise a name we invented and called
upstream's would make its own snapshot agree with it (spec R1.1). The `dw` half
is what `semconv.py` declares under our own prefixes.

Usage:
  uv run python scripts/genai_semconv_snapshot.py            # write the snapshot
  uv run python scripts/genai_semconv_snapshot.py --check    # fail if drifted
  uv run python scripts/genai_semconv_snapshot.py --upstream DIR   # read a checkout instead
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
import urllib.request
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import yaml

from dw_observability.semconv import (
    GENAI_SEMCONV_COMMIT,
    GENAI_SEMCONV_REPOSITORY,
    dw_names,
    snapshot_path,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
_TARBALL = "https://codeload.github.com/{repo}/tar.gz/{sha}"
_TIMEOUT_SECONDS = 60


def _tarball_documents(repo: str, sha: str) -> Iterator[tuple[str, Any]]:
    url = _TARBALL.format(repo=repo, sha=sha)
    with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as response:
        data = response.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            # `<repo>-<sha>/model/...`: only the model, which is the normative part.
            parts = member.name.split("/", 1)
            if member.isfile() and len(parts) == 2 and _is_model_yaml(parts[1]):
                handle = archive.extractfile(member)
                if handle is not None:
                    yield parts[1], yaml.safe_load(handle.read())


def _directory_documents(root: Path) -> Iterator[tuple[str, Any]]:
    for path in sorted(root.rglob("*.yaml")):
        relative = path.relative_to(root).as_posix()
        if _is_model_yaml(relative):
            yield relative, yaml.safe_load(path.read_text(encoding="utf-8"))


def _is_model_yaml(relative: str) -> bool:
    return relative.startswith("model/") and relative.endswith(".yaml")


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def upstream_names(documents: Iterable[tuple[str, Any]]) -> dict[str, list[str]]:
    """Attribute keys (defined or referenced), operation names and metric names."""
    attributes: set[str] = set()
    operations: set[str] = set()
    metrics: set[str] = set()
    for _, document in documents:
        for entry in document.get("attributes", []) if isinstance(document, dict) else []:
            if isinstance(entry, dict) and "key" in entry:
                attributes.add(str(entry["key"]))
                if entry["key"] == "gen_ai.operation.name":
                    members = entry.get("type", {}).get("members", [])
                    operations.update(str(m["value"]) for m in members if "value" in m)
        for node in _walk(document):
            ref = node.get("ref")
            # `ref:` names an attribute only inside an attribute list; a span or
            # group refinement's `ref` names a span type, which has no dot-free key.
            if isinstance(ref, str) and "requirement_level" in node:
                attributes.add(ref)
        for metric in document.get("metrics", []) if isinstance(document, dict) else []:
            if isinstance(metric, dict) and "name" in metric:
                metrics.add(str(metric["name"]))
    return {
        "attributes": sorted(attributes),
        "operations": sorted(operations),
        "metrics": sorted(metrics),
    }


def build_snapshot(documents: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    return {
        "repository": GENAI_SEMCONV_REPOSITORY,
        "commit": GENAI_SEMCONV_COMMIT,
        "upstream": upstream_names(documents),
        "dw": dw_names(),
    }


def render(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the snapshot drifted")
    parser.add_argument("--upstream", type=Path, help="a checkout of upstream at the pinned commit")
    args = parser.parse_args(argv)

    documents = (
        _directory_documents(args.upstream)
        if args.upstream
        else _tarball_documents(GENAI_SEMCONV_REPOSITORY, GENAI_SEMCONV_COMMIT)
    )
    expected = render(build_snapshot(documents))
    target = snapshot_path(REPO_ROOT)
    if args.check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != expected:
            print(
                f"{target.relative_to(REPO_ROOT)} is stale: run scripts/genai_semconv_snapshot.py"
            )
            return 1
        print(f"{target.relative_to(REPO_ROOT)} is current")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    stale = sorted(p for p in target.parent.glob("genai-semconv@*.json") if p != target)
    for old in stale:
        old.unlink()
    target.write_text(expected, encoding="utf-8", newline="\n")
    print(f"wrote {target.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
