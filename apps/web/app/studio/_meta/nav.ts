import { AppstoreOutlined } from "@ant-design/icons";
import type { NavItem } from "../../../lib/nav/types";
import { t } from "./messages";
import { STUDIO_SECTIONS, type StudioSection } from "./sections";

/**
 * The one "Studio" item of the top navigation (R7.1), shown to a holder of at
 * least one area's read key (R7.2). With no area, `anyScope` is empty and
 * `isNavItemVisible` hides the item from everyone: an empty list fails closed.
 * Navigation, not authorization: `GET /api/v1/studio/artifacts` still filters
 * by each kind's read key.
 */
export function studioNavItem(sections: readonly StudioSection[]): NavItem {
  return {
    href: "/studio",
    label: t("nav.label"),
    hint: t("nav.hint"),
    icon: AppstoreOutlined,
    anyScope: sections.map((section) => section.readKey),
  };
}

export const studioNav: NavItem[] = [studioNavItem(STUDIO_SECTIONS)];
