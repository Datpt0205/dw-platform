import { act, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  ARTIFACT,
  FakeServer,
  byLabel,
  installShims,
  queryByLabel,
  renderBuilder,
  setWidth,
  stopNamed,
  treeItem,
} from "./builder-harness";

/**
 * The grammar on the builder page at 1280 px (workflow-builder-ui R1.5, R1.7,
 * R2.5, R2.6; BU7, BU8, BU11; ticket 04): folding a frame is the viewer's,
 * kept under `wbui.collapsed.<user_id>.<artifact_id>` and never in the
 * document; the keyboard skips a folded frame and Ctrl+K opens it; the outline
 * reads the same fold; a lane comes off from its head; the loop's menu adds
 * and removes "Đã đủ N lần"; the save's warnings reach their card, and a
 * folded frame counts those inside it.
 */

let server = new FakeServer("f3");
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
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const KEY = (viewer: string) => `wbui.collapsed.${viewer}.${ARTIFACT}`;
const LOOP = "Làm giàu dữ liệu tới khi đủ";

async function open(
  fixture = "f3",
  viewer: string | null = "u_an",
  prepare: (s: FakeServer) => void = () => {},
) {
  server = new FakeServer(fixture);
  prepare(server);
  await renderBuilder(
    WorkflowBuilder,
    () => document.querySelector("[data-stop]"),
    viewer,
  );
}

const settle = () => act(async () => new Promise((r) => setTimeout(r, 30)));

async function menu(stop: HTMLElement, label: string) {
  stop.focus();
  fireEvent.keyDown(stop, { key: "F10", shiftKey: true });
  const item = await waitFor(() => {
    const found = [...document.querySelectorAll("[role=menuitem]")].find(
      (m) => m.textContent === label,
    );
    if (!found) {
      throw new Error(
        `no ${label} in ${[...document.querySelectorAll("[role=menuitem]")].map((m) => m.textContent).join(", ")}`,
      );
    }
    return found;
  });
  fireEvent.click(item);
}

const folded = (name: string) =>
  stopNamed(name).getAttribute("aria-label")?.includes("khung đang thu gọn") ??
  false;

type Doc = { steps: Record<string, unknown>[] };
const lastSaved = () =>
  server.puts[server.puts.length - 1]!.body as { document: Doc };

describe("folding a frame is the viewer's, never the document's (R1.7, BU8)", () => {
  it("folds from the menu: the card stands for the frame, nothing is saved, the key names the viewer", async () => {
    await open();
    const before = JSON.stringify(server.document);
    expect(document.querySelector('[data-frame="lam_giau"]')).not.toBeNull();
    await menu(stopNamed(LOOP), "Thu gọn khung");
    await waitFor(() => expect(folded(LOOP)).toBe(true));
    expect(document.querySelector('[data-frame="lam_giau"]')).toBeNull();
    expect(document.querySelector('[data-stop="gop"]')).toBeNull();
    await settle();
    expect(server.puts).toHaveLength(0);
    expect(JSON.stringify(server.document)).toBe(before);
    expect(window.localStorage.getItem(KEY("u_an"))).toBe('["lam_giau"]');
    // No other key holds it: not one without the viewer, not the document.
    expect(window.localStorage.getItem(`wbui.collapsed.${ARTIFACT}`)).toBe(
      null,
    );
    expect(window.localStorage).toHaveLength(1);
  });

  it("an edit after a fold saves a document that carries no fold", async () => {
    await open();
    await menu(stopNamed(LOOP), "Thu gọn khung");
    await waitFor(() => expect(folded(LOOP)).toBe(true));
    const first = stopNamed("Chấm điểm lead bằng AI");
    first.focus();
    fireEvent.keyDown(first, { key: "Delete" });
    await waitFor(() => expect(server.puts).toHaveLength(1));
    const text = JSON.stringify(lastSaved().document);
    for (const word of ["wbui", "collapsed", "folded", "fold"]) {
      expect(text).not.toContain(word);
    }
    expect(text).toContain('"lam_giau"');
  });

  it("stays folded for the same viewer, opens for another on the same browser", async () => {
    window.localStorage.setItem(KEY("u_an"), '["lam_giau"]');
    await open("f3", "u_an");
    expect(folded(LOOP)).toBe(true);
    cleanup();
    await open("f3", "u_binh");
    expect(folded(LOOP)).toBe(false);
    expect(document.querySelector('[data-frame="lam_giau"]')).not.toBeNull();
    // Without a known viewer nothing is read or written.
    cleanup();
    await open("f3", null);
    expect(folded(LOOP)).toBe(false);
    await menu(stopNamed(LOOP), "Thu gọn khung");
    await waitFor(() => expect(folded(LOOP)).toBe(true));
    expect(window.localStorage.getItem(KEY("u_an"))).toBe('["lam_giau"]');
    expect(window.localStorage).toHaveLength(1);
  });

  it("draws in full with every frame open when storage cannot be used", async () => {
    window.localStorage.setItem(KEY("u_an"), '["lam_giau"]');
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    await open();
    expect(folded(LOOP)).toBe(false);
    expect(document.querySelectorAll("[data-frame]")).toHaveLength(2);
    // A fold still works for the page.
    await menu(stopNamed(LOOP), "Thu gọn khung");
    await waitFor(() => expect(folded(LOOP)).toBe(true));
  });

  it("an unreadable entry reads as nothing folded", async () => {
    window.localStorage.setItem(KEY("u_an"), "{not json");
    await open();
    expect(folded(LOOP)).toBe(false);
  });
});

describe("the keyboard through frames (R2.5, R1.7)", () => {
  it("↓ skips a folded frame's steps; ↓ enters it again once it is open", async () => {
    window.localStorage.setItem(KEY("u_an"), '["soan_lai"]');
    await open("f5");
    const loop = stopNamed("Soạn lại báo giá tới khi được duyệt");
    loop.focus();
    fireEvent.keyDown(loop, { key: "ArrowDown" });
    await waitFor(() =>
      expect(document.activeElement).toBe(
        stopNamed("Hội đồng duyệt báo giá lớn"),
      ),
    );
    await menu(stopNamed("Soạn lại báo giá tới khi được duyệt"), "Mở khung");
    await waitFor(() =>
      expect(folded("Soạn lại báo giá tới khi được duyệt")).toBe(false),
    );
    const again = stopNamed("Soạn lại báo giá tới khi được duyệt");
    again.focus();
    fireEvent.keyDown(again, { key: "ArrowDown" });
    await waitFor(() =>
      expect(document.activeElement).toBe(stopNamed("Soạn báo giá")),
    );
    expect(window.localStorage.getItem(KEY("u_an"))).toBeNull();
  });

  it("→ goes to the Từ chối lane, and arrows never move a step", async () => {
    await open("f5");
    const approved = stopNamed("Ghi nhận đã duyệt");
    approved.focus();
    fireEvent.keyDown(approved, { key: "ArrowRight" });
    await waitFor(() =>
      expect(document.activeElement).toBe(stopNamed("Ghi nhận cần sửa")),
    );
    for (const key of ["ArrowUp", "ArrowLeft", "ArrowDown", "ArrowRight"]) {
      fireEvent.keyDown(document.activeElement!, { key });
    }
    await settle();
    expect(server.puts).toHaveLength(0);
  });

  it("Ctrl+K to a step inside a folded frame opens the frames around it and keeps that", async () => {
    window.localStorage.setItem(KEY("u_an"), '["lam_giau","tra_cuu"]');
    await open();
    expect(document.querySelector('[data-stop="tom_cong_ty"]')).toBeNull();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const search = await waitFor(() => byLabel("Tìm Bước theo tên"));
    fireEvent.change(search, { target: { value: "tom tat cong ty" } });
    fireEvent.keyDown(search, { key: "Enter" });
    await waitFor(() =>
      expect(document.activeElement).toBe(stopNamed("Tóm tắt công ty")),
    );
    expect(window.localStorage.getItem(KEY("u_an"))).toBeNull();
  });

  it("folding the frame focus is in brings focus to its card", async () => {
    await open();
    const inner = stopNamed("Tóm tắt công ty");
    inner.focus();
    await settle();
    // Fold the outer loop from its card's own button.
    fireEvent.click(byLabel(`Thu gọn khung «${LOOP}»`));
    await waitFor(() => expect(folded(LOOP)).toBe(true));
    await settle();
    expect(document.activeElement?.getAttribute("data-stop")).toBe("lam_giau");
  });
});

describe("one fold, two views: the outline's expandedKeys (R1.7, R2.6)", () => {
  it("shows the folded frame closed in the Tree, and opening it there opens it on the canvas", async () => {
    window.localStorage.setItem(KEY("u_an"), '["lam_giau"]');
    await open();
    fireEvent.click(
      [...document.querySelectorAll(".ant-segmented-item")].find(
        (el) => el.textContent === "Danh sách",
      )!,
    );
    const row = await waitFor(() => {
      const found = treeItem("lam_giau");
      if (!found) throw new Error("no row");
      return found;
    });
    expect(row.getAttribute("aria-expanded")).toBe("false");
    expect(treeItem("tra_cuu")).toBeNull();
    fireEvent.click(row.querySelector(".ant-tree-switcher")!);
    await waitFor(() =>
      expect(treeItem("lam_giau")!.getAttribute("aria-expanded")).toBe("true"),
    );
    expect(window.localStorage.getItem(KEY("u_an"))).toBeNull();
  });
});

describe("lanes come off from their head; the loop names its optional lane", () => {
  it("Bỏ nhánh on a cases head removes the entry and its steps, with Hoàn tác", async () => {
    await open();
    fireEvent.click(byLabel("Thao tác nhánh «hot»"));
    const item = await waitFor(() => {
      const found = [...document.querySelectorAll("[role=menuitem]")].find(
        (m) => m.textContent === "Bỏ nhánh",
      );
      if (!found) throw new Error("no menu");
      return found;
    });
    fireEvent.click(item);
    await waitFor(() => expect(server.puts).toHaveLength(1));
    const sw = lastSaved().document.steps.find((s) => s.id === "phan_loai")!;
    expect(Object.keys((sw.config as { cases: object }).cases)).not.toContain(
      "hot",
    );
    const undo = await waitFor(() => {
      const found = [...document.querySelectorAll("button")].find(
        (b) => b.textContent === "Hoàn tác",
      );
      if (!found) throw new Error("no notice");
      return found;
    });
    expect(document.body.textContent).toContain(
      "«Làm giàu dữ liệu tới khi đủ»",
    );
    fireEvent.click(undo);
    await waitFor(() => expect(server.puts).toHaveLength(2));
    expect(JSON.stringify(lastSaved().document)).toContain('"hot"');
  });

  it("Thêm làn «Đã đủ N lần» then Bỏ làn «Đã đủ N lần» on the loop", async () => {
    await open("f10");
    const loop = () => stopNamed(LOOP);
    await menu(loop(), "Thêm làn «Đã đủ N lần»");
    await waitFor(() => expect(server.puts).toHaveLength(1));
    const config = () =>
      lastSaved().document.steps.find((s) => s.id === "lam_giau")!
        .config as Record<string, unknown>;
    expect(config().max_reached).toEqual([]);
    await waitFor(() =>
      expect(
        document.querySelector('[data-lane-head="head:lam_giau:max_reached"]'),
      ).not.toBeNull(),
    );
    await menu(loop(), "Bỏ làn «Đã đủ N lần»");
    await waitFor(() => expect(server.puts).toHaveLength(2));
    expect(config()).not.toHaveProperty("max_reached");
  });

  it("a card with no lane of its own has no Thêm làn and no fold", async () => {
    await open("f10");
    const sub = stopNamed("Kiểm lead trùng");
    sub.focus();
    fireEvent.keyDown(sub, { key: "F10", shiftKey: true });
    await waitFor(() =>
      expect(
        document.querySelectorAll("[role=menuitem]").length,
      ).toBeGreaterThan(0),
    );
    const labels = [...document.querySelectorAll("[role=menuitem]")].map(
      (m) => m.textContent ?? "",
    );
    expect(labels.some((l) => l.startsWith("Thêm làn"))).toBe(false);
    expect(labels).not.toContain("Thu gọn khung");
    expect(queryByLabel(/^Thu gọn khung «Kiểm lead trùng»/)).toBeNull();
  });
});

describe("the save's warnings on their card (R3.4, R1.7)", () => {
  it("puts a warning on the step it points into, and a folded frame counts it", async () => {
    await open("f3", "u_an", (s) => {
      s.warnings = [
        {
          pointer: "/steps/1/config/cases/hot/0/config/body/1/config",
          code: "wf.unreachable_node",
          detail: "Bước này không tới được",
        },
      ];
    });
    // A change, so the draft saves and the check answers.
    const last = stopNamed("Báo kênh bán hàng");
    last.focus();
    fireEvent.keyDown(last, { key: "Delete" });
    await waitFor(() => expect(server.puts).toHaveLength(1));
    const gop = () =>
      document.querySelector<HTMLElement>(
        '.react-flow__node-step[data-id="gop"]',
      );
    await waitFor(() => expect(gop()?.textContent).toContain("1 lỗi"));
    await menu(stopNamed(LOOP), "Thu gọn khung");
    await waitFor(() => expect(folded(LOOP)).toBe(true));
    expect(
      document.querySelector('.react-flow__node-step[data-id="lam_giau"]')
        ?.textContent,
    ).toContain("1 lỗi");
  });
});
