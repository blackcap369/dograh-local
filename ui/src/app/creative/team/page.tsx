"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
  approveDeletionRequestApiV1AgencyDeletionRequestsRequestIdApprovePost,
  createStaffAccountApiV1AgencyStaffPost,
  deleteStaffAccountApiV1AgencyStaffStaffUserIdDelete,
  listAgencyClientsApiV1AgencyClientsGet,
  listDeletionRequestsApiV1AgencyDeletionRequestsGet,
  listStaffApiV1AgencyStaffGet,
  listTrashedClientsApiV1AgencyTrashGet,
  purgeTrashedClientApiV1AgencyTrashOrganizationIdPurgePost,
  rejectDeletionRequestApiV1AgencyDeletionRequestsRequestIdRejectPost,
  replaceStaffAssignmentsApiV1AgencyStaffStaffUserIdAssignmentsPut,
  resetStaffPasswordApiV1AgencyStaffStaffUserIdResetPasswordPost,
  restoreTrashedClientApiV1AgencyTrashOrganizationIdRestorePost,
  setStaffSuspendedApiV1AgencyStaffStaffUserIdSuspendedPatch,
} from "@/client/sdk.gen";
import type {
  AgencyClientSummary,
  DeletionRequestSummary,
  StaffAccountSummary,
  TrashedClientSummary,
} from "@/client/types.gen";
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
import { Checkbox } from "@/components/ui/checkbox";
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
import { Skeleton } from "@/components/ui/skeleton";
import { isAgencyOwner } from "@/lib/agency";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";
import logger from "@/lib/logger";

/**
 * Owner portal: the access-management page. Staff accounts, their client
 * assignments, and the deletion-request queue.
 *
 * Owner-only -- staff are redirected to the Clients page. Every action here
 * is enforced server-side as well; this page only decides what the owner
 * sees and clicks.
 */
function TeamContent() {
  const { user } = useAuth();
  const owner = isAgencyOwner(user);
  const router = useRouter();

  // Owner-only page. Staff land here only by typing the URL; the backend
  // refuses every call they could make, so send them to their Clients page
  // instead of showing a wall of 403s.
  useEffect(() => {
    if (!owner) {
      router.replace("/creative/clients");
    }
  }, [owner, router]);

  const [staff, setStaff] = useState<StaffAccountSummary[]>([]);
  const [requests, setRequests] = useState<DeletionRequestSummary[]>([]);
  const [clients, setClients] = useState<AgencyClientSummary[]>([]);
  const [trash, setTrash] = useState<TrashedClientSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [purgeTarget, setPurgeTarget] = useState<TrashedClientSummary | null>(null);
  const [isPurging, setIsPurging] = useState(false);

  const [addOpen, setAddOpen] = useState(false);
  const [newEmail, setNewEmail] = useState("");
  const [newName, setNewName] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  const [assignTarget, setAssignTarget] = useState<StaffAccountSummary | null>(null);
  const [assignmentDraft, setAssignmentDraft] = useState<Set<number>>(new Set());
  const [isSavingAssignments, setIsSavingAssignments] = useState(false);

  const [resetTarget, setResetTarget] = useState<StaffAccountSummary | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [isResetting, setIsResetting] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<StaffAccountSummary | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [staffResponse, requestResponse, clientsResponse, trashResponse] =
        await Promise.all([
          listStaffApiV1AgencyStaffGet(),
          listDeletionRequestsApiV1AgencyDeletionRequestsGet(),
          listAgencyClientsApiV1AgencyClientsGet(),
          listTrashedClientsApiV1AgencyTrashGet(),
        ]);
      for (const response of [
        staffResponse,
        requestResponse,
        clientsResponse,
        trashResponse,
      ]) {
        if (response.error) {
          throw new Error(detailFromError(response.error, "Failed to load team data"));
        }
      }
      setStaff(staffResponse.data ?? []);
      setRequests(requestResponse.data ?? []);
      setClients(clientsResponse.data ?? []);
      setTrash(trashResponse.data ?? []);
    } catch (err) {
      logger.error("Failed to load team page", err);
      toast.error(err instanceof Error ? err.message : "Failed to load team data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (owner) {
      fetchData();
    }
  }, [fetchData, owner]);

  const handleCreateStaff = async () => {
    const trimmedEmail = newEmail.trim();
    if (!trimmedEmail || !newPassword) {
      toast.error("Email and password are required");
      return;
    }
    try {
      setIsCreating(true);
      const response = await createStaffAccountApiV1AgencyStaffPost({
        body: {
          email: trimmedEmail,
          password: newPassword,
          name: newName.trim() || null,
        },
      });
      if (response.error || !response.data) {
        throw new Error(detailFromError(response.error, "Could not create the account"));
      }
      toast.success(`Staff account for ${response.data.email} created`);
      setAddOpen(false);
      setNewEmail("");
      setNewName("");
      setNewPassword("");
      await fetchData();
    } catch (err) {
      logger.error("Failed to create staff account", err);
      toast.error(err instanceof Error ? err.message : "Could not create the account");
    } finally {
      setIsCreating(false);
    }
  };

  const openAssign = (account: StaffAccountSummary) => {
    setAssignTarget(account);
    setAssignmentDraft(new Set((account.assigned_clients ?? []).map((c) => c.id)));
  };

  const toggleAssignment = (orgId: number) => {
    setAssignmentDraft((current) => {
      const next = new Set(current);
      if (next.has(orgId)) {
        next.delete(orgId);
      } else {
        next.add(orgId);
      }
      return next;
    });
  };

  const handleSaveAssignments = async () => {
    if (!assignTarget) return;
    try {
      setIsSavingAssignments(true);
      const response = await replaceStaffAssignmentsApiV1AgencyStaffStaffUserIdAssignmentsPut(
        {
          path: { staff_user_id: assignTarget.id },
          body: { organization_ids: Array.from(assignmentDraft) },
        }
      );
      if (response.error || !response.data) {
        throw new Error(detailFromError(response.error, "Could not save assignments"));
      }
      toast.success("Assignments saved");
      setAssignTarget(null);
      await fetchData();
    } catch (err) {
      logger.error("Failed to save assignments", err);
      toast.error(err instanceof Error ? err.message : "Could not save assignments");
    } finally {
      setIsSavingAssignments(false);
    }
  };

  const handleResetPassword = async () => {
    if (!resetTarget) return;
    if (resetPassword.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }
    try {
      setIsResetting(true);
      const response = await resetStaffPasswordApiV1AgencyStaffStaffUserIdResetPasswordPost(
        { path: { staff_user_id: resetTarget.id }, body: { new_password: resetPassword } }
      );
      if (response.error) {
        throw new Error(detailFromError(response.error, "Could not reset the password"));
      }
      toast.success(`Password reset for ${resetTarget.email}`);
      setResetTarget(null);
      setResetPassword("");
    } catch (err) {
      logger.error("Failed to reset password", err);
      toast.error(err instanceof Error ? err.message : "Could not reset the password");
    } finally {
      setIsResetting(false);
    }
  };

  const handleToggleSuspended = async (account: StaffAccountSummary) => {
    try {
      const response = await setStaffSuspendedApiV1AgencyStaffStaffUserIdSuspendedPatch({
        path: { staff_user_id: account.id },
        body: { suspended: !account.suspended },
      });
      if (response.error || !response.data) {
        throw new Error(detailFromError(response.error, "Could not update the account"));
      }
      toast.success(account.suspended ? "Account reactivated" : "Account suspended");
      await fetchData();
    } catch (err) {
      logger.error("Failed to change suspension", err);
      toast.error(err instanceof Error ? err.message : "Could not update the account");
    }
  };

  const handleDeleteStaff = async () => {
    if (!deleteTarget) return;
    try {
      setIsDeleting(true);
      const response = await deleteStaffAccountApiV1AgencyStaffStaffUserIdDelete({
        path: { staff_user_id: deleteTarget.id },
      });
      if (response.error) {
        throw new Error(detailFromError(response.error, "Could not delete the account"));
      }
      toast.success(`Deleted ${deleteTarget.email}`);
      setDeleteTarget(null);
      await fetchData();
    } catch (err) {
      logger.error("Failed to delete staff account", err);
      toast.error(err instanceof Error ? err.message : "Could not delete the account");
    } finally {
      setIsDeleting(false);
    }
  };

  const handleDeletionDecision = async (
    request: DeletionRequestSummary,
    decision: "approve" | "reject"
  ) => {
    try {
      const response =
        decision === "approve"
          ? await approveDeletionRequestApiV1AgencyDeletionRequestsRequestIdApprovePost({
              path: { request_id: request.id },
            })
          : await rejectDeletionRequestApiV1AgencyDeletionRequestsRequestIdRejectPost({
              path: { request_id: request.id },
            });
      if (response.error || !response.data) {
        throw new Error(detailFromError(response.error, "Could not record the decision"));
      }
      toast.success(
        decision === "approve"
          ? `Deleted "${request.business_label}"`
          : `Request for "${request.business_label}" rejected`
      );
      await fetchData();
    } catch (err) {
      logger.error("Failed to record deletion decision", err);
      toast.error(err instanceof Error ? err.message : "Could not record the decision");
    }
  };

  const handleRestore = async (item: TrashedClientSummary) => {
    try {
      const response = await restoreTrashedClientApiV1AgencyTrashOrganizationIdRestorePost(
        { path: { organization_id: item.id } }
      );
      if (response.error) {
        throw new Error(detailFromError(response.error, "Could not restore the business"));
      }
      toast.success(`Restored "${item.label}"`);
      await fetchData();
    } catch (err) {
      logger.error("Failed to restore", err);
      toast.error(err instanceof Error ? err.message : "Could not restore the business");
    }
  };

  const handlePurge = async () => {
    if (!purgeTarget) return;
    try {
      setIsPurging(true);
      const response = await purgeTrashedClientApiV1AgencyTrashOrganizationIdPurgePost(
        { path: { organization_id: purgeTarget.id } }
      );
      if (response.error) {
        throw new Error(
          detailFromError(response.error, "Could not destroy the business")
        );
      }
      toast.success(`Permanently deleted "${purgeTarget.label}"`);
      setPurgeTarget(null);
      await fetchData();
    } catch (err) {
      logger.error("Failed to purge", err);
      toast.error(err instanceof Error ? err.message : "Could not destroy the business");
      setPurgeTarget(null);
    } finally {
      setIsPurging(false);
    }
  };

  if (loading) {
    return (
      <div className="container mx-auto space-y-6 px-4 py-8">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-40" />
        <Skeleton className="h-80" />
      </div>
    );
  }

  return (
    <div className="container mx-auto space-y-8 px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">Team</h1>
          <p className="mt-1 text-muted-foreground">
            Staff accounts, what each one may work on, and their deletion
            requests waiting for your decision.
          </p>
        </div>
        <Button onClick={() => setAddOpen(true)}>Add Staff</Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Deletion requests</CardTitle>
          <CardDescription>
            Staff can ask for a business to be deleted; only your approval
            removes it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {requests.length === 0 ? (
            <p className="py-4 text-sm text-muted-foreground">
              No pending requests.
            </p>
          ) : (
            <ul className="divide-y divide-border/60">
              {requests.map((request) => (
                <li
                  key={request.id}
                  className="flex flex-wrap items-center justify-between gap-3 py-3"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">{request.business_label}</p>
                    <p className="text-sm text-muted-foreground">
                      Requested by {request.requested_by_email ?? "unknown"}
                      {request.reason ? ` — ${request.reason}` : ""}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleDeletionDecision(request, "reject")}
                    >
                      Reject
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => handleDeletionDecision(request, "approve")}
                    >
                      Approve &amp; delete
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Trash</CardTitle>
          <CardDescription>
            Deleted businesses stay restorable for 10 days. Those with call
            history are never removed automatically and stay restorable until
            you destroy them yourself.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {trash.length === 0 ? (
            <p className="py-4 text-sm text-muted-foreground">The trash is empty.</p>
          ) : (
            <ul className="divide-y divide-border/60">
              {trash.map((item) => (
                <li
                  key={item.id}
                  className="flex flex-wrap items-center justify-between gap-3 py-3"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">{item.label}</p>
                    <p className="text-sm text-muted-foreground">
                      Deleted{" "}
                      {item.deleted_at
                        ? new Date(item.deleted_at).toLocaleString()
                        : "recently"}
                      {item.purge_eligible_at
                        ? ` — auto-destroys after ${new Date(
                            item.purge_eligible_at
                          ).toLocaleDateString()}`
                        : " — kept: has work history"}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleRestore(item)}
                    >
                      Restore
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={item.purge_eligible_at === null}
                      onClick={() => setPurgeTarget(item)}
                    >
                      Delete forever
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Staff accounts</CardTitle>
          <CardDescription>
            Assign clients to grant Creative-Mode access; suspend to cut it off
            immediately.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {staff.length === 0 ? (
            <p className="py-4 text-sm text-muted-foreground">
              No staff accounts yet. Add one and assign their clients.
            </p>
          ) : (
            <ul className="divide-y divide-border/60">
              {staff.map((account) => (
                <li key={account.id} className="py-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="flex items-center gap-2 font-medium">
                        <span className="truncate">{account.email}</span>
                        {account.suspended && (
                          <Badge variant="secondary">Suspended</Badge>
                        )}
                      </p>
                      {account.name && (
                        <p className="text-sm text-muted-foreground">{account.name}</p>
                      )}
                      <p className="mt-1 text-sm text-muted-foreground">
                        {(account.assigned_clients ?? []).length === 0
                          ? "No clients assigned"
                          : `Assigned: ${(account.assigned_clients ?? [])
                              .map((c) => c.label)
                              .join(", ")}`}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openAssign(account)}
                      >
                        Assign clients
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setResetTarget(account);
                          setResetPassword("");
                        }}
                      >
                        Reset password
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => handleToggleSuspended(account)}
                      >
                        {account.suspended ? "Reactivate" : "Suspend"}
                      </Button>
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => setDeleteTarget(account)}
                      >
                        Delete
                      </Button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Add staff */}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add staff account</DialogTitle>
            <DialogDescription>
              Hand the password to the hire yourself. Assign their clients after
              the account exists.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <Label htmlFor="staff-email">Email</Label>
              <Input
                id="staff-email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                placeholder="hire@youragency.com"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="staff-name">Name (optional)</Label>
              <Input
                id="staff-name"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="staff-password">Password</Label>
              <Input
                id="staff-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="At least 8 characters"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreateStaff} disabled={isCreating}>
              {isCreating ? "Creating..." : "Create account"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Assign clients */}
      <Dialog open={!!assignTarget} onOpenChange={(open) => !open && setAssignTarget(null)}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Assign clients</DialogTitle>
            <DialogDescription>
              Businesses {assignTarget?.email} may work on in Creative Mode.
              Saving replaces their whole set.
            </DialogDescription>
          </DialogHeader>
          <div className="grid max-h-96 gap-2 overflow-y-auto py-2">
            {clients.map((client) => (
              <label
                key={client.id}
                className="flex items-center gap-3 rounded-lg border border-border/60 px-3 py-2 text-sm"
              >
                <Checkbox
                  checked={assignmentDraft.has(client.id)}
                  onCheckedChange={() => toggleAssignment(client.id)}
                />
                <span className="min-w-0 truncate">{client.label}</span>
              </label>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAssignTarget(null)}>
              Cancel
            </Button>
            <Button onClick={handleSaveAssignments} disabled={isSavingAssignments}>
              {isSavingAssignments ? "Saving..." : "Save assignments"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reset password */}
      <Dialog
        open={!!resetTarget}
        onOpenChange={(open) => !open && setResetTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reset password</DialogTitle>
            <DialogDescription>
              Set a new password for {resetTarget?.email} and deliver it to them
              yourself.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2 py-2">
            <Label htmlFor="reset-password">New password</Label>
            <Input
              id="reset-password"
              type="password"
              value={resetPassword}
              onChange={(e) => setResetPassword(e.target.value)}
              placeholder="At least 8 characters"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetTarget(null)}>
              Cancel
            </Button>
            <Button onClick={handleResetPassword} disabled={isResetting}>
              {isResetting ? "Resetting..." : "Reset password"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete staff confirmation */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete {deleteTarget?.email}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              The account and its client assignments are removed. If this
              person built any agents, the delete is refused -- suspend them
              instead to cut access while keeping their work.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                handleDeleteStaff();
              }}
              disabled={isDeleting}
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {isDeleting ? "Deleting..." : "Delete account"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Purge (destroy forever) confirmation */}
      <AlertDialog
        open={!!purgeTarget}
        onOpenChange={(open) => !open && setPurgeTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Permanently destroy &ldquo;{purgeTarget?.label}&rdquo;?
            </AlertDialogTitle>
            <AlertDialogDescription>
              This cannot be undone. Every agent, call recording, and setting
              for this business is destroyed immediately. If you might still
              want it, restore it instead.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isPurging}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                handlePurge();
              }}
              disabled={isPurging}
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {isPurging ? "Destroying..." : "Destroy forever"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default function CreativeTeamPage() {
  return (
    <CreativePageGate>
      <TeamContent />
    </CreativePageGate>
  );
}
