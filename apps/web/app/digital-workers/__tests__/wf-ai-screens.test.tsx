import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  type AssistantAnswer,
  type DigitalWorker,
  type WorkflowDraft,
  type WorkflowDraftReview,
} from "@dw/api-client";
import type { Approval } from "@dw/contracts";
import { App } from "antd";
import type { ReactElement } from "react";

/**
 * The workflow assistant's page and the publication's approval card over a
 * fake API (wf-ai ticket 04: R7.1, R7.2). Each test runs in a workspace of
 * its own, because the resource cache behind every page is keyed by
 * workspace.
 */

let workspace = "";
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: DW_ID }),
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/approvals",
}));
vi.mock("../../../lib/auth/auth-context", () => ({
  useAuth: () => ({ active: { workspaceId: workspace }, hasScope: () => true }),
}));

const api = {
  getDigitalWorker: vi.fn(),
  getWorkflowDraft: vi.fn(),
  askWorkflowAssistant: vi.fn(),
  saveWorkflowDraft: vi.fn(),
  simulateWorkflowDraft: vi.fn(),
  submitWorkflowDraft: vi.fn(),
  withdrawWorkflowDraft: vi.fn(),
  reviewWorkflowDraft: vi.fn(),
  listApprovals: vi.fn(),
  decideApproval: vi.fn(),
};
vi.mock("../../../lib/session", () => ({ apiClient: () => api }));

import AssistantPage from "../[id]/assistant/page";
import ApprovalsPage from "../../approvals/page";

const DW_ID = "6f1c0000-0000-4000-8000-000000000001";
const SHA = "a".repeat(64);

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

function show(page: ReactElement) {
  return render(<App>{page}</App>);
}

let counter = 0;
function freshWorkspace() {
  counter += 1;
  workspace = `wf-ai-${counter}`;
  api.getDigitalWorker.mockResolvedValue({
    id: DW_ID,
    name: "Chăm sóc lead",
  } as DigitalWorker);
}

afterEach(() => {
  cleanup();
  for (const fn of Object.values(api)) fn.mockReset();
});

function refusal(status: number, reason: string): ApiError {
  return new ApiError(status, {
    code: status === 404 ? "not_found" : "permission_denied",
    message: reason,
    details: { reason_code: reason },
    errors: [],
  });
}

const ADDED = {
  change: "added" as const,
  step_id: "wait_more",
  type: "time.wait@1",
  lane: "approve_send.approved",
  from_lane: null,
};

function proposal(overrides: Partial<AssistantAnswer> = {}): AssistantAnswer {
  return {
    kind: "proposal",
    question: null,
    plan: ["Thêm một lần chờ sau khi gửi thư"],
    steps: [{ id: "draft" }],
    diff: [ADDED],
    problems: [],
    publishable: true,
    outline: [
      {
        id: "draft",
        type: "ai.llm@1",
        description: "Soạn thư chào",
        decision_class: null,
        tool: null,
        lanes: [],
      },
    ],
    ...overrides,
  };
}

function draft(overrides: Partial<WorkflowDraft> = {}): WorkflowDraft {
  return {
    dw_id: DW_ID,
    content: {},
    content_sha256: SHA,
    base_sha256: "b".repeat(64),
    saved_by: "a0000000-0000-4000-8000-00000000000a",
    author_ids: ["a0000000-0000-4000-8000-00000000000a"],
    state: "draft",
    reason: null,
    updated_at: "2026-11-02T02:00:00Z",
    approval_id: null,
    simulation: null,
    ...overrides,
  };
}

const PASSED = {
  content_sha256: SHA,
  outcome: "passed" as const,
  trail: [],
  tool_calls: [{ tool: "email.send@1.0.0", decision_class: "email.send" }],
  failed_step: null,
  error: null,
  created_at: "2026-11-02T02:05:00Z",
};

async function ask(text: string) {
  fireEvent.change(await screen.findByLabelText("Bạn muốn đổi gì?"), {
    target: { value: text },
  });
  fireEvent.click(screen.getByRole("button", { name: /Gửi cho trợ lý/ }));
}

function button(name: RegExp): HTMLButtonElement {
  return screen.getByRole("button", { name }) as HTMLButtonElement;
}

describe("R7.1 the assistant page", () => {
  it("shows the plan, an added step and a problem in words, and locks the save", async () => {
    freshWorkspace();
    api.getWorkflowDraft.mockRejectedValue(refusal(404, "draft_not_found"));
    api.askWorkflowAssistant.mockResolvedValue(
      proposal({
        publishable: false,
        problems: [
          {
            path: "steps/2",
            code: "wf.hitl_gate_missing",
            message_vi: "Bước gửi thư phải nằm sau một bước người duyệt",
            message_en: "a send needs an approval gate",
          },
        ],
      }),
    );
    show(<AssistantPage />);
    await ask("chờ thêm một ngày");
    expect(
      await screen.findByText("Thêm một lần chờ sau khi gửi thư"),
    ).toBeTruthy();
    expect(screen.getByText("Thêm")).toBeTruthy();
    expect(screen.getByText("wait_more")).toBeTruthy();
    expect(screen.getByText(/Khi duyệt của approve_send/)).toBeTruthy();
    expect(
      screen.getByText(/Bước gửi thư phải nằm sau một bước người duyệt/),
    ).toBeTruthy();
    expect(button(/Lưu bản nháp/).disabled).toBe(true);
    expect(
      screen.getByText(
        "Đề xuất còn lỗi nên chưa lưu được; nhờ trợ lý sửa tiếp.",
      ),
    ).toBeTruthy();
    expect(api.askWorkflowAssistant).toHaveBeenCalledWith(DW_ID, {
      instruction: "chờ thêm một ngày",
      history: [],
    });
  });

  it("saves a clean proposal under a fresh key and draws its tree", async () => {
    freshWorkspace();
    api.getWorkflowDraft.mockRejectedValue(refusal(404, "draft_not_found"));
    api.askWorkflowAssistant.mockResolvedValue(proposal());
    api.saveWorkflowDraft.mockResolvedValue(draft());
    show(<AssistantPage />);
    await ask("chờ thêm");
    expect(await screen.findByText("Soạn thư chào")).toBeTruthy();
    expect(button(/Gửi duyệt/).disabled).toBe(true);
    fireEvent.click(button(/Lưu bản nháp/));
    await waitFor(() => expect(api.saveWorkflowDraft).toHaveBeenCalled());
    const [dw, steps, key] = api.saveWorkflowDraft.mock.calls[0] as [
      string,
      unknown,
      string,
    ];
    expect([dw, steps]).toEqual([DW_ID, [{ id: "draft" }]]);
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
    expect(
      await screen.findByText(
        "Chạy mô phỏng bản này và thấy qua trước khi gửi duyệt.",
      ),
    ).toBeTruthy();
  });

  it("opens the submission only after a passed simulation of this content", async () => {
    freshWorkspace();
    api.getWorkflowDraft.mockResolvedValue(
      draft({ simulation: { ...PASSED, content_sha256: "c".repeat(64) } }),
    );
    api.simulateWorkflowDraft.mockResolvedValue(PASSED);
    api.submitWorkflowDraft.mockResolvedValue(
      draft({
        state: "submitted",
        approval_id: "8d6c1f8e-0000-4000-8000-0000000000bb",
        simulation: PASSED,
      }),
    );
    show(<AssistantPage />);
    expect(
      await screen.findByText(/Kết quả này của một bản nháp trước/),
    ).toBeTruthy();
    expect(button(/Gửi duyệt/).disabled).toBe(true);
    fireEvent.click(button(/Chạy mô phỏng/));
    await waitFor(() => expect(button(/Gửi duyệt/).disabled).toBe(false));
    expect(screen.getByText("Qua")).toBeTruthy();
    fireEvent.click(button(/Gửi duyệt/));
    expect(await screen.findByText("Chờ duyệt")).toBeTruthy();
    expect(button(/Rút lại/)).toBeTruthy();
    expect(button(/Chạy mô phỏng/).disabled).toBe(true);
  });

  it("tells a validator the assistant is the owners'", async () => {
    freshWorkspace();
    api.getWorkflowDraft.mockRejectedValue(refusal(403, "not_dw_owner"));
    show(<AssistantPage />);
    expect(
      await screen.findByText(/Chỉ Business Owner hay Technical Owner/),
    ).toBeTruthy();
    expect(button(/Gửi cho trợ lý/).disabled).toBe(true);
  });

  it("says why a decided draft came back", async () => {
    freshWorkspace();
    api.getWorkflowDraft.mockResolvedValue(draft({ reason: "base_changed" }));
    show(<AssistantPage />);
    expect(
      await screen.findByText(/Quy trình đang chạy đã đổi từ khi gửi duyệt/),
    ).toBeTruthy();
  });
});

function publication(overrides: Partial<Approval> = {}): Approval {
  return {
    id: "8d6c1f8e-0000-4000-8000-0000000000bb",
    approval_type: "dw.workflow.publish",
    reason: "Chăm sóc lead: aaaaaaaaaaaa",
    status: "pending",
    run_id: null,
    payload: {
      dw_id: DW_ID,
      content_sha256: SHA,
      base_sha256: "b".repeat(64),
      author_ids: ["a0000000-0000-4000-8000-00000000000a"],
    },
    created_at: "2026-11-02T02:10:00Z",
    decided_at: null,
    requires_comment: true,
    required_scope: null,
    can_decide: true,
    requested_by_me: false,
    ...overrides,
  };
}

function review(
  overrides: Partial<WorkflowDraftReview> = {},
): WorkflowDraftReview {
  return {
    dw_id: DW_ID,
    content_sha256: SHA,
    base_sha256: "b".repeat(64),
    base_current: true,
    author_ids: ["a0000000-0000-4000-8000-00000000000a"],
    state: "submitted",
    approval_id: "8d6c1f8e-0000-4000-8000-0000000000bb",
    diff: [ADDED],
    outline: [],
    simulation: PASSED,
    ...overrides,
  };
}

describe("R7.2 the dw.workflow.publish card", () => {
  it("shows the diff and the passed simulation, and decides with a reason", async () => {
    freshWorkspace();
    api.listApprovals.mockResolvedValue({
      items: [publication()],
      next_cursor: null,
    });
    api.reviewWorkflowDraft.mockResolvedValue(review());
    api.decideApproval.mockResolvedValue(publication({ status: "approved" }));
    show(<ApprovalsPage />);
    expect(
      await screen.findByRole("link", {
        name: "Phát hành quy trình của Chăm sóc lead",
      }),
    ).toBeTruthy();
    expect(await screen.findByText("wait_more")).toBeTruthy();
    expect(screen.getByText("Qua")).toBeTruthy();
    expect(screen.getByText("email.send@1.0.0")).toBeTruthy();
    expect(button(/Duyệt và phát hành/).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Lý do (bắt buộc)"), {
      target: { value: "đã xem mô phỏng" },
    });
    fireEvent.click(button(/Duyệt và phát hành/));
    await waitFor(() =>
      expect(api.decideApproval).toHaveBeenCalledWith(
        "8d6c1f8e-0000-4000-8000-0000000000bb",
        { approve: true, comment: "đã xem mô phỏng" },
      ),
    );
  });

  it("locks both buttons with the reason when can_decide is false", async () => {
    freshWorkspace();
    api.listApprovals.mockResolvedValue({
      items: [publication({ can_decide: false })],
      next_cursor: null,
    });
    api.reviewWorkflowDraft.mockResolvedValue(review());
    show(<ApprovalsPage />);
    expect(await screen.findByText("wait_more")).toBeTruthy();
    expect(button(/Duyệt và phát hành/).disabled).toBe(true);
    expect(button(/Từ chối/).disabled).toBe(true);
    expect(
      screen.getByText(/không phải người đã soạn hay gửi bản nháp, được quyết/),
    ).toBeTruthy();
  });

  it("warns when the draft is no longer the one submitted", async () => {
    freshWorkspace();
    api.listApprovals.mockResolvedValue({
      items: [publication()],
      next_cursor: null,
    });
    api.reviewWorkflowDraft.mockResolvedValue(
      review({ content_sha256: "d".repeat(64), base_current: false }),
    );
    show(<ApprovalsPage />);
    expect(
      await screen.findByText(/Bản nháp đã đổi từ khi gửi duyệt/),
    ).toBeTruthy();
    expect(
      screen.getByText(/đang chạy đã đổi từ khi soạn bản này/),
    ).toBeTruthy();
  });
});
