---
status: Accepted (Đạt, 2026-10-29)
date: 2026-10-29
source:
    - ../../apps/docgen/src/dw_docgen/runner.py
    - ../../apps/docgen/src/dw_docgen/workspace.py
    - ../../infra/compose/docker-compose.yml
    - ../../infra/docker/docgen.Dockerfile
    - ../../.claude/plans/platform-runtime/docgen-session-isolation/issues/01-moi-phien-mot-uid.md
---

# 0025. Each docgen session's shell runs under a uid of its own; the service holds five capabilities to make that so

Numbered 0025 in the platform's sequence after 0024. It is the residual-risk record that
`apps/docgen/src/dw_docgen/settings.py` pointed at and that ADR-0119 found missing.

## Context

One docgen container serves every tenant. A session is `t<tenant8hex>-<conversation>`
(`dw_agent_runtime.adapters.sandbox.session_id_for`), and an agent sends it shell commands written
by a model that read a customer's attachment. Until this decision every session's shell ran as
uid 1001 over one `/work`, the same uid as the service itself. That was measured on 2026-10-28 and
2026-10-29 to give three failures:

- `cat ../<other session>/<file>` read another tenant's draft. The path check guards only the
  service's file routes, never the shell.
- `/proc/<service>/environ` was readable, and it holds `DW_DOCGEN_TOKEN`.
- `setsid cmd &` left the command's process group, so the group kill after each command missed it
  and it outlived the request.

Serial execution (`max_concurrency: 1`) closed none of them. Files at rest stay readable between
commands.

## Decision

1. **A uid per session.** A session directory gets the lowest free uid in a fixed pool (20000 for
   1024 uids). The directory is mode `0700` and owned by that uid. The uid is read back from the
   owner whenever it is needed, so there is one owner of that fact. An owner outside the pool, root
   included, is refused rather than run. `/work` is `0711`, so a shell cannot list sibling sessions.
2. **The shell has nothing.** It is started with `user`, `group`, `extra_groups=[]` and `umask 077`
   (CPython's `_posixsubprocess`, so no `preexec_fn`). Moving from uid 0 to another uid clears every
   capability, and that was measured: `CapEff` is 0.
3. **Nothing of a session outlives its command, and a uid is reused only clean.** `kill -9 -1` runs
   under the session's uid until `/proc` shows none of its processes. That reaches what `setsid` moved
   out of the process group. Whatever the uid left in `/tmp`, `/dev/shm`, `/dev/mqueue` or SysV IPC
   (`ipcrm --all` under the uid) is then removed. A uid is free only while no session directory owns it
   and no process of it is alive, and it is purged again before it is handed out. So a process that
   survived the kill rounds keeps its uid out of the pool.
4. **File routes wait for commands.** Upload, download, release and the sweep take the same semaphore
   as execute, and the file routes touch only regular files, so a FIFO cannot hang the one semaphore. The service writes with `DAC_OVERRIDE`, so a process of the session must not be able to
   swap a path component for a symlink between the containment check and the write.
5. **The service runs as uid 0 in the container with `SETUID`, `SETGID`, `CHOWN`, `DAC_OVERRIDE`
   and `FOWNER` only.** The root filesystem stays read-only, `no-new-privileges` stays, and
   `cap_drop: [ALL]` stays, with these five added back. The image keeps `USER dw`. The service
   refuses to start in four cases:
    - isolation is on and it is not uid 0;
    - isolation is off and it is uid 0;
    - isolation is on and `max_concurrency` is not 1;
    - a pool uid has no `passwd` entry named `dws<n>`.

    So the image run bare fails loudly, and does not run unisolated. The pool's `passwd`
    entries exist because LibreOffice cannot build a user installation for a uid without one
    (measured 2026-10-29).

## Alternatives considered

- **User namespaces (bubblewrap).** These keep the service unprivileged, but Docker's default
  seccomp profile and the host's AppArmor refuse `unshare` without `CAP_SYS_ADMIN`. Loosening the
  host's profile trades one boundary for another, it depends on the host, and it was not measured
  (failure-modes #4).
- **Wait for ADR-0119's gVisor runner.** That needs a second VM and is W2 to W3. The hole stays open
  until then, and ADR-0119 keeps docgen's own container for document generation anyway.
- **Encrypting the files at rest of inactive sessions.** A same-uid process can still reach the
  key's holder, and every command would pay to re-encrypt a session.

## Consequences

- **Residual risk: the service is stronger than before.** A bug in the service's own request
  handling now gives an attacker the five capabilities above in the container, not just uid 1001.
  The container still has no network off `dw-sandbox`, a read-only root, no secrets beyond the
  token, and `no-new-privileges`. The shell, which is the part that runs hostile input, holds none
  of them.
- **Residual risk: a process wedged in uninterruptible sleep** survives the kill rounds. That is
  logged, as before.
- `max_concurrency` must stay 1 while sessions are isolated, and the service refuses anything else.
  Raising it needs a lock per session instead of the one semaphore that decision 4 relies on.
- The pool is shared by every tenant, with no per-tenant cap: 1024 uids, swept after an hour idle.
- The hostile-script tests in `apps/docgen/tests/integration/test_sandbox_image.py` assert each
  decision above, and each is shown red with its guard removed.
