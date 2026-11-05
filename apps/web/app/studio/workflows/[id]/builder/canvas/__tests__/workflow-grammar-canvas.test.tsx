import { render } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import {
  catalogueOf,
  locate,
  toTree,
  walk,
  type WorkflowTree,
} from "../../../../../../../lib/workflow-graph";
import {
  layoutWorkflow,
  metricsFor,
} from "../../../../../../../lib/workflow-layout";
import {
  NODE_TYPES,
  loadFixture,
} from "../../../../../../../lib/__tests__/workflow-catalogue";
import {
  cardView,
  laneLabel,
  laneMenu,
  type CardView,
} from "../../builder-model";
import WorkflowCanvas, { arrowHead, type CardIssues } from "../workflow-canvas";

/**
 * The grammar as antd draws it (workflow-builder-ui R1.3, R1.5, R1.7, BU14;
 * ticket 04): a frame's card heads it with its words, the parallel frame's
 * floor says "Chờ tất cả nhánh xong", each lane head is a Tag with words (a
 * `cases` key, "Khác", "Duyệt", "Từ chối", a `branches` name), a keyed lane
 * head has "Bỏ nhánh", the approver card says who and how many, a
 * sub-workflow is one card with its mark and wait, and a folded frame is its
 * card with the problems inside it counted. Nothing the grammar draws is a
 * colour without words.
 */

beforeAll(() => {
  globalThis.DOMMatrixReadOnly ??= class {
    m22 = 1;
    constructor() {}
  } as unknown as typeof DOMMatrixReadOnly;
});

const catalogue = catalogueOf(NODE_TYPES);
const METRICS = metricsFor({ width: 256, height: 120 });

function draw(
  name: string,
  options: {
    folded?: ReadonlySet<string>;
    toggle?: boolean;
    issues?: ReadonlyMap<string, CardIssues>;
  } = {},
) {
  const tree: WorkflowTree = toTree(loadFixture(name), catalogue);
  const shapes = layoutWorkflow(tree, METRICS, options.folded);
  const views = new Map<string, CardView>();
  const labels = new Map<string, string>();
  walk(tree, (node) => {
    views.set(node.id, cardView(node, catalogue));
    for (const lane of node.lanes)
      labels.set(`head:${node.id}:${lane.port}`, laneLabel(lane));
  });
  const { container } = render(
    <div style={{ width: 1600, height: 1200 }}>
      <WorkflowCanvas
        shapes={shapes}
        views={views}
        laneLabels={labels}
        laneMenus={(head) => {
          const lane = locate(tree, head.parent)?.node.lanes.find(
            (l) => l.port === head.port,
          );
          return lane ? laneMenu(lane) : [];
        }}
        issues={options.issues}
        onToggleFrame={options.toggle === false ? undefined : () => {}}
      />
    </div>,
  );
  return { container, tree, shapes };
}

function card(container: HTMLElement, id: string): HTMLElement {
  const node = container.querySelector<HTMLElement>(
    `.react-flow__node-step[data-id="${id}"]`,
  );
  if (!node) throw new Error(`no card ${id}`);
  return node;
}

function heads(container: HTMLElement): string[] {
  return [...container.querySelectorAll("[data-lane-head]")].map(
    (el) => el.textContent ?? "",
  );
}

describe("frames, their cards and the Điểm nối (F3)", () => {
  it("draws both frames, each headed by its own card", () => {
    const { container } = draw("f3");
    expect(
      container
        .querySelector('[data-frame="tra_cuu"]')
        ?.getAttribute("data-frame-kind"),
    ).toBe("parallel");
    expect(
      container
        .querySelector('[data-frame="lam_giau"]')
        ?.getAttribute("data-frame-kind"),
    ).toBe("loop");
    const loop = card(container, "lam_giau");
    expect(loop.querySelector(".ant-card")).not.toBeNull();
    expect(loop.textContent).toContain(
      "Lặp lại khi !steps.gop.response.complete (tối đa 5 lần)",
    );
    expect(card(container, "tra_cuu").textContent).toContain("Song song");
    // The card's own menu and badges sit at the head of the frame.
    for (const id of ["lam_giau", "tra_cuu"]) {
      const el = card(container, id);
      expect(el.querySelector('[aria-label^="Thao tác «"]'), id).not.toBeNull();
      expect(el.querySelector("[data-stop]"), id).not.toBeNull();
    }
  });

  it("floors the parallel frame with the Chờ tất cả nhánh xong bar", () => {
    const { container } = draw("f3");
    const bar = container.querySelector('[data-join="bar:tra_cuu"]');
    expect(bar?.textContent).toBe("Chờ tất cả nhánh xong");
    expect(bar?.querySelector(".anticon")).not.toBeNull();
  });

  it("names every lane head in words, with Bỏ nhánh on a keyed one only", () => {
    const { container } = draw("f3");
    expect(heads(container)).toEqual(
      expect.arrayContaining([
        "hot",
        "Khác",
        "cong_ty",
        "mang_xa_hoi",
        "lich_su",
        "Đã đủ N lần",
      ]),
    );
    for (const lane of ["hot", "cong_ty", "mang_xa_hoi", "lich_su"]) {
      expect(
        container.querySelector(`[aria-label="Thao tác nhánh «${lane}»"]`),
        lane,
      ).not.toBeNull();
    }
    for (const lane of ["Khác", "Đã đủ N lần"]) {
      expect(
        container.querySelector(`[aria-label="Thao tác nhánh «${lane}»"]`),
        lane,
      ).toBeNull();
    }
  });

  it("folds from the frame's card, and a read-only canvas has no fold at all", () => {
    expect(
      draw("f3").container.querySelector(
        '[aria-label="Thu gọn khung «Tra cứu song song»"]',
      ),
    ).not.toBeNull();
    // The read-only canvas (run screen, publish review) reads no fold, even
    // with this viewer's entry in storage: every frame is open.
    window.localStorage.setItem(
      "wbui.collapsed.u_an.00000000-0000-4000-8000-0000000000a1",
      '["lam_giau","tra_cuu"]',
    );
    const readOnly = draw("f3", { toggle: false }).container;
    window.localStorage.clear();
    expect(readOnly.querySelector("[data-frame-toggle]")).toBeNull();
    expect(readOnly.querySelectorAll("[data-frame]")).toHaveLength(2);
  });
});

describe("a folded frame is its card (R1.7)", () => {
  it("draws the card alone, opens from it, and counts the problems inside", () => {
    const issues = new Map<string, CardIssues>([
      ["lam_giau", { own: [], inside: 2 }],
      ["gop", { own: ["Thiếu biến đầu vào"], inside: 0 }],
    ]);
    const { container } = draw("f3", {
      folded: new Set(["lam_giau"]),
      issues,
    });
    expect(container.querySelector('[data-frame="lam_giau"]')).toBeNull();
    expect(
      container.querySelector('.react-flow__node-step[data-id="gop"]'),
    ).toBeNull();
    const folded = card(container, "lam_giau");
    expect(
      folded.querySelector(
        '[aria-label="Mở khung «Làm giàu dữ liệu tới khi đủ»"]',
      ),
    ).not.toBeNull();
    expect(folded.textContent).toContain("2 lỗi");
    expect(
      folded.querySelector("[data-stop]")?.getAttribute("aria-label"),
    ).toContain("khung đang thu gọn");
  });

  it("an open frame shows only its own problems", () => {
    const issues = new Map<string, CardIssues>([
      ["lam_giau", { own: [], inside: 2 }],
      ["gop", { own: ["Thiếu biến đầu vào"], inside: 0 }],
    ]);
    const { container } = draw("f3", { issues });
    expect(card(container, "lam_giau").textContent).not.toContain("lỗi");
    expect(card(container, "gop").textContent).toContain("1 lỗi");
  });
});

describe("the approver card and its lanes (F5)", () => {
  it("says who approves, the scope, and Cần cả 3 người duyệt", () => {
    const { container } = draw("f5");
    const council = card(container, "duyet_hoi_dong");
    expect(council.textContent).toContain("Cần cả 3 người duyệt");
    expect(council.textContent).toContain(
      "Người duyệt: u_truong_phong, u_ke_toan, u_giam_doc",
    );
    expect(council.textContent).toContain("Phạm vi: studio.leads.approve");
    const lead = card(container, "duyet_bao_gia");
    expect(lead.textContent).not.toContain("Cần");
    expect(heads(container)).toEqual(
      expect.arrayContaining(["Duyệt", "Từ chối"]),
    );
  });
});

describe("a sub-workflow is one card (F10)", () => {
  it("carries its mark, the called workflow's api_name and its wait", () => {
    const { container } = draw("f10");
    expect(container.querySelectorAll(".react-flow__node-step")).toHaveLength(
      4,
    );
    for (const [id, api] of [
      ["kiem_trung", "kiem_lead_trung"],
      ["lam_giau_mot_lan", "lam_giau_lead"],
    ] as const) {
      const el = card(container, id);
      const mark = [...el.querySelectorAll(".ant-tag")].find(
        (t) => t.textContent === "Quy trình con",
      );
      expect(mark, id).toBeDefined();
      expect(mark!.querySelector(".anticon"), id).not.toBeNull();
      expect(el.textContent, id).toContain(api);
      expect(el.textContent, id).toContain("Chờ Quy trình con xong");
    }
  });
});

describe("never a colour without words (BU14)", () => {
  it.each(["f2", "f3", "f4", "f5", "f9", "f10"])(
    "%s: every Tag, lane head and bar the grammar draws has words",
    (name) => {
      const { container } = draw(name);
      const tags = [...container.querySelectorAll(".ant-tag")];
      expect(tags.length).toBeGreaterThan(0);
      for (const tag of tags) {
        expect((tag.textContent ?? "").trim(), tag.outerHTML).not.toBe("");
      }
      for (const bar of container.querySelectorAll('[data-join^="bar:"]')) {
        expect((bar.textContent ?? "").trim()).not.toBe("");
      }
    },
  );
});

describe("an arrow head points along the last segment", () => {
  it("down, left, and none on a zero-length end", () => {
    expect(
      arrowHead([
        { x: 0, y: 0 },
        { x: 0, y: 10 },
      ]),
    ).toBe("M-4.2,4 L0,10 L4.2,4");
    expect(
      arrowHead([
        { x: 10, y: 5 },
        { x: 0, y: 5 },
      ]),
    ).toBe("M6,0.8 L0,5 L6,9.2");
    expect(
      arrowHead([
        { x: 1, y: 1 },
        { x: 1, y: 1 },
      ]),
    ).toBeNull();
  });
});
