#!/usr/bin/env bash
# Tests for scripts/verify_compose_policy.py (studio-skeleton R8; SKEL16, SKEL17).
#
#   bash scripts/test_compose_policy.sh
#
# The first case runs the check on this checkout, which must pass. Every other
# case copies the compose files, the Dockerfiles, ci.yml, docs/adr/, .env.example
# and the check itself into a throwaway tree, adds a probe service that passes
# every rule (the control case proves it does), plants exactly one defect, and
# requires the check to exit 1 with the line naming that kind, service and rule.
# A case that cannot plant its defect fails loudly instead of passing
# (failure-modes.md #3). The check reads what `docker compose config` renders,
# so Docker must be available. The base violation set is always read from this
# repository (--base-repo), which holds BASE_SHA.
set -uo pipefail

here=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if [ -x "$here/.venv/bin/python" ]; then
  py=("$here/.venv/bin/python")
elif [ -x "$here/.venv/Scripts/python.exe" ]; then
  py=("$here/.venv/Scripts/python.exe")
else
  py=(uv run --project "$here" python)
fi

PINNED='alpine:3.20.10@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc'

passed=0
failed=0
check() { # description expected actual
  if [ "$2" = "$3" ]; then
    passed=$((passed + 1))
  else
    failed=$((failed + 1))
    echo "FAIL: $1 (expected $2, got $3)"
    sed 's/^/    | /' "$work/out" | head -20
  fi
}

edit() { # file old new: replace the first occurrence; a missing one is a failed case
  if ! "${py[@]}" -I - "$@" <<'PY'; then
import pathlib, sys
path, old, new = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_bytes().decode("utf-8")
if old not in text:
    sys.exit(f"mutation target not found in {path.name}: {old!r}")
path.write_bytes(text.replace(old, new, 1).encode("utf-8"))
PY
    failed=$((failed + 1))
    echo "FAIL: could not plant the defect in $1"
  fi
}

# --- the tree every case starts from ---------------------------------------

pristine="$work/pristine"
mkdir -p "$pristine/infra" "$pristine/.github/workflows" "$pristine/docs" "$pristine/scripts"
cp -r "$here/infra/compose" "$pristine/infra/compose"
mkdir -p "$pristine/infra/docker"
cp "$here"/infra/docker/*.Dockerfile "$pristine/infra/docker/"
cp "$here/.github/workflows/ci.yml" "$pristine/.github/workflows/ci.yml"
cp -r "$here/docs/adr" "$pristine/docs/adr"
cp "$here/.env.example" "$pristine/.env.example"
cp "$here/scripts/verify_compose_policy.py" "$here/scripts/verify_invariants.py" "$pristine/scripts/"
printf 'FROM %s\nCMD ["true"]\n' "$PINNED" >"$pristine/infra/docker/probe.Dockerfile"
# Two networks for the probe: its own (internal) and an open one.
edit "$pristine/infra/compose/docker-compose.yml" $'networks:\n  dw-internal:\n' \
  $'networks:\n  probe-net:\n    internal: true\n  probe-open: {}\n  dw-internal:\n'

tree() { # name -> a fresh copy of the pristine tree
  rm -rf "${work:?}/$1"
  cp -r "$pristine" "$work/$1"
  echo "$work/$1"
}

# The probe, appended to the base file. Each P_* variable overrides one line;
# set it empty to drop the line. Extra lines come as arguments.
probe() { # tree [extra service lines...]
  local t=$1 line
  shift
  {
    printf '\n  probe-svc:\n'
    [ -n "${P_IMAGE-$PINNED}" ] && printf '    image: %s\n' "${P_IMAGE-$PINNED}"
    [ -n "${P_PROFILES-[probe-svc]}" ] && printf '    profiles: %s\n' "${P_PROFILES-[probe-svc]}"
    [ -n "${P_NETWORKS-[probe-net]}" ] && printf '    networks: %s\n' "${P_NETWORKS-[probe-net]}"
    printf '    healthcheck:\n      test: ["CMD-SHELL", "exit 0"]\n'
    [ -n "${P_READ_ONLY-true}" ] && printf '    read_only: %s\n' "${P_READ_ONLY-true}"
    printf '    cap_drop: [ALL]\n    security_opt: ["no-new-privileges:true"]\n'
    [ -n "${P_INIT-true}" ] && printf '    init: %s\n' "${P_INIT-true}"
    printf '    user: "1000:1000"\n    mem_limit: 64m\n    pids_limit: %s\n' "${P_PIDS-64}"
    for line in "$@"; do printf '    %s\n' "$line"; done
  } >>"$t/infra/compose/docker-compose.yml"
  for overlay in ${P_DEPLOYED-uat prod}; do
    # pids too: compose refuses a pids_limit that differs from the deploy limit.
    printf '  probe-svc:\n    deploy:\n      resources:\n        limits:\n          memory: 64m\n          pids: %s\n' "${P_PIDS-64}" \
      >>"$t/infra/compose/docker-compose.$overlay.yml"
  done
  local anchor='          docker compose --env-file .env -f infra/compose/docker-compose.yml --profile infra config -q'
  local lines=$anchor
  [ -n "${P_CI_CONFIG-yes}" ] &&
    lines+=$'\n          docker compose --env-file .env -f infra/compose/docker-compose.yml --profile probe-svc config -q'
  [ -n "${P_CI_SMOKE-yes}" ] &&
    lines+=$'\n          docker compose --env-file .env -f infra/compose/docker-compose.yml --profile probe-svc up -d --wait probe-svc'
  edit "$t/.github/workflows/ci.yml" "$anchor" "$lines"
}

waive() { # tree python-statement: appended to the copy's exception table
  edit "$1/scripts/verify_compose_policy.py" $'CALLERS: dict[str, frozenset[str]] = {}\n' \
    "$2"$'\nCALLERS: dict[str, frozenset[str]] = {}\n'
}

policy() { # tree [base-repo] -> exit code; output in $work/out
  "${py[@]}" "$1/scripts/verify_compose_policy.py" --root "$1" --base-repo "${2:-$here}" \
    >"$work/out" 2>&1
  echo $?
}

says() { # exact line -> yes when the check printed it
  if grep -qxF "$1" "$work/out"; then echo yes; else echo no; fi
}

mentions() { # service rule -> yes when any line names both
  if grep -qE "^[a-z-]+ $1 $2\$" "$work/out"; then echo yes; else echo no; fi
}

planted() { # description expected-line -> exit 1 with that line
  local code=$1
  shift
  check "$1: exit" 1 "$code"
  check "$1: says '$2'" yes "$(says "$2")"
}

# --- the checkout, and the control ------------------------------------------

"${py[@]}" "$here/scripts/verify_compose_policy.py" >"$work/out" 2>&1
check "R8.8 the checkout passes" 0 $?

t=$(tree control)
probe "$t"
check "control: the probe passes every rule" 0 "$(policy "$t")"

# --- one defect per rule ------------------------------------------------------

t=$(tree dw-internal)
P_NETWORKS='[dw-internal]' probe "$t"
planted "$(policy "$t")" "R8.1 the probe on dw-internal" "violation probe-svc dw-internal"

t=$(tree dw-internal-waived)
P_NETWORKS='[dw-internal]' probe "$t"
waive "$t" 'EXCEPTIONS["dw-internal"]["probe-svc"] = "no ADR"'
planted "$(policy "$t")" "R8.1 waived without an ADR" "exception-needs-adr probe-svc dw-internal"

t=$(tree open-network)
P_NETWORKS='[probe-open]' probe "$t"
planted "$(policy "$t")" "R8.2 a network that is not internal" "violation probe-svc internal-network"

t=$(tree shares-with-api)
probe "$t"
edit "$t/infra/compose/docker-compose.host.yml" "    networks: [dw-proxy]" "    networks: [dw-proxy, probe-net]"
planted "$(policy "$t")" "R8.2 sharing a network with api" "violation probe-svc internal-network"

t=$(tree declared-caller)
probe "$t"
edit "$t/infra/compose/docker-compose.host.yml" "    networks: [dw-proxy]" "    networks: [dw-proxy, probe-net]"
waive "$t" 'CALLERS["probe-svc"] = frozenset({"api"})'
policy "$t" >/dev/null
check "R8.2 a caller CALLERS declares passes" no "$(mentions probe-svc internal-network)"

t=$(tree no-digest)
P_IMAGE='alpine:3.20' probe "$t"
planted "$(policy "$t")" "R8.3 a pulled image without a digest" "violation probe-svc digest"

t=$(tree built-unpinned)
printf 'FROM alpine:3.20\n' >"$t/infra/docker/probe.Dockerfile"
P_IMAGE='dw-probe:local' probe "$t" 'build: {context: ../.., dockerfile: infra/docker/probe.Dockerfile}'
planted "$(policy "$t")" "R8.3 a built image FROM an unpinned base" "violation probe-svc digest"

t=$(tree ports-in-base)
probe "$t" 'ports: ["127.0.0.1:18099:80"]'
planted "$(policy "$t")" "R8.4 ports in the base file" "violation probe-svc ports"

t=$(tree ports-in-dev)
probe "$t"
printf '\n  probe-svc:\n    ports: ["127.0.0.1:18099:80"]\n' >>"$t/infra/compose/docker-compose.dev.yml"
policy "$t" >/dev/null
check "R8.4 ports only in the dev overlay pass" no "$(mentions probe-svc ports)"

t=$(tree no-read-only)
P_READ_ONLY='' probe "$t"
planted "$(policy "$t")" "R8.5 no read_only" "violation probe-svc read_only"

t=$(tree no-init)
P_INIT='' probe "$t"
planted "$(policy "$t")" "R8.5 no init" "violation probe-svc init"

t=$(tree no-prod-deploy)
P_DEPLOYED='uat' probe "$t"
planted "$(policy "$t")" "R8.5 no deploy memory in prod" "violation probe-svc deploy-resources"

t=$(tree pids-unlimited)
P_PIDS='-1' probe "$t"
planted "$(policy "$t")" "R8.5 pids_limit -1 (unlimited)" "violation probe-svc pids_limit"

t=$(tree network-mode-service)
P_NETWORKS='' probe "$t" 'network_mode: "service:qdrant"'
planted "$(policy "$t")" "R8.5 network_mode service:qdrant" "violation probe-svc network_mode"

t=$(tree network-mode-host)
P_NETWORKS='' probe "$t" 'network_mode: host'
planted "$(policy "$t")" "R8.5 network_mode host" "violation probe-svc network_mode"

t=$(tree privileged)
probe "$t" 'privileged: true'
planted "$(policy "$t")" "R8.5 privileged" "violation probe-svc privileged"

t=$(tree cap-add)
probe "$t" 'cap_add: [NET_ADMIN]'
planted "$(policy "$t")" "R8.5 cap_add" "violation probe-svc cap_add"

t=$(tree pid-host)
probe "$t" 'pid: host'
planted "$(policy "$t")" "R8.5 pid host" "violation probe-svc pid-host"

t=$(tree ipc-host)
probe "$t" 'ipc: host'
planted "$(policy "$t")" "R8.5 ipc host" "violation probe-svc ipc-host"

t=$(tree docker-socket)
probe "$t" 'volumes: ["/var/run/docker.sock:/var/run/docker.sock"]'
planted "$(policy "$t")" "R8.5 the docker socket" "violation probe-svc docker-socket"

t=$(tree profile-full)
P_PROFILES='[full]' probe "$t"
planted "$(policy "$t")" "R8.6 only the full profile" "violation probe-svc profile"

t=$(tree no-ci-config)
P_CI_CONFIG='' probe "$t"
planted "$(policy "$t")" "R8.7 no config -q line" "violation probe-svc ci-config"

t=$(tree no-ci-smoke)
P_CI_SMOKE='' probe "$t"
planted "$(policy "$t")" "R8.7 no up --wait line" "violation probe-svc ci-smoke"

t=$(tree built-unscanned)
P_IMAGE='dw-probe:local' probe "$t" 'build: {context: ../.., dockerfile: infra/docker/probe.Dockerfile}'
planted "$(policy "$t")" "R8.7 a built image trivy does not scan" "violation probe-svc ci-trivy"

t=$(tree built-scanned)
P_IMAGE='dw-probe:local' probe "$t" 'build: {context: ../.., dockerfile: infra/docker/probe.Dockerfile}'
edit "$t/.github/workflows/ci.yml" "for image in dw-api:local" "for image in dw-probe:local dw-api:local"
check "R8.7 a built image in the trivy list passes" 0 "$(policy "$t")"

t=$(tree pulled-unscanned)
probe "$t"
edit "$t/.github/workflows/ci.yml" \
  "pinned=\$(grep -hoE 'image: *[^ ]+@sha256:[0-9a-f]{64}' infra/compose/*.yml" "pinned=\$(true"
planted "$(policy "$t")" "R8.7 the pinned-pull scan removed" "violation probe-svc ci-trivy"

# --- the exception table -------------------------------------------------------

t=$(tree postgres-unwaived)
waive "$t" 'del EXCEPTIONS["dw-internal"]["postgres"]'
planted "$(policy "$t")" "R8.8 postgres taken off the dw-internal list" "violation postgres dw-internal"

t=$(tree stale)
waive "$t" 'EXCEPTIONS["read_only"]["docgen-gateway"] = "stale"'
planted "$(policy "$t")" "R8.9 an exception for a rule the service meets" "stale-exception docgen-gateway read_only"

t=$(tree gateway-writable)
edit "$t/infra/compose/docker-compose.yml" $'    networks: [dw-sandbox, dw-internal, dw-edge]\n    read_only: true\n' \
  $'    networks: [dw-sandbox, dw-internal, dw-edge]\n'
planted "$(policy "$t")" "R8.9 docgen-gateway loses read_only" "violation docgen-gateway read_only"

cat >"$pristine/docs/adr/9999-probe-svc.md" <<'EOF'
---
status: Accepted
date: 2026-11-05
---

# 9999. The probe leaves its network

`probe-svc` is exempt from `internal-network`.
EOF

adr_case() { # name waiver-adr-arg -> sets t: the probe on an open network, waived
  t=$(tree "$1")
  P_NETWORKS='[probe-open]' probe "$t"
  waive "$t" "EXCEPTIONS[\"internal-network\"] = {\"probe-svc\": Waiver(\"probe\"$2)}"
}

adr_case adr-none ''
planted "$(policy "$t")" "R8.10 a waiver with no ADR" "exception-needs-adr probe-svc internal-network"

adr0115=$(cd "$here" && ls docs/adr/0115-*.md | head -1)
adr_case adr-other ", adr=\"$adr0115\""
planted "$(policy "$t")" "R8.10 an Accepted ADR that does not name the probe" \
  "exception-needs-adr probe-svc internal-network"

adr_case adr-accepted ', adr="docs/adr/9999-probe-svc.md"'
policy "$t" >/dev/null
check "R8.10 an Accepted ADR naming both admits" no "$(mentions probe-svc internal-network)"

adr_case adr-proposed ', adr="docs/adr/9999-probe-svc.md"'
edit "$t/docs/adr/9999-probe-svc.md" "status: Accepted" "status: Proposed"
planted "$(policy "$t")" "R8.10 the same ADR, Proposed" "exception-needs-adr probe-svc internal-network"

t=$(tree postgres-privileged-waived)
edit "$t/infra/compose/docker-compose.yml" "    command: [\"postgres\", \"-c\", \"wal_level=logical\"]" \
  $'    command: ["postgres", "-c", "wal_level=logical"]\n    privileged: true'
waive "$t" 'EXCEPTIONS["privileged"] = {"postgres": "not at the base commit"}'
planted "$(policy "$t")" "R8.10 a pre-existing service waived for a new violation" \
  "exception-needs-adr postgres privileged"
check "R8.10 that is not reported stale" no "$(says 'stale-exception postgres privileged')"

t=$(tree postgres-privileged)
edit "$t/infra/compose/docker-compose.yml" "    command: [\"postgres\", \"-c\", \"wal_level=logical\"]" \
  $'    command: ["postgres", "-c", "wal_level=logical"]\n    privileged: true'
planted "$(policy "$t")" "R8.10 a pre-existing service, a new violation, no line" "violation postgres privileged"

# --- the check refuses to judge what it cannot see ------------------------------

t=$(tree no-base)
git init -q "$work/empty-repo"
code=$(policy "$t" "$work/empty-repo")
check "BASE_SHA missing: exit" 1 "$code"
check "BASE_SHA missing: names it" yes "$(grep -q '^BASE_SHA [0-9a-f]\{40\} is not in' "$work/out" && echo yes || echo no)"

t=$(tree broken-overlay)
# A `:?` variable nobody sets: the prod combination cannot render at all.
printf '\n  probe-broken:\n    image: %s\n    environment:\n      PROBE: ${PROBE_UNSET:?}\n' "$PINNED" \
  >>"$t/infra/compose/docker-compose.prod.yml"
code=$(policy "$t")
check "a combination that does not render: exit" 1 "$code"
check "a combination that does not render: names it" yes \
  "$(grep -q '^combination prod (docker-compose.yml + docker-compose.prod.yml) did not render' "$work/out" && echo yes || echo no)"

echo "compose policy tests: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
