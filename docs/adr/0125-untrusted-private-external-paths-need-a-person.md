---
status: Proposed (direction chosen by the requester on 2026-10-22 and 2026-10-23; not yet reviewed by Đạt)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/agent-lifecycle/spec.md
    - ../../.claude/plans/studio/compliance-pdpl/spec.md
    - ../../packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py
    - ../../configs/workers/README.md
---

# 0125. Every agent and workflow version is analysed at publish, a path combining untrusted input, private data and an external effect must pass a person before the effect, and an AI risk tier travels with the publish approval

Numbered in the block 0100-0199 reserved for Studio (ADR-0100 records the block). It rests on requester decision D4
(2026-10-22): the Marketing pilot reads leads from forms, Facebook and Zalo, scores them with AI, and sends a Zalo or
email message after a human approval, which is exactly the combination this ADR governs. The publish approval that
carries the tier needs a second person under D11 (2026-10-23, ADR-0120). The mechanism is agent-proposed; the Rule of
Two survives as the Marketing pack's design. The `agent-lifecycle` spec owns the analysis at submit, and
`compliance-pdpl` the risk tier record.

## Context

- **The pilot is the dangerous shape.** Anyone on the internet can write a lead's message field; the scoring step and
  the assistant read it; lead records are personal data; and the workflow ends in a message to a person. Untrusted
  input, private data and an external effect in one path is the "lethal trifecta"
  (https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/, 2025-06-16, opinion). Detection does not solve prompt
  injection, so the controls are architectural (https://arxiv.org/abs/2506.08837, 2025-06-10); Meta's "Agents Rule of
  Two" allows at most two of the three without supervision (https://ai.meta.com/blog/practical-ai-agent-security/,
  2025-10-31, vendor opinion). All cited by the Studio research on 2026-10-22.
- **Autonomy today.** The ladder lets A3 run `external` tools unasked when idempotent and A4 always
  (`packages/python/dw_agent_runtime/src/dw_agent_runtime/autonomy.py:14-18`); two floors hold at every level,
  `critical` and `approval_policy: always` (`:29-33`). `configs/workers/README.md:14-17` still says `autonomy_level` is
  read by nothing, which is stale.
- **Prior art.** dw-proterial `docs/adr/0007-document-content-turns-cannot-call-outbound-tools.md` (accepted
  2026-10-18) refuses outbound tools in turns that read document content. si-platform
  `docs/adr/0033-the-agent-reaches-crm-tools-over-mcp.md` keeps its agent to proposals, not writes, as an ADR only.
- **The AI Law.** Law 134/2025/QH15, in force since 2026-03-01, adds risk tiers, notice of AI interaction, labelling
  and incident reporting, and bars obstructing human oversight, per a law-firm summary
  (https://www.allenandgledhill.com/perspectives/publications/bulletins-vietnam/2026/vietnam-s-new-law-on-artificial-intelligence-risk-based-regulatory-framework-in-force-1-march-2026/,
  2026-03-30); the law's text and its decrees are unread (FOG-74). The PDPL asks for AI processing of personal data
  to be risk-categorised (Art. 30.4, unofficial translation, unverified).

## Decision

1. **Three signals from the closure at submit.** A, untrusted input: an end-user channel open to non-members, an
   external trigger (a Data Hub endpoint, a provider event, an inbound message), a tool whose `output_trust` is
   `untrusted` (ADR-0116), bound knowledge, an MCP tool. B, private data: a tool whose `data_classification` is
   `personal`, `sensitive` or `secret`, a read of an object with personal-data fields (ADR-0106), memory recall. C, an
   external effect: a tool at `side_effect_level` `external` or `critical`, transitively through workflow-as-tool and
   linked agents (ADR-0117). Labels per node type and tool kind live in one dispatch table at the composition root
   (the `NodeTypeSpec` labels of ADR-0112), and an unknown kind counts as all three. A tool version missing any of
   the three classifications refuses submit with `tool_unclassified` (ADR-0116).
2. **Workflows: a person dominates every effect on such a path.** Every A to B to C path needs a `human.approval`
   node that dominates the C node, or submit answers 422 naming the path. The analysis runs on ADR-0112's
   `WorkflowIR` through the same graph module (`reachable`, `dominators`, `paths_to`), so the validator and the
   analysis cannot see different graphs. An `ai.agent` node carries its agent's signals, and its external tools
   count as gated only when they always ask.
3. **Agents: the declared autonomy must make every effect ask.** A, B and C together require a declared autonomy of
   at most A2, where `external` and `critical` tools always ask (`autonomy.py:14-18`); otherwise submit answers 422
   `capability_trifecta_autonomy` with two remedies: lower the autonomy, or split the agent so the part that reads
   untrusted content holds no effect. There is no hidden clamp; the autonomy ladder stays the only runtime reader.
4. **At run time, taint asks.** Once a run's context has taken in untrusted content (`tainted_at`, ADR-0116), every
   `external` or `critical` tool asks a person for the rest of the run, whatever its autonomy, through the one
   function `approval_required(...)` that ADR-0116 owns; taint flows to and from child runs (ADR-0117), and the
   approval shows the raw parameters.
5. **The floor only tightens.** No tenant setting and no autonomy level lowers decisions 2 to 4; the floors apply in
   order (`critical` asks, `approval_policy: always` asks, then a trifecta path or a tainted run asks). A tenant may
   tighten: block the combination, or require A1. The Rule of Two (an agent reading untrusted content and private
   records holds no external-effect tool and reaches effects only through published workflows whose every path to an
   effect passes a `human.approval` node) is the Marketing pack's design and a selectable tightening, not the floor.
6. **An AI risk tier travels with every version.** `studio.version_assessments` records per version the capability
   analysis (signals, paths, outcome, analyser version), a `suggested_tier` from policy data
   (`configs/policies/studio_risk@1.0.0.yaml`; in v1 `medium` when end-user facing or holding B or C, `low`
   otherwise, `high` only by declaration), the `declared_tier` (an agent's `ai_risk_tier`, ADR-0117), which is at
   least the suggestion (else 422 `risk_tier_below_suggested`), intended use, key inputs, safeguards and rationale.
   `high` requires autonomy of at most A1, and v1 refuses high-risk use, having no conformity-assessment path. The
   tier and the analysis outcome travel in the publish approval payload (ADR-0120), and the approver confirms them.
7. **Disclosure and incidents.** End-user chat channels disclose the AI: a persistent label in web chat, and a first
   message saying so in a Zalo conversation. AI incidents enter the incident register (`kind = ai_incident`), and
   suspension is one action, ADR-0120's kill. The explanation sheet for data subjects (Decree 356 Art. 10.3) and the
   AI Law documentation pack follow once counsel sets the criteria.

## Alternatives considered

- **Runtime detection only.** Rejected: an unsafe agent would already be live.
- **Prompt-injection detectors as the defence.** Rejected: detectors do not solve injection; one may be added later
  as a signal, never as the control.
- **Refusing outbound tools in tainted turns** (dw-proterial ADR 0007). Rejected as the remedy, ported as the
  principle: the pilot needs a send after a human approval, so the remedy is approval, not refusal.
- **The Rule of Two as the platform floor.** Rejected as the floor: it blocks agents that a human gate already makes
  safe. Kept as a tightening and as the pack's design.
- **A silent autonomy clamp stored on the version.** Rejected: a second runtime reader of one rule (failure-modes
  #2).
- **Plan-then-execute or a quarantined model.** Not in v1: an alternative remedy for v2, once a node type implements
  the pattern.

## Consequences

- Most marketing agents land at A2 or lower, and the pilot's read-only assistant holds no effect tool at all.
  tools-and-skills classifies every tool version before it can be pinned.
- compliance-pdpl 05 (W1) ships the analysis for workflows and agents and its catalogue of labels; the risk tier
  record, the explanation sheet and runtime taint at the executor are W2.
- Approval fatigue is a real risk. It is met by one approval per message in a fast queue (ADR-0124), a raw view of
  the parameters, and a verdict that explains itself.
- Tests that must exist, each shown red with its guard removed: a workflow with an A to B to C path and no dominating
  approval is refused, and so is one whose approval sits on only one branch; MP2, a `score` to `send` path without
  `approve`, is refused naming the path; an agent with A, B and C at A3 is refused with
  `capability_trifecta_autonomy`; a tainted run's external tool asks at A4; an unclassified tool refuses submit; no
  tenant setting lowers the floor.

### Contradictions and amendments

- None with an ADR. Reinforces CLAUDE.md:61-62 ("critical effects require approval") and CLAUDE.md:65
  ("Human-in-command"). Narrows `autonomy.py:14-18` for trifecta versions the way the critical floor (`:29-33`)
  already does, a tightening.
- `configs/workers/README.md:14-17` is stale on autonomy; foundations-hardening corrects it.
- si-platform: related to si-platform `docs/adr/0033-the-agent-reaches-crm-tools-over-mcp.md` ("proposals, not
  writes"), which is ADR-only there. Ports the principle of dw-proterial
  `docs/adr/0007-document-content-turns-cannot-call-outbound-tools.md` and diverges on the remedy (approval, not
  refusal).

## Open

1. **The floor (no DO id; B9 O3, the consolidator, then Đạt).** The platform floor is a person before the effect, as
   B10a and B11 propose, with B12's Rule of Two as the pack's design and a tightening, not the floor. Đạt confirms.
2. **DO-60** (counsel): under Law 134/2025/QH15, who supplies a tenant-built agent, what the tier criteria are, and
   whether a marketing agent is medium risk; may a tenant declare a tier below the suggestion (recommended: no in
   v1)? Recommended: the tenant classifies its own agents from platform defaults, the tier record ships in P1, and
   the export pack follows counsel's reading.
3. **FOG-47** (grilling): how fine must taint be for record content that came from inbound sources: a flag on the
   object or provenance per field? Too coarse forces approval everywhere; too fine is costly to track.
4. **FOG-48** (grilling): may the person who started a run approve its own approval step (`studio.step.`)? Agent
   tool approvals are non-strict by design, so an invoker may approve their own ask-before step (ADR-0117); a
   self-approved step reads like a control and may not be one.
