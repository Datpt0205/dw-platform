import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// tenant-rbac R2.6: what the web lets a person do is `GET /api/v1/me` of the
// workspace they work in, read again when they switch workspace and when the
// API refuses something; sign-in (`/auth/bootstrap`) names workspaces only.
const me = vi.fn();
vi.mock("../config", () => ({ API_BASE_URL: "", AUTH_MODE: "dev" }));
vi.mock("../keycloak", () => ({ getKeycloak: () => ({}) }));
vi.mock("../../session", () => ({
  ACCESS_REFUSED_EVENT: "dw:access-refused",
  apiClient: () => ({ me }),
  clearActiveWorkspace: vi.fn(),
  clearDevToken: vi.fn(),
  devToken: () => "dev-token",
  purgeLegacyDemoTokens: vi.fn(),
  setActiveWorkspace: vi.fn(),
}));

import { AuthProvider, useAuth } from "../auth-context";

const MEMBERSHIPS = ["ws-a", "ws-b"].map((ws) => ({
  tenant_id: "t-1",
  tenant_slug: "cty",
  tenant_name: "Công ty",
  workspace_id: ws,
  workspace_slug: ws,
  workspace_name: ws,
}));

function access(scopes: string[], bypass = false) {
  return {
    tenant_id: "t-1",
    workspace_id: "ws-a",
    principal_id: "u-1",
    roles: ["member"],
    scopes,
    grants: [],
    access_version: 3,
    platform_bypass: bypass,
    clearance: "internal",
    plan_id: "professional",
    feature_flags: [],
  };
}

function Probe() {
  const { status, hasScope, selectWorkspace } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="decide">{String(hasScope("approvals.decide"))}</span>
      <button onClick={() => selectWorkspace("ws-b")}>B</button>
    </div>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({
        principal_id: "u-1",
        subject: "dev|lan",
        email: null,
        display_name: "Lan",
        memberships: MEMBERSHIPS,
      }),
    })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

async function mounted(): Promise<void> {
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
  await waitFor(() =>
    expect(screen.getByTestId("status").textContent).toBe("ready"),
  );
}

describe("the session's scopes come from /me", () => {
  it("offers a key held only through a permission set, as /me reports it", async () => {
    me.mockResolvedValue(access(["approvals.decide"]));
    await mounted();
    await waitFor(() =>
      expect(screen.getByTestId("decide").textContent).toBe("true"),
    );
  });

  it("reads the bypass from /me, not from a role key", async () => {
    me.mockResolvedValue({ ...access([], true), roles: [] });
    await mounted();
    await waitFor(() =>
      expect(screen.getByTestId("decide").textContent).toBe("true"),
    );
  });

  it("reads /me again on a workspace change, and holds nothing meanwhile", async () => {
    me.mockResolvedValueOnce(access(["approvals.decide"]));
    await mounted();
    await waitFor(() =>
      expect(screen.getByTestId("decide").textContent).toBe("true"),
    );
    let answer: (value: unknown) => void = () => undefined;
    me.mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    act(() => screen.getByText("B").click());
    expect(screen.getByTestId("decide").textContent).toBe("false");
    await act(async () => answer(access([])));
    expect(me).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("decide").textContent).toBe("false");
  });

  it("reads /me again when the API refuses something", async () => {
    me.mockResolvedValueOnce(access(["approvals.decide"]));
    await mounted();
    await waitFor(() =>
      expect(screen.getByTestId("decide").textContent).toBe("true"),
    );
    me.mockResolvedValueOnce(access([]));
    await act(async () => {
      window.dispatchEvent(new Event("dw:access-refused"));
    });
    await waitFor(() =>
      expect(screen.getByTestId("decide").textContent).toBe("false"),
    );
  });
});
