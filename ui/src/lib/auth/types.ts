import type { CurrentUser } from '@stackframe/stack';

// Base user interface that all providers must support
export interface BaseUser {
  id: string;
  email?: string;
  name?: string;
  image?: string;
}

// Local/OSS user type
export interface LocalUser extends BaseUser {
  provider: 'local';
  organizationId?: string;
  displayName?: string;
  provider_id?: string;
  // Agency-level role from the backend (/auth/me, signup, login). 'owner'
  // sees and can enter every business; 'staff' only assigned ones. Absent on
  // sessions created before the field existed -- treated as staff.
  agencyRole?: 'owner' | 'staff';
}

// Union type for all user types
export type AuthUser = CurrentUser | LocalUser;


export interface AuthToken {
  accessToken: string;
  refreshToken?: string;
  expiresAt?: number;
}

export interface TeamPermission {
  id: string;
}

export type AuthProvider = 'stack' | 'local';

export interface AuthConfig {
  provider: AuthProvider;
  // Provider-specific configuration
  [key: string]: string | number | boolean;
}

