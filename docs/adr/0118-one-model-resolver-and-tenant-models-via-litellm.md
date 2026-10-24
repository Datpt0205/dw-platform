---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/model-connections/spec.md
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/model_stack.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/run_budget.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/langchain_usage.py
    - ../../uv.lock
---

# 0118. Every model door asks one tenant-aware ModelResolver, and a tenant's own models are connections reached through a stateless LiteLLM lane that never falls back to platform-paid or other tenants' routes

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It rests on two
requester decisions. D8 (2026-10-22): tenants may connect their own models through LiteLLM, and the
platform's model profiles stay available per agent as the plan allows. D13 (2026-10-23): tenant models
go through a separate, stateless LiteLLM model proxy in this deployment, pinned by image digest, with no
database, no provider secret in its environment and no cache or callbacks; the platform keeps each
tenant's provider secrets in its vault and injects them per call; the requester's existing gateway
keeps serving the platform's own models; data location is declared per model alias, and an undeclared
alias counts as foreign. The `model-connections` spec owns it.

## Context

Paths are under `packages/python/dw_agent_runtime/src/dw_agent_runtime/` unless they start at the
repository root. External facts were gathered by the Studio research on 2026-10-22, not re-verified here.

- Three readers of one profile disagree: the run budget resolves the profile and its chat route for
  the run's tenant (`adapters/run_budget.py:62`, `:66`), the usage meter resolves it with no tenant
  (`adapters/langchain_usage.py:138`), the structured gateway with one (`model/gateway.py:162`). A meter
  can price a route the run did not use.
- One credential per process: both OpenAI adapters are built from one API key and base URL
  (`adapters/model_stack.py:92-113`), and the chat factory's docstring leaves provider selection, keys
  and fallbacks to the LiteLLM proxy's configuration (`adapters/chat_model.py:59-64`). Neither holds
  once a tenant brings its own provider API key. Profiles carry float prices (`model/profiles.py:54-55`).
- The platform-paid route is the requester's existing gateway: one API key, an OpenAI-dialect endpoint,
  provider routing upstream (`.env.example:171-181`), probed by `make check-model`
  (`scripts/check_model_gateway.py:1-14`).
- LiteLLM cannot be imported here: it needs `openai<3`, and the lock pins `openai` 3.14.1
  (`uv.lock:2717-2718`). It shipped two hijacked releases in 2026, on 2026-03-24 and 2026-10-21
  (https://docs.litellm.ai/blog/security-incident-oct-21-2026); GHSA-3cv6-jpf6-8222 exfiltrated
  credentials through request-body routing parameters; its managed tenancy keeps provider keys at rest
  under a salt key that "must never change" (GHSA-7hp6-4w63-5g45). Client-side credentials and
  cooldowns are documented at https://docs.litellm.ai/docs/proxy/clientside_auth and
  https://docs.litellm.ai/docs/routing.
- CLAUDE.md:228 lets resolution fall back to the platform, never sideways. For a model, falling back to
  the platform spends platform money and sends data to a processor the tenant did not choose.

## Decision

1. **One resolver for every model door.** `ModelResolver.resolve(tenant_id, workspace_id, profile_id,
purpose) -> ResolvedRoute` serves `StudioModelSelection`, `LimitsMiddleware` (ADR-0121),
   `LangchainUsageMeter`, `RoutingModelGateway` (structured calls), compaction and evaluation judges.
   A `ResolvedRoute` names the profile id and version, provider family, model, `endpoint_kind` (the
   platform-paid gateway or the model proxy), `model_connection_id`, `secret_version`, `payer`,
   `data_location`, `processor`, model capabilities and a price reference. Order: the tenant layer
   (tenant configuration versions of kind `model_profile`, ADR-0110), then a platform profile only when
   `platform.plan_model_profiles (plan_id, profile_id)` lists it for the tenant's plan; never another
   tenant; no answer refuses with `model_profile_unavailable`. The answer is pinned at admission in the
   run manifest (ADR-0109); the residency gate (ADR-0123) runs before content leaves, and a profile the
   effective route class forbids is refused at submit and at admission.
2. **ModelProfile v2, in one change** (`model/profiles.py`): a `version`; per route the model
   capabilities plus `data_location`, `processor`, `retention_days` and `no_training` with no defaults;
   `model_connection_model_id` on a tenant route. Model capabilities are a closed set (`tool_calling`,
   `parallel_tool_calls`, `strict_tools`, `max_strict_tools`, `numeric_bounds`, `structured_output`,
   `reasoning_effort`, `usage_reporting`, `stream_usage`, `provider_tool_search`, `max_input_tokens`,
   `vision`), and an unknown one reads as unsupported. Prices leave profiles for the price book
   (ADR-0121). `platform.plan_model_profiles` and the plan features `byom` and `code_node`
   (`platform.plans.features`, `db/migrations/sql/0001_platform_baseline.sql:332-336`) are catalogue
   rows written by migrations.
3. **A tenant model is a connection plus a model connection.** Secret and reach come from ADR-0115: a
   `platform.connections` row (`connector_key` `llm_<provider_kind>`, `auth_scheme` `api_key`, owned by
   a workspace) whose provider API key is a secret in `platform.secret_envelopes`, and
   `connection_usable(..., purpose='model')` at profile approval, admission and every call.
   `platform.model_connections` (tenant RLS): `connection_id` (UNIQUE; a composite FK
   `(tenant_id, connection_id)` to `platform.connections (tenant_id, id)`, `ON DELETE CASCADE`, since a
   foreign key check does not pass through RLS), `provider_kind`
   CHECK (`openai`, `azure_openai`, `anthropic`, `gemini`, `bedrock`, `openai_compatible`), `base_url`
   (https, no userinfo), `data_location` CHECK (`vn`, `foreign`) and `processor` with no defaults,
   `retention_days`, `no_training boolean NOT NULL`, `status` CHECK (`pending_validation`, `active`,
   `failing`, `disabled`) with no default, and `version`, bumped on every behaviour change.
   `platform.model_connection_models`: `model` (a LiteLLM model string under an anchored CHECK), `kind`
   (`chat`, `embedding`), model capabilities, `probe_status`, `probed_at`; UNIQUE
   (`model_connection_id`, `model`). An alias without a declared location counts as foreign.
4. **Validated at save and probed after.** The host must be an allowed host with purpose `model` and
   pass the egress client's address check (ADR-0115); IP literals and private or on-premises endpoints
   are out of v1. The worker lane `model_probe`, auditing as itself (ADR-0011), probes on create, edit,
   rotation and weekly: reachability (a five-token call), usage reporting, tool calling, structured
   output and reasoning parameters. A model without usage reporting or tool calling cannot back an
   agent (refused at submit), so a token limit never meets an unmetered model. Probes spend the tenant's
   tokens, and the form says so.
5. **Metered with its payer.** One usage ledger row per call (ADR-0121) with `payer = 'tenant'` and
   `model_connection_id`: tokens always, cost from the tenant's price-book entries or
   `cost_source = 'unpriced'`. Platform money limits do not apply to tenant-paid calls; tenant token
   limits do.
6. **No fallback across payers or tenants.** A failing tenant model never falls back to a platform-paid
   route or to another tenant's route, only to a second route a tenant profile lists on the tenant's
   own connections. Circuit breakers are keyed `(tenant_id, model_connection_id)`, so each connection
   breaks independently; they count 5xx, timeouts and connection errors only; a 429 honours
   `Retry-After` inside the run budget; no provider error body is copied into an error.
7. **`model_connections.manage` is a critical permission**, because it decides where tenant data goes.
   Beside it: `model_connections.read`, the plan feature `byom` and the plan ceiling
   `max_model_connections` in `platform.plan_limits`.
8. **The model proxy is a stateless translation lane, never imported.** Compose service `model-proxy`
   is built in CI from a digest-pinned Python base with `pip install --require-hashes` of one exact
   LiteLLM version, never a vendor tag; its digest is in the release manifest, and a LiteLLM version is
   adopted only after 14 days and an advisory check. Under that rule v1 pins 1.106.1, from before the
   incident of 2026-10-21, until the vendor's final incident report lets a later version through the
   same rule (FOG-19). Configuration: no `DATABASE_URL`, no provider
   variable, `cache: false`, `disable_cooldowns: true`, `num_retries: 0`,
   `turn_off_message_logging: true`, spend and error logs off, `allow_client_side_credentials: false`,
   and `configurable_clientside_auth_params` only for `api_base` under regexes anchored at both ends.
   It sits on the internal network `dw-llm` with the API, the worker and the egress proxy only, so the
   egress proxy is its only way out. The adapter is a `ChatOpenAI` aimed at the model proxy with the
   proxy's own access secret; an `httpx2` transport (`uv.lock:1712-1713`) adds `api_key` and `api_base`
   to each request body from a per-call context that `StudioModelSelection` sets, never through
   `extra_body`, headers on the model object or `model_kwargs`. The platform-paid gateway never
   receives a tenant's secret.
9. **Tools.** A tenant model on a workspace-owned connection gets tools: the `ToolExecutor`'s guards do
   not depend on the model, and the residency route class still applies (ADR-0123). v1 has no personal
   model keys and no private on-premises endpoints.

## Alternatives considered

- **Route tenant models through the requester's existing gateway.** Rejected: a shared, stateful
  gateway holding secrets and caches across tenants, whose environment holds the platform secret a
  keyless call falls back to. D13 keeps it for the platform's own models.
- **LiteLLM imported in-process.** Rejected: it needs `openai<3` against the locked 3.14.1, and tenants'
  secrets and its supply chain would sit in the API process that holds database credentials.
- **The LiteLLM proxy with its own database.** Rejected: a second store of tenants' secrets outside the
  vault, and a second registry outside RLS.
- **Fall back to a platform model on failure.** Rejected: it spends platform money and silently changes
  data location and processor.
- **Native provider adapters only.** Not now: kept as the exit plan behind the same OpenAI-compatible
  port.
- **Adding the tenant to `chat_route` later.** Rejected by CLAUDE.md:234 (new registries take
  `tenant_id` from the start).

## Consequences

- model-connections owns the resolver, the model proxy and the probe lane; usage-and-limits meters
  tenant-paid calls (ADR-0121); compliance-pdpl reads `data_location` and `processor` (ADR-0123).
- Migrations: `platform.model_connections`, `platform.model_connection_models`,
  `platform.plan_model_profiles` and the plan features, with RLS and grants; `configs/models/*.yaml`
  change shape in the same change as ModelProfile v2.
- Tests that must exist, each shown red with its guard removed: a profile the plan does not list refuses
  with `model_profile_unavailable`; tenant B's profile never resolves for tenant A
  (`packages/python/dw_agent_runtime/tests/unit/test_tenant_overlay.py`, extended); an open breaker on a
  tenant model refuses instead of reaching a platform route; `LimitsMiddleware`, the meter and the gateway
  resolve the same route; a missing secret yields the provider's 401, never an environment fallback;
  banned body parameters are refused; no secret reaches the model proxy's logs; cooldowns are really
  off; the egress proxy holds against DNS rebinding, redirects, IPv6 and `100.64.0.0/10`.
- Spikes before reliance (model-connections 01): every provider in scope, streaming with usage, tools,
  `response_format`, error mapping, and the transport injection on `openai` 3.14.1 (FOG-19, FOG-21).
- One more service and one more secret. The model proxy is a single point of failure for tenant models
  only, and its memory is part of the host measurement (FOG-23) behind D14's resize.
- Harder: a tenant whose only route fails has no model until it adds a second route of its own; nobody
  can bring a personal model key in v1.
- Every tenant starts at `vn_only` and an undeclared alias counts as foreign (ADR-0123), so the pilot
  slice needs a route declared as processed in Vietnam before its first AI step (FOG-10, FOG-18).

### Contradictions and amendments

- Model profiles stop carrying prices (`model/profiles.py:54-55`), moved to the price book (ADR-0121).
- _Contradicts CLAUDE.md:124-129 (the required stack), worth reopening because tenant models through
  LiteLLM are a requester decision (D8, D13): the stack gains LiteLLM, stateless and for tenant models
  only (amendment A10). It stays within CLAUDE.md:129 ("never `latest`"): digest and hashes pin it._
- `adapters/chat_model.py:59-64` is false for tenant models, and `adapters/model_stack.py:92-113`
  remains the platform-paid path only.
- Diverges from si-platform docs/adr/0033-the-agent-reaches-crm-tools-over-mcp.md, where a personal
  model the user brings gets no tools: here a model on a workspace-owned connection gets tools, and v1
  has no personal model keys.

## Open

1. **DO-19** (requester): direction answered by D13 on 2026-10-23. Still owed: the exact LiteLLM
   version (1.106.1, from before the incident day, until the vendor's final incident report; FOG-19),
   and, per alias, whether the models behind the requester's existing gateway are processed in Vietnam
   or abroad; until declared they count as foreign (FOG-18). Answered 2026-10-23 for the version:
   1.106.1 under decision 8's rule of 14 days and an advisory check. Still owed: the location of each
   alias (FOG-18).
2. **DO-43** (requester for fallback, on-premises endpoints and caps; Đạt for tools): provisional call
   by the agent on 2026-10-23 following the recommendation: no fallback but a second route on the
   tenant's own connections; workspace-owned tenant models get tools; no on-premises endpoints in v1;
   tenant-model tokens count only against tenant-set caps. If overturned, points 5, 6 and 9 change; the
   resolver and the model proxy do not. Answered 2026-10-23: as provisionally called (DO-43 (a)); BYOM
   ships in W2 under decisions 6 and 9.
3. Prerequisites owned elsewhere: DO-47 (Đạt and the operator: OpenBao and the egress proxy, without
   which the model proxy has no vault and no way out) and DO-54 (counsel and the requester: `vn_only`
   by default, and who files the DPIA and CTIA when a tenant picks a foreign model; ADR-0123).
   Answered 2026-10-23: OpenBao from P1, and the egress proxy before the first tenant-defined HTTP
   destination, which a tenant model's base URL is (DO-47.1 (a), DO-47.2 (a); ADR-0115); `vn_only` by
   default, loosening only with two people and a live attestation, and counsel decides who files the
   DPIA and the CTIA (DO-54.1 (a), DO-54.2 (a); ADR-0123).

## Acceptance (2026-10-23)

Accepted by Đạt on 2026-10-23 with these amendments from the decision brief:

- Decision 8: LiteLLM is pinned under the rule of 14 days and an advisory check, at 1.106.1 for v1, rather
  than left open.
- Consequences: an undeclared alias counts as foreign, so the pilot needs a route declared as
  processed in Vietnam before its first AI step (FOG-10).
- Open: DO-19 answered for the version (the location of each alias still owed, FOG-18); DO-43 and the
  prerequisites DO-47 and DO-54 answered.

## Amendments (2026-10-24)

Amended by Đạt on 2026-10-24, who accepted every recommendation the second consistency check left
open:

- Decision 8: the compose service is `model-proxy` in every document, the glossary's name, and no
  longer `litellm-byom`, so its compose profile carries that one name (studio-skeleton R8.6;
  G:ADR-0118~studio-skeleton:ngoài-phạm-vi, decided for the glossary).
- Third consistency check (round 4), second pass: decision 1 refuses a profile the effective route
  class forbids at submit, when the version is sealed, and at admission, and decision 4 refuses at
  submit an agent backed by a model without usage reporting or tool calling, no longer "at publish"
  or "a publish error", matching ADR-0123 decision 4 and ADR-0116 decision 1.
- Third consistency check (round 4), third pass: decision 1's resolver serves `LimitsMiddleware`, which
  usage-and-limits ships in the place of the run budget middleware that ADR-0121 decision 7 retires, and
  the test that the limits, the meter and the gateway resolve one route names it; decision 3's
  `connection_id` is a composite foreign key to `platform.connections (tenant_id, id)`, because a foreign
  key check does not pass through RLS and a one-column key would let a model connection point at another
  tenant's connection.
