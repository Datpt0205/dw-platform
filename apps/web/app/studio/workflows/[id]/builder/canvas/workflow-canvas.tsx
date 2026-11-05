"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  BaseEdge,
  Handle,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  Button,
  Card,
  Dropdown,
  Flex,
  Popover,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  CompressOutlined,
  FieldTimeOutlined,
  HolderOutlined,
  MinusOutlined,
  MoreOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  RedoOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { CANVAS_ICONS, CANVAS_VOCABULARY } from "@dw/ui";
import type { StepGroup } from "../../../../../../lib/workflow-graph";
import { slotAt } from "../../../../../../lib/workflow-layout";
import type {
  CanvasLaneHead,
  CanvasShapes,
  CanvasSlot,
  Point,
} from "../../../../../../lib/workflow-shapes";
import type { CardView, MenuEntry, MenuKey } from "../builder-model";
import { bt } from "../messages";
import "./workflow-canvas.css";

/**
 * The workflow canvas (workflow-builder-ui R1.3, R1.4, R1.5, R1.8, R2.5,
 * R2.7, R2.9; ADR-0101 (Accepted) decisions 2, 3 and 5): the one place
 * `@xyflow/react` is imported, under the allowlist's
 * `app/studio/**\/canvas/**` glob. It draws the shapes `lib/workflow-layout.ts`
 * computed and positions nothing itself. The library draws the pane, the
 * viewport and the edges; antd draws every card, "+", lane head, menu,
 * Popover and zoom button. Nothing on it is dragged, connected, selected,
 * focused or deleted by the library: the app owns those. Focus moves between
 * antd Buttons inside the cards (roving: one Tab stop, `activeStop`); a drag is
 * the app's own pointer handling, dropped on a slot through
 * `screenToFlowPosition`. Loaded with `next/dynamic` and `ssr: false` by the
 * builder page.
 */

/** The vocabulary's token per group, as `var(...)`: every colour here is the
 * theme's (`CANVAS_VOCABULARY`, emitted as `--ant-canvas-*`). */
const GROUP_COLOUR: Record<StepGroup, string> = {
  trigger: "var(--ant-canvas-trigger)",
  ai: "var(--ant-canvas-ai)",
  data: "var(--ant-canvas-data)",
  logic: "var(--ant-canvas-logic)",
  human: "var(--ant-canvas-human)",
  tool: "var(--ant-canvas-tool)",
};
const ERROR_COLOUR = "var(--ant-canvas-error)";

/** Above this many cards only what is in view is drawn (ADR-0101 Amendments
 * 2026-11-04), and a focus target off screen is centred first. */
const CULL_FROM = 100;

/** The Vietnamese text of the library's hidden descriptions (R2.9, DO-57). */
const ARIA_LABELS = {
  "node.a11yDescription.default": bt("a11y.node"),
  "node.a11yDescription.keyboardDisabled": bt("a11y.node"),
  "node.a11yDescription.ariaLiveMessage": () => bt("a11y.live"),
  "edge.a11yDescription.default": bt("a11y.edge"),
  "handle.ariaLabel": bt("a11y.handle"),
};

export interface WorkflowCanvasProps {
  shapes: CanvasShapes;
  /** Each card's view, by step id. */
  views: ReadonlyMap<string, CardView>;
  /** Each lane head's label, by head id. */
  laneLabels?: ReadonlyMap<string, string>;
  /** Each slot's accessible name, by slot id. */
  slotLabels?: ReadonlyMap<string, string>;
  menus?: (id: string) => MenuEntry[];
  /** The one stop Tab reaches (roving focus, R2.5). */
  activeStop?: string | null;
  /** Move DOM focus to a stop; `seq` makes a repeat request a new one. */
  focusRequest?: { stop: string; seq: number } | null;
  onStopFocus?: (stop: string) => void;
  onOpenStep?: (id: string) => void;
  openMenu?: string | null;
  onOpenMenu?: (id: string | null) => void;
  onMenu?: (id: string, key: MenuKey) => void;
  openSlot?: string | null;
  onOpenSlot?: (id: string | null) => void;
  /** The palette shown in a "+"'s Popover. */
  palette?: ReactNode;
  /** A drag from the palette or a card's handle is under way. */
  dragging?: boolean;
  acceptSlot?: (slot: CanvasSlot) => boolean;
  onDrop?: (slot: CanvasSlot | null) => void;
  onStartMove?: (id: string) => void;
}

type Actions = Omit<WorkflowCanvasProps, "shapes"> & {
  hoverSlot: string | null;
};

const CanvasActions = createContext<Actions>({
  views: new Map(),
  hoverSlot: null,
});

const { width: CARD_WIDTH, height: CARD_HEIGHT } = CANVAS_VOCABULARY.card;

function Anchors() {
  return (
    <>
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </>
  );
}

function StepBadges({ view }: { view: CardView }) {
  const badges: ReactNode[] = [];
  if (view.retry !== null) {
    badges.push(
      <Tag key="retry" icon={<RedoOutlined aria-hidden />}>
        {bt("card.retry", { n: view.retry })}
      </Tag>,
    );
  }
  if (view.timeout !== null) {
    badges.push(
      <Tag key="timeout" icon={<FieldTimeOutlined aria-hidden />}>
        {bt("card.timeout", { n: view.timeout })}
      </Tag>,
    );
  }
  if (view.onError !== null) {
    badges.push(
      <Tag
        key="error"
        icon={<WarningOutlined aria-hidden />}
        style={{ color: ERROR_COLOUR }}
      >
        {bt("card.onError", { what: bt(`onError.${view.onError}`) })}
      </Tag>,
    );
  }
  return (
    <Flex gap={4} className="overflow-hidden">
      {badges}
    </Flex>
  );
}

type StepNodeType = Node<{ id: string }, "step">;

/** A step's body: an antd Card of fixed size (R1.8). Its name is the focus
 * target and opens the configuration; the menu and the drag handle sit
 * beside it, outside the Tab order (Shift+F10 opens the menu). */
function StepCard({ data }: NodeProps<StepNodeType>) {
  const actions = useContext(CanvasActions);
  const view = actions.views.get(data.id);
  if (!view) return null;
  const Icon = view.known ? CANVAS_ICONS[view.group] : QuestionCircleOutlined;
  const entries = actions.menus?.(view.id) ?? [];
  const typeLine = view.known
    ? [view.typeLabel, view.summary].filter(Boolean).join(" · ")
    : bt("card.unknown");
  return (
    <>
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <Card
        size="small"
        style={{ width: CARD_WIDTH, height: CARD_HEIGHT }}
        styles={{ body: { padding: 8 } }}
      >
        <Flex vertical gap={4}>
          <Flex align="center" gap={4}>
            <span
              aria-hidden
              className="flex items-center justify-center"
              style={{
                color: view.known ? GROUP_COLOUR[view.group] : undefined,
              }}
            >
              <Icon />
            </span>
            <Button
              type="text"
              className="min-w-0 flex-1 justify-start"
              data-stop={view.id}
              tabIndex={actions.activeStop === view.id ? 0 : -1}
              aria-label={`${view.name}, ${view.known ? view.typeLabel : bt("card.unknown")}`}
              onFocus={() => actions.onStopFocus?.(view.id)}
              onClick={() => actions.onOpenStep?.(view.id)}
            >
              <Typography.Text strong ellipsis={{ tooltip: view.name }}>
                {view.name}
              </Typography.Text>
            </Button>
            {view.known && (
              <Tooltip title={bt("card.drag")}>
                <Button
                  type="text"
                  size="small"
                  tabIndex={-1}
                  aria-label={bt("card.drag")}
                  icon={<HolderOutlined aria-hidden />}
                  className="cursor-grab"
                  onPointerDown={(event) => {
                    event.preventDefault();
                    actions.onStartMove?.(view.id);
                  }}
                />
              </Tooltip>
            )}
            <Dropdown
              trigger={["click"]}
              open={actions.openMenu === view.id}
              onOpenChange={(open) =>
                actions.onOpenMenu?.(open ? view.id : null)
              }
              menu={{
                items: entries.map(({ key, label, danger }) => ({
                  key,
                  label,
                  danger,
                })),
                onClick: ({ key }) => {
                  actions.onOpenMenu?.(null);
                  actions.onMenu?.(view.id, key as MenuKey);
                },
              }}
            >
              <Button
                type="text"
                size="small"
                tabIndex={-1}
                aria-label={`${bt("card.menu")} «${view.name}»`}
                icon={<MoreOutlined aria-hidden />}
              />
            </Dropdown>
          </Flex>
          <Typography.Text type="secondary" ellipsis={{ tooltip: typeLine }}>
            {typeLine}
          </Typography.Text>
          <StepBadges view={view} />
        </Flex>
      </Card>
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </>
  );
}

type SlotNodeType = Node<{ slot: CanvasSlot }, "slot">;

/** A "+" on a connection, always shown and at least 24 px (R1.5), or the
 * dashed "Thêm Bước" of an empty lane, which is a keyboard stop. Both open
 * the palette in a Popover. */
function SlotButton({ data }: NodeProps<SlotNodeType>) {
  const actions = useContext(CanvasActions);
  const { slot } = data;
  const label = actions.slotLabels?.get(slot.id) ?? bt("slot.emptyText");
  const lit = actions.dragging && (actions.acceptSlot?.(slot) ?? true);
  const hovered = actions.hoverSlot === slot.id;
  const button = slot.empty ? (
    <Button
      type={lit ? "primary" : "dashed"}
      ghost={lit && !hovered}
      data-stop={slot.id}
      data-slot={slot.id}
      tabIndex={actions.activeStop === slot.id ? 0 : -1}
      aria-label={label}
      icon={<PlusOutlined aria-hidden />}
      style={{ width: slot.width, height: slot.height }}
      onFocus={() => actions.onStopFocus?.(slot.id)}
    >
      {bt("slot.emptyText")}
    </Button>
  ) : (
    <Button
      shape="circle"
      type={lit ? "primary" : "default"}
      ghost={lit && !hovered}
      data-slot={slot.id}
      tabIndex={-1}
      aria-label={label}
      icon={<PlusOutlined aria-hidden />}
      style={{ width: slot.width, height: slot.height, minWidth: slot.width }}
    />
  );
  return (
    <>
      <Anchors />
      <Popover
        trigger="click"
        open={actions.openSlot === slot.id}
        onOpenChange={(open) => actions.onOpenSlot?.(open ? slot.id : null)}
        content={actions.palette}
        destroyOnHidden
      >
        {button}
      </Popover>
    </>
  );
}

type HeadNodeType = Node<{ head: CanvasLaneHead }, "head">;

/** A lane's head: its label in a Tag (ticket 04 draws its frame). */
function LaneHead({ data }: NodeProps<HeadNodeType>) {
  const actions = useContext(CanvasActions);
  const label = actions.laneLabels?.get(data.head.id) ?? data.head.port;
  const error = data.head.port === "error_lane";
  return (
    <>
      <Anchors />
      <Flex
        justify="center"
        style={{ width: data.head.width, height: data.head.height }}
      >
        <Tag
          icon={error ? <WarningOutlined aria-hidden /> : undefined}
          style={error ? { color: ERROR_COLOUR } : undefined}
          className="max-w-full"
        >
          <Typography.Text
            ellipsis={{ tooltip: label }}
            style={{ color: "inherit" }}
          >
            {label}
          </Typography.Text>
        </Tag>
      </Flex>
    </>
  );
}

function JoinPoint() {
  return (
    <>
      <Anchors />
      <span className="block h-px w-px" />
    </>
  );
}

const NODE_TYPES = {
  step: StepCard,
  slot: SlotButton,
  head: LaneHead,
  join: JoinPoint,
};

type PathEdgeType = Edge<{ points: Point[]; dashed: boolean }, "path">;

/** A connection along the layout's polyline, not the library's routing. */
function PathEdge({ data, style }: EdgeProps<PathEdgeType>) {
  if (!data) return null;
  const d = data.points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`)
    .join(" ");
  return (
    <BaseEdge
      path={d}
      style={
        data.dashed
          ? { ...style, strokeDasharray: CANVAS_VOCABULARY.edge.dash }
          : style
      }
    />
  );
}

const EDGE_TYPES = { path: PathEdge };

/** Zoom in, zoom out and fit: antd Buttons in a React Flow Panel, in place of
 * the library's `Controls`. Bottom right: at the top right they covered cards
 * at `md` in the spike, and the badge holds the bottom left. */
function ZoomButtons() {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  const buttons = [
    { label: "Phóng to", icon: <PlusOutlined />, run: () => zoomIn() },
    { label: "Thu nhỏ", icon: <MinusOutlined />, run: () => zoomOut() },
    { label: "Vừa khung", icon: <CompressOutlined />, run: () => fitView() },
  ];
  return (
    <Panel position="bottom-right">
      <Flex vertical gap="small">
        {buttons.map(({ label, icon, run }) => (
          <Tooltip key={label} title={label} placement="left">
            <Button aria-label={label} icon={icon} onClick={run} />
          </Tooltip>
        ))}
      </Flex>
    </Panel>
  );
}

/** `CanvasShapes` as the library's nodes and edges. */
export function toFlow(shapes: CanvasShapes): {
  nodes: Node[];
  edges: PathEdgeType[];
} {
  const nodes: Node[] = [
    ...shapes.cards.map((card) => ({
      id: card.id,
      type: "step",
      position: { x: card.x, y: card.y },
      data: { id: card.id },
      width: card.width,
      height: card.height,
    })),
    ...shapes.slots.map((slot) => ({
      id: slot.id,
      type: "slot",
      position: { x: slot.x, y: slot.y },
      data: { slot },
      width: slot.width,
      height: slot.height,
    })),
    ...shapes.laneHeads.map((head) => ({
      id: head.id,
      type: "head",
      position: { x: head.x, y: head.y },
      data: { head },
      width: head.width,
      height: head.height,
    })),
    ...shapes.joins.map((join) => ({
      id: join.id,
      type: "join",
      position: { x: join.x, y: join.y },
      data: {},
      width: 1,
      height: 1,
    })),
  ];
  return {
    nodes,
    edges: shapes.connections.map((connection) => ({
      id: connection.id,
      type: "path",
      source: connection.from,
      target: connection.to,
      data: { points: connection.points, dashed: connection.dashed },
      // No English "Edge from … to …" (R2.9): a connection carries no name of
      // its own, the cards and "+" it joins do. 12.12.0 types the field as a
      // string, but its edge wrapper reads `null` as "no label" and anything
      // falsy else as the English default (dist/esm/index.mjs, EdgeWrapper).
      ariaLabel: null as unknown as undefined,
    })),
  };
}

/** Where a stop is drawn, to centre it before focusing it. */
function stopCentre(shapes: CanvasShapes, stop: string): Point | null {
  const shape =
    shapes.cards.find((c) => c.id === stop) ??
    shapes.slots.find((s) => s.id === stop);
  return shape
    ? { x: shape.x + shape.width / 2, y: shape.y + shape.height / 2 }
    : null;
}

function findStop(root: HTMLElement | null, stop: string): HTMLElement | null {
  if (!root) return null;
  for (const el of root.querySelectorAll<HTMLElement>("[data-stop]")) {
    if (el.dataset.stop === stop) return el;
  }
  return null;
}

function Flow({ shapes, ...props }: WorkflowCanvasProps) {
  const { nodes, edges } = useMemo(() => toFlow(shapes), [shapes]);
  const flow = useReactFlow();
  const root = useRef<HTMLDivElement>(null);
  const [hoverSlot, setHoverSlot] = useState<string | null>(null);
  const cull = shapes.cards.length > CULL_FROM;
  const { dragging, acceptSlot, onDrop, focusRequest } = props;

  // A drag of the app's own: the slot under the pointer lights up, and the
  // release drops there, or nowhere (R1.4).
  useEffect(() => {
    if (!dragging) return;
    const under = (event: PointerEvent): CanvasSlot | null => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target || !root.current?.contains(target)) return null;
      const point = flow.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      return slotAt(shapes, point, acceptSlot);
    };
    const move = (event: PointerEvent) =>
      setHoverSlot(under(event)?.id ?? null);
    const up = (event: PointerEvent) => {
      setHoverSlot(null);
      onDrop?.(under(event));
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [dragging, acceptSlot, onDrop, flow, shapes]);

  useEffect(() => {
    if (!focusRequest) return;
    const now = findStop(root.current, focusRequest.stop);
    if (now) {
      now.focus();
      return;
    }
    const centre = stopCentre(shapes, focusRequest.stop);
    if (!centre) return;
    void flow.setCenter(centre.x, centre.y, { zoom: flow.getZoom() });
    const timer = window.setTimeout(
      () => findStop(root.current, focusRequest.stop)?.focus(),
      50,
    );
    return () => window.clearTimeout(timer);
  }, [focusRequest, flow, shapes]);

  const actions = useMemo(() => ({ ...props, hoverSlot }), [props, hoverSlot]);

  return (
    <CanvasActions.Provider value={actions}>
      <div
        ref={root}
        className="h-full w-full"
        aria-label={bt("canvas.label")}
        role="group"
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          edgeTypes={EDGE_TYPES}
          nodesDraggable={false}
          nodesConnectable={false}
          nodesFocusable={false}
          edgesFocusable={false}
          elementsSelectable={false}
          deleteKeyCode={null}
          panActivationKeyCode={null}
          selectionKeyCode={null}
          multiSelectionKeyCode={null}
          zoomActivationKeyCode={null}
          ariaLabelConfig={ARIA_LABELS}
          onlyRenderVisibleElements={cull}
          defaultEdgeOptions={{
            style: { strokeWidth: CANVAS_VOCABULARY.edge.width },
          }}
          attributionPosition="bottom-left"
          fitView
          fitViewOptions={{ maxZoom: 1 }}
          minZoom={0.2}
        >
          <ZoomButtons />
        </ReactFlow>
      </div>
    </CanvasActions.Provider>
  );
}

export default function WorkflowCanvas(props: WorkflowCanvasProps) {
  return (
    <ReactFlowProvider>
      <Flow {...props} />
    </ReactFlowProvider>
  );
}
