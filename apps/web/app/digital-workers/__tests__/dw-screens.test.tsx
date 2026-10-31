import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  type DigitalWorkerListItem,
  type DwScorecard,
  type WorkflowOutline,
  type WorkItem,
} from "@dw/api-client";
import type { Approval } from "@dw/contracts";
import { App } from "antd";
import type { ReactElement } from "react";

/**
 * The Digital Worker screens over a fake API (digital-worker ticket 04:
 * R9.1-R9.5, DWK21). Each test runs in a workspace of its own, because the
 * resource cache behind every page is keyed by workspace.
 */

let workspace = "";
let search = new URLSearchParams();
const replace = vi.fn((href: string) => {
  search = new URLSearchParams(href.split("?")[1] ?? "");
});
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: DW_ID }),
  useSearchParams: () => search,
  useRouter: () => ({ replace }),
  usePathname: () => "/work",
}));
vi.mock("../../../lib/auth/auth-context", () => ({
  useAuth: () => ({
    active: { workspaceId: workspace },
    hasScope: () => true,
  }),
}));

const api = {
  listDigitalWorkers: vi.fn(),
  getDigitalWorker: vi.fn(),
  getDigitalWorkerWorkflow: vi.fn(),
  getDigitalWorkerScorecard: vi.fn(),
  listWorkItems: vi.fn(),
  getWorkItem: vi.fn(),
  listApprovals: vi.fn(),
  decideApproval: vi.fn(),
  listWorkspaceMembers: vi.fn(),
};
vi.mock("../../../lib/session", () => ({ apiClient: () => api }));

import DigitalWorkersPage from "../page";
import DigitalWorkerPage from "../[id]/page";
import WorkPage from "../../work/page";
import ApprovalsPage from "../../approvals/page";

const DW_ID = "6f1c0000-0000-4000-8000-000000000001";
const PEOPLE = {
  business_owner_id: "a0000000-0000-4000-8000-00000000000a",
  technical_owner_id: "b0000000-0000-4000-8000-00000000000b",
  work_assigner_id: "c0000000-0000-4000-8000-00000000000c",
  validator_id: "d0000000-0000-4000-8000-00000000000d",
};
const MEMBERS = [
  ["a", "Lan Business"],
  ["b", "Minh Kỹ thuật"],
  ["c", "Hà Giao việc"],
  ["d", "Tú Kiểm duyệt"],
].map(([letter, name]) => ({
  user_id: `${letter}0000000-0000-4000-8000-00000000000${letter}`,
  display_name: name,
  email: null,
  role_keys: [],
  department: "",
  permission_set_keys: [],
}));

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

/** Inside antd's `App`, as the shell renders a page: its `message` reports. */
function show(page: ReactElement) {
  return render(<App>{page}</App>);
}

let counter = 0;
function freshWorkspace() {
  counter += 1;
  workspace = `ws-${counter}`;
  search = new URLSearchParams();
  api.listWorkspaceMembers.mockResolvedValue(MEMBERS);
}

afterEach(() => {
  cleanup();
  for (const fn of Object.values(api)) fn.mockReset();
  replace.mockClear();
});

function worker(
  overrides: Partial<DigitalWorkerListItem> = {},
): DigitalWorkerListItem {
  return {
    id: DW_ID,
    key: "lead_care",
    name: "Chăm sóc lead",
    mandate: "Chào lead mới và bàn giao cho sales khi họ trả lời.",
    state: "operating",
    work_kinds: ["marketing.lead"],
    allowed_tools: ["email.send"],
    workflow_key: "lead_care",
    workflow_version: "1.0.0",
    parameters: {},
    principal_user_id: "e0000000-0000-4000-8000-00000000000e",
    role_keys: ["member"],
    people: PEOPLE,
    decision_classes: [
      {
        key: "email.send",
        effect_level: "external",
        reversible: false,
        ceiling: "A2",
        earned_level: "A1",
      },
      {
        key: "work.handoff",
        effect_level: "internal",
        reversible: true,
        ceiling: "A3",
        earned_level: "A3",
      },
    ],
    created_by: PEOPLE.business_owner_id,
    created_at: "2026-10-30T02:00:00Z",
    updated_at: "2026-10-30T02:00:00Z",
    open_items: 4,
    ...overrides,
  };
}

/** The shared forbidden region's own title (`@dw/ui` RegionState). */
const FORBIDDEN_TITLE = "Bạn không có quyền xem mục này";
const FORBIDDEN = new ApiError(403, {
  code: "permission_denied",
  message: "Bạn không có quyền xem Digital Worker.",
  details: {},
  errors: [],
});

describe("R9.1 the list", () => {
  it("shows name, state, mandate and open items for each DW", async () => {
    freshWorkspace();
    api.listDigitalWorkers.mockResolvedValue({
      items: [
        worker(),
        worker({
          id: "6f1c0000-0000-4000-8000-000000000002",
          name: "Nhắc hóa đơn",
          state: "paused",
          mandate: "Nhắc khách thanh toán.",
          open_items: 0,
        }),
      ],
      next_cursor: null,
    });
    show(<DigitalWorkersPage />);
    const first = (
      await screen.findByRole("link", { name: "Chăm sóc lead" })
    ).closest("tr") as HTMLElement;
    expect(within(first).getByText("Đang chạy")).toBeTruthy();
    expect(within(first).getByText(/Chào lead mới/)).toBeTruthy();
    expect(within(first).getByText("4")).toBeTruthy();
    const second = screen
      .getByRole("link", { name: "Nhắc hóa đơn" })
      .closest("tr") as HTMLElement;
    expect(within(second).getByText("Tạm dừng")).toBeTruthy();
    expect(within(second).getByText("0")).toBeTruthy();
    expect(
      screen.getAllByRole("columnheader").map((cell) => cell.textContent),
    ).toEqual(["Tên", "Trạng thái", "Nhiệm vụ", "Việc đang mở"]);
  });

  it("DWK21: a 403 shows no row, only the no-access state", async () => {
    freshWorkspace();
    api.listDigitalWorkers.mockRejectedValue(FORBIDDEN);
    show(<DigitalWorkersPage />);
    expect(await screen.findByText(FORBIDDEN_TITLE)).toBeTruthy();
    expect(screen.queryAllByRole("row")).toHaveLength(0);
    expect(screen.queryByText("Chăm sóc lead")).toBeNull();
  });
});

const OUTLINE: WorkflowOutline = {
  dw_id: DW_ID,
  key: "lead_care",
  version: "1.0.0",
  sha256: "ab".repeat(32),
  steps: [
    {
      id: "draft",
      type: "ai.llm@1",
      description: "Soạn thư đầu tiên",
      decision_class: null,
      tool: null,
      lanes: [],
    },
    {
      id: "approve_send",
      type: "human.approval@1",
      description: "Duyệt thư gửi lead",
      decision_class: "email.send",
      tool: null,
      lanes: [
        {
          port: "approved",
          steps: [
            {
              id: "send",
              type: "tool.call@1",
              description: null,
              decision_class: "email.send",
              tool: "email.send@1.0.0",
              lanes: [],
            },
          ],
        },
        {
          port: "rejected",
          steps: [
            {
              id: "handoff_rejected",
              type: "tool.call@1",
              description: null,
              decision_class: "work.handoff",
              tool: "work.handoff@1.0.0",
              lanes: [],
            },
          ],
        },
      ],
    },
  ],
  decision_classes: [
    { key: "email.send", effective_level: "A1", mode: "ask" },
    { key: "work.handoff", effective_level: "A3", mode: "blocked" },
  ],
};

const SCORECARD: DwScorecard = {
  dw_id: DW_ID,
  days: 30,
  since: "2026-10-01T00:00:00Z",
  items: {
    by_status: { done: 6, handed_off: 2 },
    total: 10,
    done_alone_rate: 0.6,
    handed_off_rate: 0.2,
  },
  decisions: { approved_as_is: 5, approved_edited: 2, rejected: 1 },
  model_cost_usd: "1.234560",
};

describe("R9.2 the profile", () => {
  it("shows the four people, each class's three levels in words, the scorecard and every step", async () => {
    freshWorkspace();
    api.getDigitalWorker.mockResolvedValue(worker());
    api.getDigitalWorkerWorkflow.mockResolvedValue(OUTLINE);
    api.getDigitalWorkerScorecard.mockResolvedValue(SCORECARD);
    show(<DigitalWorkerPage />);

    for (const name of [
      "Lan Business",
      "Minh Kỹ thuật",
      "Hà Giao việc",
      "Tú Kiểm duyệt",
    ])
      expect(await screen.findByText(name)).toBeTruthy();

    const send = (await screen.findByText("Hỏi")).closest("tr") as HTMLElement;
    expect(within(send).getByText("email.send")).toBeTruthy();
    expect(within(send).getByText("A2")).toBeTruthy();
    expect(within(send).getAllByText("A1")).toHaveLength(2);
    const handoff = screen.getByText("Chặn").closest("tr") as HTMLElement;
    expect(within(handoff).getByText("work.handoff")).toBeTruthy();
    expect(within(handoff).getAllByText("A3")).toHaveLength(3);

    expect(screen.getByText("10")).toBeTruthy();
    expect(screen.getByText("60%")).toBeTruthy();
    expect(screen.getByText("20%")).toBeTruthy();
    expect(screen.getByText("1,23 USD")).toBeTruthy();

    for (const step of ["draft", "approve_send", "send", "handoff_rejected"])
      expect(screen.getAllByText(step).length).toBeGreaterThan(0);
    expect(screen.getByText("Khi duyệt")).toBeTruthy();
    expect(screen.getByText("Khi từ chối")).toBeTruthy();
    expect(api.getDigitalWorkerScorecard).toHaveBeenCalledWith(DW_ID, 30);
  });

  it("DWK21: a 403 or a 404 shows that state and no data", async () => {
    for (const [refusal, title] of [
      [FORBIDDEN, FORBIDDEN_TITLE],
      [
        new ApiError(404, {
          code: "not_found",
          message: "Không tìm thấy Digital Worker.",
          details: {},
          errors: [],
        }),
        "Không tìm thấy",
      ],
    ] as const) {
      freshWorkspace();
      api.getDigitalWorker.mockRejectedValue(refusal);
      api.getDigitalWorkerWorkflow.mockResolvedValue(OUTLINE);
      api.getDigitalWorkerScorecard.mockResolvedValue(SCORECARD);
      show(<DigitalWorkerPage />);
      expect(await screen.findByText(title)).toBeTruthy();
      expect(screen.getAllByText(refusal.body.message).length).toBeGreaterThan(
        0,
      );
      expect(screen.queryAllByRole("row")).toHaveLength(0);
      expect(api.getDigitalWorkerWorkflow).not.toHaveBeenCalled();
      expect(api.getDigitalWorkerScorecard).not.toHaveBeenCalled();
      cleanup();
    }
  });
});

const HANDED: WorkItem = {
  id: "71000000-0000-4000-8000-000000000001",
  dw_id: DW_ID,
  kind: "marketing.lead",
  source_key: "form-7",
  status: "handed_off",
  holder_kind: "person",
  holder_id: PEOPLE.validator_id,
  available_at: "2026-10-30T02:00:00Z",
  created_at: "2026-10-30T02:00:00Z",
  closed_at: null,
  updated_at: "2026-10-30T02:00:00Z",
  wake_at: null,
  error: null,
  payload: null,
  handoff: null,
  trail: null,
};

describe("R9.3 the work queue", () => {
  it("filters by handed_off and opens the item with its packet and trail", async () => {
    freshWorkspace();
    api.listWorkItems.mockImplementation(
      async (params: { status?: string | null }) => ({
        items:
          params.status === "handed_off"
            ? [HANDED]
            : [
                HANDED,
                { ...HANDED, id: "x", source_key: "form-8", status: "open" },
              ],
        next_cursor: null,
      }),
    );
    const view = show(<WorkPage />);
    expect(await screen.findByText(/form-8/)).toBeTruthy();

    // The filter lives in the URL: choosing it replaces the query.
    search = new URLSearchParams("status=handed_off");
    view.rerender(
      <App>
        <WorkPage />
      </App>,
    );
    await screen.findByText("Đã bàn giao");
    expect(screen.queryByText(/form-8/)).toBeNull();
    expect(api.listWorkItems).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: "handed_off" }),
    );

    api.getWorkItem.mockResolvedValue({
      ...HANDED,
      handoff: {
        problem: "Khách hỏi giá đặc biệt",
        context: "Lead từ hội chợ",
        tried: "Gửi bảng giá chuẩn",
        recommendation: "Gọi lại trong hôm nay",
      },
      trail: [
        {
          step_id: "score",
          type: "ai.llm@1",
          status: "ok",
          at: "2026-10-30T02:01:00Z",
        },
        {
          step_id: "handoff_reply",
          type: "tool.call@1",
          status: "ok",
          at: "2026-10-30T02:05:00Z",
        },
      ],
    });
    search = new URLSearchParams(`status=handed_off&item=${HANDED.id}`);
    view.rerender(
      <App>
        <WorkPage />
      </App>,
    );
    for (const text of [
      "Khách hỏi giá đặc biệt",
      "Lead từ hội chợ",
      "Gửi bảng giá chuẩn",
      "Gọi lại trong hôm nay",
    ])
      expect(await screen.findByText(text)).toBeTruthy();
    expect(screen.getByText("score")).toBeTruthy();
    expect(screen.getByText("handoff_reply")).toBeTruthy();
  });

  it("choosing a status writes it into the URL", async () => {
    freshWorkspace();
    api.listWorkItems.mockResolvedValue({ items: [HANDED], next_cursor: null });
    show(<WorkPage />);
    await screen.findByText(/form-7/);
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Trạng thái" }));
    fireEvent.click(await screen.findByTitle("Đã bàn giao"));
    expect(replace).toHaveBeenCalledWith("/work?status=handed_off", {
      scroll: false,
    });
  });

  it("DWK21: a 403 shows no row", async () => {
    freshWorkspace();
    api.listWorkItems.mockRejectedValue(FORBIDDEN);
    show(<WorkPage />);
    expect(await screen.findByText(FORBIDDEN_TITLE)).toBeTruthy();
    expect(screen.queryAllByRole("row")).toHaveLength(0);
  });
});

function decision(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "8d6c1f8e-0000-4000-8000-0000000000aa",
    approval_type: "dw.decision",
    reason: "Thư đầu tiên gửi lead mới",
    status: "pending",
    run_id: "9e000000-0000-4000-8000-000000000001",
    payload: {
      dw_id: DW_ID,
      decision_class: "email.send",
      effective_level: "A1",
      proposal: {
        to: "an@khach.vn",
        subject: "Chào anh An, cảm ơn đã quan tâm",
        body: "Nội dung thư chào.",
      },
      proposal_schema: {
        type: "object",
        properties: {
          to: { type: "string" },
          subject: { type: "string", maxLength: 150 },
          body: { type: "string", maxLength: 4000 },
        },
      },
      locked_fields: ["to"],
    },
    created_at: "2026-10-30T02:00:00Z",
    decided_at: null,
    requires_comment: false,
    required_scope: null,
    can_decide: true,
    requested_by_me: false,
    ...overrides,
  };
}

describe("R9.4 the dw.decision card", () => {
  it("shows the DW, the class, the effective level and the proposed subject", async () => {
    freshWorkspace();
    api.listApprovals.mockResolvedValue({
      items: [decision()],
      next_cursor: null,
    });
    api.getDigitalWorker.mockResolvedValue(worker());
    show(<ApprovalsPage />);
    expect(
      await screen.findByText("Chào anh An, cảm ơn đã quan tâm"),
    ).toBeTruthy();
    expect(screen.getByText("A1")).toBeTruthy();
    expect(screen.getByText("email.send")).toBeTruthy();
    expect(
      await screen.findByRole("link", { name: "Chăm sóc lead" }),
    ).toBeTruthy();
  });

  it("rejecting needs a reason, and edit-then-approve sends the edit with the locked field kept", async () => {
    freshWorkspace();
    api.listApprovals.mockResolvedValue({
      items: [decision()],
      next_cursor: null,
    });
    api.getDigitalWorker.mockResolvedValue(worker());
    api.decideApproval.mockResolvedValue(decision({ status: "approved" }));
    show(<ApprovalsPage />);
    const reject = await screen.findByRole("button", { name: /Từ chối/ });
    expect((reject as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /Sửa rồi duyệt/ }));
    const to = screen.getByLabelText("Người nhận") as HTMLInputElement;
    expect(to.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Tiêu đề"), {
      target: { value: "Tiêu đề đã sửa" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Duyệt bản đã sửa/ }));
    await vi.waitFor(() => expect(api.decideApproval).toHaveBeenCalled());
    expect(api.decideApproval).toHaveBeenCalledWith(decision().id, {
      approve: true,
      comment: "",
      edited_proposal: {
        to: "an@khach.vn",
        subject: "Tiêu đề đã sửa",
        body: "Nội dung thư chào.",
      },
    });
  });

  it("a viewer the server will not let decide sees the buttons locked with the reason", async () => {
    freshWorkspace();
    api.listApprovals.mockResolvedValue({
      items: [decision({ can_decide: false, payload: { dw_id: DW_ID } })],
      next_cursor: null,
    });
    api.getDigitalWorker.mockResolvedValue(worker());
    show(<ApprovalsPage />);
    const approve = await screen.findByRole("button", { name: /^Duyệt$/ });
    expect((approve as HTMLButtonElement).disabled).toBe(true);
    expect(
      screen.getByText("Chỉ người của Digital Worker này đọc được đề xuất."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Sửa rồi duyệt/ })).toBeNull();
  });
});
