import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  addLane,
  catalogueOf,
  insertStep,
  laneAt,
  locate,
  newStep,
  toStepNode,
  toTree,
  treeIds,
  walk,
  type LaneRef,
  type Slot,
  type StepNode,
  type WorkflowTree,
} from "../workflow-graph";
import { layoutWorkflow, metricsFor, slotAt } from "../workflow-layout";
import type { CanvasShapes } from "../workflow-shapes";
import { FIXTURES, NODE_TYPES, loadFixture } from "./workflow-catalogue";

/**
 * The layout is a function of the step tree (workflow-builder-ui R1.5, R1.6,
 * BU13; ADR-0101 (Accepted) decision 3), checked as properties on F1-F9 and
 * on 200 random trees: the same document lands at the same coordinates; an
 * insert moves only what follows it, and only down; a step with lanes may
 * push sibling lanes sideways but moves nothing before it vertically; vertical
 * order and lane order hold; no two cards overlap.
 */

const catalogue = catalogueOf(NODE_TYPES);
// The vocabulary's card (`CANVAS_VOCABULARY.card` of @dw/ui).
const METRICS = metricsFor({ width: 256, height: 120 });
const lay = (t: WorkflowTree) => layoutWorkflow(t, METRICS);

/** mulberry32: a seeded generator, so a failing tree can be rebuilt. */
function seeded(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ (t + t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

let serial = 0;
function randomSteps(
  random: () => number,
  depth: number,
  budget: { n: number },
): unknown[] {
  const out: unknown[] = [];
  const count = Math.floor(random() * 4) + (depth === 0 ? 1 : 0);
  for (let i = 0; i < count && budget.n > 0; i++) {
    budget.n -= 1;
    const id = `s${(serial += 1)}`;
    const pick = depth >= 3 ? 0 : Math.floor(random() * 9);
    const nested = () => randomSteps(random, depth + 1, budget);
    const step: Record<string, unknown> = {
      id,
      type: "data.transform@1",
      config: {},
    };
    if (pick === 1) {
      step.type = "logic.switch@1";
      const cases: Record<string, unknown> = {};
      const n = 1 + Math.floor(random() * 3);
      for (let c = 0; c < n; c++) cases[`c${c}`] = nested();
      step.config = { on: "x", cases, default: nested() };
    } else if (pick === 2) {
      step.type = "human.approval@2";
      step.config = { approved: nested(), rejected: nested() };
    } else if (pick === 3) {
      step.type = "logic.loop@1";
      step.config =
        random() < 0.5
          ? { body: nested() }
          : { body: nested(), max_reached: nested() };
    } else if (pick === 4) {
      step.on_error = "route";
      step.error_lane = nested();
    } else if (pick === 5) {
      step.type = "logic.parallel@1";
      const branches: Record<string, unknown> = {};
      const n = 2 + Math.floor(random() * 2);
      for (let c = 0; c < n; c++) branches[`b${c}`] = nested();
      step.config = { branches };
    } else if (pick === 6) {
      step.type = "flow.stop@1";
    } else if (pick === 7) {
      step.type = "logic.break@1";
    }
    out.push(step);
  }
  return out;
}

function randomTree(seed: number): WorkflowTree {
  const random = seeded(seed);
  const steps = randomSteps(random, 0, { n: 40 });
  return toTree({ schema: "dw.workflow/v1", triggers: [], steps }, catalogue);
}

const TREES = Array.from({ length: 200 }, (_, i) => randomTree(42 + i));

function overlaps(
  a: { x: number; y: number; width: number; height: number },
  b: typeof a,
) {
  return (
    a.x < b.x + b.width &&
    b.x < a.x + a.width &&
    a.y < b.y + b.height &&
    b.y < a.y + a.height
  );
}

function noOverlap(shapes: CanvasShapes): string[] {
  const boxes = [
    ...shapes.cards.map((c) => ({ ...c, what: `card ${c.id}` })),
    ...shapes.laneHeads.map((h) => ({ ...h, what: `head ${h.id}` })),
    ...shapes.slots.map((s) => ({ ...s, what: `slot ${s.id}` })),
    ...shapes.joins
      .filter((j) => j.kind === "bar")
      .map((j) => ({ ...j, what: `bar ${j.id}` })),
  ];
  const found: string[] = [];
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      if (overlaps(boxes[i]!, boxes[j]!))
        found.push(`${boxes[i]!.what} × ${boxes[j]!.what}`);
    }
  }
  return found;
}

/** Vertical order within every lane and lane order within every block. */
function orderProblems(t: WorkflowTree, shapes: CanvasShapes): string[] {
  const card = new Map(shapes.cards.map((c) => [c.id, c]));
  const head = new Map(shapes.laneHeads.map((h) => [h.id, h]));
  const found: string[] = [];
  const lane = (steps: StepNode[]) => {
    for (let i = 1; i < steps.length; i++) {
      if (card.get(steps[i]!.id)!.y <= card.get(steps[i - 1]!.id)!.y) {
        found.push(`${steps[i]!.id} not below ${steps[i - 1]!.id}`);
      }
    }
  };
  lane(t.steps);
  walk(t, (node) => {
    // A loop's body has no head (its frame holds it): order counts the lanes
    // that do.
    const block = node.lanes.filter(
      (l) => l.kind !== "error" && head.has(`head:${node.id}:${l.port}`),
    );
    for (let i = 1; i < block.length; i++) {
      const a = head.get(`head:${node.id}:${block[i - 1]!.port}`)!;
      const b = head.get(`head:${node.id}:${block[i]!.port}`)!;
      if (b.x <= a.x)
        found.push(
          `${node.id}: ${block[i]!.port} not right of ${block[i - 1]!.port}`,
        );
    }
    for (const l of node.lanes) lane(l.steps);
  });
  return found;
}

/** The ids an insert at `slot` may move: what follows it in its lane, and
 * what follows each holder in the lanes around it, with their subtrees. A
 * loop's other lanes ("Đã đủ N lần") follow its body: they hang under its
 * frame, where the flow goes once the body is done. */
function mayMove(t: WorkflowTree, slot: Slot): Set<string> {
  const allowed = new Set<string>();
  const take = (steps: StepNode[], from: number) => {
    for (const step of steps.slice(from)) {
      walk({ rest: {}, steps: [step] }, (n) => allowed.add(n.id));
    }
  };
  take(laneAt(t, slot.lane)!.steps, slot.index);
  let lane = slot.lane;
  while (lane.parent !== null) {
    const at = locate(t, lane.parent)!;
    const inner = at.node.lanes.filter((l) => l.kind !== "error");
    if (at.node.shape.block === "loop" && inner[0]?.port === lane.port) {
      for (const hung of inner.slice(1)) take(hung.steps, 0);
    }
    take(laneAt(t, at.lane)!.steps, at.index + 1);
    lane = at.lane;
  }
  return allowed;
}

function everySlot(t: WorkflowTree): Slot[] {
  const slots: Slot[] = [];
  const add = (lane: LaneRef, length: number) => {
    for (let i = 0; i <= length; i++) slots.push({ lane, index: i });
  };
  add({ parent: null, port: "steps" }, t.steps.length);
  walk(t, (node) => {
    for (const l of node.lanes)
      add({ parent: node.id, port: l.port }, l.steps.length);
  });
  return slots;
}

function plainStep(t: WorkflowTree): StepNode {
  return toStepNode(
    newStep(catalogue.get("data.transform@1")!, treeIds(t)),
    catalogue,
  );
}

/** A switch three lanes wide, wider than any card. */
function wideStep(t: WorkflowTree): StepNode {
  const raw = newStep(catalogue.get("logic.switch@1")!, treeIds(t));
  let alone: WorkflowTree = { rest: {}, steps: [toStepNode(raw, catalogue)] };
  for (const name of ["a", "b"]) {
    const out = addLane(alone, raw.id as string, name, catalogue);
    if (out.ok) alone = out.tree;
  }
  return alone.steps[0]!;
}

describe("the layout of F1-F9 (R1.5, R1.6)", () => {
  it.each(FIXTURES)(
    "%s: same document, same coordinates; nothing overlaps; order holds",
    (name) => {
      const first = lay(toTree(loadFixture(name), catalogue));
      const again = lay(toTree(loadFixture(name), catalogue));
      expect(again).toEqual(first);
      const t = toTree(loadFixture(name), catalogue);
      expect(noOverlap(first)).toEqual([]);
      expect(orderProblems(t, first)).toEqual([]);
    },
  );

  it("F1 runs top to bottom with a + of at least 24 px on every connection", () => {
    const t = toTree(loadFixture("f1"), catalogue);
    const shapes = lay(t);
    for (const c of shapes.connections.filter((c) => !c.dashed)) {
      for (let i = 1; i < c.points.length; i++) {
        expect(c.points[i]!.y, c.id).toBeGreaterThanOrEqual(c.points[i - 1]!.y);
      }
    }
    const plus = shapes.slots.filter((s) => !s.empty);
    for (const s of plus) {
      expect(s.width).toBeGreaterThanOrEqual(24);
      expect(s.height).toBeGreaterThanOrEqual(24);
    }
    // One + before, between and after the steps of every lane that has any.
    let expected = t.steps.length + 1;
    let empty = 0;
    walk(t, (node) => {
      for (const l of node.lanes) {
        if (l.steps.length > 0) expected += l.steps.length + 1;
        else empty += 1;
      }
    });
    expect(plus).toHaveLength(expected);
    expect(shapes.slots.filter((s) => s.empty)).toHaveLength(empty);
    // Every + sits on the connection into the step after it.
    const card = new Map(shapes.cards.map((c) => [c.id, c]));
    for (const s of plus.filter((s) => s.after !== null)) {
      const after = card.get(s.after!)!;
      expect(s.x + s.width / 2).toBe(after.x + after.width / 2);
    }
  });

  it("an empty lane has its dashed Thêm Bước slot, the switch's Khác lane included", () => {
    const t = toTree(loadFixture("f1"), catalogue);
    const sw = t.steps.find((s) => s.type === "logic.switch@1")!;
    const raw = newStep(catalogue.get("logic.switch@1")!, treeIds(t));
    const out = insertStep(
      t,
      { lane: { parent: null, port: "steps" }, index: 0 },
      toStepNode(raw, catalogue),
    );
    if (!out.ok) throw new Error(out.reason);
    const empty = lay(out.tree).slots.filter((s) => s.empty);
    expect(empty.map((s) => s.id)).toContain(
      `lane:${raw.id as string}:default`,
    );
    expect(sw).toBeDefined();
  });

  it("F7's 500 steps lay out under 50 ms at p95", () => {
    const t = toTree(loadFixture("f7"), catalogue);
    for (let i = 0; i < 20; i++) lay(t);
    const times: number[] = [];
    for (let i = 0; i < 200; i++) {
      const start = performance.now();
      lay(t);
      times.push(performance.now() - start);
    }
    times.sort((a, b) => a - b);
    const p = (q: number) =>
      times[Math.min(times.length - 1, Math.floor(q * times.length))]!;
    console.info(
      `workflow-layout F7: p50 ${p(0.5).toFixed(2)} ms, p95 ${p(0.95).toFixed(2)} ms, p99 ${p(0.99).toFixed(2)} ms`,
    );
    expect(p(0.95)).toBeLessThan(50);
  });
});

describe("inserting on 200 random trees (R1.6, BU13)", () => {
  it("is deterministic, and nothing overlaps or leaves its order", () => {
    for (const t of TREES) {
      const shapes = lay(t);
      expect(lay(t)).toEqual(shapes);
      expect(noOverlap(shapes)).toEqual([]);
      expect(orderProblems(t, shapes)).toEqual([]);
    }
  });

  it("a card moves only what follows the insert, and only down", () => {
    TREES.forEach((t, n) => {
      const random = seeded(7 + n);
      const slots = everySlot(t);
      const slot = slots[Math.floor(random() * slots.length)]!;
      const out = insertStep(t, slot, plainStep(t));
      if (!out.ok) throw new Error(out.reason);
      const before = new Map(lay(t).cards.map((c) => [c.id, c]));
      const after = lay(out.tree);
      const allowed = mayMove(t, slot);
      for (const card of after.cards) {
        const old = before.get(card.id);
        if (!old) continue;
        const where = `tree ${n}, ${card.id} after insert at ${JSON.stringify(slot)}`;
        expect(card.x, where).toBe(old.x);
        expect(card.y, where).toBeGreaterThanOrEqual(old.y);
        if (card.y !== old.y) expect(allowed.has(card.id), where).toBe(true);
      }
      expect(noOverlap(after)).toEqual([]);
      expect(orderProblems(out.tree, after)).toEqual([]);
    });
  });

  it("a step with lanes moves nothing before it vertically, and keeps order", () => {
    TREES.forEach((t, n) => {
      const random = seeded(1000 + n);
      const slots = everySlot(t);
      const slot = slots[Math.floor(random() * slots.length)]!;
      const out = insertStep(t, slot, wideStep(t));
      if (!out.ok) throw new Error(out.reason);
      const before = new Map(lay(t).cards.map((c) => [c.id, c]));
      const after = lay(out.tree);
      const allowed = mayMove(t, slot);
      for (const card of after.cards) {
        const old = before.get(card.id);
        if (!old || allowed.has(card.id)) continue;
        expect(card.y, `tree ${n}, ${card.id}`).toBe(old.y);
      }
      expect(noOverlap(after)).toEqual([]);
      expect(orderProblems(out.tree, after)).toEqual([]);
    });
  });
});

describe("folded frames on 200 random trees (R1.7)", () => {
  it("are cards: nothing overlaps, nothing inside is drawn, the same each time", () => {
    TREES.forEach((t, n) => {
      const frames = new Set<string>();
      walk(t, (node) => {
        if (node.shape.block === "parallel" || node.shape.block === "loop") {
          frames.add(node.id);
        }
      });
      const random = seeded(3000 + n);
      const folded = new Set([...frames].filter(() => random() < 0.5));
      const shapes = layoutWorkflow(t, METRICS, folded);
      expect(layoutWorkflow(t, METRICS, folded)).toEqual(shapes);
      expect(noOverlap(shapes), `tree ${n}`).toEqual([]);
      const drawn = new Set(shapes.cards.map((c) => c.id));
      walk(t, (node) => {
        // A frame folded inside a folded frame is not drawn at all.
        if (!folded.has(node.id) || !drawn.has(node.id)) return;
        expect(shapes.cards.find((c) => c.id === node.id)!.folded).toBe(true);
        for (const lane of node.lanes.filter((l) => l.kind !== "error")) {
          for (const step of lane.steps) {
            expect(drawn.has(step.id), `tree ${n}, ${step.id}`).toBe(false);
          }
        }
      });
    });
  });

  it("folding a frame moves nothing before it", () => {
    TREES.forEach((t, n) => {
      const open = new Map(lay(t).cards.map((c) => [c.id, c]));
      walk(t, (node) => {
        if (node.shape.block !== "parallel" && node.shape.block !== "loop")
          return;
        const shapes = layoutWorkflow(t, METRICS, new Set([node.id]));
        const at = open.get(node.id)!;
        // The frame's own card rises by the frame's padding, with its
        // Khi lỗi lane: what it holds is no longer around it.
        const own = new Set<string>();
        walk({ rest: {}, steps: [node] }, (n) => own.add(n.id));
        for (const card of shapes.cards) {
          const before = open.get(card.id)!;
          if (!own.has(card.id) && before.y <= at.y) {
            expect(card.y, `tree ${n}, ${card.id}`).toBe(before.y);
          }
        }
      });
    });
  });
});

describe("a drop lands on a slot or nowhere (R1.4)", () => {
  it("finds the + under a point, and nothing on empty canvas", () => {
    const shapes = lay(toTree(loadFixture("f1"), catalogue));
    const s = shapes.slots[1]!;
    expect(
      slotAt(shapes, { x: s.x + s.width / 2, y: s.y + s.height / 2 })?.id,
    ).toBe(s.id);
    expect(slotAt(shapes, { x: -5000, y: -5000 })).toBeNull();
    expect(slotAt(shapes, { x: s.x + 1, y: s.y + 1 }, () => false)).toBeNull();
  });
});

describe("the module imports no package", () => {
  it("only types of its sibling pure modules", () => {
    const text = readFileSync(
      resolve(__dirname, "../workflow-layout.ts"),
      "utf8",
    );
    const specifiers = [
      ...text.matchAll(/^\s*import\s[^;]*?from\s+["']([^"']+)["']/gm),
    ].map((m) => m[1]);
    expect(specifiers.length).toBeGreaterThan(0);
    for (const specifier of specifiers) {
      expect(["./workflow-graph", "./workflow-shapes"]).toContain(specifier);
    }
    expect(text).not.toMatch(/\brequire\(|\bimport\(/);
  });
});
