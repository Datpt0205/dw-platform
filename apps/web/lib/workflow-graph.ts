/**
 * Every operation the builder makes on a `dw.workflow/v1` document's step tree
 * (workflow-builder-ui R1.4, R2.5, R2.10, R2.11; ADR-0101 (Accepted) decision
 * 3; ADR-0112 (Accepted) decision 1). Pure and importing nothing: the canvas,
 * the outline `Tree` and the layout all read the one tree this module builds.
 *
 * A document is a tree of steps: each lane a step holds sits inside its
 * `config` under the port's name (a `fixed` port), as an entry of the object
 * under the type's `key` (a `keyed` port, read as `<key>.<entry>`), under the
 * `default` port's name, or, for the "Khi lỗi" lane, in the step's own
 * `error_lane` while `on_error` is `route`. Which of these a type has is read
 * from the catalogue (`GET /api/v1/studio/node-types`), never written here.
 *
 * The tree holds no position, no connection and nothing it does not read back:
 * `fromTree(toTree(doc))` is `doc`, key for key, an absent optional key still
 * absent. The content hash is the server's (`dw_kernel.canonical`); nothing
 * here hashes, normalises or diffs a document (`diff_steps` of wf-lite does).
 */

/* ------------------------------------------------------------------------- */
/* The catalogue, as much of it as the tree reads                             */
/* ------------------------------------------------------------------------- */

export interface PortSpec {
  name: string;
  label_vi: string;
}

/** Where a type's lanes sit: `NodeTypeView.ports` of the route. */
export type PortsSpec =
  | { kind: "fixed"; ports: PortSpec[] }
  | { kind: "keyed"; key: string; default: PortSpec | null };

/** One entry of the catalogue, structurally `NodeTypeView`. */
export interface StepTypeSpec {
  type: string;
  label_vi: string;
  config_schema: { [key: string]: unknown };
  ports: PortsSpec;
}

export type Catalogue = ReadonlyMap<string, StepTypeSpec>;

export function catalogueOf(types: readonly StepTypeSpec[]): Catalogue {
  return new Map(types.map((spec) => [spec.type, spec]));
}

/** A trigger type is not a step a builder places (`triggers[]` is not edited
 * in W1): the palette leaves out every `trigger.*`. */
export function isTriggerType(type: string): boolean {
  return type.startsWith("trigger.");
}

/** The groups the canvas vocabulary colours (`CANVAS_GROUPS` of `@dw/ui`). */
const GROUPS = ["trigger", "ai", "data", "logic", "human", "tool"] as const;
export type StepGroup = (typeof GROUPS)[number];

/**
 * A type's group, from its namespace (`ai.llm@2` is `ai`): the catalogue
 * carries no group code yet, so the namespace is the one owner until it does,
 * and a namespace the vocabulary has no colour for (`flow`, `time`) reads as
 * `logic`.
 */
export function stepGroup(type: string): StepGroup {
  const namespace = type.split(".")[0] ?? "";
  return (GROUPS as readonly string[]).includes(namespace)
    ? (namespace as StepGroup)
    : "logic";
}

/* ------------------------------------------------------------------------- */
/* The tree                                                                   */
/* ------------------------------------------------------------------------- */

export type JsonObject = { [key: string]: unknown };

export type LaneKind = "fixed" | "keyed" | "default" | "error";

/** The port name of the "Khi lỗi" lane, beside the catalogue's ports. */
export const ERROR_LANE = "error_lane";

export interface LaneNode {
  /** `approved`, `cases.hot`, `default`, `error_lane`. */
  port: string;
  /** The catalogue's label, or the entry's key for a keyed lane; empty for
   * the error lane, whose label is the page's. */
  label: string;
  kind: LaneKind;
  /** Written in the document; a lane drawn but not written (the default lane
   * of a switch that has none yet) is written once a step goes into it. */
  present: boolean;
  /** Only a keyed entry and a fixed port the schema does not require come
   * off ("Bỏ nhánh…"); the default lane is always there (R1.5). */
  removable: boolean;
  steps: StepNode[];
}

export interface StepNode {
  id: string;
  type: string;
  /** The type is in the catalogue: an unknown type's lanes are unknown, so
   * the page neither deletes nor moves it. */
  known: boolean;
  /** The step as written, less the lanes held in `lanes`. */
  rest: JsonObject;
  lanes: LaneNode[];
  /** A lane item that is not a step object, kept as written. */
  opaque?: unknown;
}

export interface WorkflowTree {
  /** The document less `steps`. */
  rest: JsonObject;
  steps: StepNode[];
}

/** A lane by its holder: `parent` null is the document's own `steps`. */
export interface LaneRef {
  parent: string | null;
  port: string;
}

export const ROOT_LANE: LaneRef = { parent: null, port: "steps" };

/** A place a step can go: before the step at `index` of `lane`. */
export interface Slot {
  lane: LaneRef;
  index: number;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function schemaRequired(spec: StepTypeSpec): string[] {
  const required = spec.config_schema.required;
  return Array.isArray(required)
    ? required.filter((r): r is string => typeof r === "string")
    : [];
}

/** The `config` keys a type keeps its lanes under: the Form never shows them
 * (R2.1), and an edit of the Form never touches them. */
export function laneKeys(spec: StepTypeSpec): string[] {
  if (spec.ports.kind === "fixed") return spec.ports.ports.map((p) => p.name);
  return spec.ports.default
    ? [spec.ports.key, spec.ports.default.name]
    : [spec.ports.key];
}

/** Numbers the lane items that are not step objects, per tree built. */
interface Build {
  opaque: number;
}

export function toStepNode(
  raw: unknown,
  catalogue: Catalogue,
  build: Build = { opaque: 0 },
): StepNode {
  if (
    !isObject(raw) ||
    typeof raw.id !== "string" ||
    typeof raw.type !== "string"
  ) {
    build.opaque += 1;
    return {
      id: `?${build.opaque}`,
      type: "",
      known: false,
      rest: {},
      lanes: [],
      opaque: raw,
    };
  }
  const spec = catalogue.get(raw.type);
  if (!spec) {
    return { id: raw.id, type: raw.type, known: false, rest: raw, lanes: [] };
  }
  const rest: JsonObject = { ...raw };
  const config: JsonObject | null = isObject(raw.config)
    ? { ...raw.config }
    : null;
  const lanes: LaneNode[] = [];
  const required = schemaRequired(spec);
  const steps = (items: unknown[]) =>
    items.map((item) => toStepNode(item, catalogue, build));

  if (spec.ports.kind === "fixed") {
    for (const port of spec.ports.ports) {
      const value = config?.[port.name];
      const present = Array.isArray(value);
      const isRequired = required.includes(port.name);
      if (!present && !isRequired) continue;
      if (present && config) delete config[port.name];
      lanes.push({
        port: port.name,
        label: port.label_vi,
        kind: "fixed",
        present,
        removable: !isRequired,
        steps: present ? steps(value as unknown[]) : [],
      });
    }
  } else {
    const { key } = spec.ports;
    const container = config?.[key];
    if (config && isObject(container)) {
      const kept: JsonObject = {};
      for (const [name, value] of Object.entries(container)) {
        if (!Array.isArray(value)) {
          kept[name] = value;
          continue;
        }
        lanes.push({
          port: `${key}.${name}`,
          label: name,
          kind: "keyed",
          present: true,
          removable: true,
          steps: steps(value),
        });
      }
      config[key] = kept;
    }
    const fallback = spec.ports.default;
    if (fallback) {
      const value = config?.[fallback.name];
      const present = Array.isArray(value);
      if (present && config) delete config[fallback.name];
      lanes.push({
        port: fallback.name,
        label: fallback.label_vi,
        kind: "default",
        present,
        removable: false,
        steps: present ? steps(value as unknown[]) : [],
      });
    }
  }
  if (config) rest.config = config;
  if (raw.on_error === "route") {
    const present = Array.isArray(raw.error_lane);
    if (present) delete rest.error_lane;
    lanes.push({
      port: ERROR_LANE,
      label: "",
      kind: "error",
      present,
      removable: false,
      steps: present ? steps(raw.error_lane as unknown[]) : [],
    });
  }
  return { id: raw.id, type: raw.type, known: true, rest, lanes };
}

export function toTree(doc: JsonObject, catalogue: Catalogue): WorkflowTree {
  const rest: JsonObject = { ...doc };
  if (!Array.isArray(doc.steps)) return { rest, steps: [] };
  delete rest.steps;
  const build: Build = { opaque: 0 };
  return {
    rest,
    steps: doc.steps.map((item) => toStepNode(item, catalogue, build)),
  };
}

export function fromStepNode(node: StepNode): unknown {
  if ("opaque" in node) return node.opaque;
  const out: JsonObject = { ...node.rest };
  const written = node.lanes.filter((l) => l.present || l.steps.length > 0);
  const inConfig = written.filter((l) => l.kind !== "error");
  if (inConfig.length > 0) {
    const config: JsonObject = isObject(out.config) ? { ...out.config } : {};
    for (const lane of inConfig) {
      const steps = lane.steps.map(fromStepNode);
      if (lane.kind === "keyed") {
        const dot = lane.port.indexOf(".");
        const key = lane.port.slice(0, dot);
        const container = isObject(config[key]) ? { ...config[key] } : {};
        container[lane.port.slice(dot + 1)] = steps;
        config[key] = container;
      } else {
        config[lane.port] = steps;
      }
    }
    out.config = config;
  }
  const error = written.find((l) => l.kind === "error");
  if (error) out.error_lane = error.steps.map(fromStepNode);
  return out;
}

export function fromTree(tree: WorkflowTree): JsonObject {
  if (!("steps" in tree.rest) || tree.steps.length > 0) {
    return { ...tree.rest, steps: tree.steps.map(fromStepNode) };
  }
  return { ...tree.rest };
}

/* ------------------------------------------------------------------------- */
/* Reading                                                                    */
/* ------------------------------------------------------------------------- */

/** A step's name: its `description`, or the type's Vietnamese label from the
 * catalogue, or the type as written. The page never writes `description`. */
export function stepName(node: StepNode, catalogue: Catalogue): string {
  const description = node.rest.description;
  if (typeof description === "string" && description.trim() !== "") {
    return description;
  }
  return catalogue.get(node.type)?.label_vi ?? node.type;
}

export interface Located {
  node: StepNode;
  lane: LaneRef;
  index: number;
  /** The step ids that hold it, outermost first. */
  ancestors: string[];
}

export function walk(
  tree: WorkflowTree,
  visit: (
    node: StepNode,
    lane: LaneRef,
    index: number,
    ancestors: string[],
  ) => void,
): void {
  const go = (steps: StepNode[], lane: LaneRef, ancestors: string[]) => {
    steps.forEach((node, index) => {
      visit(node, lane, index, ancestors);
      const inner = [...ancestors, node.id];
      for (const child of node.lanes) {
        go(child.steps, { parent: node.id, port: child.port }, inner);
      }
    });
  };
  go(tree.steps, ROOT_LANE, []);
}

export function locate(tree: WorkflowTree, id: string): Located | null {
  let found: Located | null = null;
  walk(tree, (node, lane, index, ancestors) => {
    if (found === null && node.id === id)
      found = { node, lane, index, ancestors };
  });
  return found;
}

/** The lane a ref names, or null. */
export function laneAt(tree: WorkflowTree, ref: LaneRef): LaneNode | null {
  if (ref.parent === null) {
    return {
      port: ROOT_LANE.port,
      label: "",
      kind: "fixed",
      present: true,
      removable: false,
      steps: tree.steps,
    };
  }
  return (
    locate(tree, ref.parent)?.node.lanes.find((l) => l.port === ref.port) ??
    null
  );
}

/** A step and every step under it, in document order. */
export function subtree(node: StepNode): StepNode[] {
  const out: StepNode[] = [node];
  for (const lane of node.lanes)
    for (const step of lane.steps) out.push(...subtree(step));
  return out;
}

/** Whether `lane` lies in the subtree of step `id` (a move there would put
 * the step inside itself). */
export function isInside(
  tree: WorkflowTree,
  id: string,
  lane: LaneRef,
): boolean {
  if (lane.parent === null) return false;
  if (lane.parent === id) return true;
  return locate(tree, lane.parent)?.ancestors.includes(id) ?? false;
}

/** Every step id anywhere in the document, triggers and unknown steps'
 * configs included: a new id must collide with none of them. */
export function collectIds(
  value: unknown,
  into = new Set<string>(),
): Set<string> {
  if (Array.isArray(value)) {
    for (const item of value) collectIds(item, into);
  } else if (isObject(value)) {
    if (typeof value.id === "string" && typeof value.type === "string")
      into.add(value.id);
    for (const item of Object.values(value)) collectIds(item, into);
  }
  return into;
}

export function treeIds(tree: WorkflowTree): Set<string> {
  const ids = collectIds(tree.rest);
  walk(tree, (node) => {
    ids.add(node.id);
    if (!node.known) collectIds(node.rest, ids);
  });
  return ids;
}

/* ------------------------------------------------------------------------- */
/* A new step                                                                 */
/* ------------------------------------------------------------------------- */

const STEP_ID = /^[a-z][a-z0-9_]{0,39}$/;
const SUFFIX_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789";

/**
 * A new step's id: the type's name between its last dot and `@`, `_`, six
 * random `[a-z0-9]`, drawn again while it collides with an id the document
 * holds (ADR-0112 (Accepted): `^[a-z][a-z0-9_]{0,39}$`). Never edited.
 */
export function newStepId(
  type: string,
  taken: ReadonlySet<string>,
  random: () => number = Math.random,
): string {
  const name = type.split("@")[0]!.split(".").pop() ?? "";
  let base = name
    .toLowerCase()
    .replace(/[^a-z0-9_]/g, "_")
    .slice(0, 33);
  if (!/^[a-z]/.test(base)) base = `b${base}`.slice(0, 33);
  for (;;) {
    let suffix = "";
    for (let i = 0; i < 6; i++) {
      suffix += SUFFIX_ALPHABET[Math.floor(random() * SUFFIX_ALPHABET.length)];
    }
    const id = `${base}_${suffix}`;
    if (STEP_ID.test(id) && !taken.has(id)) return id;
  }
}

/**
 * A new step of `spec`: `config` holds the defaults its `config_schema`
 * declares and, empty, each lane the schema requires and the default lane
 * (the "Khác" lane is always there, R1.5); an optional lane (`max_reached`, a
 * `cases` entry) comes only when the builder adds it, because its presence
 * changes how the step runs (ADR-0112 (Accepted) decision 2). No
 * `description`: the name is the type's label until the builder writes one.
 */
export function newStep(
  spec: StepTypeSpec,
  taken: ReadonlySet<string>,
  random: () => number = Math.random,
): JsonObject {
  const config: JsonObject = {};
  const properties = spec.config_schema.properties;
  const lanes = new Set(laneKeys(spec));
  if (isObject(properties)) {
    for (const [key, schema] of Object.entries(properties)) {
      if (!lanes.has(key) && isObject(schema) && "default" in schema) {
        config[key] = structuredCloneJson(schema.default);
      }
    }
  }
  const required = schemaRequired(spec);
  if (spec.ports.kind === "fixed") {
    for (const port of spec.ports.ports) {
      if (required.includes(port.name)) config[port.name] = [];
    }
  } else {
    if (required.includes(spec.ports.key)) config[spec.ports.key] = {};
    if (spec.ports.default) config[spec.ports.default.name] = [];
  }
  return { id: newStepId(spec.type, taken, random), type: spec.type, config };
}

function structuredCloneJson(value: unknown): unknown {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
}

/* ------------------------------------------------------------------------- */
/* Tree operations                                                            */
/* ------------------------------------------------------------------------- */

export type Refusal =
  | "not_found"
  | "unknown_type"
  | "into_itself"
  | "lane_exists"
  | "lane_invalid"
  | "lane_fixed";

export type Outcome =
  | { ok: true; tree: WorkflowTree; removed: StepNode[] }
  | { ok: false; reason: Refusal };

function refuse(reason: Refusal): Outcome {
  return { ok: false, reason };
}

/** `tree` with the lane `ref` replaced by `fn` of it, or null. */
function mapLane(
  tree: WorkflowTree,
  ref: LaneRef,
  fn: (lane: LaneNode) => LaneNode,
): WorkflowTree | null {
  if (ref.parent === null) {
    const root = laneAt(tree, ROOT_LANE)!;
    return { ...tree, steps: fn(root).steps };
  }
  let hit = false;
  const next = mapStep(tree, ref.parent, (node) => {
    const lanes = node.lanes.map((lane) => {
      if (lane.port !== ref.port) return lane;
      hit = true;
      return fn(lane);
    });
    return { ...node, lanes };
  });
  return hit ? next : null;
}

/** `tree` with the step `id` replaced by `fn` of it, or null; only the path
 * to it is copied. */
export function mapStep(
  tree: WorkflowTree,
  id: string,
  fn: (node: StepNode) => StepNode,
): WorkflowTree | null {
  let hit = false;
  const go = (steps: StepNode[]): StepNode[] => {
    let changed = false;
    const out = steps.map((node) => {
      if (hit) return node;
      if (node.id === id) {
        hit = true;
        changed = true;
        return fn(node);
      }
      let laneChanged = false;
      const lanes = node.lanes.map((lane) => {
        if (hit) return lane;
        const inner = go(lane.steps);
        if (inner === lane.steps) return lane;
        laneChanged = true;
        return { ...lane, steps: inner };
      });
      if (!laneChanged) return node;
      changed = true;
      return { ...node, lanes };
    });
    return changed ? out : steps;
  };
  const steps = go(tree.steps);
  return hit ? { ...tree, steps } : null;
}

export function insertStep(
  tree: WorkflowTree,
  slot: Slot,
  node: StepNode,
): Outcome {
  const next = mapLane(tree, slot.lane, (lane) => {
    const index = Math.max(0, Math.min(slot.index, lane.steps.length));
    const steps = [
      ...lane.steps.slice(0, index),
      node,
      ...lane.steps.slice(index),
    ];
    return { ...lane, present: true, steps };
  });
  return next ? { ok: true, tree: next, removed: [] } : refuse("not_found");
}

function sameLane(a: LaneRef, b: LaneRef): boolean {
  return a.parent === b.parent && (a.parent === null || a.port === b.port);
}

/**
 * Move a step into `slot`. Refused for a step of an unknown type (the page
 * cannot tell which of its config's keys hold steps) and for any slot inside
 * the step's own subtree, which would put a step inside itself.
 */
export function moveStep(tree: WorkflowTree, id: string, slot: Slot): Outcome {
  const from = locate(tree, id);
  if (!from) return refuse("not_found");
  if (!from.node.known) return refuse("unknown_type");
  if (isInside(tree, id, slot.lane)) return refuse("into_itself");
  if (!laneAt(tree, slot.lane)) return refuse("not_found");
  let index = slot.index;
  if (sameLane(from.lane, slot.lane)) {
    if (index === from.index || index === from.index + 1) {
      return { ok: true, tree, removed: [] };
    }
    if (index > from.index) index -= 1;
  }
  const without = mapLane(tree, from.lane, (lane) => ({
    ...lane,
    steps: lane.steps.filter((_, i) => i !== from.index),
  }))!;
  return insertStep(without, { lane: slot.lane, index }, from.node);
}

/** Delete a step with everything under it, returning every step removed.
 * An unknown type is refused: its config may hold steps the page cannot see. */
export function deleteStep(tree: WorkflowTree, id: string): Outcome {
  const from = locate(tree, id);
  if (!from) return refuse("not_found");
  if (!from.node.known) return refuse("unknown_type");
  const next = mapLane(tree, from.lane, (lane) => ({
    ...lane,
    steps: lane.steps.filter((_, i) => i !== from.index),
  }))!;
  return { ok: true, tree: next, removed: subtree(from.node) };
}

/**
 * Add a lane to a step: an entry `name` of a keyed type's object (a `cases`
 * key of `logic.switch`, a `branches` name of `logic.parallel`), or a fixed
 * port the schema does not require (`max_reached` of `logic.loop`).
 */
export function addLane(
  tree: WorkflowTree,
  id: string,
  name: string,
  catalogue: Catalogue,
): Outcome {
  const at = locate(tree, id);
  if (!at) return refuse("not_found");
  const spec = catalogue.get(at.node.type);
  if (!at.node.known || !spec) return refuse("unknown_type");
  const trimmed = name.trim();
  if (trimmed === "") return refuse("lane_invalid");
  let lane: LaneNode;
  let position: number;
  if (spec.ports.kind === "keyed") {
    const port = `${spec.ports.key}.${trimmed}`;
    if (at.node.lanes.some((l) => l.port === port))
      return refuse("lane_exists");
    lane = {
      port,
      label: trimmed,
      kind: "keyed",
      present: true,
      removable: true,
      steps: [],
    };
    const firstOther = at.node.lanes.findIndex((l) => l.kind !== "keyed");
    position = firstOther === -1 ? at.node.lanes.length : firstOther;
  } else {
    const order = spec.ports.ports.map((p) => p.name);
    const port = spec.ports.ports.find((p) => p.name === trimmed);
    if (!port) return refuse("lane_invalid");
    if (at.node.lanes.some((l) => l.port === trimmed))
      return refuse("lane_exists");
    lane = {
      port: port.name,
      label: port.label_vi,
      kind: "fixed",
      present: true,
      removable: true,
      steps: [],
    };
    const after = at.node.lanes.findIndex(
      (l) =>
        l.kind !== "fixed" || order.indexOf(l.port) > order.indexOf(port.name),
    );
    position = after === -1 ? at.node.lanes.length : after;
  }
  const next = mapStep(tree, id, (node) => ({
    ...node,
    lanes: [
      ...node.lanes.slice(0, position),
      lane,
      ...node.lanes.slice(position),
    ],
  }))!;
  return { ok: true, tree: next, removed: [] };
}

/** The lanes "Thêm nhánh" can add to a fixed-port type: its ports not drawn. */
export function addableFixedPorts(
  node: StepNode,
  catalogue: Catalogue,
): PortSpec[] {
  const spec = catalogue.get(node.type);
  if (!node.known || !spec || spec.ports.kind !== "fixed") return [];
  return spec.ports.ports.filter(
    (p) => !node.lanes.some((l) => l.port === p.name),
  );
}

/** Remove a lane with its steps: a deletion like any other (R2.10, R2.11). */
export function removeLane(
  tree: WorkflowTree,
  id: string,
  port: string,
): Outcome {
  const at = locate(tree, id);
  if (!at) return refuse("not_found");
  if (!at.node.known) return refuse("unknown_type");
  const lane = at.node.lanes.find((l) => l.port === port);
  if (!lane) return refuse("not_found");
  if (!lane.removable) return refuse("lane_fixed");
  const next = mapStep(tree, id, (node) => ({
    ...node,
    lanes: node.lanes.filter((l) => l.port !== port),
  }))!;
  return { ok: true, tree: next, removed: lane.steps.flatMap(subtree) };
}

export type OnError = "fail" | "continue" | "route";

/**
 * Set a step's `on_error`. `route` opens an empty "Khi lỗi" lane; any other
 * value drops the lane, and its steps go as a deletion (R2.10, R2.11).
 */
export function setOnError(
  tree: WorkflowTree,
  id: string,
  value: OnError,
): Outcome {
  const at = locate(tree, id);
  if (!at) return refuse("not_found");
  if (!at.node.known) return refuse("unknown_type");
  const error = at.node.lanes.find((l) => l.kind === "error");
  const removed =
    value !== "route" && error ? error.steps.flatMap(subtree) : [];
  const next = mapStep(tree, id, (node) => {
    const rest: JsonObject = { ...node.rest, on_error: value };
    if (value === "route") {
      const lanes = error
        ? node.lanes
        : [
            ...node.lanes,
            {
              port: ERROR_LANE,
              label: "",
              kind: "error" as const,
              present: true,
              removable: false,
              steps: [],
            },
          ];
      return { ...node, rest, lanes };
    }
    delete rest.error_lane;
    return {
      ...node,
      rest,
      lanes: node.lanes.filter((l) => l.kind !== "error"),
    };
  })!;
  return { ok: true, tree: next, removed };
}

/**
 * Replace a step's own fields from the configuration Drawer: `config` is the
 * Form's keys (never a lane key, which stays as it is), the others are the
 * step's `retry`, `timeout_s` and the name the builder wrote (`description`). An `undefined` value removes the key, so a
 * field left empty stays absent.
 */
export function updateStepFields(
  tree: WorkflowTree,
  id: string,
  fields: {
    config?: JsonObject;
    retry?: unknown;
    timeout_s?: unknown;
    description?: unknown;
  },
  catalogue: Catalogue,
): Outcome {
  const at = locate(tree, id);
  if (!at) return refuse("not_found");
  const spec = catalogue.get(at.node.type);
  if (!at.node.known || !spec) return refuse("unknown_type");
  const next = mapStep(tree, id, (node) => {
    const rest: JsonObject = { ...node.rest };
    if (fields.config !== undefined) {
      const kept = isObject(rest.config) ? rest.config : {};
      const config: JsonObject = {};
      for (const key of laneKeys(spec))
        if (key in kept) config[key] = kept[key];
      for (const [key, value] of Object.entries(fields.config)) {
        if (value !== undefined) config[key] = value;
      }
      rest.config = config;
    }
    for (const key of ["retry", "timeout_s", "description"] as const) {
      if (!(key in fields)) continue;
      if (fields[key] === undefined) delete rest[key];
      else rest[key] = fields[key];
    }
    return { ...node, rest };
  })!;
  return { ok: true, tree: next, removed: [] };
}

/** A step's `config` less its lanes: what the Form edits. */
export function formConfig(node: StepNode, catalogue: Catalogue): JsonObject {
  const spec = catalogue.get(node.type);
  const config = isObject(node.rest.config) ? node.rest.config : {};
  if (!spec) return { ...config };
  const lanes = new Set(laneKeys(spec));
  return Object.fromEntries(
    Object.entries(config).filter(([key]) => !lanes.has(key)),
  );
}

/* ------------------------------------------------------------------------- */
/* Undo and redo of tree operations                                           */
/* ------------------------------------------------------------------------- */

export interface History<T> {
  past: T[];
  present: T;
  future: T[];
  /** Consecutive commits with the same tag (one field typed into) replace
   * the top entry instead of stacking one per keystroke. */
  tag: string | null;
}

export function history<T>(present: T): History<T> {
  return { past: [], present, future: [], tag: null };
}

export function commit<T>(
  h: History<T>,
  next: T,
  tag: string | null = null,
): History<T> {
  if (next === h.present) return h;
  if (tag !== null && tag === h.tag) {
    return { past: h.past, present: next, future: [], tag };
  }
  return { past: [...h.past, h.present], present: next, future: [], tag };
}

export function undo<T>(h: History<T>): History<T> {
  const previous = h.past[h.past.length - 1];
  if (previous === undefined) return h;
  return {
    past: h.past.slice(0, -1),
    present: previous,
    future: [h.present, ...h.future],
    tag: null,
  };
}

export function redo<T>(h: History<T>): History<T> {
  const [next, ...future] = h.future;
  if (next === undefined) return h;
  return { past: [...h.past, h.present], present: next, future, tag: null };
}

/* ------------------------------------------------------------------------- */
/* Keyboard order (R2.5)                                                      */
/* ------------------------------------------------------------------------- */

/** The stop of an empty lane's "Thêm Bước" slot. */
export function emptyLaneStop(lane: LaneRef): string {
  return `lane:${lane.parent ?? ""}:${lane.port}`;
}

export function parseEmptyLaneStop(stop: string): LaneRef | null {
  if (!stop.startsWith("lane:")) return null;
  const rest = stop.slice(5);
  const colon = rest.indexOf(":");
  const parent = rest.slice(0, colon);
  return { parent: parent === "" ? null : parent, port: rest.slice(colon + 1) };
}

interface StopEntry {
  lane: LaneRef;
  /** The lane's items: step ids, or the one empty-lane stop. */
  items: string[];
  index: number;
}

/** Each stop's lane and place, and each lane's items, in document order. */
function stopIndex(tree: WorkflowTree) {
  const at = new Map<string, StopEntry>();
  const lanesOf = new Map<string, LaneRef[]>();
  const add = (lane: LaneRef, steps: StepNode[]) => {
    const items =
      steps.length > 0 ? steps.map((s) => s.id) : [emptyLaneStop(lane)];
    items.forEach((stop, index) => at.set(stop, { lane, items, index }));
  };
  add(ROOT_LANE, tree.steps);
  walk(tree, (node) => {
    const refs = node.lanes.map((l) => ({ parent: node.id, port: l.port }));
    lanesOf.set(node.id, refs);
    node.lanes.forEach((lane, i) => add(refs[i]!, lane.steps));
  });
  const itemsOf = (ref: LaneRef) => {
    for (const entry of at.values()) {
      if (sameLane(entry.lane, ref)) return entry.items;
    }
    return [];
  };
  return { at, lanesOf, itemsOf };
}

export type Direction = "up" | "down" | "left" | "right";

/**
 * Where an arrow key goes from `stop` (R2.5), by the tree's structure: ↓ to
 * the next step of the same sequence, or from the card of a step with lanes
 * into the first step of its first lane, and from the last step of a lane out
 * to the step after the block; ↑ the other way, from the first step of a lane
 * to the card that holds it; ←/→ to the first step of the neighbouring lane
 * of the same holder. An empty lane's "Thêm Bước" slot is a stop like a step.
 * Null where there is nowhere to go.
 */
export function navigate(
  tree: WorkflowTree,
  stop: string,
  direction: Direction,
): string | null {
  const { at, lanesOf, itemsOf } = stopIndex(tree);
  const entry = at.get(stop);
  if (!entry) return null;
  const { lane, items, index } = entry;
  if (direction === "down") {
    const lanes = lanesOf.get(stop);
    if (lanes && lanes.length > 0) return itemsOf(lanes[0]!)[0] ?? null;
    let current: StopEntry | undefined = entry;
    while (current) {
      if (current.index + 1 < current.items.length)
        return current.items[current.index + 1]!;
      if (current.lane.parent === null) return null;
      current = at.get(current.lane.parent);
    }
    return null;
  }
  if (direction === "up") {
    if (index > 0) return items[index - 1]!;
    return lane.parent;
  }
  if (lane.parent === null) return null;
  const siblings = lanesOf.get(lane.parent) ?? [];
  const position = siblings.findIndex((s) => sameLane(s, lane));
  const target = siblings[position + (direction === "left" ? -1 : 1)];
  return target ? (itemsOf(target)[0] ?? null) : null;
}

/** Every stop, in document order: the first is where Tab enters. */
export function stopsInOrder(tree: WorkflowTree): string[] {
  const out: string[] = [];
  const go = (steps: StepNode[], lane: LaneRef) => {
    if (steps.length === 0) out.push(emptyLaneStop(lane));
    for (const node of steps) {
      out.push(node.id);
      for (const child of node.lanes)
        go(child.steps, { parent: node.id, port: child.port });
    }
  };
  go(tree.steps, ROOT_LANE);
  return out;
}

/* ------------------------------------------------------------------------- */
/* Comparing documents                                                        */
/* ------------------------------------------------------------------------- */

/** Two JSON values equal key for key, whatever the keys' order: whether a
 * save would change anything (the server's hash is the server's). */
export function sameJson(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a)) {
    return (
      Array.isArray(b) &&
      a.length === b.length &&
      a.every((x, i) => sameJson(x, b[i]))
    );
  }
  if (isObject(a) && isObject(b)) {
    const keys = Object.keys(a);
    return (
      keys.length === Object.keys(b).length &&
      keys.every((key) => key in b && sameJson(a[key], b[key]))
    );
  }
  return false;
}
