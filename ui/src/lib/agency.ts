'use client';

import type { AuthUser, LocalUser } from '@/lib/auth';

/**
 * Whether this account holds the agency owner role.
 *
 * The role rides on the local user object (from /auth/me via the auth
 * cookie). Everything it gates is also enforced server-side -- this helper
 * only decides which buttons render; a non-owner clicking through anyway
 * gets a 403 from the API. Sessions created before the field existed carry
 * no agencyRole and are treated as staff.
 */
export function isAgencyOwner(user: AuthUser | null | undefined): boolean {
  return (user as LocalUser | null | undefined)?.agencyRole === 'owner';
}
