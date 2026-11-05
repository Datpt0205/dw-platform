import {
  addableFixedPorts,
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

export interface CardView {
  id: string;
  name: string;
  known: boolean;
  /** The catalogue's label for the type, or the type as written. */
  typeLabel: string;
  group: StepGroup;
  summary: string;
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

export function cardView(node: StepNode, catalogue: Catalogue): CardView {
  const spec = catalogue.get(node.type);
  const retry = isObject(node.rest.retry)
    ? node.rest.retry.max_attempts
    : undefined;
  const onError = node.rest.on_error;
  return {
    id: node.id,
    name: stepName(node, catalogue),
    known: node.known,
    typeLabel: spec?.label_vi ?? node.type,
    group: stepGroup(node.type),
    summary: node.known ? summary(node, catalogue) : "",
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
 * steps, so it neither moves nor deletes it.
 */
export function stepMenu(node: StepNode, catalogue: Catalogue): MenuEntry[] {
  const copy: MenuEntry = { key: "copyRef", label: bt("menu.copyRef") };
  if (!node.known) return [copy];
  const spec = catalogue.get(node.type);
  const entries: MenuEntry[] = [
    { key: "addBefore", label: bt("menu.addBefore") },
    { key: "addAfter", label: bt("menu.addAfter") },
    { key: "move", label: bt("menu.move") },
  ];
  if (
    spec?.ports.kind === "keyed" ||
    addableFixedPorts(node, catalogue).length > 0
  ) {
    entries.push({ key: "addLane", label: bt("menu.addLane") });
  }
  if (node.lanes.some((l) => l.removable)) {
    entries.push({ key: "removeLane", label: bt("menu.removeLane") });
  }
  entries.push({ key: "delete", label: bt("menu.delete"), danger: true }, copy);
  return entries;
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
