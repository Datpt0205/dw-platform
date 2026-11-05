import { describe, expect, it } from "vitest";
import {
  catalogueOf,
  locate,
  toTree,
} from "../../../../../../lib/workflow-graph";
import {
  NODE_TYPES,
  loadFixture,
} from "../../../../../../lib/__tests__/workflow-catalogue";
import {
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
