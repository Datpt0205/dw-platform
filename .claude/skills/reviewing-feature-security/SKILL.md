---
name: reviewing-feature-security
description: Run this before finishing any change that adds or alters a feature in this repository — anything touching tenants, authorization, approval or autonomy, agent tools, memory, knowledge, evidence, migrations, API routes, caches, background jobs, containers or dependencies. It walks the six trust boundaries this platform has and requires a negative test at each one that applies. Use it without being asked; finishing a feature without it is finishing half of it.
---

# Reviewing a feature before it ships

The unit tests written alongside a feature test the feature. They pass because
the author knew what the code should do. Every defect this repository has
actually shipped lived somewhere else: in what the code does for a caller it was
not written for.

So this is not a second look at the happy path. It is six questions about who
else can reach the code, and each one is answered with a **test that fails when
the protection is removed** — not with a reading of the source.

## How to use it

Work the boundaries below in order. Most changes touch two or three; say in one
line why each of the others does not apply, rather than skipping silently — the
sentence is where the mistake usually surfaces.

Then do the mutation check at the end. It is the only step that distinguishes a
test that protects something from a test that merely passes.

---

## 1. Tenant isolation

Every tenant-scoped table carries `tenant_id` and `workspace_id`, has RLS
enabled **and forced**, and a policy. `scripts/verify_invariants.py` checks that
mechanically and the commit hook runs it, so the part left to judgement is the
path _around_ SQL:

- Does the new query set tenant context per transaction, or does it inherit
  whatever the previous transaction on that pooled connection left behind?
- Does every new cache key and object-storage path contain the tenant and
  workspace? A key that does not is a cross-tenant read with a fast path.
- Does the new Qdrant call build its filter inside the knowledge gateway, or did
  the filter get passed in by a caller who could pass a different one?
- Does the runtime role own the table, or can it bypass RLS as owner? RLS does
  not apply to the owning role unless FORCE is on — that is why FORCE is checked.

**Negative test:** tenant B calls the new path with tenant A's identifier and
gets nothing back — not an error that leaks existence, nothing. Assert on the
empty result, not on the exception type.

## 2. Authorization

Separate from isolation: A may be the right tenant and still not be allowed.

- Is the decision made where the mutation happens, or only in the layer that
  renders the button? A hidden control is not a check.
- Is identity resolved server-side from a verified credential, or read from
  something the client sent?
- If the decision reads a cached membership, does a cache entry written _before_
  this field existed deserialise to the restrictive value? This has bitten here:
  a new permission field defaulted to permissive on stale entries, so every
  session cached before deploy was over-privileged until it expired.
- When a decision is _stamped_ onto a record (the role that may approve this
  request), does the reader use the stamp or re-derive it from current config?
  Re-deriving makes a past decision change when the config does.

**Negative test:** a caller who should be refused calls it directly, bypassing
the UI and any service-layer wrapper, and is refused there.

## 3. Autonomy and approval

The agent path is where this platform can act on the world.

- Does this change let an agent do something unasked that it could not do
  before? Name the new reach in one sentence. If the sentence is hard to write,
  the change is bigger than it looks.
- Is the new tool's `side_effect_level` honest? `external_idempotent` means
  running it twice is genuinely the same as running it once — not "unlikely to
  matter".
- Does the gate hold when the tenant ceiling is absent or unrecognised? The rule
  here is fail closed: an unknown level is A0, not A4.
- Is `approval_policy_version` stamped on the run, and does a run stamped with a
  version the current policy does not recognise require approval?

**Negative test:** a run at the level _below_ the one this tool needs is paused,
asserted at the executor — not through the graph node above it, which would have
stopped it anyway and hides whether the executor's own gate works.

## 4. Untrusted content

Customer documents, connector payloads, retrieved chunks and model output are
all attacker-controlled in the threat model.

- Does retrieved text reach a place where it can be read as instruction? Text
  from a document is data; it must be framed as data in the prompt, not pasted
  where a system instruction goes.
- Is model output used directly as an identifier, a route, a permission or a
  threshold? It must be validated into a Pydantic schema and then _resolved_
  against real data — a model asked to choose will choose even when nothing was
  named.
- Does a failure to understand degrade to "I did not understand", or to a
  guessed action?
- Does submitted code still run under the sandbox's pids limit, read-only root
  and `init: true`? A missing `init` turns killed descendants into zombies that
  keep counting against the process limit — that is how the fork bomb here took
  out seven later tests, not the fork bomb itself.

**Negative test:** an eval case in the `prompt_injection` set with the new
surface in it, asserting the instruction was not followed.

## 5. Provenance and audit

- Is the write on the audit trail, in the **same transaction** as the write? An
  audit row appended afterwards is absent exactly when the interesting failure
  happened.
- Can the chain be walked in SQL from the stored item back to the source
  document and byte range, without replaying a trace? Traces are sampled; a
  claim that survives only in a trace does not survive.
- Do the foreign keys that carry provenance use `ON DELETE RESTRICT`? Cascading
  a document delete through evidence silently rewrites history.
- Is every versioned artifact the run used recorded **on the run row** —
  prompt bundle, toolset, policy, memory policy, approval policy?

**Negative test:** deleting a source document while an item cites it is refused,
and the refusal is asserted as a foreign-key violation, not as a caught error.

## 6. Resource lifecycle and defaults

- What creates this, and what destroys it? Name both. Three leaks here were
  created with no owner for the destroy side — a ledger entry, a thread, a
  temporary directory.
- Does the check happen before the expensive or irreversible part, or after it?
  A budget check after the call has already been made is accounting, not a
  ceiling.
- Is the cleanup in `finally`, and is it correct when it runs twice?
- When the dependency this code calls is unavailable, does the default allow or
  refuse? Three defaults here failed open. Refusing a legitimate action is
  recoverable; allowing an illegitimate one is not.
- If a cache or a lookup fails, is the fallback the restrictive answer?

**Negative test:** the dependency raises, and the code refuses. Assert the
refusal, not the log line.

---

## The mutation check — do not skip this

A test that passes is not evidence. A test that _fails when you break the thing
it protects_ is.

For each protection this change adds, break it deliberately — invert the
comparison, delete the filter, return the permissive default — run the suite,
and confirm something goes red. Then put it back.

This repository has three recorded cases where the test was green both ways:

- the executor's approval gate had no test of its own; the graph test above it
  passed with the gate deleted;
- an evidence-verification test mutated the wrong argument, so the original
  insert still ran and the test never exercised the new path;
- a trigger test could not fail because the trigger it depended on was
  unconditional.

All three were found by mutation and none by reading. Budget the minutes.

**How:** write the mutations as data and run `scripts/mutate.py`; do not write
a script per ticket. The spec sits beside the ticket at
`.claude/plans/<area>/<feature>/mutations/<NN>.yaml`, and its format is in the
script's docstring. One mutation per "Kiểm soát" row, or per control the ticket
adds, each naming only the tests that guard it. Extra mutations cost minutes
and prove nothing new.

The script:

- runs the mutations in parallel, but integration tests that share a database
  one at a time;
- runs every group unmutated first, and a red control voids the result;
- refuses a mutation that does not reach the imported code;
- mounts a mutated package into an image already built, rather than rebuilding
  it;
- runs POSIX-only tests in a Linux container (`runner: linux`).

Exit 0 means every control is green and every mutation red.

## Two things this checklist cannot do

Read `.claude/rules/failure-modes.md` for the counts behind these. Two of the
seven shapes there are facts about the outside world and are not reachable by
thinking:

- **What a library actually does.** Run it and look. Its documentation
  describes the version someone wrote the docs for.
- **What is actually in the built image.** Scan it. `trivy image --severity
HIGH,CRITICAL --ignore-unfixed` on the image this change produces; the four
  images here were carrying fourteen fixable findings that no amount of review
  would have surfaced. This applies just as much to an image the change only
  _references_ in a compose file and pulls from a registry, not one this
  repo's own Dockerfiles build — `reviewing-deployment-security` §6 has the
  rule for that case, found missing the same way, later.

If the change touches a Dockerfile, a lockfile, a dependency pin or a compose
file's image list, one of these two applies and the checklist alone is not
enough.
