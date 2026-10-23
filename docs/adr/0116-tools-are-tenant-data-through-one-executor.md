---
status: Proposed (agent-proposed on 2026-10-23; not yet reviewed by Đạt)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/tools-and-skills/spec.md
    - ../../.claude/plans/studio/mcp-client/spec.md
    - ../../.claude/plans/studio/connections-and-vault/spec.md
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/tool_specs.py
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/adapters/agent_factory.py
---

# 0116. A tool is tenant data of a registered kind that reaches the model only as a pinned version, and every tool effect, MCP tools included, passes the one ToolExecutor

Numbered 0116 in the block 0100-0199 that ADR-0100 reserves for Studio. Agent-proposed under stances S8 and S9, inside
the requester's ask of 2026-10-22 for tenant tools, skills and MCP; its rule that someone other than the registrant
approves an MCP tool definition is also the requester's D11 (2026-10-23).

## Context

- Tools are platform code: `ToolRegistry.resolve(name, version)` takes no tenant
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/tools.py:34-45`), and `configs/tools/README.md:9-12` says
  the directory ships empty. `data_classification` is declared on `ToolSpec` and `ToolDefinition` (`tool_specs.py:54`,
  `contracts.py:167`) and read by nothing (failure-modes #1).
- LangChain validates nothing for a dict schema: `StructuredTool(args_schema=<dict>)` ignored `required`, `minimum` and
  `additionalProperties: false` (measured on langchain 1.4.1 by the research, 2026-10-22). A schema a tenant writes
  protects nothing unless the executor validates it.
- `build_agent` uses `create_agent`, not `create_deep_agent`, because the deep variant installs eight builtin tools
  that bypass the ToolExecutor and changed between releases (`adapters/agent_factory.py:28-36`,
  `.claude/plans/platform-runtime.md:307-309`).
- The official MCP Python SDK keeps shipping advisories of the same classes (issuer and principal binding, shared
  instances, SSRF through server URLs and `$ref`; <https://github.com/modelcontextprotocol/python-sdk/security/advisories>);
  FastMCP shipped a client code-execution bug through a server-supplied output schema on 2026-10-16
  (GHSA-gpgx-58w2-xwwf); `langchain-mcp-adapters` was archived on 2026-09-17 and pins `mcp<2`. Tool poisoning, rug
  pulls and shadowing are documented (<https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks>,
  2025-04-01), and the MCP tools spec tells clients never to make tool-use decisions from annotations of untrusted
  servers (<https://modelcontextprotocol.io/specification/2026-07-28/server/tools>).

## Decision

1. **Tools are tenant data of a registered kind.** A tenant tool is a `Tool` artifact (`namespace`, `name`, `kind`,
   `owner_workspace_id`, `status` `active`, `suspended` or `retired`) with immutable published versions, each a
   `dw.tool/v1` document hashed over its RFC 8785 canonical form: a tool contract (model-facing summary, when to use
   it and when not, input and output schemas), a tool policy only the executor reads, and a tool implementation of a
   registered kind, `http`, `mcp`, `workflow`, `object_crud`, `code` or `builtin`. `openapi` is an import source frozen
   into `http` (`source: imported_openapi`), so a run never re-reads the OpenAPI document. The policy may tighten but
   never loosen its kind floor: one function checks floors and platform-tool overrides, refusing at save and at
   publish, never upgrading silently. Every policy field enters the schema (`extra="forbid"`) in the same change as
   its reader. The tenant layer (`studio.tools`, `studio.tool_versions`) falls back to the platform layer in
   `configs/tools/`, never sideways.
2. **Connector actions.** `dw.connector/v1` manifests in `configs/connectors/<key>@<semver>.yaml` are the platform
   layer of the connector catalogue. Each action compiles to a `ToolSpec` with JSON Schema input and output and a
   declarative HTTP mapping (structured references such as `{"$ref": "input.user_id"}`, never string templates), run
   by one generic `ManifestActionHandler` through the egress client (ADR-0115); a non-standard provider gets a small,
   contract-tested auth adapter in code (`zalo_oa_v4`, `meta_page`). A manifest fails to load on an un-namespaced
   action, `max_retries` above 0 (the egress client owns retries), a write declared `side_effect_level: none` without
   a reason, empty `egress_hosts`, or a missing `data_location`, `pd_categories` or `effect_class`.
3. **The ToolExecutor is the only door to a tool effect.** It resolves by the run's tenant
   (`ToolRegistry.resolve(name, version, *, tenant_id)`); validates input and output itself against JSON Schema
   Draft 2020-12 with a closed format checker and an empty `referencing.Registry()` (no remote `$ref`; errors name
   paths, never values), within the profile `dw.tool-schema/v1` (root object, `additionalProperties: false`, depth at
   most 5, at most 100 properties, no `$ref`, `allOf`, `oneOf`, `not`, conditionals or `pattern` in v1); answers "does
   this call need a person" in one function, `approval_required(definition, run_context, args, step_calls)`, which the
   tool wrapper, `OneApprovalPerStepMiddleware` and the executor all call (kind floors, the approval condition, the
   autonomy level, run taint); enforces policy and run mode (ADR-0111); claims idempotency first (ADR-0108) and
   audits. Per-kind factories (`ToolKindFactory.build(...) -> ToolBehaviour`) return behaviour only, with no slot for
   policy. A suspended tool, a killed agent or a frozen tenant is refused before resolve. No unpinned tool and no
   non-`BaseTool` entry (a provider-native tool) ever reaches the model: `ScopedToolsMiddleware` and
   `OfferedToolsOnlyMiddleware` drop them and `build_agent` refuses them.
4. **Classification is required.** A tool version without a `side_effect_level`, a `data_classification` (`none`,
   `internal`, `personal`, `sensitive`, `secret`) and its output trust (`output_trust`) is refused at submit with
   `tool_unclassified`; ADR-0125's capability analysis reads all three. MCP server hints may only raise a
   classification, and their absence means destructive and open-world.
5. **The model-facing view.** A pinned version reaches the model as a `StructuredTool` named `namespace__name` in at
   most 64 characters (refused at publish and at build) with `response_format="content_and_artifact"`. The content is
   projected by `response.fields` (JSON Pointers), capped at `response.max_output_chars` (default 8,000, ceiling
   32,000) and wrapped as `<tool_output source="..." trust="untrusted">` by a function beside `contain_untrusted`,
   with ADR-0010's escaping; the artifact (`execution_id`, `tool_version_id`, `truncated`, `output_ref`) never reaches
   the model. A successful call of a tool with untrusted output marks the run tainted (`tainted_at`, `taint_source`);
   from then on `external` and `critical` tools ask a person, whatever the autonomy level.
6. **Toolsets are pinned inside the agent version.** An agent version pins its tools and skills by version id and
   content hash in an embedded `dw.toolset/v1` section, validated at agent publish (every pin published, of the same
   tenant or the platform layer, its hash matching, one version per tool name). At most 20 tools are visible per turn
   by default, 40 at the ceiling. There is no `studio.toolsets` table; code-defined workers keep `configs/toolsets`.
7. **Skills.** Versioned packages in the open Agent Skills format (<https://agentskills.io/specification>: `SKILL.md`
   plus text files, at most 64 KiB, 50 files and 5 MiB), served read-only per tenant through deepagents'
   `SkillsMiddleware` and `FilesystemMiddleware(tools=["read_file", "ls"])` with eviction disabled, on a backend that
   serves only the skill versions pinned in the run's toolset, checks SHA-256 on read and refuses every write.
   deepagents is pinned to one exact version at or above 0.7.23, with a contract test on the offered tool list. Agents
   stay on `create_agent` and never get `create_deep_agent`'s builtins; a skill never grants a tool (its
   `include_tools` must be a subset of the pinned tools; `allowed-tools` is stored and never read); a script file is
   refused, and skill scripts do not run in v1.
8. **The MCP client.** The platform is an MCP client through the official `mcp` SDK 2.x, pinned exactly at or above
   2.2.0 (which fixes GHSA-qx49-fqc8-xw99, GHSA-rwrf-2pqf-9j8j and GHSA-5h93-6whr-6q8j), inside an isolated
   `mcp-gateway` service: no Postgres role, no tenant secret at rest (a short-lived credential per call), no import of
   `dw_platform`, `dw_agent_runtime` or SQLAlchemy (an import-linter contract), the internet only through the egress
   proxy (ADR-0115), Streamable HTTP over HTTPS to 2026-07-28 and 2025-era servers
   (<https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning>), a new client per call, and never
   sampling, roots, logging or stdio; a server's `instructions` never reach the model. The runtime calls it through
   `McpGatewayPort`, which the runtime declares; MCP authorization runs on ADR-0115's OAuth broker.
9. **An MCP tool runs only as a definition a second person approved.** An MCP tool becomes a version only after a
   person other than the registrant approves the exact model-facing text: a run-less approval
   `studio.mcp.tool_approval` stamped `required_scope = studio.mcp.approve` (ADR-0004), under a strict prefix so the
   registrant cannot decide it, a comment required, its decision announced as `studio.mcp.tool_approval.decided`
   (`CLAUDE.md:230-235`). It is pinned by the SHA-256 of the server's definition (`name`, `title`, `description`,
   `inputSchema`, `outputSchema`, `annotations`, in RFC 8785 form). Drift refuses the call before `tools/call`
   (`mcp_tool_drifted`) and suspends the tool until it is re-approved; the `mcp_drift` lane re-lists approved
   servers. A server's request for input (elicitation) becomes a human task for the person the run acts for
   (ADR-0112's form), never an answer from the model; the capability is declared only once that form exists, and a
   run with no person declines.

## Alternatives considered

- **Tools only as platform code.** Rejected: D2's business builders could not add an integration.
- **Trust LangChain to validate dict schemas.** Rejected: measured, it passes them unvalidated. Pydantic models made at
  run time come back as plain dicts after a checkpoint (measured on langgraph 1.2.11) and cannot express every keyword.
- **The MCP SDK in-process, or the beta `langchain.mcp`.** Rejected: a library talking to arbitrary servers would sit
  beside Postgres credentials and tenant secrets, and `langchain.mcp` calls servers around the executor.
- **Internal tools over our own MCP server (si-platform's shape).** Rejected: an extra hop with no isolation gain for
  platform-owned tools; our own server comes later as an exposure path.
- **`create_deep_agent` for tenant agents.** Rejected: its builtins changed across versions (failure-modes #4) and
  include effects no policy reviewed.
- **Server hints setting the side-effect level.** Rejected: against the MCP spec, whose defaults are destructive and
  open-world.

## Consequences

- tools-and-skills owns the executor changes and the kind registry; mcp-client builds the gateway on it; connector
  manifests live with connections-and-vault. Every tool kind declares `simulate_safe` and `test_capable` (ADR-0111)
  and its classification (ADR-0125).
- Migrations: `studio.tools` and `studio.tool_versions` (a trigger keeps a published version immutable),
  `studio.skills`, `studio.skill_versions`, the MCP server registration and definition-snapshot tables,
  `studio.mcp_pending_inputs` (request state encrypted under ADR-0115's KMS for one hour), and `tainted_at` and
  `taint_source` on the run row. A new service, image and network (`dw-mcp`) for the gateway; `jsonschema` becomes a
  direct pinned dependency (its cost per call measured, FOG-58); the deepagents upgrade moves `langchain`,
  `langchain-core`, `langchain-anthropic` and `langsmith` with it (FOG-34).
- Tests that must exist, each red when its guard is removed: executor-direct negatives (an invalid input refused with
  no handler call; a looser policy refused at save; a reverted approval gate caught at the executor itself, not only
  through the wrapper, failure-modes #5); a contract test on the exact offered tool list; an unpinned or
  provider-native tool never offered; a changed MCP definition refusing the call; the registrant unable to approve; a
  skill write refused.
- Harder: tenant-authored descriptions are model-facing text that needs lint and approval; server updates need
  re-approval; untrusted reads bring more approvals; whether `FilesystemMiddleware` lets approval interrupts through is
  measured before it ships (FOG-35).
- `CLAUDE.md:211-213` (what a tool definition carries) gains `data_classification` with a reader and output trust;
  amendment A11 adds "tenant tools are data of a registered kind; tenant policy may tighten, never loosen, a kind's
  floor". `CLAUDE.md:111-116` (Required stack) gains the `mcp` SDK (inside `mcp-gateway` only) and `jsonschema`.
- Contradicts `CLAUDE.md:207-208` ("LLM output is always validated into a Pydantic schema"): the arguments a model
  writes for a tenant tool are validated against JSON Schema by the executor, while code tools keep their Pydantic
  models; worth amending to "a schema the platform owns", for the measured reason above.
- `CLAUDE.md:181-184` resolves toolsets through `TenantOverlay`; for Studio agents the toolset is a section of the
  immutable agent version (amended on acceptance). `.claude/plans/platform-runtime.md:307-309` and
  `agent_factory.py:28-36` are amended narrowly: two read-only deepagents tools on a read-only backend, never the deep
  agent. Extends ADR-0010 to tool output; uses ADR-0004's stamped `required_scope` as written.
- si-platform: diverges from si-platform `docs/adr/0033-the-agent-reaches-crm-tools-over-mcp.md` (an in-process
  executor for internal tools, our own MCP server later, re-deriving that ADR's server rules), and ports the
  claim-first design of si-platform `db/si/migrations/0040_tool_call_claims.sql` through ADR-0108.

## Open

1. **DO-46 (requester and Đạt).** May tenants register arbitrary MCP server URLs in v1 (behind an entitlement and
   `studio.mcp.manage`) or only platform-catalogue servers; is elicitation in v1 or v1.5; is `traceparent` propagated
   to third-party servers; and do we diverge from si-platform `docs/adr/0033-the-agent-reaches-crm-tools-over-mcp.md`
   as stated?
2. **DO-45 (requester for languages, Đạt for container lifetime).** Skill scripts do not run in v1? Provisional call
   (agent, 2026-10-23): no skill scripts in v1.
3. **DO-07, answered by D11 (2026-10-23).** The approver of an MCP tool definition differs from its registrant
   (decision 9).
4. **DO-54 (counsel and requester).** May a tool send data to an MCP server or an HTTP host outside Vietnam, and under
   which residency route class (ADR-0123)?
5. **FOG-34 (research).** The exact deepagents version (0.7.23 or later) and what moves with it.
