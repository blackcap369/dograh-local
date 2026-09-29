"use client";

import type { CurrentUser, Team } from "@stackframe/stack";
import React, { useState } from "react";
import { toast } from "sonner";

import type { OrganizationListItem } from "@/client/types.gen";
import SpinLoader from "@/components/SpinLoader";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  const { organizations, orgContext, switchOrganization, createOrganization } =
    useOrgConfig();

  if (provider === "stack" && user) {
    return <SidebarTeamSwitcherContent user={user as CurrentUser} />;
  }

  if (provider === "local") {
    return (
      <LocalTeamSwitcher
        organizations={organizations}
        currentOrganizationId={orgContext?.organization_id ?? null}
        switchOrganization={switchOrganization}
        createOrganization={createOrganization}
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
  createOrganization,
}: {
  organizations: OrganizationListItem[];
  currentOrganizationId: number | null;
  switchOrganization: (id: number) => Promise<void>;
  createOrganization: (name: string) => Promise<OrganizationListItem>;
}) {
  const [isSwitching, setIsSwitching] = useState(false);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

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

  const handleCreate = async () => {
    // Manual guard rather than disabling the button: with the button disabled on an
    // empty field there is no way to tell "nothing typed yet" from "the form is
    // broken", and the api-keys page sets an explicit message instead.
    const trimmed = newName.trim();
    if (!trimmed) {
      setCreateError("Please enter a name for the business");
      return;
    }

    try {
      setCreateError(null);
      setIsCreating(true);
      const created = await createOrganization(trimmed);
      setIsCreateOpen(false);
      setNewName("");
      toast.success(`Created "${created.name ?? created.provider_id}"`);
      // The list is refreshed inside createOrganization, so the dropdown would
      // already show the new option -- but the *active* business has not changed,
      // and every page has already loaded data scoped to it. Reloading keeps the
      // sidebar label and the rest of the app in agreement about what is loaded.
      reloadApp();
    } catch (error) {
      logger.error("Failed to create organization", error);
      setCreateError(
        error instanceof Error
          ? error.message
          : "Could not create the business. Please try again."
      );
      setIsCreating(false);
    }
  };

  // Prefer the human label. `name` is null for orgs created before the column
  // existed, and the Stack auth path may not supply one, so provider_id stays
  // as the fallback rather than rendering a blank row.
  const labelFor = (org: { name?: string | null; provider_id: string }) =>
    org.name ?? org.provider_id;

  const orgList = organizations ?? [];
  const hasChoices = orgList.length > 1;
  const activeOrganization = orgList.find(
    (org) => org.id === currentOrganizationId
  );

  return (
    <div className="relative space-y-1">
      {/*
        The switcher itself is still hidden at zero organizations -- there is nothing
        to select and no active business to name. The "New business" button is NOT
        nested inside it: a user with exactly one business was previously shown a
        read-only <span> rather than a <select>, so an affordance placed in here
        would have been unreachable for exactly the people who need it most -- an
        agency operator on their first client who is about to add their second.
      */}
      {orgList.length > 0 && (
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
              {currentOrganizationId === null && (
                <option value="">Select an organization</option>
              )}
              {orgList.map((org) => (
                <option key={org.id} value={org.id}>
                  {labelFor(org)}
                </option>
              ))}
            </select>
          ) : (
            <span
              className="min-w-0 flex-1 truncate text-foreground"
              title={
                activeOrganization ? labelFor(activeOrganization) : undefined
              }
            >
              {activeOrganization ? labelFor(activeOrganization) : "Unknown"}
            </span>
          )}
        </div>
      )}

      <Button
        variant="outline"
        size="sm"
        className="w-full justify-start text-xs"
        onClick={() => {
          setCreateError(null);
          setNewName("");
          setIsCreateOpen(true);
        }}
      >
        + New business
      </Button>

      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Business</DialogTitle>
            <DialogDescription>
              Create a separate space for a client. Its voice agents, numbers and
              API keys are kept apart from your other businesses — you switch
              between them from the dropdown above.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2 py-4">
            <Label htmlFor="org-name">Business name</Label>
            <Input
              id="org-name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isCreating) void handleCreate();
              }}
              placeholder="e.g. Acme Corp"
              maxLength={100}
              autoFocus
            />
            {createError && (
              <p className="text-sm text-destructive">{createError}</p>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsCreateOpen(false)}
              disabled={isCreating}
            >
              Cancel
            </Button>
            <Button onClick={() => void handleCreate()} disabled={isCreating}>
              {isCreating ? "Creating..." : "Create business"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
