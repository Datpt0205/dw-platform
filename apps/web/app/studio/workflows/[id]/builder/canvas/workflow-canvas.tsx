"use client";

import { useMemo } from "react";
import {
  Handle,
  Panel,
  Position,
  ReactFlow,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { Button, Card, Flex, Tooltip, Typography } from "antd";
import {
  CompressOutlined,
  MinusOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { CANVAS_VOCABULARY } from "@dw/ui";
import type { CanvasShapes } from "../../../../../../lib/workflow-shapes";
import "./workflow-canvas.css";

/**
 * The workflow canvas (workflow-builder-ui R1.3; ADR-0101 (Accepted)
 * decisions 2, 3 and 5): the one place `@xyflow/react` is imported, under the
 * allowlist's `app/studio/**\/canvas/**` glob. It draws the shapes it is given
 * and computes nothing: positions come from `lib/workflow-layout.ts`
 * (workflow-builder-ui/02) as `CanvasShapes`. The library draws the pane, the
 * viewport and the edges; antd draws every step body and the zoom buttons.
 * Nothing on it is dragged, connected, focused or deleted by the library: the
 * app owns those (R1.4, R2.5, R2.7). Loaded with `next/dynamic` and
 * `ssr: false` from a client component outside this folder (ticket 02), which
 * has no `page.tsx`, so this is not a route.
 */

interface StepData extends Record<string, unknown> {
  description: string;
}

type StepNode = Node<StepData, "step">;

const { width, height } = CANVAS_VOCABULARY.card;

/** A step's body: an antd Card with the builder's name for the step. The
 * handles are anchors for edges only, never a place to start a connection. */
function StepCard({ data }: NodeProps<StepNode>) {
  return (
    <>
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <Card size="small" style={{ width, height }}>
        <Typography.Text ellipsis={{ tooltip: data.description }}>
          {data.description}
        </Typography.Text>
      </Card>
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </>
  );
}

const NODE_TYPES = { step: StepCard };

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
  nodes: StepNode[];
  edges: Edge[];
} {
  return {
    nodes: shapes.cards.map((card) => ({
      id: card.id,
      type: "step",
      position: { x: card.x, y: card.y },
      data: { description: card.description },
      width,
      height,
    })),
    edges: shapes.connections.map((connection) => ({
      id: connection.id,
      source: connection.from,
      target: connection.to,
      // No English "Edge from … to …" (R2.9): unnamed until ticket 02 names
      // edges from the message keys. 12.12.0 types the field as a string, but
      // its edge wrapper reads `null` as "no label" and anything falsy else
      // as the English default (dist/esm/index.mjs, EdgeWrapper).
      ariaLabel: null as unknown as undefined,
    })),
  };
}

export interface WorkflowCanvasProps {
  shapes: CanvasShapes;
}

export default function WorkflowCanvas({ shapes }: WorkflowCanvasProps) {
  const { nodes, edges } = useMemo(() => toFlow(shapes), [shapes]);
  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      nodesDraggable={false}
      nodesConnectable={false}
      nodesFocusable={false}
      edgesFocusable={false}
      deleteKeyCode={null}
      panActivationKeyCode={null}
      selectionKeyCode={null}
      multiSelectionKeyCode={null}
      defaultEdgeOptions={{
        style: { strokeWidth: CANVAS_VOCABULARY.edge.width },
      }}
      attributionPosition="bottom-left"
      fitView
    >
      <ZoomButtons />
    </ReactFlow>
  );
}
