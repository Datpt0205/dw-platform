import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { ApiError, type StudioArtifact } from "@dw/api-client";
import { App } from "antd";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * `/studio` over a fake client (studio-skeleton R7.3): the artifacts the
 * route returns, keyset pages appended by "Tải thêm", times in Vietnam's, and
 * the shared region states for a refusal and for nothing at all. Each test runs
 * in a workspace of its own, because the page cache is keyed by workspace.
 */

let workspace = "";
vi.mock("next/navigation", () => ({ usePathname: () => "/studio" }));
vi.mock("../../../lib/auth/auth-context", () => ({
  useAuth: () => ({ active: { workspaceId: workspace } }),
}));
const api = { listStudioArtifacts: vi.fn() };
vi.mock("../../../lib/session", () => ({ apiClient: () => api }));

import StudioLayout from "../layout";
import StudioPage from "../page";

let counter = 0;
function freshWorkspace() {
  counter += 1;
  workspace = `ws-${counter}`;
}

function artifact(apiName: string, overrides: Partial<StudioArtifact> = {}) {
  return {
    id: `id-${apiName}`,
    kind: "object",
    api_name: apiName,
    owning_workspace_id: "w-1",
    labels: [],
    last_version_no: 3,
    version: 1,
    created_at: "2026-11-01T00:00:00Z",
    // 17:05 UTC is 00:05 the next day in Asia/Ho_Chi_Minh.
    updated_at: "2026-11-03T17:05:00Z",
    ...overrides,
  };
}

function show() {
  render(
    <App>
      <StudioLayout>
        <StudioPage />
      </StudioLayout>
    </App>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the /studio list (R7.3)", { timeout: 20_000 }, () => {
  it("shows each artifact's API name and its update time in Vietnam's time", async () => {
    freshWorkspace();
    api.listStudioArtifacts.mockResolvedValue({
      items: [artifact("lead_scoring")],
      next_cursor: null,
    });
    show();
    expect(await screen.findByText("lead_scoring")).toBeTruthy();
    expect(screen.getByText("04/11/2026 00:05")).toBeTruthy();
    // No label registered for the kind yet: its own code.
    expect(screen.getByText("object")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Tải thêm" })).toBeNull();
    expect(
      screen.getByRole("navigation", { name: "Khu vực Studio" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Tất cả thành phần" }),
    ).toBeTruthy();
  });

  it("appends the second page on Tải thêm", async () => {
    freshWorkspace();
    api.listStudioArtifacts.mockImplementation(
      ({ cursor }: { cursor: string | null }) =>
        Promise.resolve(
          cursor === null
            ? { items: [artifact("first_one")], next_cursor: "c1" }
            : { items: [artifact("second_one")], next_cursor: null },
        ),
    );
    show();
    expect(await screen.findByText("first_one")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Tải thêm" }));
    expect(await screen.findByText("second_one")).toBeTruthy();
    expect(screen.getByText("first_one")).toBeTruthy();
    expect(api.listStudioArtifacts).toHaveBeenLastCalledWith({ cursor: "c1" });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Tải thêm" })).toBeNull(),
    );
  });

  it("draws the forbidden state for permission_denied, not an empty table", async () => {
    freshWorkspace();
    api.listStudioArtifacts.mockRejectedValue(
      new ApiError(403, {
        code: "permission_denied",
        message: "Bạn không có quyền xem thành phần Studio.",
        details: {},
        errors: [],
      }),
    );
    show();
    expect(
      await screen.findByText("Bạn không có quyền xem mục này"),
    ).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText("Chưa có thành phần nào")).toBeNull();
  });

  it("draws the empty state for an empty last page", async () => {
    freshWorkspace();
    api.listStudioArtifacts.mockResolvedValue({ items: [], next_cursor: null });
    show();
    expect(await screen.findByText("Chưa có thành phần nào")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
