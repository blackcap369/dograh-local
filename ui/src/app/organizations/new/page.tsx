"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { reloadApp } from "@/lib/browserReload";
import logger from "@/lib/logger";

/**
 * The always-reachable counterpart to the "+ New business" button in the sidebar
 * switcher. That switcher is hidden on the auth screens, on a collapsed desktop rail,
 * and on any provider other than local -- this page is linked from the MANAGE group so
 * onboarding a client is never conditional on where the operator happens to be looking.
 *
 * Both entry points do the same thing; the form is inline rather than a dialog because
 * a full page gives room to say what the split actually means, which is the part an
 * agency operator needs to get right before naming a client.
 */
export default function NewOrganizationPage() {
  const { createOrganization, organizations } = useOrgConfig();
  const [name, setName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    // Manual guard, same reasoning as the api-keys page: a disabled button gives the
    // user nothing to distinguish "I haven't typed yet" from "this form is broken".
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Please enter a name for the business");
      return;
    }

    try {
      setError(null);
      setIsCreating(true);
      const created = await createOrganization(trimmed);
      toast.success(`Created "${created.name ?? created.provider_id}"`);
      // Creation deliberately does not switch the active business -- see the route's
      // comment. The dropdown gains the option; the operator switches when ready.
      reloadApp();
    } catch (err) {
      logger.error("Failed to create organization", err);
      setError(
        err instanceof Error
          ? err.message
          : "Could not create the business. Please try again."
      );
      setIsCreating(false);
    }
  };

  return (
    <div className="container mx-auto px-4 py-12">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        <div>
          <h1 className="text-2xl font-bold">New Business</h1>
          <p className="text-muted-foreground">
            Give a client its own space on this instance. Everything scoped to a
            business -- voice agents, phone numbers, files, API keys -- stays inside
            it.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Create a business</CardTitle>
            <CardDescription>
              You become its first member, and the name shows in the dropdown in the
              sidebar. Creating a business does not move you into it -- switch
              deliberately once it exists.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="grid gap-2">
                <Label htmlFor="business-name">Business name</Label>
                <Input
                  id="business-name"
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value);
                    if (error) setError(null);
                  }}
                  placeholder="e.g. Acme Corp"
                  maxLength={100}
                  autoFocus
                  disabled={isCreating}
                />
                {error && <p className="text-sm text-destructive">{error}</p>}
              </div>
              <Button type="submit" disabled={isCreating}>
                {isCreating ? "Creating..." : "Create business"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {organizations.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Your businesses</CardTitle>
              <CardDescription>
                You can switch between these from the dropdown in the sidebar.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1 text-sm">
                {organizations.map((org) => (
                  <li key={org.id} className="truncate">
                    {org.name ?? org.provider_id}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
