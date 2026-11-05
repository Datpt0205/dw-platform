import { render } from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

/**
 * What the canvas hands the library (ADR-0101 (Accepted) decision 3;
 * workflow-builder-ui R1.3, R2.9). The handles carry `isConnectable={false}`
 * themselves and jsdom draws no edge (it measures no handle), so the DOM
 * cannot show `nodesConnectable` or an edge's label: the props are read where
 * they are passed, a second layer beside `workflow-canvas.test.tsx`'s DOM
 * checks (failure-modes #3, a rule held twice needs a test per layer).
 */

const seen: { props?: Record<string, unknown> } = {};

vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  function ReactFlow(props: ComponentProps<typeof actual.ReactFlow>) {
    seen.props = props as Record<string, unknown>;
    return <actual.ReactFlow {...props} />;
  }
  return { ...actual, ReactFlow };
});

const { default: WorkflowCanvas } = await import("../workflow-canvas");
const { SHAPES, VIEWS } = await import("./canvas-fixture");

beforeAll(() => {
  globalThis.DOMMatrixReadOnly ??= class {
    m22 = 1;
  } as unknown as typeof DOMMatrixReadOnly;
});

function draw() {
  render(
    <div style={{ width: 800, height: 600 }}>
      <WorkflowCanvas shapes={SHAPES} views={VIEWS} />
    </div>,
  );
  return seen.props!;
}

describe("the library's own interaction stays off (decision 3)", () => {
  it("nothing is dragged, connected or focused by the library", () => {
    const props = draw();
    expect(props.nodesDraggable).toBe(false);
    expect(props.nodesConnectable).toBe(false);
    expect(props.nodesFocusable).toBe(false);
    expect(props.edgesFocusable).toBe(false);
  });

  it("no library key deletes, pans or selects", () => {
    const props = draw();
    for (const key of [
      "deleteKeyCode",
      "panActivationKeyCode",
      "selectionKeyCode",
      "multiSelectionKeyCode",
    ]) {
      expect(props[key], key).toBeNull();
    }
  });

  it("every edge is unnamed rather than the English default (R2.9)", () => {
    const edges = draw().edges as { ariaLabel?: unknown }[];
    expect(edges).toHaveLength(SHAPES.connections.length);
    expect(edges.length).toBeGreaterThan(0);
    for (const edge of edges) expect(edge.ariaLabel).toBeNull();
  });
});
