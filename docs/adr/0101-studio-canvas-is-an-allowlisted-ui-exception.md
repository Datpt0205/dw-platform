---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/workflow-builder-ui/spec.md
    - ../../.claude/plans/studio/studio-skeleton/spec.md
    - ../../apps/web/lib/__tests__/antd-only.test.ts
    - ../../apps/web/.eslintrc.json
    - ../../apps/web/lib/csp.ts
---

# 0101. The Studio builder canvas uses @xyflow/react laid out by @dagrejs/dagre on one path, and the antd-only guard becomes an allowlist whose every exception has its own ADR

Numbered in the block 0100-0199 reserved for Studio (ADR 0100 records the block).

## Context

D2 makes builders business admins who work without code: they drag nodes onto a canvas, configure each node in a form
and connect them. A workflow builder therefore needs a graph canvas: pan, zoom, edges, drop targets and keyboard paths.

`CLAUDE.md:140-151` allows `antd`, `@ant-design/icons` and `@ant-design/nextjs-registry` "and nothing else", the rule
Đạt set on 2026-10-08 when he asked for antd everywhere. antd ships no graph canvas. The guard behind the rule cannot
see a library it does not name: `apps/web/lib/__tests__/antd-only.test.ts:16-18` is a denylist of the removed modules,
its manifest check (`:128-141`) reads the same list, and ESLint names the same modules (`apps/web/.eslintrc.json:4-37`).
Today `@xyflow/react`, or any kit nobody listed, passes every check (failure-modes #0).

si-platform answered the same question for its approval builder and accepted `@xyflow/react` 12.12.0 with
`@dagrejs/dagre` 3.1.1 (si-platform `docs/adr/0049-the-approval-builder-canvas-is-xyflow-react-laid-out-by-dagre.md`).
On React 19.2.8, jsdom 30 and vitest 5 it measured about 73 kB gzip of JS and 2.5 kB of CSS on the builder route only,
static CSS with no runtime style injection, and a `ResizeObserver` and `DOMMatrixReadOnly` shim needed in vitest. It
rejected an own SVG canvas (an estimated 800-1,500 lines, with focus, announcements and drop hit-testing tested by
nobody else), `elkjs` (434 kB gzip against dagre's 15.7 kB, EPL or GPL) and AntV X6 (malicious versions published from
a compromised maintainer account, OSV MAL-2026-3839). These are si-platform's figures, re-measured here before the
exception lands. Both libraries are MIT (`@xyflow/react` 12.12.0 released 2026-09-24, `@dagrejs/dagre` 3.1.1 released
2026-08-08; npm registry metadata, read 2026-10-22). React Flow asks: "Only remove this attribution, if you are
subscribed to React Flow Pro" (https://reactflow.dev/learn/troubleshooting/remove-attribution, read 2026-10-22).

The web app's Content-Security-Policy gives scripts a per-request nonce with `strict-dynamic` and allows inline styles
because antd writes them at runtime (`apps/web/lib/csp.ts:16-23`); a canvas loaded as a dynamic chunk must work under
it, which the spike measures rather than assumes.

## Decision

1. **Two libraries, exact versions, one path.** `apps/web` declares `@xyflow/react` `12.12.0` and `@dagrejs/dagre`
   `3.1.1`, exact. No other manifest declares them, `@dw/ui` neither depends on nor wraps them, and only files under
   `apps/web/app/studio/**/canvas/**` import them. The canvas is a client component loaded with `next/dynamic` and
   `ssr: false` on the builder route only.
2. **antd draws everything but the pane.** The library draws the pane, the viewport and the edges. Every node body
   (antd `Card`), panel and form (`Form`, `Drawer`, `Tabs`), menu and notice is antd; the library's `Controls`,
   `MiniMap` and `NodeToolbar` are not used. `@xyflow/react/dist/base.css` is imported once into `@layer components`,
   with its `--xy-*` variables mapped to antd's `--ant-*` variables. Tailwind stays layout-only; colour, type and
   radius come from the antd theme in `@dw/ui`.
3. **The document holds topology; dagre computes positions.** Node positions are computed by dagre at render and on
   every change, and never stored. The workflow document holds topology only (nodes, ports, edges); an edit changes
   topology only (insert between, append after, connect a port, delete), so the definition hash (ADR 0109) carries no
   layout. The layout function that calls dagre lives under the canvas glob. The browser checks nothing beyond
   display: validation and graph checks belong to the server's validator (ADR 0112).
4. **The guard becomes an allowlist.** `antd-only.test.ts` accepts in `apps/web` and `packages/typescript/ui` only
   listed runtime dependencies (today `antd`, `@ant-design/icons`, `@ant-design/nextjs-registry`, `dayjs`,
   `keycloak-js`, `next`, `react`, `react-dom` and `@dw/*`) plus exceptions. An exception is a `{module, glob, adr}`
   entry: the module, the path glob that may import it and the ADR that admits it; an import of that module outside
   its glob fails. ESLint carries
   the same rule, with an `overrides` entry per glob. Any other library fails until its own ADR admits it, and the
   modules removed on 2026-10-08 stay refused because no entry lists them.
5. **The attribution badge stays.** The React Flow attribution badge is kept; no React Flow Pro licence is bought.
6. **Charts are not covered, and v1 ships none.** The usage screen (`/usage`) and every other dashboard use antd
   `Statistic`, `Table` and `Progress`; a chart library needs its own ADR, written when a requirement asks for a chart,
   and the allowlist refuses one until then.

## Alternatives considered

- **antd only.** Rejected: antd has no graph canvas, and a hand-built SVG canvas costs months plus its own
  accessibility work.
- **A form-only builder with no canvas.** Rejected: D2 asks for drag-and-drop nodes, and a linear form cannot show
  joins and maps.
- **Storing node positions.** Rejected: a second copy of layout that drifts from topology (failure-modes #2); a
  cosmetic move would change the definition hash, invalidate evaluation evidence keyed by it and cause merge conflicts.
- **A blanket exemption for the two libraries.** Rejected: the next library would slip in with no decision recorded.
- **Another graph or layout library.** `elkjs` and AntV X6 are rejected for the reasons si-platform measured, above.
- **React Flow Pro to hide the badge.** Not bought (point 5), confirmed on 2026-10-23 and open to change at any time
  (Open 2).

## Consequences

- workflow-builder-ui depends on this ADR's acceptance. studio-skeleton ticket 03 turns the guard into an allowlist
  without widening it, with a test proving an unlisted import is still red. workflow-builder-ui ticket 01 then runs a
  spike in `apps/web` (CSP with the nonce, the CSS layer order, bundle size, the jsdom shim, a 100-node workflow) and
  adds the canvas `{module, glob, adr}` entries in the same commit as the first canvas import.
- The first-load cost of the canvas route is measured on its own by workflow-builder-ui ticket 01 and recorded here
  and in the workflow-builder-ui spec: the roughly 250 kB first-load budget accepted for antd (`CLAUDE.md:162`) does
  not cover it.
- Tests, each shown red by removing its guard: either library imported outside `apps/web/app/studio/**/canvas/**`
  fails; a manifest other than `apps/web/package.json` declaring either fails; an unlisted runtime dependency fails;
  the `dw.workflow/v1` schema refuses a document that carries coordinates, so a stored position cannot slip in.
- From the canvas the builder submits a version for the quality gate ("Gửi kiểm định") and starts `simulate` runs
  (`test` runs later, ADR 0111); it never publishes by itself (ADR 0120).
- workflow-builder-ui owes the accessible path: every mouse action has a keyboard path, `ariaLabelConfig` is in
  Vietnamese, taken from the message keys (DO-57), and an outline view of the same document (antd `Tree`) serves
  screen readers and the 320 px width.
- Harder: every future UI library needs an ADR before its first import; an `@xyflow/react` major upgrade (v13 was in
  prerelease when si-platform measured) is a deliberate change with a new measurement, never an automatic bump; a module
  outside the canvas path, such as the pure document-to-graph module workflow-builder-ui plans at
  `apps/web/lib/workflow-graph.ts`, may import neither library, so it maps the document to plain shapes the canvas
  adapts.

### Contradictions (the amendment applies only when this ADR is accepted)

- Contradicts `CLAUDE.md:140-151` ("and nothing else"), Đạt's 2026-10-08 antd-everywhere decision, worth reopening
  because antd has no graph canvas and D2 asks for one. Amendment A3 replaces "and nothing else:" with "and nothing
  else unless an ADR admits a module for one path", names the canvas exception (`@xyflow/react` and `@dagrejs/dagre`,
  pinned exactly, only under `apps/web/app/studio/**/canvas/**`, antd still drawing every node body, panel, form and
  notice), and describes `antd-only.test.ts` as an allowlist of `{module, glob, adr}` entries in which an unlisted
  library, or an excepted one imported outside its glob, fails; the Bundle line adds that the canvas route is measured
  on its own.
- Changes `apps/web/lib/__tests__/antd-only.test.ts` and `apps/web/.eslintrc.json` from denylists into an allowlist.
  The amendment narrows the rule's exceptions to named paths; it does not reopen the 2026-10-08 sweep.

### Relation to si-platform

- Reuses the measured reasoning of si-platform
  `docs/adr/0049-the-approval-builder-canvas-is-xyflow-react-laid-out-by-dagre.md`: the same libraries, versions,
  layering (antd node bodies, `base.css` in the components layer, `next/dynamic` without SSR) and kept attribution.
- Diverges in three ways. The libraries are confined to one import path by test, where si-platform asserts only which
  manifest declares them. "Positions never stored" is a property of the document format that a schema test enforces,
  where si-platform computes positions the same way but leaves stored placement open as a later schema change. And it
  serves a general workflow builder in `apps/web`, not an approval builder in `apps/web-admin`.

## Open

1. **DO-42, the exception (Đạt).** Amend the Web UI rule set on 2026-10-08 (antd everywhere) for this one path, with the
   allowlist test in the same change? Blocks workflow-builder-ui ticket 01. Answered 2026-10-23: yes; Đạt admits
   `@xyflow/react` and, in the same exception, `@dagrejs/dagre`, both pinned exactly, on the one glob
   `apps/web/app/studio/**/canvas/**`; studio-skeleton ticket 03 makes the guard an allowlist, and the canvas entries
   land with the first canvas import (DO-42.1 (a)).
2. **DO-42, the badge (requester).** Keep the React Flow attribution badge rather than buy React Flow Pro? Answered
   2026-10-23: keep the badge, buy no Pro licence (DO-42.2 (a)).
3. **DO-42, charts (Đạt).** A chart library exception for dashboards, decided before v1 GA; until then P1 uses antd
   `Statistic`, `Table` and `Progress` only. Blocks the usage dashboard's charts in usage-and-limits. Answered
   2026-10-23: no chart library in v1; a requirement that asks for a chart brings its own ADR (DO-42.3 (a)).

## Acceptance (2026-10-23)

- Status Accepted by Đạt; `@dagrejs/dagre` is confirmed in the same exception as `@xyflow/react`, on one glob
  (override "React Flow (DO-42)").
- Decision 3: the dagre layout function lives under the canvas glob, so `apps/web/lib/workflow-graph.ts` stays pure
  (DO-42.1 (a)).
- Decision 4: an exception is written as a `{module, glob, adr}` entry (DO-42.1 (a)).
- Decision 6: no chart library in v1, rather than one decided before GA (DO-42.3 (a)).
- Consequences: the canvas route's bundle is measured on its own and recorded here; `ariaLabelConfig` comes from the
  message keys (DO-57 (a)).
- Amendment A3 restated to match the glob `apps/web/app/studio/**/canvas/**` and the allowlist entries.
- Open 1 to 3 answered.
