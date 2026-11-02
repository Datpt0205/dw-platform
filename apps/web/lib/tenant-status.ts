/**
 * A tenant's status as a person reads it (`ck_tenants_status` owns the set).
 * An unknown value — a status added to the database before this table —
 * reads as "Trạng thái khác", never as the raw code.
 */
const TENANT_STATUS: Record<string, { label: string; color: string }> = {
  // Created with two owners, opened when the second signs in (tenant-rbac R3.1).
  setup: { label: "Đang thiết lập", color: "processing" },
  active: { label: "Đang hoạt động", color: "success" },
  locked: { label: "Đã khóa", color: "error" },
  offboarding: { label: "Đang rời nền tảng", color: "warning" },
  offboarded: { label: "Đã rời nền tảng", color: "default" },
};

export function tenantStatus(status: string): { label: string; color: string } {
  return (
    TENANT_STATUS[status] ?? { label: "Trạng thái khác", color: "default" }
  );
}

/** The tag of a tenant whose owner keys fell below two holders (R3.13). */
export const OWNER_COVERAGE_LOW = { label: "Dưới hai người", color: "warning" };

export type TenantFilter = "all" | "setup" | "owner_coverage_low";

/** The operators' filters on the tenant list (tenant-rbac R3.13). */
export const TENANT_FILTERS: { value: TenantFilter; label: string }[] = [
  { value: "all", label: "Tất cả" },
  { value: "setup", label: "Đang thiết lập" },
  { value: "owner_coverage_low", label: OWNER_COVERAGE_LOW.label },
];

export function filterTenants<
  T extends { status: string; owner_coverage_low_since: string | null },
>(tenants: readonly T[], filter: TenantFilter): T[] {
  if (filter === "setup") return tenants.filter((t) => t.status === "setup");
  if (filter === "owner_coverage_low")
    return tenants.filter((t) => t.owner_coverage_low_since !== null);
  return [...tenants];
}
