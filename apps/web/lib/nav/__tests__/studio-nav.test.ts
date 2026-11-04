import { describe, expect, it } from "vitest";
import { studioNav, studioNavItem } from "../../../app/studio/_meta/nav";
import type { StudioSection } from "../../../app/studio/_meta/sections";
import { NAV_ITEMS } from "../registry";
import { isNavItemVisible, type NavViewer } from "../visibility";

/**
 * The one "Studio" item (studio-skeleton R7.1, R7.2), read the way the menu
 * reads it: through `isNavItemVisible` and a viewer built from what
 * `GET /api/v1/me` says the person holds (tenant-rbac/02), never a role.
 */

function viewer(scopes: string[] | "all"): NavViewer {
  return {
    isPlatformOperator: false,
    hasScope: (scope) => scopes === "all" || scopes.includes(scope),
  };
}

const AREA: StudioSection = {
  key: "object",
  href: "/studio/objects",
  label: "Đối tượng",
  readKey: "studio.objects.read",
};

describe("the Studio nav item", () => {
  it("is in NAV_ITEMS exactly once, labelled Studio (R7.1)", () => {
    const studio = NAV_ITEMS.filter((item) => item.href === "/studio");
    expect(studio).toHaveLength(1);
    expect(studio[0]?.label).toBe("Studio");
  });

  it("shows to a holder of one area's read key, hides from others (R7.2)", () => {
    const item = studioNavItem([AREA]);
    expect(isNavItemVisible(item, viewer([]))).toBe(false);
    expect(isNavItemVisible(item, viewer(["studio.flows.read"]))).toBe(false);
    expect(isNavItemVisible(item, viewer(["studio.objects.read"]))).toBe(true);
  });

  it("is hidden from everyone while no area is registered (R7.2)", () => {
    expect(studioNav).toHaveLength(1);
    const [item] = studioNav;
    expect(item?.anyScope).toEqual([]);
    expect(item && isNavItemVisible(item, viewer("all"))).toBe(false);
    expect(isNavItemVisible(studioNavItem([]), viewer("all"))).toBe(false);
  });
});
