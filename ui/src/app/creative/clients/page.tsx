"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { listAgencyClientsApiV1AgencyClientsGet } from "@/client/sdk.gen";
import type { AgencyClientSummary } from "@/client/types.gen";
import { CreativePageGate } from "@/components/creative/CreativePageGate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { detailFromError } from "@/lib/apiError";

/**
 * Creative Mode: every client business on the instance, with the resource
 * counts that make the difference between an active and a dormant account.
 * Data comes from the cross-organization /agency/clients surface -- the one
 * deliberately non-org-scoped read in the backend -- so no switching is
 * involved in seeing all of them.
 */
function ClientsContent() {
  const [clients, setClients] = useState<AgencyClientSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchClients = useCallback(async () => {
    try {
      setLoading(true);
      const response = await listAgencyClientsApiV1AgencyClientsGet();
      if (response.error) {
        throw new Error(detailFromError(response.error, "Failed to load clients"));
      }
      setClients(response.data ?? []);
      setError(null);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load clients";
      setError(message);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchClients();
  }, [fetchClients]);

  if (loading) {
    return (
      <div className="container mx-auto space-y-6 px-4 py-8">
        <Skeleton className="h-9 w-64" />
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto px-4 py-8">
        <Card className="mx-auto max-w-lg">
          <CardHeader>
            <CardTitle>Could not load clients</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" onClick={() => fetchClients()}>
              Try again
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto space-y-8 px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Clients</h1>
          <p className="mt-1 text-muted-foreground">
            Manage every client business from one place. Each one gets an
            isolated space for agents, numbers, files, and keys.
          </p>
        </div>
        <Button asChild>
          <Link href="/creative/clients/new">Add Client</Link>
        </Button>
      </div>

      {clients.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
            <p className="text-lg font-semibold">No clients yet</p>
            <p className="max-w-md text-muted-foreground">
              Onboard your first client business. Everything you build for them
              stays scoped to their space.
            </p>
            <Button asChild>
              <Link href="/creative/clients/new">Create a client</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
          {clients.map((client) => (
            <Card
              key={client.id}
              className="flex flex-col transition-shadow hover:shadow-md"
            >
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="min-w-0 truncate">
                    <Link
                      href={`/creative/clients/${client.id}`}
                      className="hover:underline"
                    >
                      {client.label}
                    </Link>
                  </CardTitle>
                  {client.archived && <Badge variant="secondary">Archived</Badge>}
                </div>
                <CardDescription className="truncate font-mono text-xs">
                  {client.provider_id}
                </CardDescription>
              </CardHeader>
              <CardContent className="grid flex-1 grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">Agents</span>
                  <span className="font-medium tabular-nums">
                    {client.workflow_count}
                  </span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">Runs</span>
                  <span className="font-medium tabular-nums">
                    {client.run_count}
                  </span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">Numbers</span>
                  <span className="font-medium tabular-nums">
                    {client.phone_number_count}
                  </span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-muted-foreground">Members</span>
                  <span className="font-medium tabular-nums">
                    {client.member_count}
                  </span>
                </div>
              </CardContent>
              <CardFooter className="border-t border-border/60 pt-4">
                <Button asChild variant="outline" size="sm">
                  <Link href={`/creative/clients/${client.id}`}>Open</Link>
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export default function CreativeClientsPage() {
  return (
    <CreativePageGate>
      <ClientsContent />
    </CreativePageGate>
  );
}
