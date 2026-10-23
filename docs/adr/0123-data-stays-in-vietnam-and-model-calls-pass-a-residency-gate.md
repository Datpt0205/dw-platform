---
status: Proposed (direction chosen by the requester on 2026-10-22 and 2026-10-23; not yet reviewed by Đạt)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/compliance-pdpl/spec.md
    - ../../.claude/plans/studio/model-connections/spec.md
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py
    - ../../packages/python/dw_knowledge/src/dw_knowledge/adapters/api_parsers.py
    - ../../infra/compose/docker-compose.yml
    - ../../.env.example
---

# 0123. The data plane stays in Vietnam, and every model call passes one residency gate that enforces the strictest route class of tenant, workspace and agent and records it

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It rests on three requester
decisions. D8 (2026-10-22): tenants may connect their own models through LiteLLM, beside the platform's model
profiles. D13 (2026-10-23): tenant models go through a separate, stateless model proxy, and data location is declared
per model alias, an undeclared alias counting as foreign. D11 (2026-10-23): loosening a residency class needs a maker
and a different checker. The mechanism is stance S14. The `compliance-pdpl` spec owns the posture and the records,
and `model-connections` the gate on the model path.

## Context

- **The law.** Law 91/2025/QH15 on personal data protection (the PDPL, in force 2026-01-01) and Decree
  356/2025/ND-CP (in force the same day, replacing Decree 13/2023), read in unofficial English
  (https://static3.luatvietnam.vn/uploaded/vietlawfile/2025/7/91_2025_qh15_incom_110725173542.pdf,
  https://www.qtsc.com.vn/uploads/files/2026/02/02/356_2025_ND-CP_689146.pdf; gathered by the Studio research on
  2026-10-22, no counsel opinion yet). Processing personal data collected in Vietnam on a platform abroad is a
  transfer (Art. 20); its impact assessment (CTIA) is due within 60 days of the first transfer, the Ministry of Public
  Security's A05 may stop it, and fines reach 5% of the previous year's revenue. Decree 356 Art. 21 counts software
  that processes personal data automatically as a personal-data processing service needing the ministry's certificate
  (Art. 24-25), and Art. 12.4 asks for encryption in transit and at rest in cloud computing. Unverified against the
  Vietnamese text.
- **Model routes carry no location.** `ModelRoute` holds provider, model, timeouts, budgets and prices only
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/model/profiles.py:28-55`); transcription posts to a fixed
  provider URL (`packages/python/dw_knowledge/src/dw_knowledge/adapters/api_parsers.py:28`); the requester's existing
  gateway routes upstream to providers nobody has located (`.env.example:171-180`, FOG-18).
- **Internal hops are plaintext**: PostgreSQL DSNs without TLS (`infra/compose/docker-compose.yml:256-258`), Qdrant
  over http (`:279`). Nothing in the repository names the PDPL, Decree 356 or the AI Law, and the retention policy
  still cites Decree 13/2023 (`configs/policies/retention@1.7.0.yaml:117-119`; ADR-0122 re-bases it).

## Decision

1. **Two roles, two kinds of data.** Studio is processor for tenant data (it follows the tenant's instructions, and
   data-subject requests go through the tenant) and controller for platform account data (users, external
   identities, operators, support staff, billing, telemetry about users). Every store is tagged `tenant_data` or
   `platform_account`, each with its own retention class and data-subject path. The processing-service certificate,
   the platform DPIA and its updates, a CTIA for any foreign processing, the data protection officer and the annual
   assessment are tracked obligations the product produces evidence for (registers, a data-flow diagram), with a DPA
   template and a sub-processor list with change notice in every tenant contract.
2. **The data plane stays in Vietnam.** PostgreSQL, Qdrant, object storage, Valkey, logs, backups and Langfuse with its
   ClickHouse run in Vietnamese data centres, encrypted in transit (TLS on internal hops in deployed profiles) and at
   rest (volumes and the backup copy). Every foreign component sits behind decision 4.
3. **Three route classes, and the strictest wins.** `vn_only`, `cross_border_minimised` and `cross_border_full`.
   `platform.tenants.data_route_class` (CHECK, default `vn_only`), `platform.workspaces.data_route_class` (NULL
   inherits; it may only tighten) and the agent or workflow version's `route_class` (tighten-only, ADR-0117) resolve
   through one function, `effective_route_class`, to the strictest, which `RunContext.route_class` carries.
    - `vn_only` admits only routes with `data_location = 'vn'`.
    - `cross_border_minimised` admits a foreign route only after pseudonymisation with every `sensitive` field removed
      (ADR-0106), and is refused until the pseudonymiser exists. Minimisation is a supporting control there, never the
      only one: the class is reached only through the attested loosening below.
    - `cross_border_full` admits a foreign route only under a live row of `platform.cross_border_attestations`
      (processor, CTIA reference, `attested_by`, `expires_at`, `revoked_at`), which must name sensitive data to cover
      it.
    - Tightening takes one person. Loosening a tenant's or a workspace's class takes a maker and a different checker
      (D11), audited, and toward a cross-border class a live attestation naming the processor.
4. **One gate before any byte leaves.** `ResidencyGate.check(route_class, route)` is injected by constructor into
   every adapter that sends content to a model: the ModelResolver's doors (ADR-0118: the agent chat model and the
   structured gateway), embeddings and rerank, document extraction and transcription, compaction and evaluation
   judges. It refuses before the request is built. A profile the effective class forbids is also refused at publish
   and at admission (ADR-0118), so a refusal at the gate is the backstop, not the first answer.
5. **Every destination declares where it processes.** Every platform profile route, tenant model alias (ADR-0118,
   D13) and connector manifest declares `data_location` (`vn` or `foreign`) and `processor` with no default; a route
   without them fails to load, and an undeclared alias counts as foreign. A tool, connector action or MCP server
   whose processing is foreign is refused under `vn_only`, at publish and in the ToolExecutor (ADR-0116) before the
   egress client sends, unless the tenant holds a live attestation for that connector and processor (one admin
   attestation per tenant and connector).
6. **Recorded on every call and run.** `route_class`, `data_location` and `processor` on every usage event
   (ADR-0121), `route_class` on the run row and in its run manifest (ADR-0109), `dw.route_class` on spans
   (ADR-0122); identifiers only, never content.

## Alternatives considered

- **Builders opt in per call.** Rejected: a builder would decide a cross-border transfer for data subjects.
- **The policy in each provider adapter.** Rejected: the next adapter forgets it (failure-modes #5).
- **Allow everything and log it.** Rejected: a log is not a transfer basis.
- **Foreign models by default, with CTIA filings** (`cross_border_full` for everyone). Rejected: the certificate
  depends on CTIA results, A05 can order a stop, and regulated buyers refuse. Strict Vietnam-only processing stays
  one class a tenant holds, not the platform's only posture.
- **Routing by data classification alone** (dw-proterial `docs/adr/0006-model-routing-by-data-classification.md`).
  Rejected: legality depends on the tenant's CTIA, not only on the data. The data label stays `pd_category`
  (ADR-0106) and the tenant's class is a separate axis.
- **Inferring the location from the URL host.** Rejected: an endpoint hosted in Vietnam can route upstream abroad.
- **One LiteLLM instance per tenant.** Not now; a v2 option for tenant models.

## Consequences

- model-connections wires the gate into the resolver and the model proxy path (compliance-pdpl 03, W1, after
  model-connections 02); tools-and-skills and connections-and-vault read `data_location` from tool versions and
  connector manifests; compliance-pdpl keeps the processing register and the attestation records.
- A `vn_only` tenant without a Vietnamese model cannot run AI nodes, and the UI says why. Every tenant starts at
  `vn_only` and an undeclared alias is foreign, so the pilot needs a declared route processed in Vietnam before its
  first AI node runs (FOG-10).
- Hosted Langfuse abroad is excluded for personal data, and counsel is engaged before the first external pilot on real
  data (compliance-pdpl 02). TLS on internal hops and encrypted backups are W2.
- Tests that must exist, each shown red with its guard removed: a `vn_only` call to a foreign or undeclared route is
  refused before the request is sent, separately for every adapter of decision 4 (failure-modes #5); a workspace
  cannot loosen past its tenant; one person cannot loosen; MP7, a personal field reaching a prompt on a cross-border
  route, is refused at publish.

### Contradictions and amendments

- Extends CLAUDE.md:286-289 (trace metadata, safe identifiers only) with route class, location and processor.
  CLAUDE.md has no residency rule yet; one is added when this ADR is accepted.
- `.claude/plans/platform-runtime.md:221` (the chat path reads the platform profile, not the tenant's) must be fixed by
  model-connections (ADR-0118) for the class to apply per tenant.
- Diverges from the vocabulary of dw-proterial `docs/adr/0006-model-routing-by-data-classification.md` as stated
  above; compatible with dw-proterial `docs/adr/0005-control-plane-data-plane-boundary.md`, the reference for a
  customer-hosted data plane in v2.
- si-platform: none; re-derived.

## Open

1. **DO-53** (counsel): is Studio a personal-data processing service that needs the Ministry of Public Security
   certificate before the first paying tenant, is there a transition, and which entity holds it (FOG-73)? It may gate
   selling at all; until it is answered, synthetic or internal data only.
2. **DO-54** (counsel and the requester): the platform as processor and the tenant as controller, attested at
   onboarding with a DPA signed before shadow runs; `vn_only` by default for every tenant, the pilot included;
   cross-border only with an attestation naming the processor and its CTIA, tools, MCP servers and connectors abroad
   included; and who files the DPIA and the CTIA when a tenant picks a foreign model or connector. Recommended: the
   product exports the dossier inputs, counsel decides who files.
3. **DO-07** (Đạt): loosening a tenant's residency class takes two people, answered for the requester by D11 on
   2026-10-23; Đạt's review is owed.
4. **DO-19** (requester): whether the models behind the requester's existing gateway are processed in Vietnam or
   abroad, alias by alias (FOG-18); until declared they count as foreign. FOG-10 asks which in-country models meet the
   pilot's quality and cost under `vn_only`.
5. **FOG-74** (research): the status of the AI Law's implementing decrees, the PDPL sanctions decree, the
   Cybersecurity Law 2025 and the Decree 53 replacement, any of which may add localisation or logging duties here.
