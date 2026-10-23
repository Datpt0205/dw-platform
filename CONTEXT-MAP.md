# Context map

This repository is a platform backbone plus bounded contexts that plug into it
(`CLAUDE.md`, "Adding a bounded context"). Each context owns its own language
and its own decisions; the platform's decisions apply to every context.

| Context  | What it covers                                                                                            | Glossary                   | Decisions   |
| -------- | --------------------------------------------------------------------------------------------------------- | -------------------------- | ----------- |
| Platform | Tenancy and authorization, the agent runtime, model gateway, knowledge, memory, audit, notifications, ops | `docs/platform/CONTEXT.md` | `docs/adr/` |

Studio is platform code, not a separate bounded context (ADR-0100); its
decisions take the block 0100–0199 in `docs/adr/`.

This checkout ships no business context. A product adds one with
`make new-context NAME=<name>` and gives it a row here, with its glossary at
`packages/python/dw_<name>/CONTEXT.md` and its decisions at
`packages/python/dw_<name>/docs/adr/`.

A glossary or decision folder listed here may not exist yet: they are written
when a term or a decision is actually resolved (`/domain-modeling`), not
upfront. How the skills read these files, and how a decision's status is
treated, is in `docs/agents/domain.md`.

## How the contexts relate

- A context depends on the platform, never the other way round.
  `lint-imports` keeps the direction.
- Where a context needs a platform capability (approvals, policy overrides,
  the inbox, who holds a scope), it declares the Protocol it needs and the
  composition root satisfies it with a platform adapter.
- Where one context needs another's data, it goes through a Protocol the
  consumer declares, never by importing the other context.
