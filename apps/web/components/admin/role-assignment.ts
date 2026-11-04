import type { AdminRole, TenantMember } from "@dw/api-client";

/** Why a role is locked to the caller: `platform.rbac_refusals` refuses them
 * handing it out or taking it away (tenant-rbac R6.1). */
export const LOCKED_ROLE_REASON = "Bạn không giao được vai trò này";

/** What a request that added a role waits for (tenant-rbac R7.1). */
export const SECOND_PERSON_PENDING = "Chờ người thứ hai xác nhận";

export type RolesByKey = ReadonlyMap<string, AdminRole>;

/** Whether the caller may assign this key. A key the catalogue did not
 * answer for counts as locked: it is kept, never dropped by a guess. */
export function isAssignable(key: string, roles: RolesByKey): boolean {
  return roles.get(key)?.assignable_by_me === true;
}

/** The keys among `held` the caller cannot change: sent back as they are. */
export function lockedOf(held: readonly string[], roles: RolesByKey): string[] {
  return held.filter((key) => !isAssignable(key, roles));
}

/** The keys among `held` the caller may change. */
export function assignableOf(
  held: readonly string[],
  roles: RolesByKey,
): string[] {
  return held.filter((key) => isAssignable(key, roles));
}

/**
 * What to send for one membership: every locked key it holds, unchanged, plus
 * what the caller chose among the keys they may assign. A locked key the
 * caller "chose" but does not hold is never added.
 */
export function keepLocked(
  held: readonly string[],
  chosen: readonly string[],
  roles: RolesByKey,
): string[] {
  const next = new Set([
    ...lockedOf(held, roles),
    ...chosen.filter((key) => isAssignable(key, roles)),
  ]);
  return [...next].sort();
}

/**
 * The body of `PUT /api/v1/admin/members/{user_id}/memberships` that changes
 * only `workspaceId`'s roles. The route replaces the person's roles workspace
 * by workspace and drops a workspace left out, so every other workspace goes
 * back exactly as `GET /api/v1/admin/members` read it.
 */
export function membershipsBody(
  member: TenantMember,
  workspaceId: string,
  chosen: readonly string[],
  roles: RolesByKey,
): { workspace_id: string; role_keys: string[] }[] {
  const here = member.memberships.find((m) => m.workspace_id === workspaceId);
  const others = member.memberships
    .filter((m) => m.workspace_id !== workspaceId)
    .map((m) => ({
      workspace_id: m.workspace_id,
      role_keys: [...m.role_keys],
    }));
  return [
    ...others,
    {
      workspace_id: workspaceId,
      role_keys: keepLocked(here?.role_keys ?? [], chosen, roles),
    },
  ];
}
