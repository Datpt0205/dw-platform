# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

This is a **multi-context** repo: a platform backbone and bounded contexts that
plug into it (see `CLAUDE.md`). `CONTEXT-MAP.md` at the root names each context
and where its glossary and decisions live.

## Before exploring, read these

- **`CONTEXT-MAP.md`** at the repo root: it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`**: system-wide decisions, which here means the platform's (tenancy, authorization, the agent runtime, data model rules). Read the ones that touch the area you're about to work in.
- **A context's own `docs/adr/`**, next to its `CONTEXT.md` (`packages/python/dw_<name>/docs/adr/`), for decisions that belong to that context alone.
- **`CLAUDE.md`**, the architecture of record, and **`.claude/rules/`** (`code-quality.md`, `failure-modes.md`), the standards a review applies.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

```
/
├── CONTEXT-MAP.md
├── CLAUDE.md                              ← architecture of record
├── docs/
│   ├── adr/                               ← system-wide (platform) decisions
│   └── platform/CONTEXT.md                ← platform glossary
└── packages/python/
    └── dw_<name>/                         ← one per bounded context
        ├── CONTEXT.md                     ← that context's glossary
        └── docs/adr/                      ← that context's decisions
```

A new bounded context (`make new-context`) gets its own `CONTEXT.md` and
`docs/adr/` inside its package, and one line in `CONTEXT-MAP.md`.

The glossary is the context's `CONTEXT.md` named in `CONTEXT-MAP.md`, never
`GLOSSARY.md` or `GLOSSARY-MAP.md`. `mattpocock-skills:domain-modeling` (1.3.0
on) names only those two; where it says `GLOSSARY.md`, write the context's
`CONTEXT.md`. A term is written as ``**<thuật ngữ>** (`code_name`)`` followed
by an `_Tránh_:` list. `scripts/check_plans.py` fails if a `GLOSSARY*.md`
appears.

## Decisions are not all settled

Not every decision recorded in this repo is right. Many were made by an agent
during a session and never reviewed; some were carried over from the product
this platform was extracted from. An ADR therefore carries a status:

- **Accepted**: reviewed and still believed; change it only with a new ADR
  that supersedes it.
- **Proposed**: recorded but not yet reviewed by Đạt. Treat it as the current
  default, not as law.
- **Questioned**: Đạt doubts it. Prefer surfacing an alternative over building
  further on it.
- **Superseded**: replaced; the ADR names its successor.

The non-negotiables in `CLAUDE.md` (tenant isolation through RLS, never trusting
a client-supplied identity or tenant, side effects through policy, idempotency
and audit, human-in-command) are rules, not ADRs up for review. Everything
else in `CLAUDE.md`, the plans' "Decisions recorded" sections, migration
docstrings and commit messages is a decision that may be wrong; when it gets
an ADR, it starts as **Proposed** unless Đạt says otherwise.

Code in this repo cites `ADR-001`, `ADR-002` and `ADR-003`. Those documents do
not exist here (they stayed with the product this was extracted from). Do not
treat a citation as evidence a decision was reviewed.

## ADR format and numbers

An ADR here has YAML front matter (`status`, `date`, `source`), a
`# NNNN. Title` heading, Context, Decision, Alternatives considered when the
choice was not obvious, and Consequences, as
`docs/adr/0024-customer-granted-support-access.md` does; not the plugin's
one-to-three-sentence form. It starts as Proposed. An area planned ahead
reserves a block of numbers in its area file and gives each ADR its number
there before anyone writes it: highest-plus-one from parallel sessions
collides exactly as hand-picked migration numbers do. `scripts/check_plans.py`
fails on a duplicate number.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_

A Proposed or Questioned ADR is exactly the kind worth reopening when the code
shows friction; say so, with the reason.
