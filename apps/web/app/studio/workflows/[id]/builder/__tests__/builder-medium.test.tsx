import { act, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  FakeServer,
  installShims,
  renderBuilder,
  setWidth,
  stopNamed,
} from "./builder-harness";

/**
 * The builder at 800 px, between `md` and `lg` (workflow-builder-ui R2.1,
 * R2.5, R2.10): the canvas and the "Sơ đồ | Danh sách" Segmented, but no side
 * palette; and "Di chuyển…", the keyboard's way to move a step.
 */

let server = new FakeServer();
vi.mock("../../../../../../lib/session", () => ({
  apiClient: () => server.client(),
}));
vi.mock("next/dynamic", async () => {
  const canvas = await import("../canvas/workflow-canvas");
  return { default: () => canvas.default };
});

setWidth(800);
const { WorkflowBuilder } = await import("../workflow-builder");

beforeAll(installShims);
afterEach(cleanup);

async function open() {
  server = new FakeServer();
  await renderBuilder(WorkflowBuilder, () =>
    document.querySelector("[data-stop]"),
  );
}

describe("between md and lg", () => {
  it("draws the canvas and the Segmented, and no side palette", async () => {
    await open();
    expect(document.querySelector(".react-flow")).not.toBeNull();
    expect(document.querySelector("aside")).toBeNull();
    const segmented = document.querySelector(".ant-segmented")!;
    expect(segmented.textContent).toBe("Sơ đồDanh sách");
    const outline = [...segmented.querySelectorAll("label")].find(
      (l) => l.textContent === "Danh sách",
    )!;
    fireEvent.click(outline.querySelector("input") ?? outline);
    await waitFor(() =>
      expect(document.querySelector("[role=tree]")).not.toBeNull(),
    );
    expect(document.querySelector(".react-flow")).toBeNull();
  });

  it("moves a step through Di chuyển…, announced with its lane", async () => {
    await open();
    const target = stopNamed("Chuẩn hóa số điện thoại và email");
    target.focus();
    fireEvent.keyDown(target, { key: "F10", shiftKey: true });
    const item = await waitFor(() => {
      const found = [...document.querySelectorAll("[role=menuitem]")].find(
        (m) => m.textContent === "Di chuyển…",
      );
      if (!found) throw new Error("no menu");
      return found;
    });
    fireEvent.click(item);
    const select = await waitFor(() => {
      const found = document.querySelector(".ant-modal-wrap .ant-select");
      if (!found) throw new Error("no modal");
      return found as HTMLElement;
    });
    fireEvent.mouseDown(select.querySelector(".ant-select-selector") ?? select);
    const option = await waitFor(() => {
      const found = document.querySelector(
        '.ant-select-tree [title="Sau «Tìm việc đang mở của lead»"]',
      );
      if (!found) throw new Error("no option");
      return found as HTMLElement;
    });
    // None inside the moving step's own subtree; its own lanes are not offered.
    expect(
      document.querySelector('.ant-select-tree [title="Vào đầu «hot»"]'),
    ).not.toBeNull();
    fireEvent.click(option);
    const ok = [...document.querySelectorAll(".ant-modal-footer button")].find(
      (b) => b.textContent === "Di chuyển",
    ) as HTMLElement;
    await act(async () => {});
    fireEvent.click(ok);
    await waitFor(() => expect(server.puts).toHaveLength(1));
    const doc = server.puts[0]!.body as {
      document: { steps: { id: string }[] };
    };
    expect(doc.document.steps.slice(0, 3).map((s) => s.id)).toEqual([
      "luu_lead",
      "tim_viec_mo",
      "chuan_hoa",
    ]);
    expect(
      document.querySelector("[data-testid=builder-live]")!.textContent,
    ).toBe(
      "Đã dời «Chuẩn hóa số điện thoại và email» sang «Quy trình», vị trí 3.",
    );
  });
});
