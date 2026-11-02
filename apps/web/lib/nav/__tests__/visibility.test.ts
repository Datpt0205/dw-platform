import { describe, expect, it } from "vitest";
import type { NavItem } from "../types";
import { isNavItemVisible, type NavViewer } from "../visibility";

const Icon = () => null;

function item(overrides: Partial<NavItem>): NavItem {
  return { href: "/x", label: "X", hint: "x", icon: Icon, ...overrides };
}

function viewer(scopes: string[], extra: Partial<NavViewer> = {}): NavViewer {
  return {
    isPlatformOperator: false,
    hasScope: (scope) => scopes.includes(scope),
    ...extra,
  };
}

describe("isNavItemVisible", () => {
  it("shows an anyScope item to a holder of one of its scopes, hides it otherwise", () => {
    const entry = item({ anyScope: ["a.read", "b.read"] });
    expect(isNavItemVisible(entry, viewer(["b.read"]))).toBe(true);
    expect(isNavItemVisible(entry, viewer(["c.read"]))).toBe(false);
    expect(isNavItemVisible(entry, viewer([]))).toBe(false);
  });

  it("needs both when scope and anyScope are declared", () => {
    const entry = item({ scope: "s", anyScope: ["a", "b"] });
    expect(isNavItemVisible(entry, viewer(["s", "a"]))).toBe(true);
    expect(isNavItemVisible(entry, viewer(["a"]))).toBe(false);
    expect(isNavItemVisible(entry, viewer(["s"]))).toBe(false);
  });

  it("hides an empty anyScope: a configuration error fails closed", () => {
    expect(isNavItemVisible(item({ anyScope: [] }), viewer(["a"]))).toBe(false);
  });

  it("keeps scope and operatorOnly as they were", () => {
    expect(isNavItemVisible(item({}), viewer([]))).toBe(true);
    expect(isNavItemVisible(item({ scope: "s" }), viewer(["s"]))).toBe(true);
    expect(isNavItemVisible(item({ scope: "s" }), viewer([]))).toBe(false);
    expect(isNavItemVisible(item({ operatorOnly: true }), viewer(["s"]))).toBe(
      false,
    );
    expect(
      isNavItemVisible(
        item({ operatorOnly: true }),
        viewer([], { isPlatformOperator: true }),
      ),
    ).toBe(true);
  });

  it("reads what the viewer holds, never a role key (tenant-rbac R2.6)", () => {
    // A viewer is what `GET /api/v1/me` says: a scope held through a
    // permission set alone shows the item, whatever role the person has.
    const entry = item({ scope: "approvals.decide" });
    expect(isNavItemVisible(entry, viewer(["approvals.decide"]))).toBe(true);
    expect(isNavItemVisible(entry, viewer([]))).toBe(false);
  });
});
