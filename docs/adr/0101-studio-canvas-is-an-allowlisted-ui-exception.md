---
status: Accepted (Đạt, 2026-10-23; amendments from the decision brief applied)
date: 2026-10-23
source:
    - ../../.claude/plans/studio/workflow-builder-ui/spec.md
    - ../../.claude/plans/studio/studio-skeleton/spec.md
    - ../../apps/web/lib/__tests__/antd-only.test.ts
    - ../../apps/web/.eslintrc.json
    - ../../apps/web/lib/csp.ts
    - ../../.claude/plans/studio/discovery/issues/24-workflow-canvas.md
    - 0112-workflows-compile-to-langgraph-one-effect-per-node.md
---

# 0101. The Studio builder canvas uses @xyflow/react on one path, laid out from the workflow's step tree by a pure module of the app, and the antd-only guard becomes an allowlist whose every exception has its own ADR

Numbered in the block 0100-0199 reserved for Studio (ADR 0100 records the block).

## Context

D2 makes builders business admins who work without code: they drag steps onto a canvas and configure each in a form
("kéo thả bước, biểu mẫu cấu hình", requirements D2). A workflow builder therefore needs a canvas: pan, zoom, drawn
connections, drop targets and keyboard paths.

`CLAUDE.md` (Web UI) allowed `antd`, `@ant-design/icons` and `@ant-design/nextjs-registry` "and nothing else" until this
ADR, the rule Đạt set on 2026-10-08 when he asked for antd everywhere. antd ships no graph canvas. The guard behind the
rule cannot see a library it does not name: `apps/web/lib/__tests__/antd-only.test.ts:16-18` is a denylist of the
removed modules, its manifest check (`:128-141`) reads the same list, and ESLint names the same modules
(`apps/web/.eslintrc.json:4-37`). Today `@xyflow/react`, or any kit nobody listed, passes every check
(failure-modes #0).

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

On 2026-10-24 Đạt asked for a canvas that business users find friendly and that holds complex flows, with back-and-forth
and human steps, and accepted the canvas research's recommendations (V4.24, V4.25). The research found that the look
comes from node and edge design rather than from the library: Activepieces (`@xyflow/react` 12.3.5 on React 19), Dify,
Windmill, Langflow, the Airflow UI and Sim all draw their own nodes on the xyflow family, and Activepieces and Windmill
ship `nodesDraggable` false, Activepieces computing positions from its flow tree with no layout library
(<https://github.com/activepieces/activepieces/blob/6f4be340d7c4bef9fb6ff874ca72224e4933d3d2/packages/web/src/app/builder/flow-canvas/index.tsx#L228-L240>).
React Flow's guide says dagre "has an open issue that prevents it from laying out sub-flows correctly"
(<https://reactflow.dev/learn/layouting/layouting>; dagre #238, open since 2018), and every container of a structured
canvas has edges crossing its boundary. In `@xyflow/react` 12.12.0 (`dist/esm/index.mjs` of
<https://registry.npmjs.org/@xyflow/react/-/react-12.12.0.tgz>) the arrow keys move a node only when it is draggable and
selected; every focusable node and every edge gets `tabIndex` 0; an edge's default label is the English "Edge from … to
…"; the node wrapper is a `div` with `onClick`; and the key handlers listen on the whole document, Backspace deleting,
Space panning and Shift selecting, so most of its accessibility defaults are switched off here and replaced. The `Tree`
of the installed antd 6.6.5 (`@rc-component/tree` 1.4.0) emits no `aria-level`, `aria-posinset` or `aria-setsize`. All
of this was read on 2026-10-24.

The web app's Content-Security-Policy gives scripts a per-request nonce with `strict-dynamic` and allows inline styles
because antd writes them at runtime (`apps/web/lib/csp.ts:16-23`); a canvas loaded as a dynamic chunk must work under
it, which the spike measures rather than assumes.

## Decision

1. **One library, an exact version, one path.** `apps/web` declares `@xyflow/react` `12.12.0`, exact: still the latest
   stable release on 2026-10-24, while `13.0.0-next.0` is a prerelease that moves its peers to zustand 5 and a compiler
   runtime and is not used. The lockfile holds one `zustand`, at 4.5.6 or above and never 5.x. No other manifest
   declares the library, `@dw/ui` neither depends on nor wraps it, and only files under
   `apps/web/app/studio/**/canvas/**` import it. `@dagrejs/dagre` is not admitted (V4.25). The canvas is a client
   component loaded with `next/dynamic` and `ssr: false` on two routes only: the builder, and the publish review
   screen (agent-lifecycle/07, YC116, V4.37), whose read-only diagram of the submitted version sits under the same
   glob, with workflow-builder-ui's layer of what differs from the `live` version, beside the gate's results and the
   estimated cost. The read-only diagram offers no slot and no move, so nothing done on it changes a document.
2. **antd draws everything but the pane.** The library draws the pane, the viewport and the edges. Every node body
   (antd `Card`), panel and form (`Form`, `Drawer`, `Tabs`), menu and notice is antd; the library's `Controls`,
   `MiniMap` and `NodeToolbar` are not used. `@xyflow/react/dist/base.css` is imported once into `@layer components`,
   with its `--xy-*` variables mapped to antd's `--ant-*` variables. Tailwind stays layout-only; colour, type and
   radius come from the antd theme in `@dw/ui`.
3. **The document holds the step tree; a pure module of the app computes every position.** The workflow document is a
   tree of steps (ADR-0112 (Accepted) decision 1) and holds no position. `apps/web/lib/workflow-layout.ts`, a pure
   TypeScript module outside the canvas glob that imports nothing, computes the positions from the tree in two passes,
   measuring bottom-up and placing top-down, in O(n), a collapsed container measured as one card, and returns plain
   shapes that the canvas maps to the library's nodes and edges. The same document always gives the same coordinates;
   inserting a step moves only what follows it in its lane and in the sequences that enclose that lane; inserting a
   block may push sibling lanes sideways but never changes vertical order or lane order. A builder never positions or
   wires anything: placing a step in a slot (the "+" on a connection, the "Thêm Bước" slot of an empty lane, or a drop
   from the palette) connects it, and moving a step is a tree operation, a drag into another slot or the keyboard; the
   flow runs from top to bottom only. The library's own interaction stays off: `nodesDraggable` and `nodesConnectable`
   are false; `nodesFocusable` and `edgesFocusable` are false, or one node at a time is focusable for roving focus, the
   focus targets being antd Buttons inside the cards (`.claude/rules/ui-quality.md` §3); every edge's `ariaLabel` is
   Vietnamese or `null`; `deleteKeyCode`, `panActivationKeyCode`, `selectionKeyCode` and `multiSelectionKeyCode` are
   `null`, the app owning deletion; and every key handler of the app ignores a key event while `isComposing`, so Telex
   typing never fires one. An edit changes the tree only (insert, move, delete), so the definition hash (ADR 0109)
   carries no layout, and which containers a viewer has collapsed is kept for that viewer, never in the document. The
   browser checks nothing beyond display: validation and graph checks belong to the server's validator (ADR 0112).
4. **The guard becomes an allowlist.** `antd-only.test.ts` accepts in `apps/web` and `packages/typescript/ui` only
   listed runtime dependencies (today `antd`, `@ant-design/icons`, `@ant-design/nextjs-registry`, `dayjs`,
   `keycloak-js`, `next`, `react`, `react-dom` and `@dw/*`) plus exceptions. An exception is a `{module, glob, adr}`
   entry: the module, the path glob that may import it, one path or the whole app, and the ADR that admits it; an import
   of that module outside its glob fails. An ADR admits only a library that supports antd without bringing a component
   set of its own (Đạt, 2026-10-24, V4.29). This ADR's one entry is `@xyflow/react` on
   `apps/web/app/studio/**/canvas/**`, so `@dagrejs/dagre`, which no entry lists, fails wherever it is imported. ESLint
   carries the same rule, with an `overrides` entry per glob. Any other library fails until its own ADR admits it, and
   the modules removed on 2026-10-08 stay refused because no entry lists them.
5. **The attribution badge stays, at the bottom left.** The React Flow attribution badge is kept, `attributionPosition`
   set to the bottom left so that the configuration Drawer never covers it, and no React Flow Pro licence is bought. The
   badge is React Flow's request, not a term of its MIT licence
   (<https://reactflow.dev/learn/troubleshooting/remove-attribution>).
6. **Charts are not covered, and v1 ships none.** The usage screen (`/usage`) and every other dashboard use antd
   `Statistic`, `Table` and `Progress`; a chart library needs its own ADR, written when a requirement asks for a chart,
   and the allowlist refuses one until then.

## Alternatives considered

- **antd only, or an own SVG canvas.** Rejected: antd has no canvas, and an own one would rebuild pan, zoom and pinch,
  viewport arithmetic, culling and touch handling, which the library still gives once its drag and connect are off;
  focus, announcements and drop targets are the app's to build either way (an own canvas was estimated at 800-1,500
  lines, above).
- **A form-only builder with no canvas.** Rejected: D2 asks for dragging steps ("kéo thả bước"), and a linear form
  cannot show parallel lanes, loops and maps.
- **A free-form graph** (n8n, Dify, Camunda's modeler), its positions stored or computed. Rejected (V4.24): its edits
  pass through unstructured states, so layout and joins break mid-edit; the library has no keyboard path to connect two
  nodes; n8n's branches run in canvas order, so moving a node changes what runs; a layout derived from structure is what
  keeps a flow tidy, and Power Automate, the largest builder for business admins, is block-structured
  (ADR-0112 (Accepted), Alternatives). Back-and-forth across days lives in a record's Stages (ADR-0126 (Accepted));
  within one run, loops and their breaks cover rework.
- **Storing node positions.** Rejected: a second copy of layout that drifts from topology (failure-modes #2); a cosmetic
  move would change the definition hash, invalidate evaluation evidence keyed by it and cause merge conflicts.
- **A blanket exemption for the library.** Rejected: the next library would slip in with no decision recorded.
- **dagre for the layout**, admitted beside the library on 2026-10-23. Removed (V4.25): React Flow's guide says it
  cannot lay out sub-flows whose nodes connect outside them (Context), which is every container of the structured
  canvas, and a global ranker can reorder lanes after a small edit, while the tree already holds the structure that
  Activepieces lays out with no layout library. If `workflow-layout.ts` fails, the module is fixed, Activepieces'
  MIT-licensed `flow-canvas-utils.ts` (729 lines at commit 6f4be340) serving as a reference credited in the source, and
  dagre is not admitted again. Provenance is no reason here: antd and most of the library's own dependencies are
  published without it too.
- **Another canvas or layout library**, each read or measured on 2026-10-24:
    - AntV X6 3.1.8: no ARIA or role attributes, and nodes that take no focus; about 172 kB gzip, with no layout engine
      and no tree-shaking; a `tslib` it uses at run time but does not declare, and `"type": "module"` over a CommonJS
      `main` (<https://github.com/antvis/X6/issues/5048>); React 19 unconfirmed
      (<https://github.com/antvis/X6/issues/4652>); plugins that inject unlayered `<style>` elements, which beat every
      `@layer`; each node in its own React root, out of reach of antd's `ConfigProvider` and `App` context; and 19
      accounts that can publish it, among them the compromised one that published the malicious 3.2.7 and 3.3.7
      (<https://api.osv.dev/v1/vulns/MAL-2026-3839>), the weakest of these reasons.
    - Rete.js v2: its nesting plugin `rete-scopes-plugin` is CC-BY-NC-SA-4.0
      (<https://registry.npmjs.org/rete-scopes-plugin>), which rules out commercial use; no keyboard or ARIA support; a
      React root per element, so antd's context is lost; and styled-components as a second CSS-in-JS runtime.
    - bpmn-js 18.31.1: its licence keeps the bpmn.io watermark "fully visible and not visually overlapped"
      (<https://raw.githubusercontent.com/bpmn-io/bpmn-js/develop/LICENSE>), which a Drawer and the 320 px width cannot
      promise; its shapes are its own SVG, not antd node bodies; its modeler is built for free placement, which a
      derived layout would fight after every edit; its shapes have no names for a screen reader; 163 kB gzip, 411 kB
      with its properties panel.
    - React Flow Pro's workflow editor templates: built on shadcn/ui, Tailwind and ELK, the stack removed on 2026-10-08,
      under a licence that forbids redistributing them (<https://reactflow.dev/ui/templates/workflow-editor>,
      <https://xyflow.com/pro-license>); their patterns (a placeholder step, "+" on an edge, a status mark, a labelled
      group) are rebuilt in antd.
    - elkjs 0.12.0: about 462-467 kB gzip as measured, where si-platform's figure above was 434 kB; a step tree needs no
      general graph layouter, though one suits a free-form graph, as the Airflow UI uses it.
    - FlowGram.ai's fixed layout (`@flowgram.ai/fixed-layout-editor` 1.0.16): about 195 kB gzip; no ARIA or role
      attributes; unlayered style injection at run time; `inversify` and `reflect-metadata` globals; form and variable
      engines of its own, second owners of facts the server owns; commits down from 349 in the second half of 2025 to 30
      in the first half of 2026. Its node set (if, switch, loop, break, try-catch) serves as a checklist for the
      grammar.
    - Not evaluated: commercial kits (JointJS+, GoJS, yFiles), `@joint/react` (MPL-2.0) and reaflow (built on ELK).
- **React Flow Pro to hide the badge.** Not bought (point 5), confirmed on 2026-10-23 and open to change at any time
  (Open 2).

## Consequences

- workflow-builder-ui depends on this ADR's acceptance. studio-skeleton ticket 03 turns the guard into an allowlist
  without widening it, with a test proving an unlisted import is still red. workflow-builder-ui ticket 01 then runs the
  spike that discovery 24 describes ("Sơ đồ quy trình: @xyflow/react với bố cục cấu trúc dưới CSP nonce, lớp antd, Next
  15.5 và React 19") and adds the canvas's `{module, glob, adr}` entry in the same commit as the first canvas import.
  The spike builds a draft page under the canvas glob, with no dagre: `workflow-layout.ts`, antd cards, lanes,
  containers, "+" slots, the error lane, the loop's return arrow, the outline `Tree`, the keyboard model, and drags from
  the palette and of a step onto slots. Its fixtures are F1 (the 15-step lead intake), F2 (an 8-lane switch nested two
  deep), F3 (three parallel lanes in a loop in a switch), F4 (an error lane on every step), F5 (a rework loop with an
  approval, and a step every approver must approve), F6 and F7 (300 and 500 steps), F8 (the longest real Vietnamese
  names) and F9 (a three-level approval whose rejection returns to different earlier steps by reason, which tests the
  tree's limit before anything is built on the document). It measures CSP violations and canvas CSS overridden by the
  antd layer (0); the canvas route's first-load JS; React 19 with a Next 15.5 production build, StrictMode, `ssr: false`
  and one zustand; the layout of F1 to F9 against decision 3's invariants, by snapshot and property tests, with its p95
  time at 500 steps; 300 and 500 antd cards (first render, pan and zoom frame rate, memory, `onlyRenderVisibleElements`,
  roving focus that survives culling); a keyboard-only Playwright run; 320 px and touch; NVDA in Vietnamese on the
  outline; the visual checks (dark mode, 3:1 contrast, reduced motion, the badge never covered); and five business users
  on scripted tasks, whose recruitment waits on DO-22 (Đạt).
- The first-load cost of the canvas route is measured on its own by workflow-builder-ui ticket 01 and recorded here and
  in the workflow-builder-ui spec: the roughly 250 kB first-load budget accepted for antd (`CLAUDE.md`, Web UI) does not
  cover it. About 60 kB gzip of JS is expected for the library with its dependencies, and the app's own canvas code is
  unmeasured until the spike.
- Tests, each shown red by removing its guard: `@xyflow/react` imported outside `apps/web/app/studio/**/canvas/**`
  fails; `@dagrejs/dagre` imported anywhere fails; a manifest other than `apps/web/package.json` declaring
  `@xyflow/react` fails; an unlisted runtime dependency fails; the `dw.workflow/v1` schema refuses a document that
  carries coordinates, so a stored position cannot slip in; one document laid out twice gives the same coordinates, and
  an insert moves only what decision 3 lets it move (property tests over random trees); every node of the outline `Tree`
  carries `aria-level`, `aria-posinset` and `aria-setsize`, which antd 6.6.5 does not emit; the review screen's
  diagram, given a drop or a key that edits in the builder, sends no save.
- From the canvas the builder submits a version for the quality gate ("Gửi kiểm định") and starts `simulate` runs
  (`test` runs later, ADR 0111); it never publishes by itself (ADR 0120). The approver of a publish reads the same
  layout, read-only, on the review screen of agent-lifecycle/07 (decision 1), so what changed is seen in the diagram
  and not only in the document; that route's first-load JS is measured on its own, as the builder's is.
- workflow-builder-ui owes the accessible path: every mouse action has a keyboard path, with roving focus in document
  order (↑ and ↓ to the step before and after, ← and → to the next lane, Enter to the configuration, Esc back to the
  step, Shift+F10 for the menu, Ctrl+Z and Ctrl+Shift+Z), single-key shortcuts only while the canvas has focus
  (WCAG 2.1.4) and an `aria-live` notice for each insert, move and delete; `ariaLabelConfig` is in Vietnamese, taken
  from the message keys (DO-57); and the outline view (antd `Tree`) is the document tree itself, the path for screen
  readers and the main editor below `md` and at 320 px.
- The canvas's visual vocabulary is the product's own (V4.27, V4.29). An agent drafts it in the spike (category colours
  from theme tokens, such as trigger blue, AI purple, data cyan, logic gold, human magenta, tool green and error red,
  each checked for 3:1 contrast; `@ant-design/icons`; card size; edge styles), it is recorded once in `@dw/ui`'s theme
  for Đạt's review, and category tiles never use antd's light preset tints (`.claude/rules/ui-quality.md` §12). Patterns
  are learned and never copied: Dify's licence claims an appearance patent on its interactive design
  (<https://raw.githubusercontent.com/langgenius/dify/main/LICENSE>, read 2026-10-24), Windmill's frontend is AGPLv3 and
  n8n is under the Sustainable Use License, so no code or look is taken from them, while Windmill's OpenFlow
  specification (Apache-2.0) and Power Automate's flows serve as checklists for the grammar. Motion beyond antd's own
  waits for a later decision with its own library ADR, the motion rules of `.claude/rules/ui-quality.md` standing until
  then.
- Harder: every future UI library needs an ADR before its first import; an `@xyflow/react` major upgrade
  (`13.0.0-next.0`, a prerelease since 2026-10-11, moves its peers to zustand 5 and a compiler runtime) is a deliberate
  change with a new measurement, never an automatic bump; the modules outside the canvas path,
  `apps/web/lib/workflow-graph.ts` (operations on the tree) and `apps/web/lib/workflow-layout.ts` (positions), import
  nothing from the library and return plain shapes the canvas adapts; and the layout is the app's to keep correct, fixed
  rather than replaced when it fails.

### Contradictions (the amendment applies only when this ADR is accepted)

- Contradicted `CLAUDE.md` (Web UI, "One component system", "and nothing else"), Đạt's 2026-10-08 antd-everywhere
  decision, worth reopening because antd has no canvas and D2 asks for one. Amendment A3 made the change on acceptance,
  and Đạt's decisions of 2026-10-24 (V4.25, V4.29) restate it: the bullet now lets a library that supports antd without
  bringing a component set of its own join through its own ADR and an allowlist entry, app-wide or for one path; names
  the canvas exception, `@xyflow/react`, pinned exactly, only under `apps/web/app/studio/**/canvas/**`, laid out by the
  app's own module from the workflow's step tree, antd still drawing every node body, panel, form and notice; keeps the
  modules removed on 2026-10-08 out; and describes `antd-only.test.ts` as an allowlist of `{module, glob, adr}` entries
  in which an unlisted library, or an excepted one imported outside its glob, fails. The Bundle line says that the
  canvas route is measured on its own.
- Changes `apps/web/lib/__tests__/antd-only.test.ts` and `apps/web/.eslintrc.json` from denylists into an allowlist. The
  amendment narrows the rule's exceptions to named globs, each admitted by its own ADR; it does not reopen the
  2026-10-08 sweep.

### Relation to si-platform

- Reuses the measured reasoning of si-platform
  `docs/adr/0049-the-approval-builder-canvas-is-xyflow-react-laid-out-by-dagre.md` for `@xyflow/react`: the same
  version, layering (antd node bodies, `base.css` in the components layer, `next/dynamic` without SSR) and kept
  attribution.
- Diverges in four ways. The library is confined to one import path by test, where si-platform asserts only which
  manifest declares it. "Positions never stored" is a property of the document format that a schema test enforces, where
  si-platform computes positions at render too but leaves stored placement open as a later schema change. It serves a
  general workflow builder in `apps/web`, not an approval builder in `apps/web-admin`. And since 2026-10-24 the
  positions come from the workflow's step tree through the app's own module, with no dagre.

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

## Amendments (2026-10-24)

- Third consistency check (round 4), seventh pass, Đạt's V4.24, V4.25, V4.27 and V4.29 after the canvas research: the
  title and decisions 1 and 4 admit `@xyflow/react` 12.12.0 alone, with one `zustand` of the 4.x line in the lockfile,
  and drop `@dagrejs/dagre`, which DO-42.1 (a) and the Acceptance lines above had admitted in the same exception;
  decision 3 makes the document a step tree whose positions the pure module `apps/web/lib/workflow-layout.ts` computes
  under the invariants it states, steps placed in slots and the library's drag, connect, focus and key handling switched
  off, replacing the dagre layout function under the canvas glob; decision 4 lets an exception's glob name the whole app
  and admits only a library that supports antd without a component set of its own, as `CLAUDE.md` (Web UI) now says;
  decision 5 places the badge at the bottom left; Context and Alternatives carry the research's sourced reasons as its
  review corrected them (X6's malware advisory the weakest of its reasons, elkjs measured at 462-467 kB gzip, provenance
  no reason at all, FlowGram.ai added, D2 quoted as "kéo thả bước" with no "connect"); Consequences carry the new spike
  of discovery 24, the visual vocabulary, the accessible path and the outline's `aria-level`, `aria-posinset` and
  `aria-setsize`.

## Amendments (2026-10-25)

- Third consistency check (round 4), eighth pass, Đạt's V4.37: decision 1 loads the canvas on a second route, the
  publish review screen of agent-lifecycle/07 (YC116), whose read-only diagram of the submitted version, with
  workflow-builder-ui's layer of what differs from the `live` version, sits under the same glob, where the canvas
  was loaded on the builder route only; Consequences add that the approver reads the diagram there, that the route's
  first-load JS is measured on its own, and a test that the read-only diagram sends no save.
