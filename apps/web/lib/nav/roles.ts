/**
 * Role keys the workbench branches on.
 *
 * A role decides what a user is shown; a scope decides what they may do, and the
 * API checks the scope on every request regardless of what the shell rendered.
 * Hiding a link is therefore navigation, never authorization.
 */

/**
 * How a role key reads to a person: the ONE label table for roles in the web
 * app (session menu, members, hierarchy, dev login, role catalog). The tenant
 * role catalog in the database owns the keys; this owns only the wording, and
 * `__tests__/roles.test.ts` fails when the catalog seeds a key this table does
 * not name.
 *
 * PLUG-IN POINT: a bounded context adds its own roles' labels here, in the same
 * change that seeds them.
 */
const ROLE_LABELS: Record<string, string> = {
  member: "Nhân viên",
  approver: "Người duyệt",
  manager: "Quản lý",
  director: "Giám đốc",
  executive: "Ban điều hành",
  // Naming (2026-09-10): org_admin manages users, roles and settings;
  // platform_admin is the in-tenant role that passes every scope. Neither is
  // the cross-tenant operator who creates tenants (OPERATOR_LABEL).
  org_admin: "Quản trị hệ thống",
  platform_admin: "Quản trị toàn quyền",
};

/** The W1 bypass role's key: the one place the web names it. Whether someone
 * holds the bypass is `GET /api/v1/me`'s `platform_bypass`, never this key. */
export const PLATFORM_ADMIN_ROLE = "platform_admin";

/** How the bypass reads, beside the role it comes from. */
export const BYPASS_LABEL = roleLabel(PLATFORM_ADMIN_ROLE);

/** How a platform operator (creates tenants, ADR-002) is named; not a role key. */
export const OPERATOR_LABEL = "Quản trị nền tảng";

/** What a role with no label and no catalog name reads as: never its code. */
export const UNNAMED_ROLE = "Vai khác";

/**
 * Label for a single role key. A key this table does not name falls back to
 * the name the role catalog gave it, then to a generic label: a raw key like
 * `sc_operator` is never shown to a person.
 */
export function roleLabel(key: string, catalogName?: string): string {
  return ROLE_LABELS[key] ?? catalogName ?? UNNAMED_ROLE;
}

/** Deduplicated, comma-joined labels for a member's role keys. */
export function roleLabels(keys: readonly string[]): string {
  return [...new Set(keys.map((key) => roleLabel(key)))].join(", ");
}
