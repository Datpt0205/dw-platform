import {
  addableFixedPorts,
  isFrame,
  isInside,
  laneAt,
  locate,
  stepGroup,
  stepName,
  type Catalogue,
  type LaneNode,
  type LaneRef,
  type OnError,
  type StepGroup,
  type StepNode,
  type WorkflowTree,
} from "../../../../../lib/workflow-graph";
import type { CanvasSlot } from "../../../../../lib/workflow-shapes";
import { bt } from "./messages";

/**
 * What the builder shows of the tree, in words: a card's view, a lane's and a
 * slot's names, a step's menu and the targets of "Di chuyển…". Read by the
 * canvas, the outline `Tree` and the page alike, so the three never name a
 * thing two ways (ui-quality.md §1).
 */

export function laneLabel(lane: Pick<LaneNode, "kind" | "label">): string {
  return lane.kind === "error" ? bt("lane.error") : lane.label;
}

/** A lane as an announcement names it: "«Duyệt» của «Duyệt ưu đãi»". */
export function laneName(
  tree: WorkflowTree,
  catalogue: Catalogue,
  ref: LaneRef,
): string {
  if (ref.parent === null) return `«${bt("lane.root")}»`;
  const parent = locate(tree, ref.parent)?.node;
  const lane = parent?.lanes.find((l) => l.port === ref.port);
  if (!parent || !lane) return `«${ref.port}»`;
  return bt("announce.lane", {
    lane: laneLabel(lane),
    parent: stepName(parent, catalogue),
  });
}

/** A lane's own label, for "Vào đầu «…»". */
function shortLaneLabel(tree: WorkflowTree, ref: LaneRef): string {
  if (ref.parent === null) return bt("lane.root");
  const lane = laneAt(tree, ref);
  return lane ? laneLabel(lane) : ref.port;
}

/** A word the card carries with its icon, never the icon alone (BU14). */
export interface CardMark {
  key: "subworkflow" | "rule";
  text: string;
}

export interface CardView {
  id: string;
  name: string;
  known: boolean;
  /** The catalogue's label for the type, or the type as written. */
  typeLabel: string;
  group: StepGroup;
  summary: string;
  /** The card's second line in place of "type · summary": a loop frame's
   * "Lặp lại khi … (tối đa N lần)". */
  title: string | null;
  /** A third line: who approves, or "Chờ Quy trình con xong". */
  detail: { text: string; wait: boolean } | null;
  marks: CardMark[];
  /** A frame the viewer can fold (R1.7). */
  frame: boolean;
  retry: number | null;
  timeout: number | null;
  onError: OnError | null;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The first plain value the step's config holds, in the order the schema
 * requires its keys, for the card's second line. */
function summary(node: StepNode, catalogue: Catalogue): string {
  const config = isObject(node.rest.config) ? node.rest.config : {};
  const spec = catalogue.get(node.type);
  const required = Array.isArray(spec?.config_schema.required)
    ? (spec.config_schema.required as unknown[]).filter(
        (k): k is string => typeof k === "string",
      )
    : [];
  const keys = [
    ...required,
    ...Object.keys(config).filter((k) => !required.includes(k)),
  ];
  for (const key of keys) {
    const value = config[key];
    if (typeof value === "string" && value !== "") return value;
    if (typeof value === "number" || typeof value === "boolean")
      return String(value);
  }
  return "";
}

/** A type's name without its version: `logic.loop@1` is `logic.loop`. */
function typeName(type: string): string {
  return type.split("@")[0] ?? type;
}

type TypeContent = Pick<CardView, "summary" | "title" | "detail" | "marks">;

/**
 * What a card of one W1 type says beyond its type and summary, chosen by the
 * type's name (ticket 04: only a card's content is, never its shape): the
 * approver card, the switch's `on` as stored, the "Quy trình con" mark and
 * its wait, the loop frame's "Lặp lại khi …". Any other type, a type with a
 * known block and a name the page does not know included, is the plain R1.8
 * card.
 */
function typeContent(
  node: StepNode,
  config: Record<string, unknown>,
): TypeContent | null {
  switch (typeName(node.type)) {
    case "logic.switch":
      // Verbatim, as the server stores it: no CEL is shortened here.
      return {
        summary: typeof config.on === "string" ? config.on : "",
        title: null,
        detail: null,
        marks: [],
      };
    case "human.approval":
      return approvalContent(config);
    case "flow.subworkflow":
      return {
        summary: typeof config.workflow === "string" ? config.workflow : "",
        title: null,
        detail: { text: bt("card.subworkflowWait"), wait: true },
        marks: [{ key: "subworkflow", text: bt("card.subworkflow") }],
      };
    case "logic.loop": {
      const condition =
        typeof config.condition === "string" && config.condition !== ""
          ? config.condition
          : "…";
      const n =
        typeof config.max_iterations === "number" ? config.max_iterations : "N";
      return {
        summary: "",
        title: bt("frame.loop", { condition, n }),
        detail: null,
        marks: [],
      };
    }
    default:
      return null;
  }
}

/**
 * The approver card (workflow-nodes R9.1, R12.1): who is assigned and the
 * scope they must hold; "Cần cả N người duyệt" when every assignee must
 * approve and the config names N ≥ 2 people, "Cần mọi người được giao duyệt"
 * when every assignee must approve and who they are is known only at run time
 * (an expression, or whoever holds the scope); no rule line otherwise.
 */
function approvalContent(config: Record<string, unknown>): TypeContent {
  const scope =
    typeof config.required_scope === "string" ? config.required_scope : "";
  const assignees = config.assignees;
  const people = Array.isArray(assignees)
    ? assignees.filter((a): a is string => typeof a === "string")
    : null;
  const detail =
    people !== null && people.length > 0
      ? bt("card.approvers", { who: people.join(", ") })
      : typeof assignees === "string" && assignees !== ""
        ? bt("card.approversExpression", { expression: assignees })
        : bt("card.approversScope");
  const marks: CardMark[] = [];
  if (config.approval_rule === "all") {
    if (people !== null && people.length >= 2) {
      marks.push({
        key: "rule",
        text: bt("card.ruleAllOf", { n: people.length }),
      });
    } else if (people === null || people.length === 0) {
      marks.push({ key: "rule", text: bt("card.ruleAll") });
    }
  }
  return {
    summary: scope === "" ? "" : bt("card.scope", { scope }),
    title: null,
    detail: { text: detail, wait: false },
    marks,
  };
}

export function cardView(node: StepNode, catalogue: Catalogue): CardView {
  const spec = catalogue.get(node.type);
  const retry = isObject(node.rest.retry)
    ? node.rest.retry.max_attempts
    : undefined;
  const onError = node.rest.on_error;
  const config = isObject(node.rest.config) ? node.rest.config : {};
  const content = node.known ? typeContent(node, config) : null;
  return {
    id: node.id,
    name: stepName(node, catalogue),
    known: node.known,
    typeLabel: spec?.label_vi ?? node.type,
    group: stepGroup(node.type),
    summary: content?.summary ?? (node.known ? summary(node, catalogue) : ""),
    title: content?.title ?? null,
    detail: content?.detail ?? null,
    marks: content?.marks ?? [],
    frame: isFrame(node),
    retry: typeof retry === "number" && retry > 1 ? retry : null,
    timeout:
      typeof node.rest.timeout_s === "number" ? node.rest.timeout_s : null,
    onError: onError === "continue" || onError === "route" ? onError : null,
  };
}

export function slotLabel(
  slot: CanvasSlot,
  tree: WorkflowTree,
  catalogue: Catalogue,
): string {
  const lane = { parent: slot.parent, port: slot.port };
  if (slot.empty) return bt("slot.empty", { lane: shortLaneLabel(tree, lane) });
  if (slot.after !== null) {
    const before = locate(tree, slot.after)?.node;
    return bt("slot.after", {
      name: before ? stepName(before, catalogue) : slot.after,
    });
  }
  return bt("slot.first", { lane: shortLaneLabel(tree, lane) });
}

export type MenuKey =
  | "addBefore"
  | "addAfter"
  | "move"
  | "addLane"
  | "removeLane"
  | `addPort:${string}`
  | `removePort:${string}`
  | "fold"
  | "unfold"
  | "removeBranch"
  | "delete"
  | "copyRef";

export interface MenuEntry {
  key: MenuKey;
  label: string;
  danger?: boolean;
}

/**
 * A step's "…" menu. A step whose type the catalogue lacks has only "Sao
 * chép tham chiếu": the page cannot tell which of its config's keys hold
 * steps, so it neither moves nor deletes it. A keyed type adds and removes
 * its entries ("Thêm nhánh", "Bỏ nhánh…"); a type with an optional fixed lane
 * names it ("Thêm làn «Đã đủ N lần»", "Bỏ làn «Đã đủ N lần»"); a frame folds
 * and opens from here too, the keyboard's way to it (R1.7, R2.5).
 */
export function stepMenu(
  node: StepNode,
  catalogue: Catalogue,
  folded = false,
): MenuEntry[] {
  const copy: MenuEntry = { key: "copyRef", label: bt("menu.copyRef") };
  if (!node.known) return [copy];
  const spec = catalogue.get(node.type);
  const entries: MenuEntry[] = [
    { key: "addBefore", label: bt("menu.addBefore") },
    { key: "addAfter", label: bt("menu.addAfter") },
    { key: "move", label: bt("menu.move") },
  ];
  if (isFrame(node)) {
    entries.push(
      folded
        ? { key: "unfold", label: bt("menu.unfold") }
        : { key: "fold", label: bt("menu.fold") },
    );
  }
  if (spec?.ports.kind === "keyed") {
    entries.push({ key: "addLane", label: bt("menu.addLane") });
    if (node.lanes.some((l) => l.kind === "keyed")) {
      entries.push({ key: "removeLane", label: bt("menu.removeLane") });
    }
  } else {
    for (const port of addableFixedPorts(node, catalogue)) {
      entries.push({
        key: `addPort:${port.name}`,
        label: bt("menu.addPort", { lane: port.label_vi }),
      });
    }
    for (const lane of node.lanes) {
      if (lane.kind !== "fixed" || !lane.removable) continue;
      entries.push({
        key: `removePort:${lane.port}`,
        label: bt("menu.removePort", { lane: lane.label }),
      });
    }
  }
  entries.push({ key: "delete", label: bt("menu.delete"), danger: true }, copy);
  return entries;
}

/** A lane head's menu: "Bỏ nhánh" on a keyed entry (a `cases` key, a
 * `branches` name), through the tree's lane operation; none elsewhere. */
export function laneMenu(lane: Pick<LaneNode, "kind">): MenuEntry[] {
  return lane.kind === "keyed"
    ? [{ key: "removeBranch", label: bt("menu.removeBranch"), danger: true }]
    : [];
}

/** One target of "Di chuyển…": a slot's value, or a lane's group. */
export interface MoveTarget {
  title: string;
  value: string;
  selectable: boolean;
  children: MoveTarget[];
}

export function slotValue(lane: LaneRef, index: number): string {
  return JSON.stringify([lane.parent, lane.port, index]);
}

export function parseSlotValue(value: string): {
  lane: LaneRef;
  index: number;
} {
  const [parent, port, index] = JSON.parse(value) as [
    string | null,
    string,
    number,
  ];
  return { lane: { parent, port }, index };
}

/** Every slot a step may move to, as a tree of lanes, none inside the step's
 * own subtree (R1.4). */
export function moveTargets(
  tree: WorkflowTree,
  catalogue: Catalogue,
  moving: string,
): MoveTarget[] {
  const laneNode = (
    ref: LaneRef,
    label: string,
    steps: StepNode[],
  ): MoveTarget => {
    const children: MoveTarget[] = [
      {
        title: bt("move.first", { lane: label }),
        value: slotValue(ref, 0),
        selectable: true,
        children: [],
      },
    ];
    steps.forEach((step, index) => {
      const inner =
        step.id === moving
          ? []
          : step.lanes
              .map((l) => ({ ref: { parent: step.id, port: l.port }, lane: l }))
              .filter(({ ref }) => !isInside(tree, moving, ref))
              .map(({ ref, lane }) =>
                laneNode(ref, laneLabel(lane), lane.steps),
              );
      children.push({
        title: bt("move.after", { name: stepName(step, catalogue) }),
        value: slotValue(ref, index + 1),
        selectable: true,
        children: inner,
      });
    });
    return {
      title: label,
      value: `lane:${JSON.stringify([ref.parent, ref.port])}`,
      selectable: false,
      children,
    };
  };
  return [
    laneNode({ parent: null, port: "steps" }, bt("lane.root"), tree.steps),
  ];
}
