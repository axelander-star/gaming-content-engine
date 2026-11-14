import type { UserRole } from "./types";

const RANK: Record<UserRole, number> = { viewer: 0, operator: 1, admin: 2 };

/** True if `role` is at least `minimum`. The backend enforces the same rule. */
export function hasRole(role: UserRole | undefined, minimum: UserRole): boolean {
  return role !== undefined && RANK[role] >= RANK[minimum];
}

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Admin",
  operator: "Operator",
  viewer: "Betrachter",
};
