"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
  listAgencyClientsApiV1AgencyClientsGet,
} from "@/client/sdk.gen";
import type { AgencyClientSummary } from "@/client/types.gen";
import { CreativePageGate } from "@/components/creative/CreativePageGate";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { isAgencyOwner } from "@/lib/agency";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import { APP_NAME } from "@/lib/branding";

/**
 * Creative Mode home. The KPI numbers are aggregates of the same
 * cross-organization clients query the Clients page uses -- one request, so the
 * dashboard costs the instance no more than the page it links to.
 */
function DashboardContent() {
  const { user } = useAuth();
  const owner = isAgencyOwner(user);
  const [clients, setClients] = useState<AgencyClientSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchClients = async () => {
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
  };

  useEffect(() => {
    fetchClients();
  }, []);

  // The generated type carries the counts as optional (Pydantic defaults are
  // not `required` over the wire), so every sum needs a nullish fallback.
  const totalWorkflows = clients.reduce((sum, c) => sum + (c.workflow_count ?? 0), 0);
  const totalRuns = clients.reduce((sum, c) => sum + (c.run_count ?? 0), 0);
  const totalPhoneNumbers = clients.reduce(
    (sum, c) => sum + (c.phone_number_count ?? 0),
    0
  );

  if (loading) {
    return (
      <div className="container mx-auto space-y-6 px-4 py-8">
        <Skeleton className="h-9 w-64" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto px-4 py-8">
        <Card className="mx-auto max-w-lg">
          <CardHeader>
            <CardTitle>Could not load the dashboard</CardTitle>
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

  const kpis = [
    { label: "Clients", value: clients.length },
    { label: "Voice Agents", value: totalWorkflows },
    { label: "Agent Runs", value: totalRuns },
    { label: "Phone Numbers", value: totalPhoneNumbers },
  ];

  return (
    <div className="container mx-auto space-y-8 px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Home</h1>
          <p className="mt-1 text-muted-foreground">
            {owner
              ? `Every client business on this ${APP_NAME} instance, at a glance.`
              : "Your assigned client businesses, at a glance."}
          </p>
        </div>
        {owner && (
          <Button asChild>
            <Link href="/creative/clients/new">Add Client</Link>
          </Button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {kpis.map((kpi) => (
          <Card key={kpi.label}>
            <CardHeader className="pb-2">
              <CardDescription>{kpi.label}</CardDescription>
              <CardTitle className="text-3xl tabular-nums">
                {kpi.value.toLocaleString()}
              </CardTitle>
            </CardHeader>
            <CardContent />
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Clients</CardTitle>
            <CardDescription>
              {clients.length === 0
                ? "No client businesses yet."
                : "Your most active client businesses."}
            </CardDescription>
          </div>
          {clients.length > 0 && (
            <Button asChild variant="outline" size="sm">
              <Link href="/creative/clients">View all</Link>
            </Button>
          )}
        </CardHeader>
        {clients.length > 0 && (
          <CardContent>
            <ul className="divide-y divide-border/60">
              {[...clients]
                .sort((a, b) => (b.run_count ?? 0) - (a.run_count ?? 0))
                .slice(0, 5)
                .map((client) => (
                  <li key={client.id} className="flex items-center justify-between py-2.5">
                    <Link
                      href={`/creative/clients/${client.id}`}
                      className="min-w-0 truncate font-medium hover:underline"
                    >
                      {client.label}
                    </Link>
                    <span className="ml-4 shrink-0 text-sm text-muted-foreground tabular-nums">
                      {client.workflow_count} agents · {client.run_count} runs
                    </span>
                  </li>
                ))}
            </ul>
          </CardContent>
        )}
        {clients.length === 0 && (
          <CardContent>
            {owner && (
              <Button asChild>
                <Link href="/creative/clients/new">Create your first client</Link>
              </Button>
            )}
          </CardContent>
        )}
      </Card>
    </div>
  );
}

export default function CreativeDashboardPage() {
  return (
    <CreativePageGate>
      <DashboardContent />
    </CreativePageGate>
  );
}
