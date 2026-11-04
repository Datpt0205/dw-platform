import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App } from "antd";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AdminRole, TenantMember } from "@dw/api-client";

const listWorkspaceMembers = vi.fn();
const listGrantCandidates = vi.fn();
const listAdminRoles = vi.fn();
const listTenantMembers = vi.fn();
const setMemberships = vi.fn();
const setMemberPermissionSets = vi.fn();
const grantMember = vi.fn();
vi.mock("../../../lib/session", () => ({
  apiClient: () => ({
    listWorkspaceMembers,
    listGrantCandidates,
    listAdminRoles,
    listTenantMembers,
    setMemberships,
    setMemberPermissionSets,
    grantMember,
    revokeMember: vi.fn(),
  }),
}));
vi.mock("../../../lib/auth/auth-context", () => ({
  useAuth: () => ({
    active: { workspaceId: "w-1", workspaceName: "Kinh doanh" },
  }),
}));

import { MembersManager } from "../members-manager";
import {
  LOCKED_ROLE_REASON,
  keepLocked,
  membershipsBody,
} from "../role-assignment";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function role(
  key: string,
  name: string,
  assignable: boolean,
  kind = "role",
): AdminRole {
  return {
    id: `r-${key}`,
    key,
    name,
    description: null,
    kind,
    is_system: true,
    template_key: key,
    holder_count: 1,
    version: 1,
    assignable_by_me: assignable,
    updated_at: "2026-11-01T00:00:00Z",
  };
}

const ROLES = [
  role("member", "Nhân viên", true),
  role("approver", "Người duyệt", true),
  role("org_admin", "Quản trị hệ thống", false),
  role("approver_boost", "Duyệt nhanh", false, "permission_set"),
];
const BY_KEY = new Map(ROLES.map((r) => [r.key, r]));

const LAN: TenantMember = {
  user_id: "u-1",
  display_name: "Lan",
  email: "lan@acme.vn",
  status: "active",
  memberships: [
    {
      workspace_id: "w-1",
      workspace_name: "Kinh doanh",
      role_keys: ["member", "org_admin"],
    },
    { workspace_id: "w-2", workspace_name: "Kho", role_keys: ["approver"] },
  ],
};

describe("what a role change sends", () => {
  it("keeps a locked role the person holds and never adds one", () => {
    expect(
      keepLocked(["member", "org_admin"], ["approver", "org_admin"], BY_KEY),
    ).toEqual(["approver", "org_admin"]);
    expect(keepLocked(["member"], ["org_admin"], BY_KEY)).toEqual([]);
  });

  it("keeps a key the catalogue did not answer for", () => {
    expect(keepLocked(["sc_operator"], [], BY_KEY)).toEqual(["sc_operator"]);
  });

  it("changes only the active workspace and sends the others back", () => {
    expect(membershipsBody(LAN, "w-1", ["approver"], BY_KEY)).toEqual([
      { workspace_id: "w-2", role_keys: ["approver"] },
      { workspace_id: "w-1", role_keys: ["approver", "org_admin"] },
    ]);
  });
});

// antd's Select in jsdom takes seconds under a full parallel run.
describe("the members manager", { timeout: 20_000 }, () => {
  function arrange() {
    listWorkspaceMembers.mockResolvedValue([
      {
        user_id: "u-1",
        display_name: "Lan",
        email: "lan@acme.vn",
        role_keys: ["member", "org_admin"],
        department: "general",
        permission_set_keys: [],
      },
    ]);
    listGrantCandidates.mockResolvedValue([]);
    listAdminRoles.mockResolvedValue(ROLES);
    listTenantMembers.mockResolvedValue([LAN]);
    render(
      <App>
        <MembersManager />
      </App>,
    );
  }

  it("shows a role the caller cannot assign locked, with the reason", async () => {
    arrange();
    expect(
      await screen.findByText(new RegExp(`${LOCKED_ROLE_REASON}: Quản trị`)),
    ).toBeTruthy();
    expect(screen.getAllByText("Quản trị hệ thống").length).toBeGreaterThan(0);
  });

  it("sends the locked role back as it is and says a second person must confirm", async () => {
    setMemberships.mockResolvedValue({
      user_id: "u-1",
      memberships: LAN.memberships,
      applied: [],
      proposals: ["p-1"],
    });
    arrange();
    await screen.findByText(new RegExp(LOCKED_ROLE_REASON));

    fireEvent.click(screen.getByRole("button", { name: /Lưu$/ }));

    await waitFor(() =>
      expect(setMemberships).toHaveBeenCalledWith("u-1", [
        { workspace_id: "w-2", role_keys: ["approver"] },
        { workspace_id: "w-1", role_keys: ["member", "org_admin"] },
      ]),
    );
    expect(await screen.findByText("Chờ người thứ hai xác nhận")).toBeTruthy();
  });

  it("offers a role the caller cannot assign only as a disabled option", async () => {
    arrange();
    await screen.findByText(new RegExp(LOCKED_ROLE_REASON));
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Vai của Lan" }));
    const locked = await screen.findByTitle(
      `Quản trị hệ thống: ${LOCKED_ROLE_REASON}`,
    );
    expect(locked.className.includes("ant-select-item-option-disabled")).toBe(
      true,
    );
  });
});
