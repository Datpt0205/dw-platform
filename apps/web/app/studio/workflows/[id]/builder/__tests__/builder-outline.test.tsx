import { cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  catalogueOf,
  toTree,
  type StepNode,
} from "../../../../../../lib/workflow-graph";
import { NODE_TYPES } from "../../../../../../lib/__tests__/workflow-catalogue";
import {
  ARTIFACT,
  FakeServer,
  buttonsByText,
  byLabel,
  installShims,
  renderBuilder,
  setWidth,
  treeItem,
} from "./builder-harness";

/**
 * The builder at a 320 px phone (workflow-builder-ui R2.6, BU11; R2.2's
 * horizontal scroll is Playwright's): the outline `Tree` is the editor, built
 * from the same tree as the canvas, every node carrying its level and place;
 * no canvas, no Segmented, no side palette. Plus the page states: no draft,
 * another kind.
 */

let server = new FakeServer("f2");
vi.mock("../../../../../../lib/session", () => ({
  apiClient: () => server.client(),
}));
vi.mock("next/dynamic", async () => {
  const canvas = await import("../canvas/workflow-canvas");
  return { default: () => canvas.default };
});

setWidth(320);
const { WorkflowBuilder } = await import("../workflow-builder");

beforeAll(installShims);
afterEach(cleanup);

async function open(fixture = "f2") {
  server = new FakeServer(fixture);
  await renderBuilder(WorkflowBuilder, () =>
    document.querySelector("[role=tree]"),
  );
}

/** The level, place and set size each node must have, from the document. */
function expected(
  steps: StepNode[],
  level = 1,
  out = new Map<string, number[]>(),
) {
  steps.forEach((step, i) => {
    out.set(step.id, [level, i + 1, steps.length]);
    step.lanes.forEach((lane, j) => {
      out.set(`lane:${step.id}:${lane.port}`, [
        level + 1,
        j + 1,
        step.lanes.length,
      ]);
      expected(lane.steps, level + 2, out);
    });
  });
  return out;
}

describe("the outline is the document's tree (R2.6, BU11)", () => {
  it("carries aria-level, aria-posinset and aria-setsize on every node of F2", async () => {
    await open();
    expect(document.querySelector(".react-flow")).toBeNull();
    expect(document.querySelector("aside")).toBeNull();
    expect(document.querySelector(".ant-segmented")).toBeNull();
    const want = expected(
      toTree(server.document, catalogueOf(NODE_TYPES)).steps,
    );
    const items = [...document.querySelectorAll("[role=treeitem]")];
    expect(items.length).toBe(want.size);
    for (const [key, values] of want) {
      const item = treeItem(key);
      expect(item, key).not.toBeNull();
      const got = ["aria-level", "aria-posinset", "aria-setsize"].map((a) =>
        Number(item!.getAttribute(a)),
      );
      expect(got, key).toEqual(values);
    }
  });

  it("a step added through a lane's Thêm Bước appears at its level and place", async () => {
    await open("f1");
    const menuOf = async (key: string, label: string) => {
      fireEvent.click(byLabel(`Thao tác «${label}»`, treeItem(key)!));
      const sheet = await waitFor(() => {
        const found = document.querySelector(".ant-drawer-open .ant-menu");
        if (!found) throw new Error("no sheet");
        return found as HTMLElement;
      });
      return sheet;
    };
    const item = (sheet: HTMLElement, text: string) =>
      [...sheet.querySelectorAll("[role=menuitem]")].find(
        (m) => m.textContent === text,
      )!;
    fireEvent.click(
      item(await menuOf("phan_loai", "Phân loại theo hạng"), "Thêm nhánh"),
    );
    const dialog = await waitFor(() => {
      const found = document.querySelector<HTMLInputElement>(
        ".ant-modal-wrap input#lane-key",
      );
      if (!found) throw new Error("no dialog");
      return found;
    });
    fireEvent.change(dialog, { target: { value: "cold" } });
    fireEvent.click(
      buttonsByText(
        "Thêm nhánh",
        document.querySelector(".ant-modal-footer")!,
      )[0]!,
    );
    const laneKey = "lane:phan_loai:cases.cold";
    await waitFor(() => expect(treeItem(laneKey)).not.toBeNull());
    expect(treeItem(laneKey)!.getAttribute("aria-posinset")).toBe("3");
    expect(treeItem(laneKey)!.getAttribute("aria-setsize")).toBe("4");
    await waitFor(() =>
      expect(document.querySelector(".ant-drawer-open .ant-menu")).toBeNull(),
    );
    fireEvent.click(item(await menuOf(laneKey, "cold"), "Thêm Bước"));
    const entry = await waitFor(() => {
      const found = buttonsByText(
        "Hỏi AI",
        document.querySelector(".ant-modal-wrap .ant-modal-body")!,
      )[0];
      if (!found) throw new Error("no palette");
      return found;
    });
    fireEvent.click(entry);
    await waitFor(() => expect(server.puts.length).toBeGreaterThan(0));
    const doc = server.puts[server.puts.length - 1]!.body as {
      document: {
        steps: {
          id: string;
          config: { cases: Record<string, { id: string; type: string }[]> };
        }[];
      };
    };
    const saved = doc.document.steps.find((s) => s.id === "phan_loai")!;
    const cold = saved.config.cases.cold!;
    expect(cold.map((s) => s.type)).toEqual(["ai.llm@2"]);
    const added = await waitFor(() => {
      const found = treeItem(cold[0]!.id);
      if (!found) throw new Error("not in the outline");
      return found;
    });
    expect(added.getAttribute("aria-level")).toBe("3");
    expect(added.getAttribute("aria-posinset")).toBe("1");
    expect(added.getAttribute("aria-setsize")).toBe("1");
    expect(added.textContent).toContain("Hỏi AI");
  });
});

describe("the outline's keys (R2.5, R2.6)", () => {
  it("Delete removes the active step, Ctrl+Z restores it, Shift+F10 opens its menu", async () => {
    await open("f1");
    const tree = document.querySelector<HTMLElement>("[role=tree]")!;
    fireEvent.keyDown(tree, { key: "ArrowDown" });
    await waitFor(() =>
      expect(treeItem("chuan_hoa")!.className).toContain("active"),
    );
    fireEvent.keyDown(tree, { key: "Delete", isComposing: true });
    fireEvent.keyDown(tree, { key: "Delete" });
    await waitFor(() => expect(server.puts).toHaveLength(1));
    const saved = () =>
      (
        server.puts[server.puts.length - 1]!.body as {
          document: { steps: { id: string }[] };
        }
      ).document.steps.map((s) => s.id);
    expect(saved()).not.toContain("chuan_hoa");
    fireEvent.keyDown(tree, { key: "z", ctrlKey: true });
    await waitFor(() => expect(server.puts).toHaveLength(2));
    expect(saved()[0]).toBe("chuan_hoa");
    fireEvent.keyDown(tree, { key: "ArrowDown" });
    fireEvent.keyDown(tree, { key: "F10", shiftKey: true });
    await waitFor(() =>
      expect(
        document.querySelector(".ant-drawer-open .ant-menu"),
      ).not.toBeNull(),
    );
  });
});

describe("the page's own states", () => {
  it("a workflow with no draft shows so, and calls no write route", async () => {
    server = new FakeServer();
    server.hasDraft = false;
    await renderBuilder(WorkflowBuilder, () =>
      document.body.textContent?.includes("Quy trình chưa có bản Nháp")
        ? document.body
        : null,
    );
    expect(server.calls.every((c) => c.method === "GET")).toBe(true);
    expect(server.calls.map((c) => c.path)).toContain(
      `/api/v1/studio/artifacts/${ARTIFACT}/draft`,
    );
  });

  it("a caller the catalogue route refuses sees the forbidden state, and nothing is written", async () => {
    server = new FakeServer();
    server.refuse.types = 403;
    await renderBuilder(WorkflowBuilder, () =>
      document.body.textContent?.includes("Bạn không có quyền xem mục này")
        ? document.body
        : null,
    );
    expect(document.querySelector("[role=tree]")).toBeNull();
    expect(server.puts).toHaveLength(0);
  });

  it("a save the server refuses shows its sentence under Lưu thất bại, the edit kept", async () => {
    server = new FakeServer("f1");
    server.refuse.save = 403;
    await renderBuilder(WorkflowBuilder, () =>
      document.querySelector("[role=tree]"),
    );
    const tree = document.querySelector<HTMLElement>("[role=tree]")!;
    fireEvent.keyDown(tree, { key: "ArrowDown" });
    await waitFor(() =>
      expect(treeItem("chuan_hoa")!.className).toContain("active"),
    );
    fireEvent.keyDown(tree, { key: "Delete" });
    await waitFor(() => expect(server.puts).toHaveLength(1));
    await waitFor(() => {
      const alert = document.querySelector(".ant-alert-error");
      expect(alert?.textContent).toContain("Lưu thất bại");
      expect(alert?.textContent).toContain("refused: permission_denied");
    });
    expect(treeItem("chuan_hoa")).toBeNull();
    expect(server.document.steps).toHaveLength(7);
  });

  it("an artifact of another kind reads as not found", async () => {
    server = new FakeServer();
    server.kind = "object";
    await renderBuilder(WorkflowBuilder, () =>
      document.body.textContent?.includes("Không tìm thấy quy trình này.")
        ? document.body
        : null,
    );
    expect(server.calls.map((c) => c.path)).not.toContain(
      `/api/v1/studio/artifacts/${ARTIFACT}/draft`,
    );
  });
});
