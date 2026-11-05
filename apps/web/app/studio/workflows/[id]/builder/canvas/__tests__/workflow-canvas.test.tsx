import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { render } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import {
  globMatches,
  sources,
} from "../../../../../../../lib/__tests__/source-tree";
import WorkflowCanvas from "../workflow-canvas";
import { SHAPES, VIEWS } from "./canvas-fixture";

/**
 * The canvas draws what it is given and lets the library do nothing a builder
 * could mistake for editing (workflow-builder-ui R1.3; ADR-0101 (Accepted)
 * decisions 2, 3 and 5): every step body is an antd Card, none of the
 * library's own panels is drawn, the badge sits at the bottom left, and no
 * node is draggable, focusable or connectable. The library's own keys
 * (Backspace, Space, Shift) are R2.7, checked in a browser by ticket 02.
 */

const WEB = resolve(__dirname, "../../../../../../..");
const HERE = "app/studio/workflows/[id]/builder/canvas";

beforeAll(() => {
  // jsdom has no DOMMatrixReadOnly; the library reads the viewport's
  // transform through it. Identity is enough for what this test asserts.
  globalThis.DOMMatrixReadOnly ??= class {
    m22 = 1;
    constructor() {}
  } as unknown as typeof DOMMatrixReadOnly;
});

function draw(): HTMLElement {
  const { container } = render(
    <div style={{ width: 800, height: 600 }}>
      <WorkflowCanvas shapes={SHAPES} views={VIEWS} />
    </div>,
  );
  return container;
}

describe("the workflow canvas (R1.3)", () => {
  it("draws each step body as an antd Card carrying its description", () => {
    const view = draw();
    const nodes = [...view.querySelectorAll(".react-flow__node-step")];
    expect(nodes).toHaveLength(2);
    for (const [i, node] of nodes.entries()) {
      const card = node.querySelector(".ant-card");
      expect(card).not.toBeNull();
      expect(card?.textContent).toContain(VIEWS.get(SHAPES.cards[i]!.id)!.name);
    }
  });

  it("draws none of the library's own panels", () => {
    const view = draw();
    for (const name of ["minimap", "controls", "node-toolbar"]) {
      expect(view.querySelector(`.react-flow__${name}`)).toBeNull();
    }
  });

  it("keeps the badge, at the bottom left", () => {
    const badge = draw().querySelector(".react-flow__attribution");
    expect(badge).not.toBeNull();
    expect(badge?.closest(".react-flow__panel")?.classList).toContain("bottom");
    expect(badge?.closest(".react-flow__panel")?.classList).toContain("left");
  });

  it("leaves no node draggable or focusable, and no handle connectable", () => {
    const view = draw();
    const nodes = [...view.querySelectorAll(".react-flow__node")];
    expect(nodes.length).toBeGreaterThan(0);
    for (const node of nodes) {
      expect(node.classList).not.toContain("draggable");
      expect(node.hasAttribute("tabindex")).toBe(false);
    }
    const handles = [...view.querySelectorAll(".react-flow__handle")];
    // Two anchors on each card, "+" and join: one in, one out.
    expect(handles.length).toBe(2 * nodes.length);
    for (const handle of handles) {
      expect(handle.classList).not.toContain("connectable");
    }
  });

  it("names no edge with the library's English default", () => {
    const view = draw();
    expect(view.innerHTML).not.toContain("Edge from");
  });

  it("draws the zoom buttons with antd, named in Vietnamese", () => {
    const view = draw();
    for (const name of ["Phóng to", "Thu nhỏ", "Vừa khung"]) {
      const button = view.querySelector(`button[aria-label="${name}"]`);
      expect(button?.classList).toContain("ant-btn");
    }
  });
});

describe("the library's CSS sits in the components layer", () => {
  it("is imported once, by the canvas stylesheet, into @layer components", () => {
    const css = readFileSync(join(WEB, HERE, "workflow-canvas.css"), "utf8");
    expect(css).toContain(
      '@import "@xyflow/react/dist/base.css" layer(components);',
    );
    const importers = sources(join(WEB, "app"))
      .map((path) => `app/${path}`)
      .filter((path) => !path.split("/").includes("__tests__"))
      .filter((path) =>
        readFileSync(join(WEB, path), "utf8").includes("@xyflow/react/dist/"),
      );
    expect(importers).toEqual([`${HERE}/workflow-canvas.css`]);
    expect(globMatches("app/studio/**/canvas/**", importers[0]!)).toBe(true);
  });
});
