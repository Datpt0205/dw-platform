import { describe, expect, it } from "vitest";
import {
  catalogueOf,
  locate,
  toStepNode,
  toTree,
} from "../../../../../../lib/workflow-graph";
import {
  NODE_TYPES,
  loadFixture,
} from "../../../../../../lib/__tests__/workflow-catalogue";
import {
  cardView,
  laneMenu,
  moveTargets,
  parseSlotValue,
  stepMenu,
  type MoveTarget,
} from "../builder-model";

/**
 * What the builder offers on a step (workflow-builder-ui R1.4, R2.1, R2.5):
 * the menu of a known and of an unknown type, and the slots "Di chuyển…"
 * lists, none inside the moving step's own subtree.
 */

const catalogue = catalogueOf(NODE_TYPES);

function slots(targets: MoveTarget[], out: string[] = []): string[] {
  for (const t of targets) {
    if (t.selectable) out.push(t.value);
    slots(t.children, out);
  }
  return out;
}

describe("the step menu", () => {
  it("has the five actions, and the lane actions for a keyed type", () => {
    const tree = toTree(loadFixture("f1"), catalogue);
    const sw = locate(tree, "phan_loai")!.node;
    expect(stepMenu(sw, catalogue).map((e) => e.label)).toEqual([
      "Thêm trước",
      "Thêm sau",
      "Di chuyển…",
      "Thêm nhánh",
      "Bỏ nhánh…",
      "Xóa",
      "Sao chép tham chiếu",
    ]);
    const plain = locate(tree, "chuan_hoa")!.node;
    expect(stepMenu(plain, catalogue).map((e) => e.key)).toEqual([
      "addBefore",
      "addAfter",
      "move",
      "delete",
      "copyRef",
    ]);
  });

  it("has only Sao chép tham chiếu for a type the catalogue lacks", () => {
    const doc = loadFixture("f1");
    (doc.steps as unknown[]).push({
      id: "la",
      type: "x.unknown@1",
      config: {},
    });
    const node = locate(toTree(doc, catalogue), "la")!.node;
    expect(stepMenu(node, catalogue).map((e) => e.key)).toEqual(["copyRef"]);
  });
});

describe("Di chuyển… (R1.4)", () => {
  it("offers no slot inside the moving step's subtree, and every other one", () => {
    const tree = toTree(loadFixture("f2"), catalogue);
    const sw = tree.steps.find((s) => s.type === "logic.switch@1")!;
    const offered = slots(moveTargets(tree, catalogue, sw.id)).map(
      parseSlotValue,
    );
    const inner = new Set<string>([sw.id]);
    const collect = (node: typeof sw) => {
      for (const lane of node.lanes) {
        for (const step of lane.steps) {
          inner.add(step.id);
          collect(step);
        }
      }
    };
    collect(sw);
    for (const slot of offered) {
      expect(slot.lane.parent === null || !inner.has(slot.lane.parent)).toBe(
        true,
      );
    }
    expect(offered.filter((s) => s.lane.parent === null)).toHaveLength(
      tree.steps.length + 1,
    );
    const other = slots(moveTargets(tree, catalogue, tree.steps[0]!.id)).map(
      parseSlotValue,
    );
    expect(other.some((s) => s.lane.parent === sw.id)).toBe(true);
  });
});

describe("what a card of each W1 type says (R1.5, R1.8; ticket 04)", () => {
  const approval = (config: Record<string, unknown>) =>
    cardView(
      toStepNode(
        {
          id: "duyet",
          type: "human.approval@2",
          config: { approved: [], rejected: [], ...config },
        },
        catalogue,
      ),
      catalogue,
    );
  const rule = (config: Record<string, unknown>) =>
    approval(config).marks.map((m) => m.text);

  it("names who approves and the scope", () => {
    const view = approval({
      required_scope: "studio.leads.approve",
      assignees: ["u_a", "u_b"],
    });
    expect(view.summary).toBe("Phạm vi: studio.leads.approve");
    expect(view.detail?.text).toBe("Người duyệt: u_a, u_b");
    expect(approval({ assignees: "record.owner" }).detail?.text).toBe(
      "Người duyệt theo Biểu thức: record.owner",
    );
    expect(approval({}).detail?.text).toBe("Người duyệt: người giữ quyền");
  });

  it("says Cần cả N only for N ≥ 2 named people, Cần mọi người when known at run time, nothing otherwise", () => {
    expect(rule({ approval_rule: "all", assignees: ["a", "b", "c"] })).toEqual([
      "Cần cả 3 người duyệt",
    ]);
    expect(rule({ approval_rule: "all", assignees: "record.team" })).toEqual([
      "Cần mọi người được giao duyệt",
    ]);
    expect(rule({ approval_rule: "all" })).toEqual([
      "Cần mọi người được giao duyệt",
    ]);
    expect(rule({ approval_rule: "all", assignees: ["a"] })).toEqual([]);
    expect(rule({ approval_rule: "any", assignees: ["a", "b"] })).toEqual([]);
    expect(rule({ assignees: ["a", "b"] })).toEqual([]);
  });

  it("shows a switch's on as stored, no CEL shortened", () => {
    const on = "steps.cham_diem.response.tier  ==  'hot' && true";
    const view = cardView(
      toStepNode(
        { id: "re", type: "logic.switch@1", config: { on, cases: {} } },
        catalogue,
      ),
      catalogue,
    );
    expect(view.summary).toBe(on);
  });

  it("titles a loop by its condition and cap, verbatim", () => {
    const tree = toTree(loadFixture("f3"), catalogue);
    const view = cardView(locate(tree, "lam_giau")!.node, catalogue);
    expect(view.title).toBe(
      "Lặp lại khi !steps.gop.response.complete (tối đa 5 lần)",
    );
    expect(view.frame).toBe(true);
  });

  it("marks a sub-workflow, names what it calls and its wait", () => {
    const tree = toTree(loadFixture("f10"), catalogue);
    const view = cardView(locate(tree, "kiem_trung")!.node, catalogue);
    expect(view.marks).toEqual([{ key: "subworkflow", text: "Quy trình con" }]);
    expect(view.summary).toBe("kiem_lead_trung");
    expect(view.detail).toEqual({ text: "Chờ Quy trình con xong", wait: true });
    expect(view.frame).toBe(false);
  });

  it("draws a type with a known block and an unknown name as the plain card", () => {
    const types = NODE_TYPES.map((t) =>
      t.type === "logic.parallel@1" ? { ...t, type: "x.par@1" } : t,
    );
    const renamed = catalogueOf(types);
    const node = toStepNode(
      { id: "ss", type: "x.par@1", config: { branches: { a: [], b: [] } } },
      renamed,
    );
    const view = cardView(node, renamed);
    expect(view.frame).toBe(true);
    expect(view.title).toBeNull();
    expect(view.marks).toEqual([]);
  });
});

describe("the menus of frames and lanes (R1.7, R2.5; ticket 04)", () => {
  it("folds or opens a frame, and adds or removes the loop's optional lane by name", () => {
    const tree = toTree(loadFixture("f10"), catalogue);
    const loop = locate(tree, "lam_giau")!.node;
    const labels = (folded: boolean) =>
      stepMenu(loop, catalogue, folded).map((e) => e.label);
    expect(labels(false)).toContain("Thu gọn khung");
    expect(labels(true)).toContain("Mở khung");
    expect(labels(false)).toContain("Thêm làn «Đã đủ N lần»");
    expect(labels(false)).not.toContain("Thêm nhánh");
    const f5 = toTree(loadFixture("f5"), catalogue);
    const withLane = locate(f5, "soan_lai")!.node;
    expect(stepMenu(withLane, catalogue).map((e) => e.key)).toEqual(
      expect.arrayContaining(["fold", "removePort:max_reached"]),
    );
    expect(stepMenu(withLane, catalogue).map((e) => e.key)).not.toContain(
      "addPort:max_reached",
    );
  });

  it("offers Bỏ nhánh on a keyed lane's head only", () => {
    const tree = toTree(loadFixture("f3"), catalogue);
    const sw = locate(tree, "phan_loai")!.node;
    expect(sw.lanes.map((l) => laneMenu(l).map((e) => e.label))).toEqual([
      ["Bỏ nhánh"],
      [],
    ]);
    const approval = toTree(loadFixture("f5"), catalogue);
    for (const lane of locate(approval, "duyet_hoi_dong")!.node.lanes) {
      expect(laneMenu(lane)).toEqual([]);
    }
  });
});
