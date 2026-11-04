'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

import SpinLoader from '@/components/SpinLoader';
import { useMode } from '@/context/ModeContext';
import { useAuth } from '@/lib/auth';

/**
 * Guard for Creative Mode pages. Renders `children` only once the visitor is
 * authenticated AND the workspace is in creative mode; an organization-mode
 * visitor (or a stale bookmark) is sent to /overview, an unauthenticated one
 * to login.
 *
 * Two waits here are load-bearing:
 *
 * - `hydrated`: until ModeContext has read localStorage every visitor reads as
 *   'organization', so acting before hydration would kick a creative-mode user
 *   off the page on every hard reload.
 * - `auth.loading`: the API client's Authorization header is attached by
 *   OrgConfigProvider once auth resolves. Children fetch on mount, so rendering
 *   them before that point fires requests with no credentials -- which is how
 *   a hard reload of /creative/clients ended in "Authorization header required".
 *   Same fetch-gating convention as /usage and /api-keys, centralized here.
 */
export function CreativePageGate({ children }: { children: React.ReactNode }) {
  const { mode, hydrated } = useMode();
  const { loading: authLoading, isAuthenticated, redirectToLogin } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (hydrated && mode !== 'creative') {
      router.replace('/overview');
    }
  }, [hydrated, mode, router]);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      redirectToLogin();
    }
  }, [authLoading, isAuthenticated, redirectToLogin]);

  if (!hydrated || authLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <SpinLoader />
      </div>
    );
  }
  if (!isAuthenticated || mode !== 'creative') {
    return null;
  }

  return <>{children}</>;
}
