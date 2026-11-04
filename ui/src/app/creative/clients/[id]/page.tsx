"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
  archiveAgencyClientApiV1AgencyClientsOrganizationIdArchivePost,
  createDeletionRequestApiV1AgencyClientsOrganizationIdDeletionRequestPost,
  deleteAgencyClientApiV1AgencyClientsOrganizationIdDelete,
  getAgencyClientApiV1AgencyClientsOrganizationIdGet,
  renameAgencyClientApiV1AgencyClientsOrganizationIdPatch,
  unarchiveAgencyClientApiV1AgencyClientsOrganizationIdUnarchivePost,
} from "@/client/sdk.gen";
import type { AgencyClientSummary } from "@/client/types.gen";
import { CreativePageGate } from "@/components/creative/CreativePageGate";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
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
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useMode } from "@/context/ModeContext";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { isAgencyOwner } from "@/lib/agency";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import logger from "@/lib/logger";

/**
 * Creative Mode: manage one client business -- rename it, archive it, delete
 * it, or step into it to build agents on its behalf.
 *
 * Reads the single-client agency endpoint, which includes archived businesses
 * on purpose: the operator who archived a client must still be able to open
 * it and restore it.
 */
function ClientDetailContent() {
  const params = useParams<{ id: string }>();
  const clientId = Number(params.id);
  const router = useRouter();
  const { setMode } = useMode();
  const { switchOrganization } = useOrgConfig();
  const { user } = useAuth();
  const owner = isAgencyOwner(user);

  const [client, setClient] = useState<AgencyClientSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  const [nameDraft, setNameDraft] = useState("");
  const [isRenaming, setIsRenaming] = useState(false);
  const [isTogglingArchive, setIsTogglingArchive] = useState(false);
  const [isSwitchingIn, setIsSwitchingIn] = useState(false);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [isRequestingDeletion, setIsRequestingDeletion] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const loadClient = useCallback(
    async (showLoading: boolean) => {
      try {
        if (showLoading) setLoading(true);
        const response = await getAgencyClientApiV1AgencyClientsOrganizationIdGet({
          path: { organization_id: clientId },
        });
        if (response.error || !response.data) {
          // The endpoint's only error responses are 404 (no such business) and
          // 422 (malformed id); both mean the operator cannot work with it.
          setNotFound(true);
          return;
        }
        setNotFound(false);
        setClient(response.data);
        setNameDraft(response.data.name ?? "");
      } catch (err) {
        logger.error("Failed to load client", err);
        toast.error(err instanceof Error ? err.message : "Failed to load client");
      } finally {
        if (showLoading) setLoading(false);
      }
    },
    [clientId]
  );

  const fetchClient = useCallback(() => loadClient(true), [loadClient]);

  // Post-action refreshes keep the page put; only the first load shows the
  // full-page skeleton.
  const refreshClient = useCallback(() => loadClient(false), [loadClient]);

  useEffect(() => {
    if (Number.isNaN(clientId)) {
      setNotFound(true);
      setLoading(false);
      return;
    }
    fetchClient();
  }, [clientId, fetchClient]);

  const handleRename = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!client) return;

    const trimmed = nameDraft.trim();
    if (!trimmed) {
      toast.error("Name must not be blank");
      return;
    }

    try {
      setIsRenaming(true);
      const response = await renameAgencyClientApiV1AgencyClientsOrganizationIdPatch(
        { path: { organization_id: client.id }, body: { name: trimmed } }
      );
      if (response.error || !response.data) {
        throw new Error(detailFromError(response.error, "Rename failed"));
      }
      toast.success("Client renamed");
      await refreshClient();
    } catch (err) {
      logger.error("Failed to rename client", err);
      toast.error(err instanceof Error ? err.message : "Rename failed");
    } finally {
      setIsRenaming(false);
    }
  };

  const handleToggleArchive = async () => {
    if (!client) return;

    try {
      setIsTogglingArchive(true);
      const response = client.archived
        ? await unarchiveAgencyClientApiV1AgencyClientsOrganizationIdUnarchivePost(
            { path: { organization_id: client.id } }
          )
        : await archiveAgencyClientApiV1AgencyClientsOrganizationIdArchivePost({
            path: { organization_id: client.id },
          });
      if (response.error) {
        throw new Error(detailFromError(response.error, "Archive failed"));
      }
      toast.success(client.archived ? "Client restored" : "Client archived");
      await refreshClient();
    } catch (err) {
      logger.error("Failed to change archive state", err);
      toast.error(err instanceof Error ? err.message : "Archive failed");
    } finally {
      setIsTogglingArchive(false);
    }
  };

  const handleWorkInBusiness = async () => {
    if (!client) return;

    try {
      setIsSwitchingIn(true);
      await switchOrganization(client.id);
      setMode("organization");
      router.push("/overview");
    } catch (err) {
      logger.error("Failed to switch into client business", err);
      toast.error(err instanceof Error ? err.message : "Could not switch");
      setIsSwitchingIn(false);
    }
  };

  const handleDeleteClick = async () => {
    if (!client) return;

    // Staff never delete: they ask, and the owner decides. The badge on the
    // client comes from the backend once the request exists.
    if (!owner) {
      try {
        setIsRequestingDeletion(true);
        const response =
          await createDeletionRequestApiV1AgencyClientsOrganizationIdDeletionRequestPost(
            { path: { organization_id: client.id }, body: {} }
          );
        if (response.error || !response.data) {
          throw new Error(
            detailFromError(response.error, "Could not send the request")
          );
        }
        toast.success("Deletion request sent to the agency owner");
        await refreshClient();
      } catch (err) {
        logger.error("Failed to create deletion request", err);
        toast.error(
          err instanceof Error ? err.message : "Could not send the request"
        );
      } finally {
        setIsRequestingDeletion(false);
      }
      return;
    }

    // Owner: open the trash confirm. No safety pre-check -- trashing is
    // reversible, so business history is not a reason to refuse; the
    // irreversible purge (on the Team page) carries the guard.
    setIsDeleteDialogOpen(true);
  };

  const handleConfirmDelete = async () => {
    if (!client) return;

    try {
      setIsDeleting(true);
      const response = await deleteAgencyClientApiV1AgencyClientsOrganizationIdDelete(
        { path: { organization_id: client.id } }
      );
      if (response.error) {
        throw new Error(detailFromError(response.error, "Delete failed"));
      }
      toast.success(`"${client.label}" moved to the trash`);
      setIsDeleteDialogOpen(false);
      router.push("/creative/clients");
    } catch (err) {
      logger.error("Failed to trash client", err);
      toast.error(err instanceof Error ? err.message : "Could not trash the client");
      setIsDeleteDialogOpen(false);
    } finally {
      setIsDeleting(false);
    }
  };

  if (loading) {
    return (
      <div className="container mx-auto space-y-6 px-4 py-8">
        <Skeleton className="h-9 w-72" />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Skeleton className="h-64" />
          <Skeleton className="h-64" />
        </div>
      </div>
    );
  }

  if (notFound || !client) {
    return (
      <div className="container mx-auto px-4 py-8">
        <Card className="mx-auto max-w-lg">
          <CardHeader>
            <CardTitle>Client not found</CardTitle>
            <CardDescription>
              It may have been deleted, or the link is out of date.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild variant="outline">
              <Link href="/creative/clients">Back to clients</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto space-y-8 px-4 py-8">
      <div>
        <Button asChild variant="ghost" size="sm" className="mb-2 -ml-2">
          <Link href="/creative/clients">← Back to clients</Link>
        </Button>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-bold">{client.label}</h1>
          {client.archived && <Badge variant="secondary">Archived</Badge>}
          {client.deletion_pending && (
            <Badge variant="destructive">Deletion pending owner approval</Badge>
          )}
        </div>
        <p className="mt-1 font-mono text-xs text-muted-foreground">
          {client.provider_id}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Work in this business</CardTitle>
            <CardDescription>
              Switch your active organization to this client and build on their
              behalf. Everything you do next is scoped to their space.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex items-center gap-6">
            <Button onClick={handleWorkInBusiness} disabled={isSwitchingIn}>
              {isSwitchingIn ? "Switching..." : "Enter Organization Mode"}
            </Button>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
              <span className="text-muted-foreground">Agents</span>
              <span className="text-right font-medium tabular-nums">
                {client.workflow_count}
              </span>
              <span className="text-muted-foreground">Runs</span>
              <span className="text-right font-medium tabular-nums">
                {client.run_count}
              </span>
              <span className="text-muted-foreground">Numbers</span>
              <span className="text-right font-medium tabular-nums">
                {client.phone_number_count}
              </span>
              <span className="text-muted-foreground">Members</span>
              <span className="text-right font-medium tabular-nums">
                {client.member_count}
              </span>
              <span className="text-muted-foreground">Credits</span>
              <span className="text-right font-medium tabular-nums">
                {client.credit_minutes} min
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Client details</CardTitle>
            <CardDescription>
              The name is the label your whole team sees. The id never changes.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form className="flex items-end gap-3" onSubmit={handleRename}>
              <div className="grid flex-1 gap-2">
                <Label htmlFor="client-name">Name</Label>
                <Input
                  id="client-name"
                  value={nameDraft}
                  onChange={(e) => setNameDraft(e.target.value)}
                  maxLength={100}
                  disabled={isRenaming}
                />
              </div>
              <Button type="submit" variant="outline" disabled={isRenaming}>
                {isRenaming ? "Saving..." : "Rename"}
              </Button>
            </form>

            <Separator className="my-6" />

            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium">
                  {client.archived ? "This client is archived" : "Archive this client"}
                </p>
                <p className="text-sm text-muted-foreground">
                  {client.archived
                    ? "Restore it to the switcher and the client list."
                    : "Hides it from the switcher and the client list. All data is kept and it can be restored."}
                </p>
              </div>
              <Button
                variant={client.archived ? "outline" : "secondary"}
                onClick={handleToggleArchive}
                disabled={isTogglingArchive}
              >
                {isTogglingArchive
                  ? "..."
                  : client.archived
                    ? "Restore"
                    : "Archive"}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle className="text-destructive">Danger zone</CardTitle>
          <CardDescription>
            {owner
              ? "Moves the business to the trash: hidden everywhere, restorable for 10 days from the Team page. Businesses with call history are never auto-destroyed."
              : "Send the agency owner a request to delete this business. Nothing happens until they approve it."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" onClick={handleDeleteClick} disabled={isRequestingDeletion}>
            {isRequestingDeletion
              ? "Sending..."
              : owner
                ? "Delete client"
                : client.deletion_pending
                  ? "Deletion pending owner approval"
                  : "Request deletion"}
          </Button>
        </CardContent>
      </Card>

      <AlertDialog
        open={isDeleteDialogOpen}
        onOpenChange={(open) => {
          if (!isDeleting) setIsDeleteDialogOpen(open);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Move &ldquo;{client.label}&rdquo; to the trash?
            </AlertDialogTitle>
            <AlertDialogDescription>
              It disappears from every list and the switcher immediately, but
              nothing is destroyed: it stays restorable for 10 days from the
              Team page, and businesses with call history are kept restorable
              indefinitely.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                handleConfirmDelete();
              }}
              disabled={isDeleting}
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {isDeleting ? "Moving..." : "Move to trash"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default function CreativeClientDetailPage() {
  return (
    <CreativePageGate>
      <ClientDetailContent />
    </CreativePageGate>
  );
}
