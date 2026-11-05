import { act, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  ARTIFACT,
  FakeServer,
  allByLabel,
  buttonsByText,
  byLabel,
  installShims,
  queryByLabel,
  renderBuilder,
  setWidth,
  stopNamed,
} from "./builder-harness";

/**
 * The builder at 1280 px, on F1 (workflow-builder-ui R1.4, R1.5, R1.8, R2.1,
 * R2.3, R2.4, R2.5, R2.7-R2.11; BU4, BU7, BU8, BU10, BU12, BU14): the canvas
 * with the side palette, against a fake of the draft and catalogue routes
 * reached through the real `ApiClient`.
 */

let server = new FakeServer();
vi.mock("../../../../../../lib/session", () => ({
  apiClient: () => server.client(),
}));
vi.mock("next/dynamic", async () => {
  const canvas = await import("../canvas/workflow-canvas");
  return { default: () => canvas.default };
});

setWidth(1280);
const { WorkflowBuilder } = await import("../workflow-builder");

beforeAll(installShims);
afterEach(cleanup);

async function open(
  prepare: (s: FakeServer) => void = () => {},
  fixture = "f1",
) {
  server = new FakeServer(fixture);
  prepare(server);
  await renderBuilder(WorkflowBuilder, () =>
    document.querySelector("[data-stop]"),
  );
}

type Doc = { steps: Record<string, unknown>[] };
const ids = (doc: Doc) => doc.steps.map((s) => s.id);
const lastSaved = () =>
  server.puts[server.puts.length - 1]!.body as { document: Doc };
const settle = () => act(async () => new Promise((r) => setTimeout(r, 30)));
const live = () =>
  document.querySelector("[data-testid=builder-live]")!.textContent ?? "";
const AFTER_FIRST = "Thêm Bước sau «Chuẩn hóa số điện thoại và email»";

/** Run a palette entry from the open Popover or Modal. */
async function pick(label: string) {
  const entry = await waitFor(() => {
    const overlay = document.querySelector(
      ".ant-popover:not(.ant-popover-hidden) .ant-popover-content, .ant-modal-wrap .ant-modal-body",
    );
    const found = overlay ? buttonsByText(label, overlay)[0] : undefined;
    if (!found)
      throw new Error(
        `no ${label} in ${overlay?.outerHTML.slice(0, 200) ?? "no overlay"}`,
      );
    return found;
  });
  fireEvent.click(entry);
}

describe("autosave under If-Match (R2.3, R2.4, BU4)", () => {
  it("saves with the ETag read, then the ETag the save returned", async () => {
    await open();
    fireEvent.click(byLabel(AFTER_FIRST));
    await pick("Hỏi AI");
    await waitFor(() => expect(server.puts).toHaveLength(1));
    expect(server.puts[0]!.ifMatch).toBe('"1"');
    expect(server.puts[0]!.path).toBe(
      `/api/v1/studio/artifacts/${ARTIFACT}/draft`,
    );
    expect(ids(lastSaved().document)[1]).toMatch(/^llm_[a-z0-9]{6}$/);
    fireEvent.click(byLabel(AFTER_FIRST));
    await pick("Biến đổi dữ liệu");
    await waitFor(() => expect(server.puts).toHaveLength(2));
    expect(server.puts[1]!.ifMatch).toBe('"2"');
    await waitFor(() => expect(document.body.textContent).toContain("Đã lưu"));
  });

  it("stops at a 412, keeps what is on the page, and reloads only on the button", async () => {
    await open();
    server.savedElsewhere({
      ...server.document,
      steps: (server.document.steps as unknown[]).slice(0, 2),
    });
    fireEvent.click(byLabel(AFTER_FIRST));
    await pick("Hỏi AI");
    await waitFor(() =>
      expect(document.body.textContent).toContain("Bản nháp đã đổi ở nơi khác"),
    );
    expect(server.puts).toHaveLength(1);
    // What was being edited stays: the new step is still drawn.
    expect(stopNamed("Hỏi AI")).toBeTruthy();
    fireEvent.click(byLabel(AFTER_FIRST));
    await pick("Biến đổi dữ liệu");
    await settle();
    expect(server.puts).toHaveLength(1);
    fireEvent.click(buttonsByText("Tải bản mới nhất")[0]!);
    await waitFor(() =>
      expect(document.querySelectorAll(".react-flow__node-step")).toHaveLength(
        2,
      ),
    );
    expect(byLabel("Hoàn tác").hasAttribute("disabled")).toBe(true);
    server.stale = false;
    fireEvent.click(byLabel(AFTER_FIRST));
    await pick("Hỏi AI");
    await waitFor(() => expect(server.puts).toHaveLength(2));
    expect(server.puts[1]!.ifMatch).toBe('"2"');
  });
});

describe("placing a step in a slot (R1.4, R1.5, R2.1, BU8)", () => {
  it("draws a + of at least 24 px on every connection, named after the step before it", async () => {
    await open();
    const plus = allByLabel(/^Thêm Bước sau «/);
    expect(plus.length).toBeGreaterThan(10);
    for (const button of plus) {
      expect(parseInt(button.style.width, 10)).toBeGreaterThanOrEqual(24);
      expect(parseInt(button.style.height, 10)).toBeGreaterThanOrEqual(24);
      expect(button.closest(".react-flow__node")).not.toBeNull();
    }
    expect(queryByLabel(AFTER_FIRST)).not.toBeNull();
    expect(allByLabel(/^Edge from/)).toEqual([]);
  });

  it("opens the palette from a +: searchable, grouped, no trigger; the choice lands in that slot", async () => {
    await open();
    fireEvent.click(byLabel("Thêm Bước sau «Lưu hoặc cập nhật Lead»"));
    const popover = await waitFor(() => {
      const found = document.querySelector(".ant-popover .ant-popover-content");
      if (!found) throw new Error("no popover");
      return found as HTMLElement;
    });
    const search = byLabel("Tìm Loại bước", popover);
    expect(popover.textContent).not.toContain("Khi Nguồn dữ liệu");
    expect(popover.textContent).toContain("Logic");
    fireEvent.change(search, { target: { value: "re nhanh" } });
    const entries = [...popover.querySelectorAll("button")].filter(
      (b) => !b.closest(".ant-input-affix-wrapper"),
    );
    expect(entries.map((b) => b.textContent)).toEqual(["Rẽ nhánh"]);
    fireEvent.click(entries[0]!);
    await waitFor(() => expect(server.puts).toHaveLength(1));
    const placed = lastSaved().document.steps[2]!;
    expect(placed.type).toBe("logic.switch@1");
    expect(placed).not.toHaveProperty("description");
    expect(placed.config).toEqual({ match: "first", cases: {}, default: [] });
    // Its Khác lane is empty with its dashed slot; the + after it is named by the type.
    expect(byLabel("Thêm Bước vào «Khác»").className).toContain(
      "ant-btn-dashed",
    );
    expect(queryByLabel("Thêm Bước sau «Rẽ nhánh»")).not.toBeNull();
  });

  it("drags from the side palette (lg and up) onto the + under the pointer", async () => {
    await open();
    const side = document.querySelector(
      "aside[aria-label='Loại bước']",
    ) as HTMLElement;
    expect(side).not.toBeNull();
    const entry = byLabel("Kéo «Hỏi AI» vào một ô", side);
    const plus = byLabel(AFTER_FIRST);
    fireEvent.pointerDown(entry);
    await act(async () => {});
    expect(plus.className).toContain("ant-btn-primary");
    const node = plus.closest(".react-flow__node") as HTMLElement;
    const [, x, y] = /translate\(([-\d.]+)px, ?([-\d.]+)px\)/.exec(
      node.style.transform,
    )!;
    fireEvent.pointerUp(plus, {
      clientX: Number(x) + 14,
      clientY: Number(y) + 14,
    });
    await waitFor(() => expect(server.puts).toHaveLength(1));
    expect(lastSaved().document.steps[1]!.type).toBe("ai.llm@2");
  });

  it("a card dropped on empty canvas or outside it changes nothing", async () => {
    await open();
    const before = JSON.stringify(server.document);
    const handle = allByLabel("Kéo để dời")[0]!;
    fireEvent.pointerDown(handle);
    await act(async () => {});
    fireEvent.pointerUp(document.querySelector(".react-flow__pane")!, {
      clientX: -4000,
      clientY: -4000,
    });
    fireEvent.pointerDown(handle);
    await act(async () => {});
    fireEvent.pointerUp(document.body, { clientX: 0, clientY: 0 });
    await settle();
    expect(server.puts).toHaveLength(0);
    expect(JSON.stringify(server.document)).toBe(before);
  });

  it("a card dropped on a + moves there", async () => {
    await open();
    const handle = allByLabel("Kéo để dời")[0]!;
    const plus = byLabel("Thêm Bước sau «Tìm việc đang mở của lead»");
    fireEvent.pointerDown(handle);
    await act(async () => {});
    const node = plus.closest(".react-flow__node") as HTMLElement;
    const [, x, y] = /translate\(([-\d.]+)px, ?([-\d.]+)px\)/.exec(
      node.style.transform,
    )!;
    fireEvent.pointerUp(plus, {
      clientX: Number(x) + 14,
      clientY: Number(y) + 14,
    });
    await waitFor(() => expect(server.puts).toHaveLength(1));
    expect(ids(lastSaved().document).slice(0, 3)).toEqual([
      "luu_lead",
      "tim_viec_mo",
      "chuan_hoa",
    ]);
  });
});

describe("the configuration Drawer (R2.1)", () => {
  it("opens a switch with a Form from config_schema and no field for a lane key", async () => {
    await open();
    fireEvent.click(stopNamed("Phân loại theo hạng"));
    const drawer = await waitFor(() => {
      const found = document.querySelector(".ant-drawer-open .ant-drawer-body");
      if (!found) throw new Error("no drawer");
      return found as HTMLElement;
    });
    const labels = [...drawer.querySelectorAll("label")].map(
      (l) => l.textContent,
    );
    expect(labels).toEqual(expect.arrayContaining(["Tên Bước", "on", "match"]));
    expect(labels).not.toContain("cases");
    expect(labels).not.toContain("default");
    expect(drawer.textContent).toContain("Khi lỗi");
  });

  it("Ctrl+Z inside a Drawer input leaves the tree alone", async () => {
    await open();
    fireEvent.click(stopNamed("Phân loại theo hạng"));
    const input = await waitFor(() => {
      const found = document.querySelector<HTMLInputElement>(
        ".ant-drawer-open input#on",
      );
      if (!found) throw new Error("no input");
      return found;
    });
    input.focus();
    fireEvent.keyDown(input, { key: "z", ctrlKey: true });
    fireEvent.keyDown(input, { key: "Delete" });
    await settle();
    expect(server.puts).toHaveLength(0);
  });
});

describe("the step card (R1.8, BU14)", () => {
  it("F8 truncates a long name, with the whole of it in a Tooltip and the name", async () => {
    await open(() => {}, "f8");
    const card = document.querySelector(".react-flow__node-step .ant-card")!;
    expect(card.querySelector(".ant-typography-ellipsis")).not.toBeNull();
    const label = card
      .querySelector("[data-stop]")!
      .getAttribute("aria-label")!;
    expect(label.length).toBeGreaterThan(40);
  });

  it("names retry, timeout and on_error in words beside an icon", async () => {
    await open(() => {}, "f4");
    const tags = [
      ...document.querySelectorAll(".react-flow__node-step .ant-tag"),
    ];
    const text = (t: Element) => t.textContent ?? "";
    const retry = tags.find((t) => /^Thử lại ×\d$/.test(text(t)));
    const timeout = tags.find((t) => /^Hết giờ \d+ s$/.test(text(t)));
    const onError = tags.find((t) => text(t).startsWith("Khi lỗi: "));
    for (const tag of [retry, timeout, onError]) {
      expect(tag).toBeDefined();
      expect(tag!.querySelector(".anticon")).not.toBeNull();
    }
  });
});

describe("the keyboard (R2.5, R2.7, R2.8, BU7, BU10)", () => {
  it("one Tab stop; ↓ ↑ move focus, never a node, and change nothing", async () => {
    await open();
    const tabbable = [...document.querySelectorAll("[data-stop]")].filter(
      (el) => el.getAttribute("tabindex") === "0",
    );
    expect(tabbable).toHaveLength(1);
    const first = stopNamed("Chuẩn hóa số điện thoại và email");
    const transforms = () =>
      [...document.querySelectorAll<HTMLElement>(".react-flow__node-step")].map(
        (n) => n.style.transform,
      );
    const before = transforms();
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowDown" });
    await waitFor(() =>
      expect(document.activeElement).toBe(stopNamed("Lưu hoặc cập nhật Lead")),
    );
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    await waitFor(() => expect(document.activeElement).toBe(first));
    expect(transforms()).toEqual(before);
    await settle();
    expect(server.puts).toHaveLength(0);
  });

  it("deletes with Delete, undoes with Ctrl+Z, redoes with Ctrl+Shift+Z", async () => {
    await open();
    const target = stopNamed("Lưu hoặc cập nhật Lead");
    target.focus();
    fireEvent.keyDown(target, { key: "Delete" });
    await waitFor(() => expect(server.puts).toHaveLength(1));
    expect(ids(lastSaved().document)).not.toContain("luu_lead");
    expect(live()).toBe("Đã xóa «Lưu hoặc cập nhật Lead» khỏi «Quy trình».");
    fireEvent.keyDown(document.querySelector("[data-stop]")!, {
      key: "z",
      ctrlKey: true,
    });
    await waitFor(() => expect(server.puts).toHaveLength(2));
    expect(lastSaved().document).toEqual(new FakeServer().document);
    fireEvent.keyDown(document.querySelector("[data-stop]")!, {
      key: "Z",
      ctrlKey: true,
      shiftKey: true,
    });
    await waitFor(() => expect(server.puts).toHaveLength(3));
    expect(ids(lastSaved().document)).not.toContain("luu_lead");
  });

  it("Shift+F10 opens the menu; Thêm trước on the first step of a lane goes to index 0", async () => {
    await open();
    const target = stopNamed("Giao cho nhân viên kinh doanh");
    target.focus();
    fireEvent.keyDown(target, { key: "F10", shiftKey: true });
    const item = await waitFor(() => {
      const found = [...document.querySelectorAll("[role=menuitem]")].find(
        (m) => m.textContent === "Thêm trước",
      );
      if (!found) throw new Error("no menu");
      return found;
    });
    fireEvent.click(item);
    await pick("Hỏi AI");
    await waitFor(() => expect(server.puts).toHaveLength(1));
    const sw = lastSaved().document.steps.find(
      (s) => s.type === "logic.switch@1",
    )!;
    const hot = (sw.config as { cases: { hot: { type: string }[] } }).cases.hot;
    expect(hot[0]!.type).toBe("ai.llm@2");
    expect(live()).toBe(
      "Đã thêm «Hỏi AI» vào «hot» của «Phân loại theo hạng», vị trí 1.",
    );
  });

  it("Ctrl+K reaches a step by name, without diacritics", async () => {
    await open();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const search = await waitFor(() => byLabel("Tìm Bước theo tên"));
    fireEvent.change(search, { target: { value: "cham diem" } });
    fireEvent.keyDown(search, { key: "Enter" });
    await waitFor(() =>
      expect(document.activeElement).toBe(stopNamed("Chấm điểm lead bằng AI")),
    );
  });

  it("Space, Shift and Backspace outside the canvas touch nothing on it", async () => {
    await open();
    stopNamed("Lưu hoặc cập nhật Lead").focus();
    const outside = buttonsByText("Đi tới Bước (Ctrl+K)")[0]!;
    outside.focus();
    for (const key of [" ", "Shift", "Backspace", "Delete"]) {
      fireEvent.keyDown(outside, { key });
      fireEvent.keyDown(document.body, { key });
    }
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    for (const key of [" ", "Shift", "Backspace"])
      fireEvent.keyDown(input, { key });
    input.remove();
    await settle();
    expect(server.puts).toHaveLength(0);
    expect(document.querySelectorAll(".react-flow__node-step")).toHaveLength(
      15,
    );
  });

  it("ignores every key mid-composition (Telex)", async () => {
    await open();
    const target = stopNamed("Lưu hoặc cập nhật Lead");
    target.focus();
    fireEvent.keyDown(target, { key: "Delete", isComposing: true });
    fireEvent.keyDown(target, { key: "ArrowDown", isComposing: true });
    fireEvent.keyDown(target, { key: "z", ctrlKey: true, isComposing: true });
    expect(document.activeElement).toBe(target);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true, isComposing: true });
    await settle();
    expect(queryByLabel("Tìm Bước theo tên")).toBeNull();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const search = await waitFor(() => byLabel("Tìm Bước theo tên"));
    fireEvent.change(search, { target: { value: "cham" } });
    fireEvent.keyDown(search, { key: "Enter", isComposing: true });
    await settle();
    expect(queryByLabel("Tìm Bước theo tên")).not.toBeNull();
    expect(server.puts).toHaveLength(0);
  });
});

describe("deleting has an undo, no confirmation (R2.10, R2.11, BU7, BU12)", () => {
  it("names every step a block takes, and Hoàn tác gives the document back", async () => {
    await open();
    const original = new FakeServer().document;
    const target = stopNamed("Phân loại theo hạng");
    target.focus();
    fireEvent.keyDown(target, { key: "Delete" });
    expect(document.querySelector(".ant-modal-confirm")).toBeNull();
    const notice = await waitFor(() => {
      const found = document.querySelector(".ant-notification-notice");
      if (!found) throw new Error("no notice");
      return found as HTMLElement;
    });
    for (const name of [
      "Phân loại theo hạng",
      "Giao cho nhân viên kinh doanh",
      "Duyệt ưu đãi cho lead nóng",
      "Gửi email ưu đãi",
    ]) {
      expect(notice.textContent).toContain(`«${name}»`);
    }
    await waitFor(() => expect(server.puts).toHaveLength(1));
    fireEvent.click(buttonsByText("Hoàn tác", notice)[0]!);
    await waitFor(() => expect(server.puts).toHaveLength(2));
    expect(lastSaved().document).toEqual(original);
  });
});

describe("a step whose type the catalogue lacks (R2.9)", () => {
  it("is drawn as such, menu only Sao chép tham chiếu, and neither Delete nor drag", async () => {
    await open((s) => {
      (s.document.steps as unknown[]).splice(1, 0, {
        id: "la",
        type: "x.unknown@1",
        config: {
          inner: [{ id: "trong_la", type: "data.transform@1", config: {} }],
        },
      });
    });
    const card = stopNamed(/^x\.unknown@1, Loại bước không có trong danh mục$/);
    const body = card.closest(".ant-card") as HTMLElement;
    expect(body.textContent).toContain("Loại bước không có trong danh mục");
    expect(queryByLabel("Kéo để dời", body)).toBeNull();
    card.focus();
    fireEvent.keyDown(card, { key: "F10", shiftKey: true });
    await waitFor(() =>
      expect(
        document.querySelectorAll("[role=menuitem]").length,
      ).toBeGreaterThan(0),
    );
    expect(
      [...document.querySelectorAll("[role=menuitem]")].map(
        (i) => i.textContent,
      ),
    ).toEqual(["Sao chép tham chiếu"]);
    fireEvent.keyDown(card, { key: "Delete" });
    await settle();
    expect(server.puts).toHaveLength(0);
  });
});
