"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
  acknowledgeFailureAlertApiV1AgencyFailureAlertsAlertIdAcknowledgePost,
  getAgencyRunHealthApiV1AgencyHealthGet,
  listAgencyClientsApiV1AgencyClientsGet,
} from "@/client/sdk.gen";
import type { AgencyClientSummary, RunHealthResponse } from "@/client/types.gen";
import { CreativePageGate } from "@/components/creative/CreativePageGate";
import { Badge } from "@/components/ui/badge";
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
  const [health, setHealth] = useState<RunHealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchClients = async () => {
    try {
      setLoading(true);
      const [clientsResponse, healthResponse] = await Promise.all([
        listAgencyClientsApiV1AgencyClientsGet(),
        getAgencyRunHealthApiV1AgencyHealthGet(),
      ]);
      if (clientsResponse.error) {
        throw new Error(detailFromError(clientsResponse.error, "Failed to load clients"));
      }
      setClients(clientsResponse.data ?? []);
      // Health is an enhancement: a failed load must not blank the dashboard.
      if (!healthResponse.error) {
        setHealth(healthResponse.data ?? null);
      }
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

  const handleAcknowledgeAlert = async (alertId: number) => {
    try {
      const response =
        await acknowledgeFailureAlertApiV1AgencyFailureAlertsAlertIdAcknowledgePost({
          path: { alert_id: alertId },
        });
      if (response.error) {
        throw new Error(detailFromError(response.error, "Could not acknowledge"));
      }
      toast.success("Alert acknowledged");
      await fetchClients();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not acknowledge");
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

  // Credit balances (V2.5-billing): surface low balances next to failures --
  // both mean "this business is about to stop working".
  const lowCreditBusinesses = health
    ? health.businesses.filter(
        (b) => (health.credit_minutes?.[String(b.organization_id)] ?? 999) <= 30
      )
    : [];
  const showHealthCard =
    !!health &&
    (health.alerts.length > 0 ||
      health.businesses.some((b) => b.failed_24h > 0) ||
      lowCreditBusinesses.length > 0);

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

      {showHealthCard && (
        <Card className="border-amber-500/40">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div>
              <CardTitle className="flex items-center gap-2">
                Business health
                <Badge variant="destructive">
                  {health!.alerts.length > 0
                    ? `${health!.alerts.length} open alert${health!.alerts.length > 1 ? "s" : ""}`
                    : lowCreditBusinesses.length > 0
                      ? "low credits"
                      : "failures in the last 24h"}
                </Badge>
              </CardTitle>
              <CardDescription>
                Failed runs in the last {health!.window_hours} hours, per
                business. Fix the cause; the alert auto-clears on the next
                successful run.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {health.alerts.map((alert) => (
              <div
                key={alert.id}
                className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium">
                    {alert.agent_name}{" "}
                    <span className="text-muted-foreground">
                      — {alert.business_label}
                    </span>
                  </p>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {alert.failure_count} failed run
                    {alert.failure_count > 1 ? "s" : ""}
                    {alert.last_error ? ` — ${alert.last_error}` : ""}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleAcknowledgeAlert(alert.id)}
                >
                  Acknowledge
                </Button>
              </div>
            ))}
            {health.businesses
              .filter((b) => b.failed_24h > 0)
              .map((b) => (
                <div
                  key={b.organization_id}
                  className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-3 text-sm"
                >
                  <span className="font-medium">{b.label}</span>
                  <span className="text-muted-foreground">
                    {b.failed_24h} failed / {b.runs_24h} runs in {health.window_hours}h
                    {b.last_failure?.agent_name
                      ? ` — last: ${b.last_failure.agent_name}`
                      : ""}
                  </span>
                </div>
              ))}
            {lowCreditBusinesses.map((b) => (
              <div
                key={`credits-${b.organization_id}`}
                className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-3 text-sm"
              >
                <span className="font-medium">{b.label}</span>
                <span className="text-muted-foreground">
                  {health!.credit_minutes?.[String(b.organization_id)] ?? 0} credits
                  remaining — top up from the Team page
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

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
