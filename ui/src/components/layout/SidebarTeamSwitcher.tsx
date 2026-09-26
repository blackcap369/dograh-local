"use client";

import type { CurrentUser, Team } from "@stackframe/stack";
import React, { useState } from "react";
import { toast } from "sonner";

import type { OrganizationListItem } from "@/client/types.gen";
import SpinLoader from "@/components/SpinLoader";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useAuth } from "@/lib/auth";
import { reloadApp } from "@/lib/browserReload";
import logger from "@/lib/logger";

const StackTeamSwitcher = React.lazy(() =>
  import("@stackframe/stack").then((mod) => ({
    default: mod.SelectedTeamSwitcher,
  }))
);

export function SidebarTeamSwitcher() {
  const { provider, user } = useAuth();
  const { organizations, orgContext, switchOrganization } = useOrgConfig();

  if (provider === "stack" && user) {
    return <SidebarTeamSwitcherContent user={user as CurrentUser} />;
  }

  if (provider === "local") {
    return (
      <LocalTeamSwitcher
        organizations={organizations}
        currentOrganizationId={orgContext?.organization_id ?? null}
        switchOrganization={switchOrganization}
      />
    );
  }

  return null;
}

function SidebarTeamSwitcherContent({ user }: { user: CurrentUser }) {
  const [isSwitching, setIsSwitching] = useState(false);

  const handleChange = async (team: Team | null) => {
    setIsSwitching(true);
    try {
      await user.setSelectedTeam(team);
      reloadApp();
    } catch (error) {
      logger.error("Failed to switch Stack team", error);
      toast.error("Could not switch teams. Please try again.");
      setIsSwitching(false);
    }
  };

  return (
    <div className="relative">
      <React.Suspense fallback={<div className="h-9 w-full animate-pulse rounded bg-muted" />}>
        <StackTeamSwitcher
          selectedTeam={user.selectedTeam || undefined}
          noUpdateSelectedTeam
          onChange={(team) => {
            void handleChange(team);
          }}
          triggerClassName="w-full"
        />
      </React.Suspense>
      {isSwitching && (
        <div
          className="fixed inset-0 z-[100] flex min-h-screen items-center justify-center bg-background/90 backdrop-blur-sm"
          role="status"
          aria-live="polite"
        >
          <SpinLoader label="Switching teams..." />
        </div>
      )}
    </div>
  );
}

function LocalTeamSwitcher({
  organizations,
  currentOrganizationId,
  switchOrganization,
}: {
  organizations: OrganizationListItem[];
  currentOrganizationId: number | null;
  switchOrganization: (id: number) => Promise<void>;
}) {
  const [isSwitching, setIsSwitching] = useState(false);

  const handleSelect = async (orgId: number) => {
    if (orgId === currentOrganizationId) return;
    setIsSwitching(true);
    try {
      await switchOrganization(orgId);
      reloadApp();
    } catch (error) {
      logger.error("Failed to switch organization", error);
      toast.error(
        error instanceof Error
          ? error.message
          : "Could not switch organization. Please try again."
      );
      setIsSwitching(false);
    }
  };

  // Nothing to show only when the user belongs to no organizations at all. A user
  // with exactly one still sees it, so which organization they are acting in is
  // always visible rather than implied.
  if (!organizations || organizations.length === 0) return null;

  const hasChoices = organizations.length > 1;
  const activeOrganization = organizations.find(
    (org) => org.id === currentOrganizationId
  );
  // Prefer the human label. `name` is null for orgs created before the column
  // existed, and the Stack auth path may not supply one, so provider_id stays
  // as the fallback rather than rendering a blank row.
  const labelFor = (org: { name?: string | null; provider_id: string }) =>
    org.name ?? org.provider_id;

  return (
    <div className="relative">
      <div className="flex items-center gap-2 rounded-lg border bg-background px-2 py-1.5 text-xs">
        <span className="shrink-0 text-muted-foreground">Org</span>
        {hasChoices ? (
          <select
            // Controlled: without this the control displays the first organization
            // in the list regardless of which one is actually active.
            value={currentOrganizationId ?? ""}
            onChange={(e) => void handleSelect(Number(e.target.value))}
            aria-label="Select active organization"
            disabled={isSwitching}
            className="min-w-0 flex-1 truncate rounded bg-background text-xs text-foreground outline-none disabled:opacity-60"
          >
            {currentOrganizationId === null && <option value="">Select an organization</option>}
            {organizations.map((org) => (
              <option key={org.id} value={org.id}>
                {labelFor(org)}
              </option>
            ))}
          </select>
        ) : (
          <span
            className="min-w-0 flex-1 truncate text-foreground"
            title={activeOrganization ? labelFor(activeOrganization) : undefined}
          >
            {activeOrganization ? labelFor(activeOrganization) : "Unknown"}
          </span>
        )}
      </div>
      {isSwitching && (
        <div
          className="fixed inset-0 z-[100] flex min-h-screen items-center justify-center bg-background/90 backdrop-blur-sm"
          role="status"
          aria-live="polite"
        >
          <SpinLoader label="Switching organization..." />
        </div>
      )}
    </div>
  );
}
