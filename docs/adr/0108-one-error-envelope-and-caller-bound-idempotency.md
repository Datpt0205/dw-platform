---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/app-standards/spec.md
    - ../../.claude/plans/studio/foundations-hardening/spec.md
    - ../../apps/api/src/dw_api/exception_handlers.py
    - ../../packages/python/dw_platform/src/dw_platform/application/idempotency.py # RequestFingerprint
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py # canonical_hash, replay
---

# 0108. Every platform route speaks one problem+json envelope and one set of list and mutation conventions, and every idempotency claim is bound to its verified caller and fenced

Numbered in the block 0100-0199 reserved for Studio (ADR 0100 records the block), although it binds every
route of the platform: Studio's generic records API (ADR 0107) is the first consumer that cannot work
without it, and Studio's tools and workflow nodes are the first effects that retry at scale.

## Context

- **Errors.** `ErrorResponse` calls itself "The single error envelope returned by every endpoint"
  (`apps/api/src/dw_api/errors.py:28-34`), but handlers exist only for `ReplayedResponse`, `DWError` and
  `Exception` (`apps/api/src/dw_api/exception_handlers.py:14`, `:28`, `:41`). A schema validation error, an
  unknown route and a wrong method reach clients in FastAPI's own shape, `details` is stringified (`:33`),
  and the generated client shows a person "HTTP 422" (`packages/typescript/api-client/src/client.ts:271-282`).
- **Lists.** The cursor carries a `datetime` only (`packages/python/dw_kernel/src/dw_kernel/pagination.py:108-118`)
  and the keyset helper pages descending only
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/keyset.py:22-27`), while records sort on
  typed fields both ways, with NULLs. Under RLS a predicate whose operator is not LEAKPROOF silently loses its
  index (ADR 0107), so `CLAUDE.md:290-293` needs a mechanical check.
- **HTTP idempotency.** `RequestFingerprint` holds method, path, workspace and body hash, not the caller
  (`packages/python/dw_platform/src/dw_platform/application/idempotency.py:45-67`): a second member who sends
  the same key and body in the same workspace receives the first member's stored answer, and the handler with
  its authorization never runs. `complete` matches only `completed_at IS NULL` although its comment says only
  the reservation holder may write
  (`packages/python/dw_platform/src/dw_platform/adapters/persistence/idempotency_store.py:139-143`), and the
  sweep the schema promises was never built (`db/migrations/sql/0002_http_idempotency.sql:66-69`).
- **Tool idempotency.** The executor looks for a succeeded call and only then runs the handler
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/executor.py:202-204`); the backstop
  `uq_tool_executions_idempotency` covers succeeded rows only (`db/migrations/sql/0001_platform_baseline.sql:698`),
  so two concurrent calls with one key both run the effect. `CLAUDE.md:253`: "All side effects use
  idempotency keys."
- si-platform found and fixed both idempotency defects in its copy of this code: the 2026-10-20 amendment of
  `docs/adr/0045-one-idempotency-key-store-handed-to-modules-by-the-host.md`,
  `db/si/migrations/0040_tool_call_claims.sql` and `db/si/migrations/0041_idempotency_reservation_token.sql`.

## Decision

1. **One error envelope.** Every route answers an error as `application/problem+json` (RFC 9457,
   https://www.rfc-editor.org/rfc/rfc9457.html, read 2026-10-22): `type` `urn:dw:problem:<code>` (one per
   `ErrorCode`), `title` (stable English per code), `status`, `detail`, `instance`
   `urn:dw:request:<request_id>`, and the extension members `code`, `message` (the value of `detail`),
   `details` (structured JSON, no longer stringified), `request_id`, `trace_id` and `errors[]` of
   `{pointer | parameter | header, code, detail}` with JSON pointers. Registered handlers cover `DWError`,
   `RequestValidationError`, Starlette's `HTTPException` (unknown route 404, wrong method 405) and unexpected
   exceptions (500, nothing internal). `ErrorCode` gains `method_not_allowed` (405), `precondition_failed`
   (412) and `precondition_required` (428), mirrored in TypeScript; OpenAPI carries one `Problem` schema on
   every 4XX and 5XX. Adopted additively: every member of the platform envelope a client reads today keeps
   its name and meaning. The one shape that changes is FastAPI's own 422 body, whose `detail` was a list: it
   becomes a string and the list moves to `errors[]`, which only an outside integration parsing FastAPI's
   shape would notice (neither `apps/web` nor the generated client reads `detail`). People read text the web
   builds from `code` and `errors[].code`; a tenant-written validation message travels in `errors[].detail`.
2. **Lists.** A typed keyset cursor v2: `sort_value` tagged `text|int|float|date|datetime|bool|null` with a
   phase `values|nulls`, so NULLS LAST is two index-backed phases; `id` is always the last sort key; v1
   cursors still decode; no offset; a cursor never grants access (re-checked on every page,
   https://google.aip.dev/158). Filters are the JSON filter AST (`$and`, `$or`, `$not`; leaves
   `{field: {op: value}}`; depth at most 5, at most 50 leaves, `$in` at most 500 values, strings at most
   1 KB; errors point into the AST); sorting is AIP-132 `order_by` (https://google.aip.dev/132); `fields`
   selects. A CI plan-shape test runs each paged statement, captured from the real repository code, as
   `dw_app` with tenant settings under `SET LOCAL enable_seqscan = off`, and fails unless every declared
   predicate and sort column is an `Index Cond` or `Recheck Cond`, or an index scan delivers the ORDER BY.
3. **Mutations.** A strong ETag carries the record version; `If-Match` compares strongly (a weak tag never
   matches) and a mismatch is 412; a route whose object requires a precondition answers 428 without one;
   `If-None-Match: *` makes a create create-only. `PATCH` is JSON Merge Patch (RFC 7396) under
   `application/merge-patch+json` and `application/json` alike. Custom methods are `POST` sub-resources in
   the platform's spelling (`/records/batch-create`) with AIP semantics. One long-running operation resource,
   `/api/v1/operations/{id}` (AIP-151 shape: 202 with `Location`, kept 30 days, cancellable). Body limits per
   route class with a streamed cap (413). Every 429 carries `Retry-After`; `RateLimit` headers only behind a
   setting, never `X-RateLimit-*`. A route retires with `Deprecation` (RFC 9745), `Sunset` (RFC 8594, not
   earlier than `Deprecation`) and `Link rel="deprecation"`, at least six months ahead; changes inside
   `/api/v1` stay additive.
4. **HTTP idempotency is bound to the caller and fenced.** `platform.idempotency_keys` gains
   `caller_ref text NOT NULL DEFAULT ''` (`user:<principal_id>`, or `support:<grant_id>` in a support
   context, ADR 0024), `reservation_token uuid NOT NULL DEFAULT gen_random_uuid()` and `response_headers jsonb`
   (allow-list `ETag`, `Location`). A stored answer replays only to the verified caller who spent the key,
   with its `ETag` and `Location`; existing rows carry `''`, which equals no real caller, so they conflict
   instead of replaying. `reserve` and `take_over` return a token, a takeover mints a fresh one, and
   `complete` and `release` match `(tenant_id, idempotency_key, reservation_token)`. In flight: 409
   `conflict`; another caller or another body: 409 `idempotency_conflict` (a mismatch stays 409); missing
   where required: 422 with `details.reason_code` `idempotency_key_required`. Required on a `POST` that starts
   a long-running operation, on batches and on upsert; optional on a single create, which `create_key`
   covers (ADR 0107). A retention lane deletes keys older than 24 hours.
5. **Tool idempotency is claim-first.** `platform.tool_execution_claims` (`tenant_id`, `workspace_id`,
   `tool_name`, `idempotency_key`, `run_id`, `claim_token`, `claimed_at`, `expires_at`; primary key
   `(tenant_id, tool_name, idempotency_key)`) is inserted before the executor looks for a succeeded call. A
   duplicate while the first runs gets `ConflictError`; a duplicate after success replays; an expired claim is
   taken over by `DELETE ... WHERE claim_token = :old AND expires_at < now()` then `INSERT`; release deletes
   only its own token; `expires_at = now() + timeout_seconds * (1 + max_retries) + 30 s`. Two calls with one
   key can never both run the effect. `uq_tool_executions_idempotency` stays as the backstop (an
   `IntegrityError` there becomes a replay), and `dw_app` loses UPDATE on `platform.tool_executions`.
   ADR 0122's 30-day clearing of `output` therefore runs in the retention lane through a SECURITY DEFINER
   function that takes no argument, reads its term from `platform.retention_terms`, the provisioner's copy of
   the pinned retention policy (ADR 0122 decision 7), nulls `output` past it and changes nothing else, so
   UPDATE never returns to `dw_app`.
6. **One key grammar for run effects.** A workflow node's effect carries `wf:{run_id}:{node_id}:{iteration_path}`
   (map index and loop counter path, never the attempt; the node catalogue's `run_id:node_id:iteration` is
   this key), derived through the existing `executor.canonical_hash`, which stays unchanged so in-flight runs
   keep their keys. A retried node reuses its key, and the claim turns the retry into a replay.

## Alternatives considered

- **Keep today's envelope and let Studio routes extend it.** Rejected: each spec would invent its own
  `errors[]` and pointers. A Studio-only problem+json is two envelopes; RFC 7807 is obsoleted by RFC 9457.
- **Offset pagination.** Rejected: page 50 costs what the whole match set costs (`CLAUDE.md:290-293`). OData
  `$filter` or AIP-160 strings as the primary syntax: a string parser may come later and compile to the AST.
- **Replay a stored answer to anyone holding the key.** Rejected: a leaked key discloses another caller's
  answer, and the replay skips that caller's authorization.
- **422 on a mismatch, as the expired IETF draft says**
  (https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/, read 2026-10-22). Rejected:
  it breaks today's clients for no gain; with no RFC, the documented behaviour is the contract.
- **Look up, then claim, for tool calls.** Rejected: a race runs the effect twice. Advisory locks per key are
  released at commit while a handler runs across network calls outside any transaction, and
  `SELECT ... FOR UPDATE` on `platform.tool_executions` has no row to lock before the first call.
- **A second key format for workflow nodes.** Rejected: two answers to one question; the executor and the
  node wrapper would disagree on retries.

## Consequences

- app-standards (P0) lands before custom-objects' generic API. The OpenAPI snapshot and the generated
  TypeScript client change with the envelope, a web helper maps `errors[]` onto form fields, and every error
  changes content type.
- foundations-hardening ports the claim-first table (its ticket 04) before tools-and-skills ships tenant
  tools; every Studio tool kind then inherits single execution.
- Migrations: one Alembic revision adds `caller_ref`, `reservation_token` and `response_headers` to
  `platform.idempotency_keys`; one creates `platform.tool_execution_claims` (RLS ENABLE and FORCE, grants)
  and revokes `dw_app` UPDATE on `platform.tool_executions`, asserted by `test_privileges.py`.
- Tests that must exist: another caller with the same key and body gets 409 and never the stored body
  (dropping `caller_ref` from the comparison turns it red); a late `complete` with a stale token writes
  nothing; two concurrent calls with one key, made on the executor directly and not through a graph, run one
  effect; a route walker finds every error in problem+json; the plan-shape test covers every existing paged
  endpoint and the records compiler.
- One retry that spans the deploy answers 409 instead of replaying (it fails closed). A crashed claim holder
  blocks its key until `expires_at`, which is bounded. The 24-hour key term follows common vendor practice
  (unverified). The worker's lane-set test (`apps/worker/tests/unit/test_worker.py`) gains the retention lane.
- No ADR is contradicted. The current envelope is extended additively, so the claim at
  `apps/api/src/dw_api/errors.py:28-34` becomes true rather than broken; `CLAUDE.md:253` and
  `CLAUDE.md:290-293` gain tests; ADR 0024's refusal shape holds (a feature's reason stays in
  `details.reason_code`, and `ErrorCode` grows only by three HTTP-level codes). The "Append-only" docstring
  of `packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/tool_execution_store.py:1` becomes true
  for UPDATE by `dw_app`, which the default privileges grant today
  (`db/migrations/sql/0001_platform_grants.sql:44-46`); DELETE stays for offboarding, and clearing `output` past its
  term goes only through decision 5's function.
- si-platform (D5): ports `docs/adr/0045-one-idempotency-key-store-handed-to-modules-by-the-host.md` with its
  2026-10-20 amendment and the claim-first design of `db/si/migrations/0040_tool_call_claims.sql`, re-derived
  as Alembic revisions on `platform.*` for `dw_app`. It diverges by storing the caller as a column
  (`caller_ref`) instead of hashing it into the body hash, so a 409 can say which part differed.

## Open

All three are DO-16, owned by Đạt:

1. Adopt RFC 9457 problem+json platform-wide, additively, as decision 1 states? Answered 2026-10-23: yes
   (DO-16.2 (a)).
2. The custom-method spelling: `/records/batch-create` (the platform's style, proposed) or the AIP colon form
   `/records:batchCreate`, which would be a second URL convention? Answered 2026-10-23: `/records/batch-create`,
   so ADR 0112's task submission and ADR 0114's expression routes take the sub-resource form too (DO-16.2 (a)).
3. The deprecation notice period for integrator routes: at least six months, as proposed? Answered 2026-10-23: at
   least six months (DO-16.2 (a)).

## Acceptance (2026-10-23)

- Status Accepted by Đạt; DO-16 (a) answers Open 1 to 3 as proposed, and Studio's routes form one group under
  `/api/v1/studio/` (DO-16.1 (a)).
- Decision 1 states the one shape that changes, FastAPI's own 422 `detail` list, beside the additive members
  (DO-16.2 (a)).
- The colon spellings in ADR 0112 and ADR 0114 give way to sub-resources (`/tasks/{id}/submit`, `/expressions/check`,
  `/expressions/evaluate`); no `CLAUDE.md` line changes (`:214` and `:246-249` gain tests).

## Amendments (2026-10-24)

- Đạt accepted the open recommendations of the second consistency check; the status stays Accepted.
- Decision 5: ADR 0122's 30-day clearing of `platform.tool_executions.output` goes through a SECURITY DEFINER
  function of the retention lane, with its term in the retention policy, so `dw_app` regains no UPDATE on the table
  (H:ADR-0122~foundations-hardening:R6.3).
- Third consistency check (round 4), sixth pass, Đạt's V4.21: decision 5's function that clears `output` takes
  no argument and reads its term from `platform.retention_terms`, which the provisioner loads from the pinned
  retention policy (ADR 0122 decision 7), so a new term from counsel takes a policy version and no code.
