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
  EdgeLabelRenderer,
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
  ArrowsAltOutlined,
  CompressOutlined,
  FieldTimeOutlined,
  HolderOutlined,
  MinusOutlined,
  MoreOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  RedoOutlined,
  ShrinkOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { CANVAS_ICONS, CANVAS_MARKS, CANVAS_VOCABULARY } from "@dw/ui";
import type { StepGroup } from "../../../../../../lib/workflow-graph";
import { slotAt } from "../../../../../../lib/workflow-layout";
import type {
  CanvasFrame,
  CanvasJoin,
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

/** What the validator said about a step: its own problems, and how many lie
 * on steps inside it, which a folded frame shows (R1.7, R3.4). */
export interface CardIssues {
  own: string[];
  inside: number;
}

export interface WorkflowCanvasProps {
  shapes: CanvasShapes;
  /** Each card's view, by step id. */
  views: ReadonlyMap<string, CardView>;
  /** Each lane head's label, by head id. */
  laneLabels?: ReadonlyMap<string, string>;
  /** A lane head's menu ("Bỏ nhánh"), by head id. */
  laneMenus?: (head: CanvasLaneHead) => MenuEntry[];
  onLaneMenu?: (head: CanvasLaneHead, key: MenuKey) => void;
  /** The validator's problems, by step id. */
  issues?: ReadonlyMap<string, CardIssues>;
  /** Fold or open a frame (R1.7); absent on a read-only canvas, where every
   * frame is open and none folds. */
  onToggleFrame?: (id: string) => void;
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

const MarkIcon = {
  subworkflow: CANVAS_MARKS.subworkflow,
  rule: CANVAS_ICONS.human,
} as const;

/** The card's badges: its marks ("Quy trình con", "Cần cả 3 người duyệt"),
 * the validator's "N lỗi", then retry, timeout and Khi lỗi; each a word with
 * its icon (R1.8, BU14). A folded frame counts the problems inside it. */
function StepBadges({
  view,
  issues,
  folded,
}: {
  view: CardView;
  issues: CardIssues | undefined;
  folded: boolean;
}) {
  const badges: ReactNode[] = [];
  for (const mark of view.marks) {
    const Icon = MarkIcon[mark.key];
    badges.push(
      <Tag key={mark.key} icon={<Icon aria-hidden />}>
        {mark.text}
      </Tag>,
    );
  }
  const own = issues?.own ?? [];
  const inside = folded ? (issues?.inside ?? 0) : 0;
  if (own.length + inside > 0) {
    const lines = [
      ...own,
      ...(inside > 0 ? [bt("card.issuesInside", { n: inside })] : []),
    ];
    badges.push(
      <Tooltip key="issues" title={lines.join(" · ")}>
        <Tag
          icon={<WarningOutlined aria-hidden />}
          style={{ color: ERROR_COLOUR }}
        >
          {bt("card.issues", { n: own.length + inside })}
        </Tag>
      </Tooltip>,
    );
  }
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

type StepNodeType = Node<{ id: string; folded: boolean }, "step">;

/** A step's body: an antd Card of fixed size (R1.8). Its name is the focus
 * target and opens the configuration; the menu, a frame's fold toggle and
 * the drag handle sit beside it, outside the Tab order (Shift+F10 opens the
 * menu, which folds and opens a frame too). A frame's card heads its frame,
 * and is what a folded frame is drawn as (R1.7). */
function StepCard({ data }: NodeProps<StepNodeType>) {
  const actions = useContext(CanvasActions);
  const view = actions.views.get(data.id);
  if (!view) return null;
  const Icon = view.known ? CANVAS_ICONS[view.group] : QuestionCircleOutlined;
  const entries = actions.menus?.(view.id) ?? [];
  const typeLine = !view.known
    ? bt("card.unknown")
    : (view.title ??
      [view.typeLabel, view.summary].filter(Boolean).join(" · "));
  const toggle =
    view.frame && actions.onToggleFrame
      ? bt(data.folded ? "card.unfold" : "card.fold", { name: view.name })
      : null;
  const WaitIcon = CANVAS_MARKS.wait;
  return (
    <>
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <Card
        size="small"
        style={{ width: CARD_WIDTH, height: CARD_HEIGHT }}
        styles={{ body: { padding: 8 } }}
      >
        <Flex vertical gap={view.detail ? 2 : 4}>
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
              aria-label={`${view.name}, ${view.known ? view.typeLabel : bt("card.unknown")}${data.folded ? `, ${bt("card.foldedState")}` : ""}`}
              onFocus={() => actions.onStopFocus?.(view.id)}
              onClick={() => actions.onOpenStep?.(view.id)}
            >
              <Typography.Text strong ellipsis={{ tooltip: view.name }}>
                {view.name}
              </Typography.Text>
            </Button>
            {toggle && (
              <Tooltip title={toggle}>
                <Button
                  type="text"
                  size="small"
                  tabIndex={-1}
                  aria-label={toggle}
                  data-frame-toggle={view.id}
                  icon={
                    data.folded ? (
                      <ArrowsAltOutlined aria-hidden />
                    ) : (
                      <ShrinkOutlined aria-hidden />
                    )
                  }
                  onClick={() => actions.onToggleFrame?.(view.id)}
                />
              </Tooltip>
            )}
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
          {view.detail && (
            <Typography.Text
              ellipsis={{ tooltip: view.detail.text }}
              style={{ fontSize: "var(--ant-font-size-sm)" }}
            >
              {view.detail.wait && <WaitIcon aria-hidden />} {view.detail.text}
            </Typography.Text>
          )}
          <StepBadges
            view={view}
            issues={actions.issues?.get(view.id)}
            folded={data.folded}
          />
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

/** A lane's head: its label in a Tag, the words the outline reads too (a
 * `cases` key, "Khác", "Duyệt", a `branches` name, "Đã đủ N lần", "Khi
 * lỗi"), with a "…" menu where the lane comes off ("Bỏ nhánh"). */
function LaneHead({ data }: NodeProps<HeadNodeType>) {
  const actions = useContext(CanvasActions);
  const { head } = data;
  const label = actions.laneLabels?.get(head.id) ?? head.port;
  const error = head.port === "error_lane";
  const entries = actions.laneMenus?.(head) ?? [];
  const open = actions.openMenu === head.id;
  return (
    <>
      <Anchors />
      <Flex
        justify="center"
        align="center"
        gap={2}
        style={{ width: head.width, height: head.height }}
      >
        <Tag
          icon={error ? <WarningOutlined aria-hidden /> : undefined}
          style={error ? { color: ERROR_COLOUR } : undefined}
          className="min-w-0"
          data-lane-head={head.id}
        >
          <Typography.Text
            ellipsis={{ tooltip: label }}
            style={{ color: "inherit" }}
          >
            {label}
          </Typography.Text>
        </Tag>
        {entries.length > 0 && (
          <Dropdown
            trigger={["click"]}
            open={open}
            onOpenChange={(next) => actions.onOpenMenu?.(next ? head.id : null)}
            menu={{
              items: entries.map(({ key, label: text, danger }) => ({
                key,
                label: text,
                danger,
              })),
              onClick: ({ key }) => {
                actions.onOpenMenu?.(null);
                actions.onLaneMenu?.(head, key as MenuKey);
              },
            }}
          >
            <Button
              type="text"
              size="small"
              tabIndex={-1}
              aria-label={bt("lane.menu", { lane: label })}
              icon={<MoreOutlined aria-hidden />}
            />
          </Dropdown>
        )}
      </Flex>
    </>
  );
}

type FrameNodeType = Node<{ frame: CanvasFrame }, "frame">;

/** A frame's outline behind its card and lanes: drawn only, never pressed;
 * its card heads it and carries its words. */
function FrameBox({ data }: NodeProps<FrameNodeType>) {
  return (
    <div
      aria-hidden
      data-frame={data.frame.step}
      data-frame-kind={data.frame.kind}
      style={{
        width: data.frame.width,
        height: data.frame.height,
        border: "1px solid var(--ant-color-border)",
        borderRadius: "var(--ant-border-radius-lg)",
        background: "var(--ant-color-fill-quaternary)",
        pointerEvents: "none",
      }}
    />
  );
}

type JoinNodeType = Node<{ join: CanvasJoin }, "join">;

/** Where flow meets again: a point, or a parallel frame's Điểm nối, a bar
 * across its lanes saying "Chờ tất cả nhánh xong". */
function JoinPoint({ data }: NodeProps<JoinNodeType>) {
  const { join } = data;
  if (join.kind !== "bar") {
    return (
      <>
        <Anchors />
        <span className="block h-px w-px" data-join={join.id} />
      </>
    );
  }
  const WaitIcon = CANVAS_MARKS.wait;
  return (
    <>
      <Anchors />
      <Flex
        align="center"
        justify="center"
        gap={4}
        data-join={join.id}
        style={{
          width: join.width,
          height: join.height,
          border: "1px solid var(--ant-color-border)",
          borderRadius: "var(--ant-border-radius)",
          background: "var(--ant-color-bg-container)",
        }}
      >
        <WaitIcon aria-hidden />
        <Typography.Text>{bt("frame.bar")}</Typography.Text>
      </Flex>
    </>
  );
}

const NODE_TYPES = {
  frame: FrameBox,
  step: StepCard,
  slot: SlotButton,
  head: LaneHead,
  join: JoinPoint,
};

type PathEdgeType = Edge<
  {
    points: Point[];
    dashed: boolean;
    arrow: boolean;
    label: "repeat" | null;
    labelAt: Point | null;
  },
  "path"
>;

/** An arrow head at the end of a polyline, along its last segment. */
export function arrowHead(points: Point[], size = 6): string | null {
  const end = points[points.length - 1];
  const from = points[points.length - 2];
  if (!end || !from) return null;
  const dx = end.x - from.x;
  const dy = end.y - from.y;
  const length = Math.hypot(dx, dy);
  if (length === 0) return null;
  const ux = dx / length;
  const uy = dy / length;
  const bx = end.x - ux * size;
  const by = end.y - uy * size;
  const px = -uy * (size * 0.7);
  const py = ux * (size * 0.7);
  const r = (v: number) => Math.round(v * 10) / 10;
  return `M${r(bx + px)},${r(by + py)} L${end.x},${end.y} L${r(bx - px)},${r(by - py)}`;
}

/** A connection along the layout's polyline, not the library's routing: an
 * arrow head where it climbs back or leaves a loop, and the loop's "Lặp
 * lại" label in antd. */
function PathEdge({ data, style }: EdgeProps<PathEdgeType>) {
  if (!data) return null;
  const d = data.points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`)
    .join(" ");
  const head = data.arrow ? arrowHead(data.points) : null;
  const RepeatIcon = CANVAS_MARKS.repeat;
  return (
    <>
      <BaseEdge
        path={d}
        style={
          data.dashed
            ? { ...style, strokeDasharray: CANVAS_VOCABULARY.edge.dash }
            : style
        }
      />
      {head && (
        <path d={head} className="react-flow__edge-path" style={style} />
      )}
      {data.label === "repeat" && data.labelAt && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan absolute"
            style={{
              transform: `translate(-50%, -50%) translate(${data.labelAt.x}px, ${data.labelAt.y}px)`,
            }}
          >
            <Tag icon={<RepeatIcon aria-hidden />}>{bt("frame.repeat")}</Tag>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
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
    // First, so every card and lane is drawn over the frame around it.
    ...shapes.frames.map((frame) => ({
      id: frame.id,
      type: "frame",
      position: { x: frame.x, y: frame.y },
      data: { frame },
      width: frame.width,
      height: frame.height,
      style: { pointerEvents: "none" as const },
    })),
    ...shapes.cards.map((card) => ({
      id: card.id,
      type: "step",
      position: { x: card.x, y: card.y },
      data: { id: card.id, folded: card.folded },
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
      data: { join },
      width: Math.max(1, join.width),
      height: Math.max(1, join.height),
    })),
  ];
  return {
    nodes,
    edges: shapes.connections.map((connection) => ({
      id: connection.id,
      type: "path",
      source: connection.from,
      target: connection.to,
      data: {
        points: connection.points,
        dashed: connection.dashed,
        arrow: connection.arrow,
        label: connection.label,
        labelAt: connection.labelAt,
      },
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
