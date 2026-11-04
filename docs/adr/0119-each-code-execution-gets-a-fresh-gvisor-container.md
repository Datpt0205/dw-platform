---
status: Proposed (held until code-sandbox/01 reports its numbers; Đạt, 2026-10-23)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/code-sandbox/spec.md
    - ../../apps/docgen/src/dw_docgen/settings.py
    - ../../infra/compose/docker-compose.yml
    - ../../infra/compose/docker-compose.prod.yml
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/ports.py
---

# 0119. Every execution of tenant code runs in its own fresh gVisor container launched by a first-party sandbox-runner, on a separate host before any deployed environment runs tenant code

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It rests on three requester
decisions. D7 (2026-10-22): v1 has a code node; every execution of tenant-written code runs in its own fresh
container with no network and with CPU, memory, pids, disk and wall-clock limits; the one-container shape of
document generation is not acceptable for it; infrastructure beyond the current 2 vCPU / 8 GB host is expected. D2
(2026-10-22): a code node exists only behind a dedicated permission and a plan entitlement. D14 (2026-10-23): the
primary host grows to at least 4 vCPU / 16 GB before OpenBao and the egress proxy ship, and a separate VM carries the
sandbox-runner before any tenant code runs in uat or production, sized by measurement first. Its call on DO-45 was
confirmed on 2026-10-23 for languages and billing (DO-45.1), and the lifetime of agent code tools moved to Open for W3
(DO-45.2). The `code-sandbox` spec owns it.

## Context

- **Nothing runs tenant code safely today.** `apps/docgen` runs every command in one long-lived container under one
  uid with a shared `/work` tmpfs (`infra/compose/docker-compose.yml:333-370`), one command at a time because "two
  sessions sharing a container share a uid" (`apps/docgen/src/dw_docgen/settings.py:38-41`). The residual-risk ADR
  that comment names (`:40`) is not in `docs/adr/`. D7 rejects this shape for tenant code.
- **The host is already full.** The production overlay is "Sized for a 2 vCPU / ~8 GB box"
  (`infra/compose/docker-compose.prod.yml:24`); its memory ceilings add up to about 7.0 GB before docgen's
  `mem_limit: 3g` (`infra/compose/docker-compose.yml:369`), arithmetic the planning briefs did over both files (FOG-23).
- **Isolation without `/dev/kvm`.** gVisor's systrap platform "is a better choice when running inside a VM, or on a
  machine without virtualization support" (https://gvisor.dev/docs/architecture_guide/platforms/), and `runsc` can
  turn networking off at the runtime (https://gvisor.dev/docs/user_guide/networking/). Kata and Firecracker need
  `/dev/kvm`, unverified on the host. Docker's AuthZ plugins were bypassed (CVE-2024-41110,
  https://www.docker.com/blog/docker-security-advisory-docker-engine-authz-plugin/), and a socket proxy that filters
  by endpoint cannot refuse a privileged create (https://github.com/Tecnativa/docker-socket-proxy). gVisor's
  published startup numbers were taken on ptrace, not systrap, so nothing here is sized from them. All of this was
  gathered by the Studio research on 2026-10-22, is not re-verified here, and has not run on our host (FOG-24).
- **Three callers.** The code node `code.python@1` (ADR-0112 decision 9), the `code` tool kind (ADR-0116), and later
  agent code tools on deepagents' `BaseSandbox`, which keeps files between calls (deepagents 0.7.15 and 0.7.30
  source, read by the research on 2026-10-22).

## Decision

1. **One process holds the engine.** `apps/sandbox-runner`, a uv workspace member (FastAPI, the Engine API over a
   Unix socket with the locked `httpx`, no Docker SDK), is the only process holding the socket of a dedicated
   rootless engine: Docker or Podman under the host user `dwsandbox` (code-sandbox 01 chooses), with the cgroup v2
   controllers `cpu`, `cpuset`, `io`, `memory` and `pids` delegated. The engine's runtime `runsc-dw` is gVisor
   `runsc` registered with `--platform=systrap` and `--network=none`. The runner holds no database, object-store,
   model or tenant credential, runs non-root with a read-only root and `cap_drop: [ALL]`, and sits on the internal
   network `dw-runner` with the worker, which alone holds `DW_SANDBOX_RUNNER_TOKEN`.
2. **Callers pass a profile, never a container.** The runner builds every container from one fixed template. A caller
   passes a sandbox profile, a language, code, input and files, never an image, mount, network or privilege; an
   unknown profile or a limit above the profile's ceiling is `rejected`. When `settings.is_deployed`, the worker's
   adapter refuses to start unless the runner's `/health` reports `rootless: true` and `runtime: runsc-dw`, read from
   the engine's `info` and a canary container's `HostConfig.Runtime`. If the rootless spike fails, the fallback is a
   rootful daemon with `runsc-dw` and the socket in the runner only, its residual risk written into this ADR.
3. **A fresh container per code execution, used once.** The image `dw-code-python:<semver>@sha256:...` is built in CI
   from a lock, scanned by trivy for HIGH and CRITICAL findings, with a root-owned, read-only harness. A container runs
   with `--runtime=runsc-dw`, `--network=none`, `--read-only`, `--init`, `--log-driver=none`, `--user 10001`,
   `--cap-drop=ALL`, `--security-opt=no-new-privileges:true`, `--pids-limit=64`, `--memory` equal to
   `--memory-swap` (no swap), `--cpus`,
   `--cgroup-parent=dw-sandbox.slice`, `--ulimit nofile=256:256` and `--stop-timeout=1`; tmpfs `/work` (64 MiB) and
   `/tmp` (16 MiB) mounted `noexec,nosuid,nodev`; labels `dw.sandbox=1` and `dw.expires`; no environment beyond the
   interpreter's, no secret, and code never in arguments or environment. Sandbox profiles: `py-small` (0.5 vCPU,
   256 MiB, 30 s) and `py-medium` (1 vCPU, 512 MiB, 120 s, when the plan allows). A warm pool per profile (2 on the
   v1 host) holds harness containers with no tenant identity until claimed; each is used once and destroyed, and an
   unclaimed one is recycled after 10 idle minutes. A pool never re-issues a container.
4. **A byte-capped JSON envelope.** stdin carries `entrypoint`, `source`, `input` (at most 1 MiB) and `files` (at most
   10 MiB); stdout carries one result frame of at most 1 MiB plus stdout and stderr tails of at most 64 KiB, counted
   while reading and killed past the cap. Status: `ok`, `error`, `timeout`, `oom`, `output_limit`, `killed` or
   `rejected`. The caller validates the output against its schema and wraps it as untrusted (ADR-0116).
5. **Admitted by the platform, enforced by the runner and the kernel.** One unit meters, limits and prices tenant
   code: the profile's reserved vCPU and GB times wall time, since a container holds its pool slot until it ends
   whether it uses the CPU or not (DO-45.1 (a)). A tenant's concurrency and monthly allowance in that unit come from
   its plan and are admitted before the call through ADR-0121's leases, each sized at the profile's reservation times
   its timeout and settled after; a refusal is `sandbox_quota_exceeded`. The runner's per-tenant semaphore (2) is the
   backstop. The kernel caps the whole class: `dw-sandbox.slice` with `CPUQuota` and `MemoryMax` (v1 host: one vCPU,
   1.5 GiB) and a lower CPU weight than platform services, under a global semaphore equal to pool capacity. Each
   execution is reported through `SandboxUsagePort` as a `sandbox_exec` usage event carrying the profile and the wall
   time. The measured use from the container's cgroup (`usage_usec` in `cpu.stat`, `memory.peak`), read after the
   result frame and before removal, as the harness blocks on stdin until then, is kept for abuse detection. Numbers
   printed inside the container are never trusted.
6. **One door.** `CodeExecutionService.execute(ctx, code_ref, input)` checks the `code_node` plan feature, admits,
   checks the source SHA-256, calls `CodeSandboxPort` (declared in `dw_agent_runtime.ports`, used by the code node and
   the `code` tool kind), meters, and audits `sandbox.execute` with the code hash, image digest, profile and status.
   There is no `studio.code_executions` table: the tool execution row, the usage event and the audit event already
   hold every fact (failure-modes #2). A reaper removes every `dw.sandbox=1` container when the runner starts and
   sweeps any past `dw.expires`.
7. **A hostile-script suite gates every version** of the runner and of every image. CI job `sandbox-hostile`, on a
   runner with `runsc`, runs a fork bomb, a memory bomb, a tmpfs fill, an output flood, an endless sleep and zombie
   reaping; tries `postgres:5432`, `valkey:6379`, `qdrant:6333`, `s3:8333`, `169.254.169.254`, `1.1.1.1:53`, DNS
   and another execution's files; and asserts the uid, the Linux capabilities, `HostConfig.Runtime == runsc-dw`, an empty
   environment, a pool that never re-issues a container and the reaper after `kill -9`. Each test is shown red with
   its guard removed (failure-modes #3).
8. **Who may write code, and in what.** Adding a code node or changing its source needs `studio.code.author`;
   publish and admission need the `code_node` plan entitlement (ADR-0112, D2). v1 runs Python 3.12 only, packages
   arrive only as new image versions, and there is no JavaScript and no skill script (DO-45.1 (a)).
9. **Where it runs.** `apps/docgen` never runs tenant code. Per D14 the runner and its engine move to a second VM
   (2 to 4 vCPU, 4 to 8 GB, sized by code-sandbox 01) that holds no PostgreSQL, Qdrant, object store or secret,
   before any tenant code runs in uat or production (`settings.is_deployed`); only the runner URL and token change.
   v2 puts a Kubernetes backend behind the same runner API: RuntimeClass `gvisor` on a tainted node pool with
   `overhead.podFixed`, Pod Security "restricted", a deny-all NetworkPolicy, a ResourceQuota,
   `automountServiceAccountToken: false`, a ValidatingAdmissionPolicy pinning the pod template, and
   kubernetes-sigs/agent-sandbox warm pools without reuse.
10. **Agent code tools: moved to Open (W3).** v1 runs one fresh container per code execution (D7, decision 3); the
    lifetime of a container behind an agent's code tools is decided in W3 (Open 5, DO-45.2).

## Alternatives considered

- **Reuse `apps/docgen`.** Rejected by D7: one container, one uid and a shared tmpfs leak between executions.
- **Give the API or the worker the engine socket.** Rejected: root-equivalent access inside the processes that hold
  tenant data and database credentials (the API holds three PostgreSQL roles, `infra/compose/docker-compose.yml:256-258`).
- **A socket proxy or an AuthZ plugin in front of a shared engine.** Rejected: neither reliably refuses a privileged
  create.
- **Firecracker or Kata microVMs.** Rejected for v1: they need hardware virtualisation and their own orchestration,
  heavier than v1 needs.
- **WASM or Pyodide.** Rejected: package compatibility gaps and a second Python runtime to reason about.
- **Reusing warm containers.** Rejected: residue from one tenant's execution reaches the next.
- **A hosted code sandbox.** Rejected: tenant data would leave Vietnam (ADR-0123).

## Consequences

- **Order.** code-sandbox ships before workflow-nodes' code node and the `code` tool kind. W1 holds only the spike
  (code-sandbox 01: `runsc` systrap under a rootless engine on the target host and on CI runners); the image, the
  runner, the suite, `CodeExecutionService` and the second VM are W2; agent code tools, the Kubernetes backend and a
  kill that stops containers are W3.
- **Infrastructure.** Hardware beyond the 2 vCPU / 8 GB host before any deployed environment runs tenant code (D7,
  D14): an operator-owned VM, a release-checklist item, and host changes outside compose (the rootless engine, the
  delegated cgroups, `dw-sandbox.slice`). `dw-sandbox` already names docgen's compose network
  (`infra/compose/docker-compose.yml:355`); the runner never joins it.
- **To be measured** in code-sandbox 01: cold start (estimated 0.5 to 1.5 s) and memory per idle pooled container
  (estimated 25 to 50 MB).
- **Tests that must exist,** each shown red with its guard removed: a deployed worker refuses a runner that does not
  report rootless and `runsc-dw`; admission past the tenant's allowance is refused with `sandbox_quota_exceeded`; a
  draft save adding a code node without `studio.code.author` is refused; the hostile-script suite above.

### Contradictions and amendments

- _Contradicts CLAUDE.md:124-129 (the required stack), worth reopening because D7 asks for isolation stronger than
  runc on a host without `/dev/kvm`: the stack gains gVisor `runsc` behind a first-party runner (amendment A10, with
  ADR-0118's LiteLLM)._ It stays within CLAUDE.md:128-129 ("never `latest`"): the image and runtime are pinned.
- `apps/docgen/src/dw_docgen/settings.py:40` points at a residual-risk ADR this repository does not have; this ADR
  does not stand in for it, and docgen keeps its own container for document generation.
- si-platform: none; re-derived.

## Measurements (code-sandbox 01, 02)

Taken by `tests/spike/sandbox/`: `setup_rootless.sh` builds the host (Docker rootless with `cpu cpuset io memory pids`
delegated to `user@<uid>.service`, gVisor release 20261019 checked against its sha512, the runtime `runsc-dw` with
`--platform=systrap --network=none`, `python:3.12-slim@sha256:b18b261e…` with pandas 3.0.5 hash-pinned), `harness.py
measure` writes the ten rows of R1.1 and the tests in `test_runsc_spike.py` hold the thresholds of ticket 01 steps 3 to
5 with the `py-small` flags of decision 3 (`CAPPED_FLAGS`). CI column: run 41919844717 of the `sandbox-spike` job
(commit b138e84, GitHub `ubuntu-24.04`), read from the job's public annotations; `results-ci.json` is its artifact.
Host column: ticket 02, on the target host, with the same script and harness.

One finding shapes every row below. **Under a rootless engine runsc cannot place the sandbox in a cgroup**: its
systemd cgroup driver speaks only to the system bus (`systemd error: Permission denied`), and pointed at the user's bus
it writes the hierarchy root's `cgroup.subtree_control` (`permission denied`). Without `--ignore-cgroups` no container
starts; with it, which `setup_rootless.sh` registers, the sandbox runs in the rootless engine's own cgroup
(`user@1001.service/app.slice/docker.service`) and no container cgroup exists to hold a cap.

| #   | Item (R1.1)                                                       | CI, rootless engine                                                                                                           | Host (ticket 02) |
| --- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| 1   | cgroup v2 delegation to `user@<uid>.service`                      | `cpuset cpu io memory pids`: đạt                                                                                              |                  |
| 2   | fork bomb under runsc (`--pids-limit=64`)                         | 8 475 processes counted in the guest's `/proc`, then the sentry panicked (exit 2); no host `pids.peak` (no cgroup): không đạt |                  |
| 3   | `docker stats` beside `memory.peak` and `usage_usec`              | stats 179.4 MiB, 81 PIDs; no container cgroup to read `memory.peak` or `cpu.stat` from: không đạt                             |                  |
| 4   | `--log-driver none` with 1 MiB on stdin                           | 1 048 576 B back, same sha256, 0.15 s: đạt                                                                                    |                  |
| 5   | tmpfs `noexec` on `/work` and `/tmp`                              | both refused (EACCES): đạt                                                                                                    |                  |
| 6   | cold and warm latency, 20 runs each                               | cold P50 118.8 ms, P95 140.1 ms; warm P50 0.5 ms, P95 1.4 ms: đạt (measured; the 0.5 to 1.5 s estimate was high)              |                  |
| 7   | pandas `import` and `describe()` on 100 000 rows under `py-small` | import 1.09 s, describe 0.02 s, 1.32 s wall of 30 s: đạt                                                                      |                  |
| 8   | reaper after `kill -9` of a harness holding three containers      | 3 outlived it; `docker rm -f` by label in 0.08 s left none, no runsc process after 10 s: đạt                                  |                  |
| 9   | rootless engine beside the runner's rootful daemon                | both ran at once; rootless socket owned by uid 1001, engine reports `name=rootless`: đạt                                      |                  |
| 10  | `/dev/kvm`                                                        | present, not readable by the runner's user: không áp dụng (systrap needs none; the target host's is ticket 02's question)     |                  |

The caps of decision 3 (CS1), the host under bombs (R1.3) and the runtime (CS2), from the Done command on the rootless
engine and the same tests on the runner's rootful daemon with `runsc-dw` registered (decision 2's fallback):

| Test                                         | CI, rootless engine                                    | CI, rootful fallback                                                                        | Host (ticket 02) |
| -------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------- | ---------------- |
| CPU: two busy processes, 10 s, ≤ 0.55 vCPU   | 2.105 vCPU (sandbox process tree): xfail B1            | 0.497 vCPU (`cpu.max 50000 100000`): đạt                                                    |                  |
| Memory: 512 MiB in 16 MiB steps              | all 512 MiB allocated, not killed: xfail B2            | OOMKilled at 224 MiB after 0.94 s, exit 137, `memory.peak` 260 104 192 B ≤ 268 435 456: đạt |                  |
| Pids: fork bomb, ≤ 64 in the guest, survives | 9 910 in the guest: xfail B3                           | sentry panicked at the first fork, host `pids.peak` 64: xfail B3                            |                  |
| R1.3: 10 probes ≤ 5 s, `docker info` ≤ 2 s   | 10 of 10 in 0.27 to 0.36 s; `docker info` 0.046 s: đạt | 10 of 10 in 0.14 to 0.24 s; `docker info` 0.044 s: đạt                                      |                  |
| CS2: `HostConfig.Runtime` and `dmesg` inside | `runsc-dw`, "Starting gVisor...": đạt                  | `runsc-dw`, "Starting gVisor...": đạt                                                       |                  |

**Blocking rows (R1.2).** The code step does not ship while any of these is open; each test stays as written with
`pytest.mark.xfail(strict=True)` naming its row, and turns red the day the cap starts holding.

- **B1 `--cpus`** and **B2 `--memory`**: not held under the rootless engine, for the cgroup reason above. Both hold on
  the rootful fallback. Closing them needs either runsc placing a rootless sandbox in a delegated cgroup (a runsc
  change, or a runtime shim that does it) or decision 2's fallback with its residual risk written here.
- **B3 `--pids-limit`**: not held on either engine, because gVisor's guest processes are not host processes. Rootless:
  nothing bounds the guest until systrap cannot clone another stub thread and the sentry panics (exit 2). Rootful:
  `pids.max = 64` is consumed by the sandbox's own host threads and the first forks panic the sentry. Measured remedy,
  not yet adopted: `--ulimit=nproc=64:64` (RLIMIT_NPROC, enforced inside the guest) with `--pids-limit=512` as the
  host backstop held the guest at exactly 64 processes and the sandbox survived, on the rootless engine in CI (row 2)
  and on both engines in a local rig. Adopting it amends decision 3's flags and is decided with ticket 02.

Docker or Podman, and rootless or the fallback, are ticket 02's choice on the target host; this ADR stays Proposed.

## Open

1. **DO-45** (requester for languages and billing, Đạt for the container lifetime). Provisional call (agent,
   2026-10-23, option (a)): Python 3.12 only, a minimal data package set added as new image versions, no JavaScript
   and no skill scripts in v1; one container per agent run, destroyed at run end, after 15 idle minutes or at 2 hours;
   billing by the profile's vCPU and GB times wall time, with measured CPU seconds kept for abuse detection. If wrong:
   JavaScript adds an image and a harness, not a runner; per-command containers change decision 10 only; billing by
   measured CPU changes the price-book entry (ADR-0121), not the metering. Answered 2026-10-23: Python 3.12 only,
   packages only as new image versions, no JavaScript and no skill scripts in v1, and billing by the profile's
   reserved vCPU and GB times wall time with measured CPU kept for abuse detection (DO-45.1 (a); decisions 5 and 8).
   The container lifetime of agent code tools moved to Open 5 for W3 (DO-45.2 (A)).
2. **DO-24** (requester for the hardware budget, operator): direction answered by D14 on 2026-10-23. Still owed: the
   second VM's size and the primary host's final size once measured (FOG-23, code-sandbox 01), and the money for both.
3. **FOG-24** (prototype, code-sandbox 01): does `runsc` on systrap run on the second host's kernel and hypervisor,
   honour `--cpus`, `--memory` and `--pids-limit` under a rootless engine with delegated cgroup v2, fill
   `memory.peak` before removal, and run on the CI runners; does the host expose `/dev/kvm`? This ADR stays Proposed
   until code-sandbox 01 answers it. Answered for the CI runner on 2026-11-05 (Measurements): runsc runs there under a
   rootless engine only with `--ignore-cgroups` and then holds no cap (B1 to B3); the rootful fallback holds CPU and
   memory; `/dev/kvm` is present. The target host's answer is ticket 02's.
4. **The package list of `dw-code-python`** (requester, part of DO-45): the research's data set minus parsers is the
   starting point, each addition a new image version that the hostile-script suite gates.
5. **Agent code tools (W3; the requester, then Đạt).** Moved from decision 10 on 2026-10-23 (DO-45.2 (A)). Does an
   agent session count as one code execution under D7, and do an agent's code tools get one fresh container per agent
   run (the earlier provisional call: never shared across threads, tenants or workspaces, destroyed at run end, after
   15 idle minutes or at 2 hours, each command audited by `AuditedSandbox`, through a `RunnerSandbox(BaseSandbox)`
   beside `DocgenSandbox`) or one per command (every `ls` pays a container start, and `BaseSandbox` needs files to
   persist across calls)?

## Review (2026-10-23)

Reviewed by Đạt on 2026-10-23 and held as Proposed until code-sandbox 01 reports its numbers: the whole direction
rests on `runsc` behaving on hosts it has not yet run on (FOG-24), and no W1 ticket but the spike needs this ADR.
Amendments from the decision brief, applied above:

- Decision 5: one unit meters, limits and prices tenant code, the profile's reserved vCPU and GB times wall time; the
  `sandbox_exec` event carries the profile and the wall time, and measured CPU is kept for abuse detection
  (DO-45.1 (a)). It replaces `units.cpu_seconds` as the billed unit.
- Decision 8: Python 3.12 only, no JavaScript and no skill scripts in v1, confirmed (DO-45.1 (a)).
- Decision 10: moved to Open 5 for W3; v1 runs one fresh container per code execution, as D7 says, and the title
  stays (DO-45.2 (A)). The alternative it rejected moved with it.
- Open: DO-45 answered; Open 5 added.
