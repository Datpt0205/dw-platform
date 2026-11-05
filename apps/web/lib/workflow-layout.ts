import {
  isFrame,
  type LaneNode,
  type StepNode,
  type WorkflowTree,
} from "./workflow-graph";
import type {
  CanvasConnection,
  CanvasJoin,
  CanvasShapes,
  CanvasSlot,
  Point,
} from "./workflow-shapes";

/**
 * Every position on the workflow canvas, computed from the step tree
 * (workflow-builder-ui R1.5, R1.6, R1.7; ADR-0101 (Accepted) decision 3).
 * Pure and importing no package: two passes, measuring bottom-up and placing
 * top-down along one vertical axis, O(n) in the steps.
 *
 * Five blocks, shared by every type (R1.5), chosen by the step's `block`,
 * `ends_run` and `exits_loop` from the catalogue, never by its type's name:
 * - a chain: cards top to bottom with a "+" slot on every connection;
 * - lanes: a `choice` step's lanes side by side under its card, in document
 *   order under a lane head, meeting at one join point under the tallest;
 * - a frame: a `parallel` step's card and lanes inside a frame whose floor is
 *   the Điểm nối bar; a `loop` step's card and body inside a frame, its other
 *   lanes ("Đã đủ N lần") hanging right of the exit under it;
 * - the way back: a loop's "Lặp lại" arrow up its left gutter;
 * - the error lane: the "Khi lỗi" lane right of the step (of its whole frame),
 *   meeting the flow again under everything the step holds.
 * A lane whose last step ends the run or leaves its loop does not reach its
 * join; a step after such a step stays where it is with no connection into
 * it; a block none of whose lanes reaches its join has no join and leads
 * nowhere. A step that leaves its loop points at that loop's exit. The
 * document is drawn as it is, valid or not: what the validator refuses is the
 * validator's to say (R3.4).
 *
 * A folded frame (R1.7) is measured and drawn as its card alone. Space for a
 * join, a bar or an exit is kept whether or not anything reaches it, so a
 * lane that starts or stops ending moves nothing.
 *
 * Each lane and step is measured as a left and a right extent from its axis,
 * so a lane wider on one side never runs into its neighbour (ADR-0101
 * Amendments 2026-11-04). What holds (R1.6): the same document gives the same
 * coordinates; inserting a step moves only what follows it in its lane and in
 * the sequences around that lane, and only down; a step with lanes may push
 * sibling lanes sideways but never changes vertical or lane order.
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
  /** Inside a frame, around its card and lanes. */
  framePad: number;
  /** A loop frame's left gutter, where "Lặp lại" climbs back. */
  gutter: number;
  /** The height of a parallel frame's Điểm nối bar. */
  bar: number;
  /** Under a loop frame, down to its exit. */
  exit: number;
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
    framePad: 24,
    gutter: 104,
    bar: 32,
    exit: 24,
  };
}

const NOTHING_FOLDED: ReadonlySet<string> = new Set();

interface Extent {
  left: number;
  right: number;
  height: number;
}

interface Sequence extends Extent {
  items: MeasuredStep[];
  /** The last step leads nowhere: the lane does not reach its join. */
  ends: boolean;
  /** Steps that leave their loop, no loop inside having taken them. */
  breaks: number;
}

interface MeasuredLane extends Sequence {
  lane: LaneNode;
}

interface Hung {
  lane: MeasuredLane;
  /** The lane's axis from the step's axis. */
  offset: number;
}

type Kind = "card" | "choice" | "parallel" | "loop";

/** One step, every y from the step's top. */
interface MeasuredStep extends Extent {
  node: StepNode;
  kind: Kind;
  folded: boolean;
  cardTop: number;
  /** choice and parallel: the lanes under the card. */
  block: Hung[];
  lanesTop: number;
  /** parallel: the Điểm nối bar's top. */
  barTop: number;
  /** loop: the body inside the frame, and the lanes hung under it. */
  body: MeasuredLane | null;
  extras: Hung[];
  frame: { left: number; right: number; height: number } | null;
  /** loop: the exit under the frame, and the join under it and the extras. */
  exitY: number;
  loopJoinY: number;
  /** choice: the join point. */
  joinY: number;
  /** Where the main flow leaves, or null when nothing of it does. */
  mainOut: number | null;
  error: Hung | null;
  rejoinY: number;
  /** Where the step as a whole leaves, or null. */
  out: number | null;
  breaks: number;
}

class Measurer {
  constructor(
    private readonly m: LayoutMetrics,
    private readonly folded: ReadonlySet<string>,
  ) {}

  sequence(steps: StepNode[], withHead: boolean): Sequence {
    const m = this.m;
    const head = withHead ? m.laneHead.height : 0;
    const headHalf = withHead ? m.laneHead.width / 2 : 0;
    if (steps.length === 0) {
      const half = Math.max(m.empty.width / 2, headHalf, m.card.width / 2);
      return {
        left: half,
        right: half,
        height: head + m.gap / 2 + m.empty.height,
        items: [],
        ends: false,
        breaks: 0,
      };
    }
    const items = steps.map((step) => this.step(step));
    let left = Math.max(m.card.width / 2, headHalf);
    let right = left;
    let height = head + m.gap;
    let breaks = 0;
    for (const item of items) {
      left = Math.max(left, item.left);
      right = Math.max(right, item.right);
      height += item.height + m.gap;
      breaks += item.breaks;
    }
    const ends = items[items.length - 1]!.out === null;
    return { left, right, height, items, ends, breaks };
  }

  lane(lane: LaneNode, withHead = true): MeasuredLane {
    return { lane, ...this.sequence(lane.steps, withHead) };
  }

  /** Lanes side by side, centred on the axis, in document order. */
  private sideBySide(lanes: MeasuredLane[]): { hung: Hung[]; half: number } {
    if (lanes.length === 0) return { hung: [], half: 0 };
    const total =
      lanes.reduce((sum, l) => sum + l.left + l.right, 0) +
      this.m.laneGap * (lanes.length - 1);
    let x = -total / 2;
    const hung: Hung[] = [];
    for (const lane of lanes) {
      hung.push({ lane, offset: x + lane.left });
      x += lane.left + lane.right + this.m.laneGap;
    }
    return { hung, half: total / 2 };
  }

  step(node: StepNode): MeasuredStep {
    const m = this.m;
    const half = m.card.width / 2;
    const leaves = !node.shape.endsRun && !node.shape.exitsLoop;
    const inner = node.lanes.filter((l) => l.kind !== "error");
    const block = node.shape.block;
    const kind: Kind =
      block === "none" ? (inner.length > 0 ? "choice" : "card") : block;
    const item: MeasuredStep = {
      node,
      kind,
      folded: false,
      left: half,
      right: half,
      height: m.card.height,
      cardTop: 0,
      block: [],
      lanesTop: 0,
      barTop: 0,
      body: null,
      extras: [],
      frame: null,
      exitY: 0,
      loopJoinY: 0,
      joinY: 0,
      mainOut: leaves ? m.card.height : null,
      error: null,
      rejoinY: 0,
      out: null,
      breaks: node.shape.exitsLoop ? 1 : 0,
    };
    if (kind === "choice") this.choice(item, inner);
    else if (kind === "parallel") this.parallel(item, inner);
    else if (kind === "loop") this.loop(item, inner);
    if (kind !== "card" && isFrame(node) && this.folded.has(node.id)) {
      // Drawn as its card (R1.7); what leaves it and what it lets out are
      // the frame's, measured above.
      Object.assign(item, {
        folded: true,
        left: half,
        right: half,
        height: m.card.height,
        cardTop: 0,
        block: [],
        body: null,
        extras: [],
        frame: null,
        mainOut: item.mainOut === null ? null : m.card.height,
      });
    }
    this.errorLane(item);
    return item;
  }

  private choice(item: MeasuredStep, inner: LaneNode[]) {
    const m = this.m;
    const lanes = inner.map((l) => this.lane(l));
    const { hung, half } = this.sideBySide(lanes);
    item.block = hung;
    item.lanesTop = m.card.height + m.fork;
    const lanesBottom =
      lanes.length > 0
        ? item.lanesTop + Math.max(...lanes.map((l) => l.height))
        : m.card.height;
    item.joinY = lanesBottom + m.join / 2;
    item.left = item.right = Math.max(m.card.width / 2, half);
    item.height = lanesBottom + m.join;
    const reached = lanes.some((l) => !l.ends);
    item.mainOut = reached && item.mainOut !== null ? item.joinY : null;
    item.breaks += lanes.reduce((n, l) => n + l.breaks, 0);
  }

  private parallel(item: MeasuredStep, inner: LaneNode[]) {
    const m = this.m;
    const p = m.framePad;
    const lanes = inner.map((l) => this.lane(l));
    const { hung, half } = this.sideBySide(lanes);
    item.block = hung;
    item.cardTop = p;
    item.lanesTop = p + m.card.height + m.fork;
    const lanesBottom =
      lanes.length > 0
        ? item.lanesTop + Math.max(...lanes.map((l) => l.height))
        : p + m.card.height;
    item.barTop = lanesBottom + m.join / 2;
    const height = item.barTop + m.bar + p;
    const side = Math.max(m.card.width / 2, half) + p;
    item.frame = { left: side, right: side, height };
    item.left = item.right = side;
    item.height = height;
    const reached = lanes.length === 0 || lanes.some((l) => !l.ends);
    item.mainOut =
      reached && item.mainOut !== null ? item.barTop + m.bar : null;
    item.breaks += lanes.reduce((n, l) => n + l.breaks, 0);
  }

  private loop(item: MeasuredStep, inner: LaneNode[]) {
    const m = this.m;
    const p = m.framePad;
    const [first, ...rest] = inner;
    // The body is the type's first lane: the catalogue lists `body` first
    // (workflow-nodes R11.2), so no lane name is written here.
    const body = first ? this.lane(first, false) : null;
    item.body = body;
    item.cardTop = p;
    const bodyTop = p + m.card.height;
    const bodyBottom = bodyTop + (body?.height ?? 0);
    const height = bodyBottom + p;
    const bodyLeft = Math.max(m.card.width / 2, body?.left ?? 0);
    const bodyRight = Math.max(m.card.width / 2, body?.right ?? 0);
    item.frame = {
      left: bodyLeft + m.gutter,
      right: bodyRight + p,
      height,
    };
    item.exitY = height + m.exit;
    const exits =
      (body !== null && (!body.ends || body.breaks > 0)) || body === null;
    let right = item.frame.right;
    let cursor = m.laneGap;
    let extrasBottom = 0;
    for (const lane of rest.map((l) => this.lane(l))) {
      const offset = cursor + lane.left;
      item.extras.push({ lane, offset });
      cursor = offset + lane.right + m.laneGap;
      right = Math.max(right, offset + lane.right);
      extrasBottom = Math.max(extrasBottom, height + m.fork + lane.height);
      item.breaks += lane.breaks;
    }
    item.left = item.frame.left;
    item.right = right;
    const leaves = item.mainOut !== null;
    if (item.extras.length > 0) {
      item.loopJoinY = Math.max(item.exitY, extrasBottom) + m.join / 2;
      item.height = item.loopJoinY + m.join / 2;
      const reached = exits || item.extras.some((h) => !h.lane.ends);
      item.mainOut = reached && leaves ? item.loopJoinY : null;
    } else {
      item.height = item.exitY;
      item.mainOut = exits && leaves ? item.exitY : null;
    }
  }

  private errorLane(item: MeasuredStep) {
    const m = this.m;
    item.out = item.mainOut;
    const errorLane = item.node.lanes.find((l) => l.kind === "error");
    if (!errorLane) return;
    const lane = this.lane(errorLane);
    const offset = item.right + m.laneGap + lane.left;
    item.error = { lane, offset };
    item.right = offset + lane.right;
    item.rejoinY =
      Math.max(item.height, item.cardTop + lane.height) + m.join / 2;
    item.height = item.rejoinY + m.join / 2;
    item.breaks += lane.breaks;
    if (!lane.ends) item.out = item.rejoinY;
  }
}

/** Where flow leaves a placed shape: its id and the y it leaves at. */
interface Exit {
  from: string;
  y: number;
}

/** A loop being placed: where its "Thoát vòng lặp" steps point. */
interface LoopContext {
  exit: string;
  axis: number;
  /** Inside the frame, under the way back, where a break's arrow turns. */
  turnY: number;
  exitY: number;
}

class Placer {
  readonly shapes: CanvasShapes = {
    frames: [],
    cards: [],
    laneHeads: [],
    slots: [],
    joins: [],
    connections: [],
  };

  private readonly loops: LoopContext[] = [];

  constructor(private readonly m: LayoutMetrics) {}

  private connect(
    from: string,
    to: string,
    points: Point[],
    options: Partial<
      Pick<CanvasConnection, "dashed" | "arrow" | "label" | "labelAt">
    > & { suffix?: string } = {},
  ) {
    this.shapes.connections.push({
      id: `${from}->${to}${options.suffix ?? ""}`,
      from,
      to,
      points,
      dashed: options.dashed ?? false,
      arrow: options.arrow ?? false,
      label: options.label ?? null,
      labelAt: options.labelAt ?? null,
    });
  }

  private point(
    kind: CanvasJoin["kind"],
    step: string,
    x: number,
    y: number,
  ): string {
    const id = `${kind}:${step}`;
    this.shapes.joins.push({ id, step, kind, x, y, width: 0, height: 0 });
    return id;
  }

  /**
   * Place a lane's items with its axis at `axis` from `top`, under a head when
   * `head` names one; returns where its last connection leaves from, or null
   * when its last step leads nowhere. `dashed` draws the lane's own chain
   * dashed (the "Khi lỗi" lane).
   */
  sequence(
    items: MeasuredStep[],
    axis: number,
    top: number,
    parent: string | null,
    port: string,
    head: string | null,
    entry: Exit | null,
    dashed = false,
  ): Exit | null {
    const m = this.m;
    let y = top;
    let previous = entry;
    if (head !== null && parent !== null) {
      this.shapes.laneHeads.push({
        id: head,
        parent,
        port,
        x: axis - m.laneHead.width / 2,
        y,
        width: m.laneHead.width,
        height: m.laneHead.height,
      });
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
        this.connect(
          previous.from,
          id,
          [
            { x: axis, y: previous.y },
            { x: axis, y: slot.y },
          ],
          { dashed },
        );
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
        this.connect(
          previous.from,
          item.node.id,
          [
            { x: axis, y: previous.y },
            { x: axis, y: y + item.cardTop },
          ],
          { dashed },
        );
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
    return previous;
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

  /** Lanes hung from `from` along `fork`, each from its head at `top`;
   * returns each lane's way out with its axis. */
  private lanes(
    item: MeasuredStep,
    hung: Hung[],
    axis: number,
    top: number,
    from: string,
    fork: (laneAxis: number) => Point[],
  ): { exit: Exit | null; axis: number }[] {
    const { node } = item;
    return hung.map(({ lane, offset }) => {
      const laneAxis = axis + offset;
      const head = `head:${node.id}:${lane.lane.port}`;
      this.connect(from, head, fork(laneAxis));
      const exit = this.sequence(
        lane.items,
        laneAxis,
        top,
        node.id,
        lane.lane.port,
        head,
        null,
      );
      return { exit, axis: laneAxis };
    });
  }

  /** Place one step with its top at `y`; returns where it is left, if
   * anywhere. */
  step(item: MeasuredStep, axis: number, y: number): Exit | null {
    const m = this.m;
    const { node } = item;
    const half = m.card.width / 2;
    const cardY = y + item.cardTop;
    const cardBottom = cardY + m.card.height;
    if (item.frame) {
      this.shapes.frames.push({
        id: `frame:${node.id}`,
        step: node.id,
        kind: item.kind === "loop" ? "loop" : "parallel",
        x: axis - item.frame.left,
        y,
        width: item.frame.left + item.frame.right,
        height: item.frame.height,
      });
    }
    this.shapes.cards.push({
      id: node.id,
      x: axis - half,
      y: cardY,
      width: m.card.width,
      height: m.card.height,
      folded: item.folded,
    });
    const loop = this.loops[this.loops.length - 1];
    if (node.shape.exitsLoop && loop) {
      this.connect(
        node.id,
        loop.exit,
        [
          { x: axis, y: cardBottom },
          { x: axis, y: loop.turnY },
          { x: loop.axis, y: loop.turnY },
          { x: loop.axis, y: loop.exitY },
        ],
        { arrow: true },
      );
    }

    let main: Exit | null =
      item.mainOut === null ? null : { from: node.id, y: y + item.mainOut };
    if (item.kind === "choice" && !item.folded)
      main = this.choice(item, axis, y);
    if (item.kind === "parallel" && !item.folded)
      main = this.parallel(item, axis, y);
    if (item.kind === "loop" && !item.folded) main = this.loop(item, axis, y);
    return this.error(item, axis, y, main);
  }

  private choice(item: MeasuredStep, axis: number, y: number): Exit | null {
    const m = this.m;
    const id = item.node.id;
    const bottom = y + m.card.height;
    const forkY = bottom + m.fork / 2;
    const joinY = y + item.joinY;
    const exits = this.lanes(
      item,
      item.block,
      axis,
      y + item.lanesTop,
      id,
      (x) => [
        { x: axis, y: bottom },
        { x: axis, y: forkY },
        { x, y: forkY },
        { x, y: y + item.lanesTop },
      ],
    );
    if (item.mainOut === null) return null;
    const join = this.point("join", id, axis, joinY);
    for (const { exit, axis: x } of exits) {
      if (!exit) continue;
      this.connect(exit.from, join, [
        { x, y: exit.y },
        { x, y: joinY },
        { x: axis, y: joinY },
      ]);
    }
    return { from: join, y: joinY };
  }

  private parallel(item: MeasuredStep, axis: number, y: number): Exit | null {
    const m = this.m;
    const id = item.node.id;
    const bottom = y + item.cardTop + m.card.height;
    const forkY = bottom + m.fork / 2;
    const barTop = y + item.barTop;
    const exits = this.lanes(
      item,
      item.block,
      axis,
      y + item.lanesTop,
      id,
      (x) => [
        { x: axis, y: bottom },
        { x: axis, y: forkY },
        { x, y: forkY },
        { x, y: y + item.lanesTop },
      ],
    );
    if (item.mainOut === null) return null;
    const inner = item.frame!.left - m.framePad;
    const bar = `bar:${id}`;
    this.shapes.joins.push({
      id: bar,
      step: id,
      kind: "bar",
      x: axis - inner,
      y: barTop,
      width: inner * 2,
      height: m.bar,
    });
    for (const { exit, axis: x } of exits) {
      if (!exit) continue;
      this.connect(exit.from, bar, [
        { x, y: exit.y },
        { x, y: barTop },
      ]);
    }
    if (item.block.length === 0) {
      this.connect(id, bar, [
        { x: axis, y: bottom },
        { x: axis, y: barTop },
      ]);
    }
    return { from: bar, y: barTop + m.bar };
  }

  private loop(item: MeasuredStep, axis: number, y: number): Exit | null {
    const m = this.m;
    const id = item.node.id;
    const frame = item.frame!;
    const cardY = y + item.cardTop;
    const cardMid = cardY + m.card.height / 2;
    const frameBottom = y + frame.height;
    const repeatY = frameBottom - (m.framePad * 2) / 3;
    const turnY = frameBottom - m.framePad / 3;
    const exitY = y + item.exitY;
    const body = item.body;
    const exitWanted = body === null || !body.ends || body.breaks > 0;
    const exit = exitWanted ? `exit:${id}` : null;
    let end: Exit | null = null;
    if (body) {
      this.loops.push({ exit: exit ?? `exit:${id}`, axis, turnY, exitY });
      end = this.sequence(
        body.items,
        axis,
        cardY + m.card.height,
        id,
        body.lane.port,
        null,
        { from: id, y: cardY + m.card.height },
      );
      this.loops.pop();
    }
    if (exit) this.point("exit", id, axis, exitY);
    if (end && exit) {
      const gutterX = axis - (frame.left - m.gutter) - m.gutter / 2;
      this.connect(
        end.from,
        id,
        [
          { x: axis, y: end.y },
          { x: axis, y: repeatY },
          { x: gutterX, y: repeatY },
          { x: gutterX, y: cardMid },
          { x: axis - m.card.width / 2, y: cardMid },
        ],
        {
          dashed: true,
          arrow: true,
          label: "repeat",
          labelAt: { x: gutterX, y: (repeatY + cardMid) / 2 },
          suffix: ":repeat",
        },
      );
      this.connect(end.from, exit, [
        { x: axis, y: end.y },
        { x: axis, y: exitY },
      ]);
    } else if (body === null && exit) {
      this.connect(id, exit, [
        { x: axis, y: cardY + m.card.height },
        { x: axis, y: exitY },
      ]);
    }
    if (item.extras.length === 0) {
      return exit && item.mainOut !== null ? { from: exit, y: exitY } : null;
    }
    const forkY = frameBottom + m.fork / 2;
    const lanesTop = frameBottom + m.fork;
    const startX = Math.min(
      axis + item.extras[0]!.offset,
      axis + frame.right - m.framePad,
    );
    // The hung lanes leave from the frame's floor, right of the exit.
    const exits = this.lanes(
      item,
      item.extras,
      axis,
      lanesTop,
      `frame:${id}`,
      (x) => [
        { x: startX, y: frameBottom },
        { x: startX, y: forkY },
        { x, y: forkY },
        { x, y: lanesTop },
      ],
    );
    if (item.mainOut === null) return null;
    const joinY = y + item.loopJoinY;
    const join = this.point("join", id, axis, joinY);
    if (exit) {
      this.connect(exit, join, [
        { x: axis, y: exitY },
        { x: axis, y: joinY },
      ]);
    }
    for (const { exit: laneExit, axis: x } of exits) {
      if (!laneExit) continue;
      this.connect(laneExit.from, join, [
        { x, y: laneExit.y },
        { x, y: joinY },
        { x: axis, y: joinY },
      ]);
    }
    return { from: join, y: joinY };
  }

  private error(
    item: MeasuredStep,
    axis: number,
    y: number,
    main: Exit | null,
  ): Exit | null {
    if (!item.error) return main;
    const m = this.m;
    const id = item.node.id;
    const laneAxis = axis + item.error.offset;
    const port = item.error.lane.lane.port;
    const head = `head:${id}:${port}`;
    const top = y + item.cardTop;
    const mid = top + m.laneHead.height / 2;
    this.connect(
      id,
      head,
      [
        { x: axis + m.card.width / 2, y: mid },
        { x: laneAxis - m.laneHead.width / 2, y: mid },
      ],
      { dashed: true },
    );
    const end = this.sequence(
      item.error.lane.items,
      laneAxis,
      top,
      id,
      port,
      head,
      null,
      true,
    );
    if (!end) return main;
    const rejoinY = y + item.rejoinY;
    const rejoin = this.point("rejoin", id, axis, rejoinY);
    this.connect(
      end.from,
      rejoin,
      [
        { x: laneAxis, y: end.y },
        { x: laneAxis, y: rejoinY },
        { x: axis, y: rejoinY },
      ],
      { dashed: true },
    );
    if (main) {
      this.connect(main.from, rejoin, [
        { x: axis, y: main.y },
        { x: axis, y: rejoinY },
      ]);
    }
    return { from: rejoin, y: rejoinY };
  }
}

/**
 * The shapes of a document's step tree, its root axis at x = 0, top at 0.
 * `folded` names the frames drawn as their card alone (R1.7); a read-only
 * canvas passes none, so every frame is open.
 */
export function layoutWorkflow(
  tree: WorkflowTree,
  metrics: LayoutMetrics,
  folded: ReadonlySet<string> = NOTHING_FOLDED,
): CanvasShapes {
  const root = new Measurer(metrics, folded).sequence(tree.steps, false);
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
