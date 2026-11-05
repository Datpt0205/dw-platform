import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  addLane,
  catalogueOf,
  commit,
  deleteStep,
  emptyLaneStop,
  fromTree,
  history,
  insertStep,
  locate,
  moveStep,
  navigate,
  newStep,
  removeLane,
  setOnError,
  stepName,
  stopsInOrder,
  toStepNode,
  toTree,
  treeIds,
  undo,
  redo,
  updateStepFields,
  type WorkflowTree,
} from "../workflow-graph";
import { FIXTURES, NODE_TYPES, loadFixture } from "./workflow-catalogue";

/**
 * The tree operations of the builder (workflow-builder-ui R1.4, R2.5, R2.10,
 * R2.11; BU8): every edit is one insert, move or delete on the document's
 * step tree, nothing positional ever reaches the document, and the tree
 * reads back as the document it came from.
 */

const catalogue = catalogueOf(NODE_TYPES);
const tree = (name: string) => toTree(loadFixture(name), catalogue);
const ids = (t: WorkflowTree) => {
  const out: string[] = [];
  const go = (steps: WorkflowTree["steps"]) => {
    for (const s of steps) {
      out.push(s.id);
      for (const l of s.lanes) go(l.steps);
    }
  };
  go(t.steps);
  return out;
};
const ok = (outcome: ReturnType<typeof insertStep>) => {
  if (!outcome.ok) throw new Error(`refused: ${outcome.reason}`);
  return outcome;
};

describe("document → tree → document (R1.4, BU8)", () => {
  it.each(FIXTURES)("%s reads back key for key", (name) => {
    const doc = loadFixture(name);
    // toStrictEqual: an optional key absent stays absent, not `undefined`.
    expect(fromTree(toTree(doc, catalogue))).toStrictEqual(doc);
  });

  it("keeps a lane the catalogue has no port for, and a step it has no type for", () => {
    const doc = loadFixture("f1");
    const steps = doc.steps as Record<string, unknown>[];
    steps.push({
      id: "la",
      type: "x.unknown@1",
      config: { inner: [{ id: "con", type: "data.transform@1", config: {} }] },
    });
    expect(fromTree(toTree(doc, catalogue))).toStrictEqual(doc);
  });

  it("writes an edited tree with no position, edge or layout key", () => {
    const t = tree("f1");
    const spec = catalogue.get("ai.llm@2")!;
    const step = toStepNode(newStep(spec, treeIds(t)), catalogue);
    const out = JSON.stringify(
      fromTree(
        ok(
          insertStep(
            t,
            { lane: { parent: null, port: "steps" }, index: 2 },
            step,
          ),
        ).tree,
      ),
    );
    for (const key of [
      '"x"',
      '"y"',
      '"position"',
      '"edges"',
      '"nodes"',
      '"collapsed"',
    ]) {
      expect(out).not.toContain(`${key}:`);
    }
  });
});

describe("insert and move are one tree operation at the slot's lane and index (R1.4)", () => {
  it("inserts at the index of the slot, the lane's other steps in order", () => {
    const t = tree("f1");
    const step = toStepNode(
      newStep(catalogue.get("ai.llm@2")!, treeIds(t)),
      catalogue,
    );
    const before = t.steps.map((s) => s.id);
    const next = ok(
      insertStep(t, { lane: { parent: null, port: "steps" }, index: 0 }, step),
    ).tree;
    expect(next.steps.map((s) => s.id)).toEqual([step.id, ...before]);
  });

  it("writes a default lane that was drawn but not written once a step goes in", () => {
    const doc = loadFixture("f1");
    const sw = (doc.steps as Record<string, unknown>[]).find(
      (s) => s.type === "logic.switch@1",
    )!;
    delete (sw.config as Record<string, unknown>).default;
    const t = toTree(doc, catalogue);
    const step = toStepNode(
      newStep(catalogue.get("ai.llm@2")!, treeIds(t)),
      catalogue,
    );
    const out = fromTree(
      ok(
        insertStep(
          t,
          { lane: { parent: sw.id as string, port: "default" }, index: 0 },
          step,
        ),
      ).tree,
    );
    const written = (out.steps as Record<string, unknown>[]).find(
      (s) => s.id === sw.id,
    )!;
    expect((written.config as Record<string, unknown[]>).default).toHaveLength(
      1,
    );
  });

  it("moves a step into another lane, and back to where it was is a no-op", () => {
    const t = tree("f1");
    const sw = t.steps.find((s) => s.type === "logic.switch@1")!;
    const first = t.steps[0]!;
    const moved = ok(
      moveStep(t, first.id, {
        lane: { parent: sw.id, port: "default" },
        index: 0,
      }),
    );
    expect(locate(moved.tree, first.id)!.lane).toEqual({
      parent: sw.id,
      port: "default",
    });
    expect(moved.tree.steps.map((s) => s.id)).not.toContain(first.id);
    const back = ok(
      moveStep(t, first.id, {
        lane: { parent: null, port: "steps" },
        index: 1,
      }),
    );
    expect(back.tree).toBe(t);
  });

  it("moves down a lane to the index the slot names", () => {
    const t = tree("f1");
    const [a, b, c] = t.steps;
    const moved = ok(
      moveStep(t, a!.id, { lane: { parent: null, port: "steps" }, index: 3 }),
    );
    expect(moved.tree.steps.slice(0, 3).map((s) => s.id)).toEqual([
      b!.id,
      c!.id,
      a!.id,
    ]);
  });

  it("refuses to move a switch into one of its own lanes, the document unchanged", () => {
    const t = tree("f2");
    const sw = t.steps.find((s) => s.type === "logic.switch@1")!;
    const before = fromTree(t);
    const lane = sw.lanes[0]!;
    expect(
      moveStep(t, sw.id, {
        lane: { parent: sw.id, port: lane.port },
        index: 0,
      }),
    ).toEqual({
      ok: false,
      reason: "into_itself",
    });
    const inner = lane.steps.find((s) => s.type === "logic.switch@1")!;
    expect(
      moveStep(t, sw.id, {
        lane: { parent: inner.id, port: inner.lanes[0]!.port },
        index: 0,
      }),
    ).toEqual({ ok: false, reason: "into_itself" });
    expect(fromTree(t)).toStrictEqual(before);
  });
});

describe("deleting returns every step it removes (R2.10, R2.11)", () => {
  it("a step with lanes takes its whole subtree, and undo gives the document back", () => {
    const t = tree("f1");
    const sw = t.steps.find((s) => s.type === "logic.switch@1")!;
    const out = ok(deleteStep(t, sw.id));
    const inside = ids({ rest: {}, steps: [sw] });
    expect(out.removed.map((s) => s.id)).toEqual(inside);
    let h = history(t);
    h = commit(h, out.tree);
    expect(fromTree(undo(h).present)).toStrictEqual(loadFixture("f1"));
    expect(redo(undo(h)).present).toBe(out.tree);
  });

  it("removing a cases entry with two steps names both, and undo restores it", () => {
    const t = tree("f1");
    const sw = t.steps.find((s) => s.type === "logic.switch@1")!;
    const hot = sw.lanes.find((l) => l.port === "cases.hot")!;
    expect(hot.steps.length).toBeGreaterThanOrEqual(2);
    const out = ok(removeLane(t, sw.id, "cases.hot"));
    const names = out.removed.map((s) => stepName(s, catalogue));
    expect(names).toContain("Giao cho nhân viên kinh doanh");
    expect(names).toContain("Duyệt ưu đãi cho lead nóng");
    const cases = (
      (fromTree(out.tree).steps as Record<string, unknown>[]).find(
        (s) => s.id === sw.id,
      )!.config as Record<string, Record<string, unknown>>
    ).cases;
    expect(cases).not.toHaveProperty("hot");
    expect(fromTree(undo(commit(history(t), out.tree)).present)).toStrictEqual(
      loadFixture("f1"),
    );
  });

  it("the default lane does not come off", () => {
    const t = tree("f1");
    const sw = t.steps.find((s) => s.type === "logic.switch@1")!;
    expect(removeLane(t, sw.id, "default")).toEqual({
      ok: false,
      reason: "lane_fixed",
    });
  });

  it("on_error other than route drops F4's error lane as a deletion", () => {
    const t = tree("f4");
    const step = t.steps[0]!;
    const errorLane = step.lanes.find((l) => l.kind === "error")!;
    expect(errorLane.steps.length).toBeGreaterThan(0);
    const out = ok(setOnError(t, step.id, "continue"));
    expect(out.removed.map((s) => s.id)).toEqual(
      ids({ rest: {}, steps: errorLane.steps }),
    );
    const written = (fromTree(out.tree).steps as Record<string, unknown>[])[0]!;
    expect(written.on_error).toBe("continue");
    expect(written).not.toHaveProperty("error_lane");
    const back = ok(setOnError(out.tree, step.id, "route"));
    expect(
      (fromTree(back.tree).steps as Record<string, unknown>[])[0]!.error_lane,
    ).toEqual([]);
  });

  it("adds a cases entry and refuses one that exists", () => {
    const t = tree("f1");
    const sw = t.steps.find((s) => s.type === "logic.switch@1")!;
    const out = ok(addLane(t, sw.id, "cold", catalogue));
    const lanes = locate(out.tree, sw.id)!.node.lanes.map((l) => l.port);
    expect(lanes.indexOf("cases.cold")).toBeLessThan(lanes.indexOf("default"));
    expect(addLane(out.tree, sw.id, "cold", catalogue)).toEqual({
      ok: false,
      reason: "lane_exists",
    });
  });
});

describe("a new step (R2.9)", () => {
  it("1 000 inserts into F1 give 1 000 distinct ids, none an id F1 had", () => {
    let t = tree("f1");
    const existing = treeIds(t);
    const spec = catalogue.get("data.object.create@1")!;
    const made: string[] = [];
    for (let i = 0; i < 1000; i++) {
      const raw = newStep(spec, treeIds(t));
      made.push(raw.id as string);
      t = ok(
        insertStep(
          t,
          { lane: { parent: null, port: "steps" }, index: 0 },
          toStepNode(raw, catalogue),
        ),
      ).tree;
    }
    expect(new Set(made).size).toBe(1000);
    for (const id of made) {
      expect(id).toMatch(/^[a-z][a-z0-9_]{0,39}$/);
      expect(id).toMatch(/^create_[a-z0-9]{6}$/);
      expect(existing.has(id)).toBe(false);
    }
  });

  it("draws again when the id collides", () => {
    const spec = catalogue.get("logic.switch@1")!;
    const draws = [0, 0, 0, 0, 0, 0, 0.99, 0.99, 0.99, 0.99, 0.99, 0.99];
    const random = () => draws.shift()!;
    expect(newStep(spec, new Set(["switch_aaaaaa"]), random).id).toBe(
      "switch_999999",
    );
  });

  it("a switch carries its schema's default values, an empty default lane, no description", () => {
    const raw = newStep(catalogue.get("logic.switch@1")!, new Set());
    expect(raw).not.toHaveProperty("description");
    expect(raw.config).toEqual({ match: "first", cases: {}, default: [] });
    const node = toStepNode(raw, catalogue);
    expect(node.lanes.map((l) => [l.port, l.steps.length])).toEqual([
      ["default", 0],
    ]);
  });

  it("an optional lane is not created: a loop has its body, not max_reached", () => {
    const raw = newStep(catalogue.get("logic.loop@1")!, new Set());
    expect(raw.config).toEqual({ body: [] });
  });
});

describe("a step of a type the catalogue does not have", () => {
  const withUnknown = () => {
    const doc = loadFixture("f1");
    (doc.steps as unknown[]).splice(1, 0, {
      id: "la",
      type: "x.unknown@1",
      config: {
        inner: [{ id: "trong_la", type: "data.transform@1", config: {} }],
      },
    });
    return toTree(doc, catalogue);
  };

  it("is neither deleted nor moved, and its inner ids still count as taken", () => {
    const t = withUnknown();
    const la = locate(t, "la")!.node;
    expect(la.known).toBe(false);
    expect(la.lanes).toEqual([]);
    expect(deleteStep(t, "la")).toEqual({ ok: false, reason: "unknown_type" });
    expect(
      moveStep(t, "la", { lane: { parent: null, port: "steps" }, index: 0 }),
    ).toEqual({
      ok: false,
      reason: "unknown_type",
    });
    expect(treeIds(t).has("trong_la")).toBe(true);
  });
});

describe("the Form's fields never touch a lane", () => {
  it("replaces the config but keeps the cases and default lanes", () => {
    const t = tree("f1");
    const sw = t.steps.find((s) => s.type === "logic.switch@1")!;
    const out = ok(
      updateStepFields(
        t,
        sw.id,
        { config: { on: "x" }, timeout_s: undefined },
        catalogue,
      ),
    );
    const written = (
      fromTree(out.tree).steps as Record<string, unknown>[]
    ).find((s) => s.id === sw.id)!;
    const config = written.config as Record<string, unknown>;
    expect(config.on).toBe("x");
    expect(Object.keys(config.cases as object)).toContain("hot");
    expect(Array.isArray(config.default)).toBe(true);
    expect(written).not.toHaveProperty("timeout_s");
  });
});

describe("the keyboard follows the structure (R2.5)", () => {
  it("↓ enters a step's first lane, leaves a lane from its last step, ↑ returns to the card", () => {
    const t = tree("f1");
    const sw = t.steps.find((s) => s.type === "logic.switch@1")!;
    const after = t.steps[t.steps.indexOf(sw) + 1];
    const hot = sw.lanes[0]!;
    expect(navigate(t, sw.id, "down")).toBe(hot.steps[0]!.id);
    expect(navigate(t, hot.steps[0]!.id, "up")).toBe(sw.id);
    const last = sw.lanes[sw.lanes.length - 1]!;
    const tail =
      last.steps.length > 0
        ? last.steps[last.steps.length - 1]!.id
        : emptyLaneStop({ parent: sw.id, port: last.port });
    expect(navigate(t, tail, "down")).toBe(after?.id ?? null);
    expect(navigate(t, t.steps[1]!.id, "up")).toBe(t.steps[0]!.id);
  });

  it("←/→ go to the first step of the neighbouring lane of the same holder", () => {
    const t = tree("f1");
    const sw = t.steps.find((s) => s.type === "logic.switch@1")!;
    const [a, b] = sw.lanes;
    const target = (lane: typeof a) =>
      lane!.steps[0]?.id ?? emptyLaneStop({ parent: sw.id, port: lane!.port });
    expect(navigate(t, a!.steps[a!.steps.length - 1]!.id, "right")).toBe(
      target(b),
    );
    expect(navigate(t, target(b), "left")).toBe(a!.steps[0]!.id);
    expect(navigate(t, t.steps[0]!.id, "left")).toBeNull();
  });

  it("an empty lane's Thêm Bước slot is a stop", () => {
    const t = tree("f1");
    const raw = newStep(catalogue.get("logic.switch@1")!, treeIds(t));
    const next = ok(
      insertStep(
        t,
        { lane: { parent: null, port: "steps" }, index: 0 },
        toStepNode(raw, catalogue),
      ),
    ).tree;
    const slot = emptyLaneStop({ parent: raw.id as string, port: "default" });
    expect(stopsInOrder(next).slice(0, 3)).toEqual([
      raw.id,
      slot,
      t.steps[0]!.id,
    ]);
    expect(navigate(next, raw.id as string, "down")).toBe(slot);
    expect(navigate(next, slot, "down")).toBe(t.steps[0]!.id);
    expect(navigate(next, slot, "up")).toBe(raw.id);
  });
});

describe("the module is pure", () => {
  it("imports nothing", () => {
    const text = readFileSync(
      resolve(__dirname, "../workflow-graph.ts"),
      "utf8",
    );
    expect(text).not.toMatch(/^\s*import\s/m);
    expect(text).not.toMatch(/\brequire\(/);
  });
});
