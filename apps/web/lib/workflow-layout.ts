import type { LaneNode, StepNode, WorkflowTree } from "./workflow-graph";
import type {
  CanvasCard,
  CanvasJoin,
  CanvasLaneHead,
  CanvasShapes,
  CanvasSlot,
  Point,
} from "./workflow-shapes";

/**
 * Every position on the workflow canvas, computed from the step tree
 * (workflow-builder-ui R1.5, R1.6; ADR-0101 (Accepted) decision 3). Pure and
 * importing no package: two passes, measuring bottom-up and placing top-down
 * along one vertical axis, O(n) in the steps.
 *
 * A step is a fixed card. A sequence stacks its cards top to bottom with a
 * "+" slot on every connection. A step's lanes sit side by side under it in
 * document order, under a lane head, and meet at a join point below the
 * tallest. The "Khi lỗi" lane hangs to the right of the step. Each lane and
 * step is measured as a left and a right extent from its axis, so a lane
 * that is wider on one side never runs into its neighbour (ADR-0101
 * Amendments 2026-11-04). Which lanes a step has is the tree's, read from the
 * catalogue by `workflow-graph.ts`; no lane name is written here.
 *
 * What holds (R1.6): the same document gives the same coordinates; inserting
 * a step moves only what follows it in its lane and in the sequences around
 * that lane, and only down; a step with lanes may push sibling lanes sideways
 * but never changes vertical or lane order.
 */

export interface LayoutMetrics {
  card: { width: number; height: number };
  /** The vertical gap between two items, which holds a "+". */
  gap: number;
  /** The "+" slot's hit area, at least 24 px (R1.5). */
  slot: number;
  /** The horizontal gap between lanes. */
  laneGap: number;
  laneHead: { width: number; height: number };
  /** Between a card and its lane heads, and under the lanes to the join. */
  fork: number;
  join: number;
  /** An empty lane's dashed "Thêm Bước" slot. */
  empty: { width: number; height: number };
}

export function metricsFor(card: {
  width: number;
  height: number;
}): LayoutMetrics {
  return {
    card,
    gap: 48,
    slot: 28,
    laneGap: 40,
    laneHead: { width: Math.min(card.width, 160), height: 28 },
    fork: 24,
    join: 24,
    empty: { width: card.width, height: 44 },
  };
}

interface Extent {
  left: number;
  right: number;
  height: number;
}

interface MeasuredLane extends Extent {
  lane: LaneNode;
  items: MeasuredStep[];
}

interface MeasuredStep extends Extent {
  node: StepNode;
  /** The lanes under the card, with each one's axis from the step's axis. */
  block: { lane: MeasuredLane; offset: number }[];
  blockHeight: number;
  error: { lane: MeasuredLane; offset: number } | null;
}

function measureSequence(
  steps: StepNode[],
  withHead: boolean,
  m: LayoutMetrics,
): { left: number; right: number; height: number; items: MeasuredStep[] } {
  const head = withHead ? m.laneHead.height : 0;
  const headHalf = withHead ? m.laneHead.width / 2 : 0;
  if (steps.length === 0) {
    const half = Math.max(m.empty.width / 2, headHalf, m.card.width / 2);
    return {
      left: half,
      right: half,
      height: head + m.gap / 2 + m.empty.height,
      items: [],
    };
  }
  const items = steps.map((step) => measureStep(step, m));
  let left = Math.max(m.card.width / 2, headHalf);
  let right = left;
  let height = head + m.gap;
  for (const item of items) {
    left = Math.max(left, item.left);
    right = Math.max(right, item.right);
    height += item.height + m.gap;
  }
  return { left, right, height, items };
}

function measureLane(lane: LaneNode, m: LayoutMetrics): MeasuredLane {
  return { lane, ...measureSequence(lane.steps, true, m) };
}

function measureStep(node: StepNode, m: LayoutMetrics): MeasuredStep {
  const half = m.card.width / 2;
  const lanes = node.lanes
    .filter((l) => l.kind !== "error")
    .map((l) => measureLane(l, m));
  const block: MeasuredStep["block"] = [];
  let blockHalf = 0;
  let blockHeight = 0;
  if (lanes.length > 0) {
    const total =
      lanes.reduce((sum, l) => sum + l.left + l.right, 0) +
      m.laneGap * (lanes.length - 1);
    let x = -total / 2;
    for (const lane of lanes) {
      block.push({ lane, offset: x + lane.left });
      x += lane.left + lane.right + m.laneGap;
    }
    blockHalf = total / 2;
    blockHeight = m.fork + Math.max(...lanes.map((l) => l.height)) + m.join;
  }
  const left = Math.max(half, blockHalf);
  let right = left;
  let height = m.card.height + blockHeight;
  let error: MeasuredStep["error"] = null;
  const errorLane = node.lanes.find((l) => l.kind === "error");
  if (errorLane) {
    const lane = measureLane(errorLane, m);
    const offset = right + m.laneGap + lane.left;
    error = { lane, offset };
    right = offset + lane.right;
    height = Math.max(height, lane.height);
  }
  return { node, left, right, height, block, blockHeight, error };
}

class Placer {
  readonly shapes: CanvasShapes = {
    cards: [],
    laneHeads: [],
    slots: [],
    joins: [],
    connections: [],
  };

  constructor(private readonly m: LayoutMetrics) {}

  private connect(from: string, to: string, points: Point[], dashed = false) {
    this.shapes.connections.push({
      id: `${from}->${to}`,
      from,
      to,
      points,
      dashed,
    });
  }

  /**
   * Place a lane's items with its axis at `axis` from `top`; returns the
   * shape its last connection leaves from and the y it leaves at.
   */
  sequence(
    items: MeasuredStep[],
    axis: number,
    top: number,
    parent: string | null,
    port: string,
    head: string | null,
    entry: { from: string; y: number } | null,
  ): { from: string; y: number } {
    const m = this.m;
    let y = top;
    let previous = entry;
    if (head !== null && parent !== null) {
      const laneHead: CanvasLaneHead = {
        id: head,
        parent,
        port,
        x: axis - m.laneHead.width / 2,
        y,
        width: m.laneHead.width,
        height: m.laneHead.height,
      };
      this.shapes.laneHeads.push(laneHead);
      y += m.laneHead.height;
      previous = { from: head, y };
    }
    if (items.length === 0) {
      const id = `lane:${parent ?? ""}:${port}`;
      const slot: CanvasSlot = {
        id,
        parent,
        port,
        index: 0,
        empty: true,
        after: null,
        x: axis - m.empty.width / 2,
        y: y + m.gap / 2,
        width: m.empty.width,
        height: m.empty.height,
      };
      this.shapes.slots.push(slot);
      if (previous) {
        this.connect(previous.from, id, [
          { x: axis, y: previous.y },
          { x: axis, y: slot.y },
        ]);
      }
      return { from: id, y: slot.y + slot.height };
    }
    items.forEach((item, index) => {
      this.slot(
        axis,
        y,
        parent,
        port,
        index,
        index > 0 ? items[index - 1]!.node.id : null,
      );
      y += m.gap;
      if (previous) {
        this.connect(previous.from, item.node.id, [
          { x: axis, y: previous.y },
          { x: axis, y },
        ]);
      }
      previous = this.step(item, axis, y);
      y += item.height;
    });
    this.slot(
      axis,
      y,
      parent,
      port,
      items.length,
      items[items.length - 1]!.node.id,
    );
    return previous!;
  }

  private slot(
    axis: number,
    gapTop: number,
    parent: string | null,
    port: string,
    index: number,
    after: string | null,
  ) {
    const m = this.m;
    this.shapes.slots.push({
      id: `slot:${parent ?? ""}:${port}:${index}`,
      parent,
      port,
      index,
      empty: false,
      after,
      x: axis - m.slot / 2,
      y: gapTop + m.gap / 2 - m.slot / 2,
      width: m.slot,
      height: m.slot,
    });
  }

  /** Place one step with its card's top at `y`; returns where it is left. */
  private step(
    item: MeasuredStep,
    axis: number,
    y: number,
  ): { from: string; y: number } {
    const m = this.m;
    const { node } = item;
    const card: CanvasCard = {
      id: node.id,
      x: axis - m.card.width / 2,
      y,
      width: m.card.width,
      height: m.card.height,
    };
    this.shapes.cards.push(card);
    const bottom = y + m.card.height;
    if (item.error) {
      const laneAxis = axis + item.error.offset;
      const head = `head:${node.id}:${item.error.lane.lane.port}`;
      const mid = y + m.laneHead.height / 2;
      this.connect(
        node.id,
        head,
        [
          { x: axis + m.card.width / 2, y: mid },
          { x: laneAxis - m.laneHead.width / 2, y: mid },
        ],
        true,
      );
      this.sequence(
        item.error.lane.items,
        laneAxis,
        y,
        node.id,
        item.error.lane.lane.port,
        head,
        null,
      );
    }
    if (item.block.length === 0) return { from: node.id, y: bottom };
    const forkY = bottom + m.fork / 2;
    const lanesTop = bottom + m.fork;
    const joinY = bottom + item.blockHeight - m.join / 2;
    const join: CanvasJoin = { id: `join:${node.id}`, x: axis, y: joinY };
    this.shapes.joins.push(join);
    for (const { lane, offset } of item.block) {
      const laneAxis = axis + offset;
      const head = `head:${node.id}:${lane.lane.port}`;
      this.connect(node.id, head, [
        { x: axis, y: bottom },
        { x: axis, y: forkY },
        { x: laneAxis, y: forkY },
        { x: laneAxis, y: lanesTop },
      ]);
      const exit = this.sequence(
        lane.items,
        laneAxis,
        lanesTop,
        node.id,
        lane.lane.port,
        head,
        null,
      );
      this.connect(exit.from, join.id, [
        { x: laneAxis, y: exit.y },
        { x: laneAxis, y: joinY },
        { x: axis, y: joinY },
      ]);
    }
    return { from: join.id, y: joinY };
  }
}

/** The shapes of a document's step tree, its root axis at x = 0, top at 0. */
export function layoutWorkflow(
  tree: WorkflowTree,
  metrics: LayoutMetrics,
): CanvasShapes {
  const root = measureSequence(tree.steps, false, metrics);
  const placer = new Placer(metrics);
  placer.sequence(root.items, 0, 0, null, "steps", null, null);
  return placer.shapes;
}

/** The slot under a canvas point, for a drop (R1.4), or null on empty canvas:
 * a "+" counts with a margin of half a gap around it, so a drop near the
 * connection lands. */
export function slotAt(
  shapes: CanvasShapes,
  point: Point,
  accept: (slot: CanvasSlot) => boolean = () => true,
): CanvasSlot | null {
  for (const slot of shapes.slots) {
    const margin = slot.empty ? 0 : slot.width / 2;
    if (
      point.x >= slot.x - margin &&
      point.x <= slot.x + slot.width + margin &&
      point.y >= slot.y - margin &&
      point.y <= slot.y + slot.height + margin &&
      accept(slot)
    ) {
      return slot;
    }
  }
  return null;
}
