---
status: Proposed (direction chosen by the requester on 2026-10-22 and 2026-10-23; not yet reviewed by Đạt)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/compliance-pdpl/spec.md
    - ../../.claude/plans/studio/marketing-pilot/spec.md
    - ../../db/migrations/versions/5a25154e0296_platform_channel_deliveries.py
    - ../../docs/adr/0006-provider-neutral-channel-delivery-outbox.md
    - ../../.claude/rules/ui-quality.md
---

# 0124. A marketing message reaches a person only through a platform send floor checked in the ToolExecutor against platform-owned consent records, which tenants may tighten but never loosen

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It rests on requester decision D4
(2026-10-22): the Marketing pilot takes leads from forms, Facebook and Zalo, scores and assigns them, and ends in a
Zalo or email message to the lead after a human approval; Marketing is the first domain pack. The mechanism is
agent-proposed, and it takes the provisional calls on DO-18 and DO-48 (agent, 2026-10-23). The `compliance-pdpl`
spec owns the floor and the consent records, `tools-and-skills` consumes the floor in the executor, and
`marketing-pilot` reads it.

## Context

- **No path reaches a lead today.** The one person-addressed delivery is for members: `platform.channel_deliveries`
  addresses `recipient_user_id` under `CHECK channel IN ('zalo')` and re-checks membership at send
  (`db/migrations/versions/5a25154e0296_platform_channel_deliveries.py`, ADR-0006). A lead is not a member. ADR-0005
  rejected Zalo OA with ZNS for staff (`docs/adr/0005-zalo-bot-is-the-first-chat-channel.md:80-82`); reaching
  customers through the tenant's own OA is a different surface.
- **The law asks for consent with proof.** PDPL Art. 28.3: advertising use of personal data "must be based on the
  customer's consent, with the customer being fully informed of the content, method, format, and frequency of product
  promotion; and a method must be provided for the customer to opt out" (Law 91/2025/QH15, unofficial English,
  https://static3.luatvietnam.vn/uploaded/vietlawfile/2025/7/91_2025_qh15_incom_110725173542.pdf); Art. 9.4: silence
  is not consent. Decree 356/2025/ND-CP Art. 6: consent verifiable as to time and content, stored, the burden of proof
  on the controller (https://www.qtsc.com.vn/uploads/files/2026/02/02/356_2025_ND-CP_689146.pdf). Anti-spam Decree
  91/2020/ND-CP is the instrument usually cited for frequency and hours; its numbers and any later amendment are
  UNVERIFIED (FOG-75). Gathered by the Studio research on 2026-10-22; no counsel opinion yet.
- **A consent check a builder places is decoration.** A condition node can be deleted, another workflow or an agent
  skips it, and a pack object a builder can edit protects nothing (failure-modes #1 and #5).

## Decision

1. **The floor.** A marketing message leaves only when, checked in this order, the recipient is not suppressed, a
   consent record of the matching purpose and channel is in force, the frequency cap allows it and the time is
   outside quiet hours; the message must carry an opt-out instruction, and its send-log row names the
   `consent_record_id` it relied on. Refusal reasons: `suppressed`, `no_consent`, `consent_withdrawn`,
   `frequency_cap`, `quiet_hours` and `processing_restricted` (ADR-0106). A refusal is a typed `blocked:<reason>`
   result on the node's error port and an audit event; nothing is sent.
2. **Checked once, in the ToolExecutor.** `SendAdmissionPort` is declared by its consumer and satisfied by the
   platform's `MarketingSendPolicy`. The ToolExecutor consults it on every connector action that its manifest marks
   as sending a message (ADR-0116), before the egress client sends (ADR-0115), so a `tool.call` node, an agent's tool
   call and a workflow-as-tool call pass the same check. No node checks it, and workflow-nodes adds no second check
   (ADR-0112 decision 6).
3. **`notify.send` reaches members only.** Its recipients are principals; an address-shaped value is a publish error
   and a non-member at run time is dropped and counted (ADR-0112). Notifications to members (ADR-0006) do not pass
   this floor. A message to anyone else is a connector message action.
4. **Consent records are platform data.** `platform.consent_records`, append-only under tenant RLS: subject key
   (E.164 phone, lowercase email or Zalo user id), purpose (`marketing`, `transactional`), channel (`zns`, `email`,
   `sms`, `messenger`, `zalo_oa`), state, `captured_at`, `source`, `evidence_ref` (a Data Hub event id or an import
   batch), `notice_version` and `withdrawn_at`; the current consent is the latest row per subject, purpose and
   channel. `platform.contact_suppressions` holds an address hash per channel. `platform.marketing_send_log` is
   range-partitioned by month through `platform.ensure_time_partitions`. The Marketing pack's Consent object is a
   read view over the records: object CRUD can neither edit nor delete a consent.
5. **Opt-out takes effect at once.** An email carries a signed one-address unsubscribe link (a public route with an
   HMAC token, rate-limited and idempotent); a Zalo message carries a keyword instruction that the inbound router
   handles. Either writes a suppression row at once, and a queued message is checked again before it sends.
6. **The floor is policy data that a tenant only tightens.** `configs/policies/marketing_send@1.0.0.yaml` holds the
   cap per address and channel per window, the quiet hours and the maximum recipients per run; a tenant overlay is
   validated as tighten-only. The defaults are conservative placeholders marked UNVERIFIED until counsel confirms
   (DO-55): 1 message per address per channel per 24 hours, and sending only between 08:00 and 20:00
   `Asia/Ho_Chi_Minh`. B12 proposed 2 per 24 hours and quiet hours from 21:00 to 08:00; the stricter set ships.
7. **A person approves every outbound message in the pilot** (P1, D4; DO-18, provisional): one approval per message
   in a fast keyboard queue, never a bulk action (`.claude/rules/ui-quality.md:225`). An AI-drafted message carries
   its provenance (the drafting run and model) on the send log. In a `test` run a message reaches only the
   workspace's test recipients (ADR-0111), and the floor applies to them too.

## Alternatives considered

- **Consent as a tenant-owned object checked by a condition node.** Rejected: a tenant could delete or loosen the
  floor the processor relies on, and any other path skips it.
- **The check in the send node** (the first placement proposed in planning). Rejected: agent tool calls and
  workflow-as-tool calls bypass it (failure-modes #5).
- **Tenant-defined floors with no platform minimum.** Rejected: the platform carries processor liability for the
  sends it executes.
- **Reusing `platform.channel_deliveries`.** Rejected: its recipients are members, re-checked as members at send.
- **Blocking at the provider only.** Rejected: no proof, and no coverage for email.

## Consequences

- compliance-pdpl ships the consent records, the suppressions, the send log and `MarketingSendPolicy` (compliance-pdpl
  04, W1) before the slice's first live message; connections-and-vault messaging manifests declare purpose, channel
  and recipient; the Data Hub mapping captures the consent checkbox and notice version at intake (FOG-03).
- A lead without consent evidence gets no message at all, so the pilot sends nothing until intake captures consent.
  Existing consents need an import with evidence. Deferring a refused send to the next allowed hour is W2.
- An `http.request` node or a tenant `http` tool aimed at a messaging provider's host would go around the floor; the
  planning briefs propose refusing such hosts for both, which tools-and-skills owns (ADR-0116).
- Tests that must exist (MP1, MP12, MP15), each shown red with its guard removed: a direct tool call, an agent tool
  call and a workflow-as-tool call to a message action without consent are each refused on their own path; a
  withdrawn consent stops a queued message; a tenant overlay looser than the floor is refused.
- Erasure must decide what of the consent records survives as proof (counsel; ADR-0122's retention).

### Contradictions and amendments

- _Diverges from ADR-0006's "Another channel (email) is one CHECK value and one adapter, not a new table"
  (`docs/adr/0006-provider-neutral-channel-delivery-outbox.md:67`), worth stating because that consequence holds for
  member notifications only: a lead is not a member, so a lead message leaves as a connector action through the
  ToolExecutor, never through `platform.channel_deliveries`, and its send log is a new table of another shape._
  ADR-0006 stays unchanged for members.
- si-platform: diverges from si-platform's fixed lead table (`db/si/migrations/0001_core.sql:104`, `crm.leads`):
  consent here is platform data and the Lead is pack data; si-platform has no consent concept.

## Open

1. **DO-55** (counsel and the requester): the statutory numbers for frequency, sending hours and recipients per run
   (the placeholders above stay UNVERIFIED; FOG-75), and the test recipients' consent wording, validity (90 days
   recommended) and who may add them (tenant admins recommended).
2. **DO-60** (counsel): must an AI-drafted, human-approved message be labelled? Recommended: provenance logged for
   email and ZNS, AI disclosure in chat channels from v1.5.
3. **DO-54** (counsel and the requester): consent and controller roles for the pilot (the platform as processor, the
   tenant as controller attesting at onboarding, a DPA signed before shadow runs) and the anti-spam position; DO-53
   gates real lead data.
4. **DO-18** (requester): provisional call (agent, 2026-10-23, option (a)): nurture waits for W2; every outbound
   message in the pilot is approved, one approval per message in a fast keyboard queue; an approval whose subject is a
   whole batch only as a recorded exception. If wrong, decision 7 changes, never the floor.
5. **DO-48** (requester; counsel on fan-out): provisional call (agent, 2026-10-23, option (a)): generic SMTP is the P1
   email path (FOG-06), connections are workspace-shared only, and the same Page or OA connected by two tenants fans
   out to both, which counsel confirms.
