import type { ComponentType } from "react";

export interface NavItem {
  href: string;
  label: string;
  hint: string;
  /** An `@ant-design/icons` component; drawn `aria-hidden` beside the label. */
  icon: ComponentType<{ "aria-hidden"?: boolean }>;
  exact?: boolean;
  /** Scope required to see this item (omit = always visible). */
  scope?: string;
  /**
   * Shown to a holder of at least one of these scopes, for a page two groups
   * open with different scopes. With `scope` as well, both must hold. An empty
   * list is a configuration error and hides the item. Navigation, not
   * authorization: the API still checks.
   */
  anyScope?: string[];
  /** Key into `useNavBadges()` for a count shown beside the label. */
  badgeKey?: string;
  /** Shown only to a Platform Operator (ADR-002), regardless of scope/role. */
  operatorOnly?: boolean;
}
