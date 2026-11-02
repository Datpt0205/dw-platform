import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { afterEach, describe, expect, it, vi } from "vitest";

// tenant-rbac R3.13: the operators list the companies still in `setup` and
// those whose owner keys fell below two holders.
const listTenants = vi.fn();
const createTenant = vi.fn();
vi.mock("../../../lib/session", () => ({
  apiClient: () => ({
    listTenants,
    createTenant,
    listOperators: vi.fn().mockResolvedValue([]),
    listPlatformUsers: vi.fn().mockResolvedValue([]),
  }),
}));
vi.mock("../../../lib/auth/auth-context", () => ({
  useAuth: () => ({ isPlatformOperator: true, principalId: "op-1" }),
}));
vi.mock("../../../components/platform/support-console", () => ({
  SupportConsole: () => null,
}));

import PlatformPage from "../page";

function tenant(
  name: string,
  status: string,
  ownerCoverageLowSince: string | null = null,
) {
  return {
    id: `t-${name}`,
    slug: name.toLowerCase(),
    name,
    status,
    plan_id: "professional",
    workspace_count: 1,
    member_count: 2,
    created_at: "2026-11-01T00:00:00Z",
    owner_coverage_low_since: ownerCoverageLowSince,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function shownNames(): Promise<string[]> {
  const card = screen
    .getByText("Công ty", { selector: ".ant-card-head-title" })
    .closest(".ant-card") as HTMLElement;
  return within(card)
    .queryAllByRole("row")
    .slice(1)
    .map((row) => row.querySelector("strong")?.textContent ?? "");
}

describe("the operators' tenant list", { timeout: 20_000 }, () => {
  it("filters the companies in setup and those below two owners", async () => {
    listTenants.mockResolvedValue([
      tenant("Alpha", "active"),
      tenant("Beta", "setup"),
      tenant("Gamma", "active", "2026-11-02T03:00:00Z"),
    ]);
    render(
      <App>
        <PlatformPage />
      </App>,
    );
    await waitFor(async () =>
      expect(await shownNames()).toEqual(["Alpha", "Beta", "Gamma"]),
    );
    expect(
      screen.getByText("Đang thiết lập", { selector: ".ant-tag" }),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByText("Đang thiết lập", {
        selector: ".ant-segmented-item-label",
      }),
    );
    await waitFor(async () => expect(await shownNames()).toEqual(["Beta"]));

    fireEvent.click(
      screen.getByText("Dưới hai người", {
        selector: ".ant-segmented-item-label",
      }),
    );
    await waitFor(async () => expect(await shownNames()).toEqual(["Gamma"]));
  });

  it("creates a company only with two owners", async () => {
    listTenants.mockResolvedValue([]);
    createTenant.mockResolvedValue({
      tenant_id: "t-new",
      workspace_id: "w-new",
      slug: "moi",
      name: "Mới",
      status: "setup",
    });
    render(
      <App>
        <PlatformPage />
      </App>,
    );
    const create = screen.getByRole("button", { name: /Tạo/ });
    fireEvent.change(screen.getByLabelText("Tên"), {
      target: { value: "Mới" },
    });
    fireEvent.change(screen.getByLabelText("Chủ sở hữu 1"), {
      target: { value: "a@cty.vn" },
    });
    expect((create as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Chủ sở hữu 2"), {
      target: { value: "b@cty.vn" },
    });
    expect((create as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(create);
    await waitFor(() => expect(createTenant).toHaveBeenCalledTimes(1));
    expect(createTenant.mock.calls[0]![0].owners).toEqual([
      "a@cty.vn",
      "b@cty.vn",
    ]);
  });
});
