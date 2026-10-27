#!/usr/bin/env bash
# Tests for the registration check of scripts/verify_architecture.py (studio-skeleton R1).
#
#   bash scripts/test_verify_architecture.sh     (also: make test-architecture)
#
# The first case runs the check on this checkout. Every other case runs it on a
# throwaway skeleton of the workspace (the root pyproject, the three Python
# Dockerfiles, the script itself and each member's manifest and package
# folders), plants exactly one missing registration, and requires exit 1 with a
# line naming the package and the place. A case that cannot plant its defect
# fails loudly instead of passing (failure-modes.md #3).
set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
py=(uv run --project "$here" python)

passed=0
failed=0
check() { # description expected actual
  if [ "$2" = "$3" ]; then
    passed=$((passed + 1))
  else
    failed=$((failed + 1))
    echo "FAIL: $1 (expected $2, got $3)"
  fi
}

# A skeleton of the checkout: enough for the check to read, nothing it does not.
skeleton() {
  local dir
  dir=$(mktemp -d -p "$work")
  "${py[@]}" - "$here" "$dir" <<'PY'
import shutil
import sys
import tomllib
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
for rel in ("pyproject.toml", "scripts/verify_architecture.py"):
    (dst / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src / rel, dst / rel)
for name in ("api", "worker", "docgen"):
    rel = Path("infra/docker") / f"{name}.Dockerfile"
    (dst / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src / rel, dst / rel)
config = tomllib.loads((src / "pyproject.toml").read_text(encoding="utf-8"))
for pattern in config["tool"]["uv"]["workspace"]["members"]:
    for member in src.glob(pattern):
        if not (member / "pyproject.toml").is_file():
            continue
        rel = member.relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        shutil.copy(member / "pyproject.toml", dst / rel / "pyproject.toml")
        for init in (member / "src").rglob("__init__.py"):
            target = dst / init.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
PY
  echo "$dir"
}

# Remove one line, searched for after an anchor; fail the case if it is not there.
drop() { # file anchor line
  "${py[@]}" - "$1" "$2" "$3" <<'PY'
import sys
from pathlib import Path

path, anchor, line = Path(sys.argv[1]), sys.argv[2], sys.argv[3] + "\n"
text = path.read_text(encoding="utf-8")
start = text.find(anchor)
at = text.find(line, start) if start >= 0 else -1
if at < 0:
    sys.exit(f"cannot plant: {line.strip()!r} after {anchor!r} in {path}")
path.write_text(text[:at] + text[at + len(line) :], encoding="utf-8")
PY
}

run() { # tree -> "exit<TAB>output"
  local out code
  out=$("${py[@]}" "$1/scripts/verify_architecture.py" --root "$1" 2>&1)
  code=$?
  printf '%s\t%s' "$code" "$out"
}

red() { # description tree expected-line
  local result code out
  result=$(run "$2")
  code=${result%%$'\t'*}
  out=${result#*$'\t'}
  check "$1: exits 1" 1 "$code"
  if grep -qF -- "$3" <<<"$out"; then check "$1: names it" yes yes; else check "$1: names it ($3)" yes no; fi
}

# The checkout itself.
"${py[@]}" "$here/scripts/verify_architecture.py" >/dev/null 2>&1
check "the checkout passes" 0 $?

base=$(skeleton)
result=$(run "$base")
check "the skeleton passes before anything is planted" 0 "${result%%$'\t'*}"

d=$(skeleton) && drop "$d/pyproject.toml" "[tool.uv.sources]" "dw-evals = { workspace = true }"
red "dw_evals absent from [tool.uv.sources]" "$d" "dw_evals: missing from [tool.uv.sources]"

d=$(skeleton) && drop "$d/pyproject.toml" "known-first-party = [" '    "dw_evals",'
red "dw_evals absent from known-first-party" "$d" "dw_evals: missing from ruff known-first-party"

d=$(skeleton) && drop "$d/pyproject.toml" "mypy_path = [" '    "packages/python/dw_evals/src",'
red "dw_evals absent from mypy_path" "$d" "dw_evals: missing from mypy mypy_path"

d=$(skeleton) && drop "$d/pyproject.toml" "[tool.coverage.run]" '    "packages/python/dw_evals/src",'
red "dw_evals absent from coverage source" "$d" "dw_evals: missing from coverage source"

d=$(skeleton) && drop "$d/pyproject.toml" "root_packages = [" '    "dw_evals",'
red "dw_evals absent from root_packages" "$d" "dw_evals: missing from import-linter root_packages"

d=$(skeleton) && drop "$d/pyproject.toml" "root_packages = [" '    "dw_docgen",'
red "dw_docgen absent from root_packages" "$d" "dw_docgen: missing from import-linter root_packages"

d=$(skeleton) && drop "$d/scripts/verify_architecture.py" "IMPORT_TO_DIST = {" '    "dw_evals": "dw-evals",'
red "dw_evals absent from IMPORT_TO_DIST" "$d" "dw_evals: missing from IMPORT_TO_DIST"

for image in api worker docgen; do
  d=$(skeleton) && drop "$d/infra/docker/$image.Dockerfile" "COPY" \
    "COPY packages/python/dw_evals/pyproject.toml packages/python/dw_evals/pyproject.toml"
  red "dw_evals absent from the $image image's manifests" "$d" \
    "dw_evals: missing from infra/docker/$image.Dockerfile COPY manifest"
done

# R1.2: a domain package outside the domain contract, at the top and nested.
d=$(skeleton)
mkdir -p "$d/packages/python/dw_probe/src/dw_probe/domain" "$d/packages/python/dw_probe/src/dw_probe/core/domain"
printf '[project]\nname = "dw-probe"\n' >"$d/packages/python/dw_probe/pyproject.toml"
touch "$d/packages/python/dw_probe/src/dw_probe/__init__.py" \
  "$d/packages/python/dw_probe/src/dw_probe/domain/__init__.py" \
  "$d/packages/python/dw_probe/src/dw_probe/core/__init__.py" \
  "$d/packages/python/dw_probe/src/dw_probe/core/domain/__init__.py"
red "dw_probe.domain outside the domain contract" "$d" "dw_probe.domain: missing from the source_modules"
red "dw_probe.core.domain outside the domain contract" "$d" "dw_probe.core.domain: missing from the source_modules"

# The guard itself: without the call in main(), a planted case would pass.
d=$(skeleton) && drop "$d/pyproject.toml" "[tool.coverage.run]" '    "packages/python/dw_evals/src",'
drop "$d/scripts/verify_architecture.py" "def main(" "    unregistered = check_registration(root)"
"${py[@]}" - "$d/scripts/verify_architecture.py" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
anchor = "            checked += 1\n"
if anchor not in text:
    sys.exit("cannot plant: the declared-dependency loop moved")
path.write_text(text.replace(anchor, anchor + "    unregistered: list[str] = []\n", 1), encoding="utf-8")
PY
result=$(run "$d")
check "with check_registration() out of main(), the coverage case would pass" 0 "${result%%$'\t'*}"

# R1.4: a context the generator writes passes the check, and the generator is
# what makes it pass.
scaffolded() { # [mutation] -> a full copy of the checkout with one context generated
  local dir
  dir=$(mktemp -d -p "$work")
  (cd "$here" && git ls-files -z | tar --null -T - -cf -) | tar -x -C "$dir"
  if [ -n "${1:-}" ]; then
    "${py[@]}" - "$dir/scripts/new_context.py" "$1" <<'PY'
import sys
from pathlib import Path

path, mutation = Path(sys.argv[1]), sys.argv[2]
text = path.read_text(encoding="utf-8")
old, new = {
    "docgen": ('("api.Dockerfile", "worker.Dockerfile", "docgen.Dockerfile")', '("api.Dockerfile", "worker.Dockerfile")'),
    "domain": ("    text = _join_domain_contract(text, ctx)\n", ""),
}[mutation]
if old not in text:
    sys.exit(f"cannot plant: {mutation}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
PY
  fi
  (cd "$dir" && "${py[@]}" scripts/new_context.py --name smoke_ctx >/dev/null 2>&1)
  echo "$dir"
}

d=$(scaffolded)
result=$(run "$d")
check "a generated context passes the registration check" 0 "${result%%$'\t'*}"

d=$(scaffolded docgen)
red "a generator that skips docgen.Dockerfile" "$d" "dw_smoke_ctx: missing from infra/docker/docgen.Dockerfile COPY manifest"

d=$(scaffolded domain)
red "a generator that skips the domain contract" "$d" "dw_smoke_ctx.domain: missing from the source_modules"

echo "verify_architecture registration: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
