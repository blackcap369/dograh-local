"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { createAgencyClientApiV1AgencyClientsPost } from "@/client/sdk.gen";
import { CreativePageGate } from "@/components/creative/CreativePageGate";
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
import { detailFromError } from "@/lib/apiError";
import logger from "@/lib/logger";

/**
 * Creative Mode: onboard a client business.
 *
 * Creation does not move the operator into the new business -- the agency
 * surface has no "selected organization", and an auto-switch would silently
 * re-point every org-scoped query made next. The client appears in the list
 * and in the switcher; entering it is a deliberate act from its detail page.
 */
function NewClientContent() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    // Manual guard, same reasoning as the api-keys page: a disabled button gives
    // the user nothing to distinguish "I haven't typed yet" from "this form is
    // broken".
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Please enter a name for the client");
      return;
    }

    try {
      setError(null);
      setIsCreating(true);
      const response = await createAgencyClientApiV1AgencyClientsPost({
        body: { name: trimmed },
      });
      if (response.error || !response.data) {
        throw new Error(
          detailFromError(response.error, "Could not create the client")
        );
      }
      const created = response.data;
      toast.success(`Created "${created.name ?? created.provider_id}"`);
      router.push("/creative/clients");
    } catch (err) {
      logger.error("Failed to create client organization", err);
      setError(
        err instanceof Error
          ? err.message
          : "Could not create the client. Please try again."
      );
      setIsCreating(false);
    }
  };

  return (
    <div className="container mx-auto px-4 py-12">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        <div>
          <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
            <Link href="/creative/clients">← Back to clients</Link>
          </Button>
          <h1 className="text-2xl font-bold">Add Client</h1>
          <p className="text-muted-foreground">
            Give the client its own space on this instance. Everything scoped to
            a business -- voice agents, phone numbers, files, API keys -- stays
            inside it.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Create a client business</CardTitle>
            <CardDescription>
              You become its first member, and the name shows in the client
              list and the sidebar switcher. Creating a client does not move
              you into it.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="grid gap-2">
                <Label htmlFor="client-name">Client name</Label>
                <Input
                  id="client-name"
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
                {isCreating ? "Creating..." : "Create client"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default function NewCreativeClientPage() {
  return (
    <CreativePageGate>
      <NewClientContent />
    </CreativePageGate>
  );
}
