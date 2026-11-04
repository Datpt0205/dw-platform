#!/usr/bin/env bash
# Sets up the code-sandbox 01 spike host: Docker rootless for the current user,
# with cgroup v2 controllers delegated, gVisor `runsc` registered as the runtime
# `runsc-dw` (systrap, no network), and the measurement image built in that
# engine. ADR-0119 (Proposed) decision 1. The CI job `sandbox-spike` and ticket
# 02 (the target host) both run this file unchanged: it is the one owner of how
# the spike host is built.
#
#   bash tests/spike/sandbox/setup_rootless.sh                     # as the unprivileged user, with sudo
#   bash tests/spike/sandbox/setup_rootless.sh --rootful-fallback  # also the rootful daemon
#
# --rootful-fallback also registers `runsc-dw` in the host's rootful daemon and
# builds the image there: ADR-0119 (Proposed) decision 2's fallback if the
# rootless engine fails a cap, measured by the same tests
# (DW_SPIKE_DOCKER_HOST=unix:///var/run/docker.sock).
#
# Every pin is here, and the harness records each one in the results table:
#   gVisor release   RUNSC_RELEASE, its tarball checked against RUNSC_SHA512 below
#                    AND against the release's own gvisor.tar.bz2.sha512
#   base image       BASE_IMAGE, by digest
#   pandas           PANDAS_VERSION, with numpy and the rest hash-pinned in
#                    requirements.txt; a mismatch between the two stops here
#   rootless extras  the exact version of the installed docker-ce (the pair must
#                    match), or DOCKER_CE_VERSION for both on a host without one
# Nothing is fetched by a `latest` path, and every download uses `curl --fail`.
set -euo pipefail

fallback=0
case "${1:-}" in
  "") ;;
  --rootful-fallback) fallback=1 ;;
  *) echo "usage: $0 [--rootful-fallback]" >&2; exit 2 ;;
esac

RUNSC_RELEASE="20261019"
RUNSC_SHA512="7cbc2aeeee809dcccfb40e612504a1b76f2c119790cee59e482f7b35428cccc4f71705e7e322442d07d1f7d29b5d9e72e31319fc3088d6dcbec9fc7c1f0d8881"
BASE_IMAGE="python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30"
PANDAS_VERSION="3.0.5"
DOCKER_CE_VERSION="5:29.9.1-1~ubuntu.24.04~noble"
DOCKER_APT_KEY_FINGERPRINT="9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
SPIKE_IMAGE="dw-sandbox-spike:1"
RUNTIME_NAME="runsc-dw"
GVISOR_DIR="/usr/local/lib/gvisor/${RUNSC_RELEASE}"
DELEGATED="cpu cpuset io memory pids"

here=$(cd "$(dirname "$0")" && pwd)
log() { printf '[setup_rootless] %s\n' "$*"; }
die() { printf '[setup_rootless] ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" != "0" ] || die "run as the unprivileged user that will own the engine, not root"
[ "$(uname -m)" = "x86_64" ] || die "the pinned gVisor release is x86_64 only"
[ -f /sys/fs/cgroup/cgroup.controllers ] || die "cgroup v2 (unified hierarchy) is required"
grep -qx "pandas==${PANDAS_VERSION} \\\\" "$here/requirements.txt" \
  || die "requirements.txt does not pin pandas==${PANDAS_VERSION}; regenerate it or change PANDAS_VERSION"

uid=$(id -u)
user=$(id -un)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# 1. Packages. Ubuntu's own are taken at the archive's current version (the
# archive keeps no old ones to pin to); the harness records what was installed.
log "apt prerequisites"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
  uidmap dbus-user-session slirp4netns iptables iproute2 curl ca-certificates gnupg bzip2 >/dev/null

# Docker's apt repository: the GitHub runner image removes it after installing
# docker-ce, and a target host may never have had it. The key is checked by
# fingerprint before apt trusts it.
keyring=/usr/share/keyrings/dw-spike-docker.gpg
curl --fail -sSL https://download.docker.com/linux/ubuntu/gpg -o "$work/docker.asc"
gpg --show-keys --with-colons "$work/docker.asc" | grep -q "^fpr:::::::::${DOCKER_APT_KEY_FINGERPRINT}:" \
  || die "Docker's apt key does not carry fingerprint ${DOCKER_APT_KEY_FINGERPRINT}"
gpg --dearmor <"$work/docker.asc" | sudo tee "$keyring" >/dev/null
# shellcheck source=/dev/null
codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
echo "deb [arch=amd64 signed-by=${keyring}] https://download.docker.com/linux/ubuntu ${codename} stable" \
  | sudo tee /etc/apt/sources.list.d/dw-spike-docker.list >/dev/null
sudo apt-get update -qq

if engine_version=$(dpkg-query -W -f='${Version}' docker-ce 2>/dev/null) && [ -n "$engine_version" ]; then
  log "docker-ce ${engine_version} is installed; rootless extras at the same version"
else
  engine_version="$DOCKER_CE_VERSION"
  log "no docker-ce; installing docker-ce ${engine_version}"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    "docker-ce=${engine_version}" "docker-ce-cli=${engine_version}" >/dev/null
fi
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
  "docker-ce-rootless-extras=${engine_version}" >/dev/null

# 2. Ubuntu 24.04 restricts unprivileged user namespaces through AppArmor
# (kernel.apparmor_restrict_unprivileged_userns). RootlessKit and runsc each
# create one, so each gets the profile Docker's rootless guide gives RootlessKit:
# unconfined, plus `userns`. Written only where the restriction is on.
restrict=/proc/sys/kernel/apparmor_restrict_unprivileged_userns
if [ -f "$restrict" ] && [ "$(cat "$restrict")" = "1" ]; then
  log "AppArmor restricts unprivileged user namespaces; profiles for rootlesskit and runsc"
  sudo tee /etc/apparmor.d/dw-spike-rootlesskit >/dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>

profile dw-spike-rootlesskit /usr/bin/rootlesskit flags=(unconfined) {
  userns,
}
EOF
  sudo tee /etc/apparmor.d/dw-spike-runsc >/dev/null <<EOF
abi <abi/4.0>,
include <tunables/global>

profile dw-spike-runsc ${GVISOR_DIR}/** flags=(unconfined) {
  userns,
}
EOF
  sudo apparmor_parser -r /etc/apparmor.d/dw-spike-rootlesskit /etc/apparmor.d/dw-spike-runsc
fi

# The user-namespace facts that decide whether RootlessKit may start, each on
# one line, so the last lines of a failed log carry them.
userns_facts() {
  local name
  for name in kernel/apparmor_restrict_unprivileged_userns kernel/unprivileged_userns_clone \
    user/max_user_namespaces; do
    echo "sysctl ${name}: $(cat "/proc/sys/${name}" 2>/dev/null || echo absent)"
  done
  echo "apparmor: $(sudo aa-status 2>/dev/null | grep -iE 'rootless|dw-spike' | tr -s ' \n' ' ')"
  echo "rootlesskit true: $(rootlesskit true 2>&1 | tail -n 2 | tr '\n' ' ')"
  echo "dmesg: $(sudo dmesg 2>/dev/null | grep -i 'apparmor=' | tail -n 2 | tr '\n' ' ')"
}
userns_facts

# 3. Subordinate ids for the user namespace: 65536 of them, past every range
# already handed out, so no two users share one.
for map in subuid subgid; do
  if ! grep -q "^${user}:" "/etc/${map}"; then
    start=$(awk -F: '$2 + $3 > end { end = $2 + $3 } END { print (end > 100000 ? end : 100000) }' "/etc/${map}")
    log "adding ${map} ${start}-$((start + 65535)) for ${user}"
    sudo usermod "--add-${map}s" "${start}-$((start + 65535))" "$user"
  fi
done

# 4. cgroup v2 delegation to the user's systemd instance, then linger so that
# instance runs without a login session. A user manager already running started
# before the drop-in, so it is restarted to pick the controllers up.
log "delegating ${DELEGATED} to user@.service"
sudo mkdir -p /etc/systemd/system/user@.service.d
printf '[Service]\nDelegate=%s\n' "$DELEGATED" \
  | sudo tee /etc/systemd/system/user@.service.d/dw-spike-delegate.conf >/dev/null
sudo systemctl daemon-reload
sudo loginctl enable-linger "$user"
if systemctl is-active --quiet "user@${uid}.service"; then
  sudo systemctl restart "user@${uid}.service"
else
  sudo systemctl start "user@${uid}.service"
fi
export XDG_RUNTIME_DIR="/run/user/${uid}"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
for _ in $(seq 1 30); do
  [ -S "${XDG_RUNTIME_DIR}/bus" ] && break
  sleep 1
done
[ -S "${XDG_RUNTIME_DIR}/bus" ] || die "the user's session bus did not appear at ${XDG_RUNTIME_DIR}/bus"
controllers="/sys/fs/cgroup/user.slice/user-${uid}.slice/user@${uid}.service/cgroup.controllers"
log "delegated controllers: $(cat "$controllers" 2>/dev/null || echo "unreadable: $controllers")"

# 5. gVisor, by release date, checked twice: against the hash pinned above and
# against the release's own .sha512 file.
log "gVisor release ${RUNSC_RELEASE}"
base_url="https://storage.googleapis.com/gvisor/releases/release/${RUNSC_RELEASE}/x86_64"
curl --fail -sSL "${base_url}/gvisor.tar.bz2" -o "$work/gvisor.tar.bz2"
curl --fail -sSL "${base_url}/gvisor.tar.bz2.sha512" -o "$work/gvisor.tar.bz2.sha512"
(cd "$work" && sha512sum -c gvisor.tar.bz2.sha512)
echo "${RUNSC_SHA512}  $work/gvisor.tar.bz2" | sha512sum -c -
sudo mkdir -p "$GVISOR_DIR"
sudo tar -xjf "$work/gvisor.tar.bz2" -C "$GVISOR_DIR" --no-same-owner
sudo chown -R root:root "$GVISOR_DIR"
sudo chmod -R go-w "$GVISOR_DIR"
"${GVISOR_DIR}/runsc" --version

# 6. The runtime, in the rootless engine's own daemon.json, written before the
# engine first starts. --ignore-cgroups because runsc cannot place a sandbox in
# a cgroup under a rootless engine (measured on release 20261019): its systemd
# driver speaks only to the system bus ("systemd error: Permission denied"),
# and pointed at the user's bus it then writes the hierarchy root's
# cgroup.subtree_control ("permission denied"). Without the flag no container
# starts; with it the sandbox stays in the engine's own cgroup, and the
# harness measures what the caps then do.
mkdir -p "${HOME}/.config/docker"
cat >"${HOME}/.config/docker/daemon.json" <<EOF
{
  "runtimes": {
    "${RUNTIME_NAME}": {
      "path": "${GVISOR_DIR}/runsc",
      "runtimeArgs": ["--platform=systrap", "--network=none", "--ignore-cgroups"]
    }
  }
}
EOF

# 7. The rootless engine. --force: a rootful daemon may run beside it (the
# GitHub runner has one; row 9 of the table measures exactly that).
log "installing the rootless engine"
# On failure: the engine's own last words, then the user-namespace facts that
# decide whether RootlessKit may start at all, last so a log's tail shows them.
engine_log() {
  journalctl --user --unit docker.service -n 12 --no-pager >&2 || true
  userns_facts >&2
}
if systemctl --user --quiet is-enabled docker.service 2>/dev/null; then
  systemctl --user restart docker.service || { engine_log; die "the rootless engine did not restart"; }
else
  dockerd-rootless-setuptool.sh install --force || { engine_log; die "the rootless engine did not start"; }
fi
# Every docker call below, buildx included, goes to the rootless engine.
export DOCKER_HOST="unix://${XDG_RUNTIME_DIR}/docker.sock"
for _ in $(seq 1 30); do
  docker info >/dev/null 2>&1 && break
  sleep 1
done
docker info --format '{{json .Runtimes}}' | grep -q "\"${RUNTIME_NAME}\"" \
  || die "the rootless engine does not list the runtime ${RUNTIME_NAME}"

# 8. The measurement image, built in the rootless engine itself.
log "building ${SPIKE_IMAGE} from ${BASE_IMAGE}"
docker build --quiet \
  --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
  --label "dw.spike.base=${BASE_IMAGE}" \
  --label "dw.spike.runsc_release=${RUNSC_RELEASE}" \
  --label "dw.spike.rootless_extras=${engine_version}" \
  -t "$SPIKE_IMAGE" "$here"

# 9. The fallback, only when asked: the same runtime without --ignore-cgroups
# (a root engine places the sandbox in the container's cgroup), merged into the
# rootful daemon's existing configuration, and the same image built there.
if [ "$fallback" = 1 ]; then
  log "registering ${RUNTIME_NAME} in the rootful daemon (decision 2's fallback)"
  sudo python3 - "${GVISOR_DIR}/runsc" "$RUNTIME_NAME" <<'EOF'
import json, pathlib, sys
path = pathlib.Path("/etc/docker/daemon.json")
config = json.loads(path.read_text()) if path.exists() and path.read_text().strip() else {}
config.setdefault("runtimes", {})[sys.argv[2]] = {
    "path": sys.argv[1],
    "runtimeArgs": ["--platform=systrap", "--network=none"],
}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(config, indent=2))
EOF
  sudo systemctl restart docker.service
  rootful="unix:///var/run/docker.sock"
  for _ in $(seq 1 30); do
    DOCKER_HOST="$rootful" docker info >/dev/null 2>&1 && break
    sleep 1
  done
  DOCKER_HOST="$rootful" docker info --format '{{json .Runtimes}}' | grep -q "\"${RUNTIME_NAME}\"" \
    || die "the rootful daemon does not list the runtime ${RUNTIME_NAME}"
  DOCKER_HOST="$rootful" docker build --quiet \
    --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
    --label "dw.spike.base=${BASE_IMAGE}" \
    --label "dw.spike.runsc_release=${RUNSC_RELEASE}" \
    -t "$SPIKE_IMAGE" "$here"
fi

log "done. The harness talks to this engine at ${DOCKER_HOST}"
