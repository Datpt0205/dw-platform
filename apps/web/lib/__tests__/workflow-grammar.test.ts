import { describe, expect, it } from "vitest";
import {
  catalogueOf,
  locate,
  toTree,
  walk,
  type StepTypeSpec,
  type WorkflowTree,
} from "../workflow-graph";
import { layoutWorkflow, metricsFor } from "../workflow-layout";
import type { CanvasShapes } from "../workflow-shapes";
import { NODE_TYPES, loadFixture } from "./workflow-catalogue";

/**
 * The canvas's grammar (workflow-builder-ui R1.5, ticket 04): each structure
 * of the step tree drawn from the five shared blocks, chosen by the
 * catalogue's `block`, `ends_run` and `exits_loop`. F2, F3, F4, F5, F9 of
 * ticket 01 and F10 of ticket 04 as snapshots of what is drawn and what joins
 * what (positions are the layout test's), and each acceptance row as a
 * property of the shapes, so a join drawn as a bar, a lane that ends joined
 * back, a shape chosen by a type's name or a sub-workflow's steps drawn in
 * the parent each turn something red.
 */

const catalogue = catalogueOf(NODE_TYPES);
const METRICS = metricsFor({ width: 256, height: 120 });

function tree(name: string, types: StepTypeSpec[] = NODE_TYPES) {
  return toTree(loadFixture(name), catalogueOf(types));
}

function lay(t: WorkflowTree, folded?: ReadonlySet<string>) {
  return layoutWorkflow(t, METRICS, folded);
}

/** What is drawn and what joins what, in the order it is drawn. */
function grammar(shapes: CanvasShapes): string[] {
  return [
    ...shapes.frames.map((f) => `frame ${f.kind} ${f.step}`),
    ...shapes.cards.map((c) => `card ${c.id}${c.folded ? " folded" : ""}`),
    ...shapes.laneHeads.map((h) => `head ${h.parent} ${h.port}`),
    ...shapes.joins.map((j) => `${j.kind} ${j.step}`),
    ...shapes.connections.map(
      (c) =>
        `${c.from} -> ${c.to}${c.dashed ? " dashed" : ""}${c.arrow ? " arrow" : ""}${c.label ? ` ${c.label}` : ""}`,
    ),
  ];
}

function inside(
  a: { x: number; y: number; width: number; height: number },
  b: typeof a,
): boolean {
  return (
    a.x >= b.x &&
    a.y >= b.y &&
    a.x + a.width <= b.x + b.width &&
    a.y + a.height <= b.y + b.height
  );
}

function overlapping(shapes: CanvasShapes): string[] {
  const boxes = shapes.cards;
  const found: string[] = [];
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i]!;
      const b = boxes[j]!;
      if (
        a.x < b.x + b.width &&
        b.x < a.x + a.width &&
        a.y < b.y + b.height &&
        b.y < a.y + a.height
      ) {
        found.push(`${a.id} × ${b.id}`);
      }
    }
  }
  return found;
}

describe("snapshots of the grammar (R1.5)", () => {
  it.each(["f2", "f3", "f4", "f5", "f9", "f10"])("%s", (name) => {
    expect(grammar(lay(tree(name)))).toMatchSnapshot();
  });
});

describe("logic.switch: lanes under their keys, one join point (F2)", () => {
  const t = tree("f2");
  const shapes = lay(t);

  it("hangs each lane under a head named by its cases key, Khác included", () => {
    walk(t, (node) => {
      if (node.type !== "logic.switch@1") return;
      const heads = shapes.laneHeads.filter((h) => h.parent === node.id);
      const lanes = node.lanes.filter((l) => l.kind !== "error");
      expect(heads.map((h) => h.port)).toEqual(lanes.map((l) => l.port));
      const labels = lanes.map((l) => l.label);
      expect(labels).toContain("Khác");
      for (const lane of lanes.filter((l) => l.kind === "keyed")) {
        expect(lane.label).toBe(lane.port.slice("cases.".length));
      }
    });
  });

  it("meets its lanes at exactly one point, never a bar", () => {
    walk(t, (node) => {
      if (node.type !== "logic.switch@1") return;
      const joins = shapes.joins.filter((j) => j.step === node.id);
      expect(
        joins.map((j) => j.kind),
        node.id,
      ).toEqual(["join"]);
      const into = shapes.connections.filter((c) => c.to === `join:${node.id}`);
      expect(into, node.id).toHaveLength(node.lanes.length);
    });
    expect(shapes.joins.some((j) => j.kind === "bar")).toBe(false);
    expect(shapes.frames).toEqual([]);
  });
});

describe("parallel inside a loop inside a switch (F3)", () => {
  const t = tree("f3");
  const shapes = lay(t);
  const frame = (step: string) => shapes.frames.find((f) => f.step === step)!;
  const card = (id: string) => shapes.cards.find((c) => c.id === id)!;

  it("draws the Song song frame with its bar inside the loop frame", () => {
    expect(frame("tra_cuu").kind).toBe("parallel");
    expect(frame("lam_giau").kind).toBe("loop");
    expect(inside(frame("tra_cuu"), frame("lam_giau"))).toBe(true);
    const bar = shapes.joins.find((j) => j.id === "bar:tra_cuu")!;
    expect(bar.kind).toBe("bar");
    expect(inside(bar, frame("tra_cuu"))).toBe(true);
    // Every branch reaches the bar, straight down.
    const into = shapes.connections.filter((c) => c.to === "bar:tra_cuu");
    expect(into).toHaveLength(3);
  });

  it("heads each frame with its own card, at the top of the frame", () => {
    for (const step of ["tra_cuu", "lam_giau"]) {
      const f = frame(step);
      const c = card(step);
      expect(inside(c, f), step).toBe(true);
      expect(c.y - f.y, step).toBe(METRICS.framePad);
    }
  });

  it("climbs back with a dashed Lặp lại arrow and hangs Đã đủ N lần under the frame", () => {
    const repeat = shapes.connections.find(
      (c) => c.label === "repeat" && c.to === "lam_giau",
    )!;
    expect(repeat).toBeDefined();
    expect(repeat.dashed && repeat.arrow).toBe(true);
    // Up the left gutter, inside the frame.
    const f = frame("lam_giau");
    const gutterX = repeat.labelAt!.x;
    expect(gutterX).toBeGreaterThan(f.x);
    expect(gutterX).toBeLessThan(card("lam_giau").x);
    const hung = shapes.laneHeads.find(
      (h) => h.parent === "lam_giau" && h.port === "max_reached",
    )!;
    expect(hung.y).toBeGreaterThanOrEqual(f.y + f.height);
    const exit = shapes.joins.find((j) => j.id === "exit:lam_giau")!;
    expect(hung.x).toBeGreaterThan(exit.x);
    // No head over the body: the frame holds it.
    expect(
      shapes.laneHeads.some(
        (h) => h.parent === "lam_giau" && h.port === "body",
      ),
    ).toBe(false);
  });

  it("draws the same when the parallel type has another name and the same block", () => {
    const renamed = NODE_TYPES.map((s) =>
      s.type === "logic.parallel@1" ? { ...s, type: "x.par@1" } : s,
    );
    const doc = JSON.parse(
      JSON.stringify(loadFixture("f3")).replaceAll(
        '"logic.parallel@1"',
        '"x.par@1"',
      ),
    ) as Record<string, unknown>;
    const again = layoutWorkflow(toTree(doc, catalogueOf(renamed)), METRICS);
    expect(again).toEqual(shapes);
  });
});

describe("the Khi lỗi lane (F4)", () => {
  const t = tree("f4");
  const shapes = lay(t);

  it("hangs a dashed lane right of every step that routes its errors", () => {
    walk(t, (node) => {
      if (!node.lanes.some((l) => l.kind === "error")) return;
      const head = shapes.laneHeads.find(
        (h) => h.parent === node.id && h.port === "error_lane",
      )!;
      const card = shapes.cards.find((c) => c.id === node.id)!;
      expect(head.x, node.id).toBeGreaterThan(card.x + card.width);
      const into = shapes.connections.find((c) => c.to === head.id)!;
      expect(into.dashed, node.id).toBe(true);
    });
  });

  it("meets the flow again under the step, unless the lane ends the run", () => {
    walk(t, (node) => {
      const lane = node.lanes.find((l) => l.kind === "error");
      if (!lane) return;
      const last = lane.steps[lane.steps.length - 1];
      const ends = last?.shape.endsRun ?? false;
      const rejoin = shapes.joins.find((j) => j.id === `rejoin:${node.id}`);
      if (ends) {
        expect(rejoin, node.id).toBeUndefined();
        expect(
          shapes.connections.some((c) => c.from === last!.id),
          node.id,
        ).toBe(false);
        return;
      }
      expect(rejoin, node.id).toBeDefined();
      const card = shapes.cards.find((c) => c.id === node.id)!;
      expect(rejoin!.y, node.id).toBeGreaterThan(card.y + card.height);
      expect(
        shapes.connections.some(
          (c) => c.to === rejoin!.id && c.from === last!.id && c.dashed,
        ),
        node.id,
      ).toBe(true);
    });
  });

  it("keeps a stop at the end of an error lane in a parallel lane as an end, with no way back", () => {
    const doc = {
      schema: "dw.workflow/v1",
      triggers: [],
      steps: [
        {
          id: "song_song",
          type: "logic.parallel@1",
          config: {
            branches: {
              a: [
                {
                  id: "goi",
                  type: "tool.call@2",
                  config: {},
                  on_error: "route",
                  error_lane: [{ id: "dung", type: "flow.stop@1", config: {} }],
                },
              ],
              b: [{ id: "ghi", type: "data.transform@1", config: {} }],
            },
          },
        },
        { id: "sau", type: "data.transform@1", config: {} },
      ],
    };
    const s = lay(toTree(doc, catalogue));
    expect(s.cards.map((c) => c.id)).toContain("dung");
    expect(s.connections.some((c) => c.from === "dung")).toBe(false);
    expect(s.joins.some((j) => j.id === "rejoin:goi")).toBe(false);
    // The branch itself still reaches the bar through its step.
    expect(
      s.connections.some((c) => c.from === "goi" && c.to === "bar:song_song"),
    ).toBe(true);
  });
});

describe("approval lanes (F5)", () => {
  const t = tree("f5");
  const shapes = lay(t);

  it("hangs Duyệt and Từ chối under the card and meets them at one point", () => {
    for (const id of ["duyet_bao_gia", "duyet_hoi_dong"]) {
      const node = locate(t, id)!.node;
      expect(node.lanes.map((l) => l.label)).toEqual(["Duyệt", "Từ chối"]);
      const heads = shapes.laneHeads.filter((h) => h.parent === id);
      expect(heads.map((h) => h.port)).toEqual(["approved", "rejected"]);
      expect(
        shapes.joins.filter((j) => j.step === id).map((j) => j.kind),
      ).toEqual(["join"]);
    }
  });

  it("a lane ending the run does not reach the join", () => {
    // duyet_hoi_dong's Từ chối lane ends with flow.stop.
    expect(
      shapes.connections.some(
        (c) => c.from === "dung_tu_choi" && c.to === "join:duyet_hoi_dong",
      ),
    ).toBe(false);
    expect(
      shapes.connections.some(
        (c) => c.from === "gui_bao_gia" && c.to === "join:duyet_hoi_dong",
      ),
    ).toBe(true);
  });
});

describe("Thoát vòng lặp (F9)", () => {
  const t = tree("f9");
  const shapes = lay(t);
  const loopOf = (id: string): string => {
    const at = locate(t, id)!;
    // The nearest loop whose body holds the step.
    let lane = at.lane;
    while (lane.parent !== null) {
      const holder = locate(t, lane.parent)!;
      if (holder.node.shape.block === "loop" && lane.port === "body") {
        return holder.node.id;
      }
      lane = holder.lane;
    }
    throw new Error(`${id} is in no loop`);
  };

  it("draws without two cards on each other", () => {
    expect(overlapping(shapes)).toEqual([]);
  });

  it("points every exit at its loop's exit under the frame, never at Đã đủ N lần", () => {
    const breaks: string[] = [];
    walk(t, (node) => {
      if (node.shape.exitsLoop) breaks.push(node.id);
    });
    expect(breaks.length).toBeGreaterThan(0);
    for (const id of breaks) {
      const out = shapes.connections.filter((c) => c.from === id);
      expect(
        out.map((c) => c.to),
        id,
      ).toEqual([`exit:${loopOf(id)}`]);
      expect(out[0]!.arrow, id).toBe(true);
      const exit = shapes.joins.find((j) => j.id === `exit:${loopOf(id)}`)!;
      const frame = shapes.frames.find((f) => f.step === loopOf(id))!;
      expect(exit.y, id).toBeGreaterThan(frame.y + frame.height);
      const end = out[0]!.points[out[0]!.points.length - 1]!;
      expect(end, id).toEqual({ x: exit.x, y: exit.y });
    }
  });

  it("a lane ending in Thoát vòng lặp never reaches the join of its block", () => {
    walk(t, (node) => {
      for (const lane of node.lanes) {
        const last = lane.steps[lane.steps.length - 1];
        if (!last?.shape.exitsLoop) continue;
        expect(
          shapes.connections.some(
            (c) => c.from === last.id && c.to.startsWith("join:"),
          ),
          last.id,
        ).toBe(false);
      }
    });
  });
});

describe("unreachable steps and blocks with no way out", () => {
  const doc = {
    schema: "dw.workflow/v1",
    triggers: [],
    steps: [
      {
        id: "re",
        type: "logic.switch@1",
        config: {
          on: "x",
          cases: { a: [{ id: "dung_a", type: "flow.stop@1", config: {} }] },
          default: [{ id: "dung_khac", type: "flow.stop@1", config: {} }],
        },
      },
      { id: "sau_khoi", type: "data.transform@1", config: {} },
      { id: "dung", type: "flow.stop@1", config: {} },
      { id: "sau_dung", type: "data.transform@1", config: {} },
    ],
  };
  const shapes = lay(toTree(doc, catalogue));

  it("a block whose every lane ends has no join and leads nowhere", () => {
    expect(shapes.joins.some((j) => j.step === "re")).toBe(false);
    expect(shapes.connections.some((c) => c.to === "sau_khoi")).toBe(false);
  });

  it("a step after a stop is drawn in its place with no connection into it", () => {
    expect(shapes.cards.map((c) => c.id)).toEqual([
      "re",
      "dung_a",
      "dung_khac",
      "sau_khoi",
      "dung",
      "sau_dung",
    ]);
    expect(shapes.connections.some((c) => c.to === "sau_dung")).toBe(false);
    // sau_khoi is unreachable too, but leads on to the stop under it.
    expect(
      shapes.connections.some((c) => c.from === "sau_khoi" && c.to === "dung"),
    ).toBe(true);
  });
});

describe("a sub-workflow is one card (F10)", () => {
  const t = tree("f10");
  const shapes = lay(t);

  it("draws a card for each step of the parent and none of the called workflow", () => {
    const ids: string[] = [];
    walk(t, (node) => ids.push(node.id));
    expect(shapes.cards.map((c) => c.id).sort()).toEqual(ids.sort());
    expect(shapes.cards.map((c) => c.id)).toEqual(
      expect.arrayContaining(["kiem_trung", "lam_giau_mot_lan"]),
    );
    expect(shapes.cards).toHaveLength(4);
    // A plain card: no lane, frame or join of its own.
    for (const id of ["kiem_trung", "lam_giau_mot_lan"]) {
      expect(shapes.laneHeads.some((h) => h.parent === id)).toBe(false);
      expect(shapes.joins.some((j) => j.step === id)).toBe(false);
    }
  });
});

describe("a folded frame is its card (R1.7)", () => {
  it("draws the loop of F3 as one card, the document as it was", () => {
    const t = tree("f3");
    const before = JSON.stringify(t);
    const shapes = lay(t, new Set(["lam_giau"]));
    expect(JSON.stringify(t)).toBe(before);
    const card = shapes.cards.find((c) => c.id === "lam_giau")!;
    expect(card.folded).toBe(true);
    expect(shapes.frames.map((f) => f.step)).toEqual([]);
    for (const id of ["tra_cuu", "tra_cong_ty", "gop", "tao_viec_tay"]) {
      expect(
        shapes.cards.some((c) => c.id === id),
        id,
      ).toBe(false);
    }
    // It still leads on to its switch's join.
    expect(
      shapes.connections.some(
        (c) => c.from === "lam_giau" && c.to === "join:phan_loai",
      ),
    ).toBe(true);
    // Measured as a card: the same height as a plain card's slot in its lane.
    expect(card.height).toBe(METRICS.card.height);
  });

  it("folds only frames: a switch named in the set is drawn open", () => {
    const t = tree("f3");
    expect(lay(t, new Set(["phan_loai"]))).toEqual(lay(t));
  });
});
