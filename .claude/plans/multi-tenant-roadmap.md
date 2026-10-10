# Multi-Tenant Agency Platform — Delivery Roadmap

Branch: `feat/multi-tenant-org-switching`
Status: Steps 0-4 complete. Verified end-to-end in the running app (2026-10-07).
V2 backlog below is agreed and not started.

> 2026-10-07 delivery note. Step 2 landed as the Creative-Mode agency surface
> (`/agency/clients` CRUD) rather than per-org member roles -- the PRD puts
> member/role management in V2, and every authenticated operator passes
> `require_agency_operator` until then (flagged in agency.py). Membership
> switching is enforced: a non-member gets 403 from `/organizations/switch`.
> Two real bugs were found by end-to-end testing and fixed with regression
> tests: the resource-count query referenced a nonexistent
> `workflow_runs.organization_id` (fixed via a workflows join), and the
> returned count dicts were sparse (KeyError in the delete guard; now
> pre-zero-filled per requested id).

## Known boundary until V2.1 ships (deliberate, must be understood)

`require_agency_operator` currently passes ANY authenticated local-auth user.
A second signup can SEE every business (names, counts) on the Clients page and
can rename/archive/delete businesses via the agency API, but cannot ENTER one
(`/organizations/switch` 403s for non-members). Acceptable while every account
on the instance is agency staff. The moment the deployment is reachable by
anyone else, this is the first hole: mitigation before roles ship is
`ENABLE_SIGNUP=false` (invite-only by manual account creation).

---

# V2 backlog (agreed 2026-10-07, not started)

## V2.1 — Roles, fixed owner, staff scoping, delete approvals, recovery trash

**Locked decisions (2026-10-07, from the owner):** a fixed owner identity gets
unrestricted access; staff see and touch only assigned clients; staff deletions
require owner confirmation; deleted businesses are recoverable for ~10 days.

### V2.1a — Fixed owner identity

- `OWNER_EMAILS` (comma-separated) in backend env. On signup/login the user's
  role is resolved against it and persisted as `agency_role` on the user row
  (`owner` | `staff`; default staff). Role checks read the column, not the env,
  so rotating the env later cannot demote anyone silently.
- Owner bypasses membership on `/organizations/switch` (may enter ANY business)
  and `require_agency_operator` passes only owners. The switcher dropdown keeps
  listing the owner's own memberships; entering client businesses happens from
  the Clients page, deliberately -- a dropdown of every client does not scale.
- **Security note that comes with this:** under local auth there is no email
  verification, so "fixed owner Gmail" is only as strong as signup control.
  Owner account must be created first, `ENABLE_SIGNUP=false` until staff
  onboarding exists, and email verification is on the hardening list.

### V2.1b — Staff scoping (backend-enforced, not UI-filtered)

- New table `staff_client_assignments` (staff user id <-> organization id),
  agency-wide. Owner needs no assignments -- ownership covers everything.
- `/agency/clients` becomes role-scoped: owner gets every business, staff gets
  only assigned ones. Same scoping on rename/archive/delete/delete-impact:
  a staff member gets 403 on any business they are not assigned to. This also
  closes the known boundary hole (staff touching unassigned businesses via the
  API).
- Staff signup flow: owner creates the staff account from the access page
  (email + one-time password) OR open signup lands as unassigned staff who see
  an empty Clients page until assigned. Default: owner-created accounts.

### V2.1c — Owner access-management settings ("advanced settings")

Owner-only settings page covering:

1. Staff list: email, role, status, assigned clients.
2. Assign/unassign clients per staff (multi-select), create staff accounts,
   reset a staff password, suspend/reactivate an account.
3. Deletion requests queue (see V2.1d) and the recovery trash (see V2.1e).

Suggestions accepted into scope (owner asked what is left):

4. **Audit log** of destructive actions (who renamed/archived/deleted/requested
   what, when) -- pairs with the approval flow; without it, "who did this" is
   unanswerable.
5. **Session revocation on access change**: local auth issues JWTs; removing a
   staff member's assignments or suspending them must invalidate existing
   sessions (token-version column checked per request) or the change is
   cosmetic until token expiry.
6. **Second owner**: supporting more than one email in `OWNER_EMAILS` from day
   one -- one Gmail should not be a single point of failure for the agency.
7. Per-staff data visibility follows assignments everywhere (runs, recordings,
   billing views) -- no separate mechanism, the same assignment predicate.

### V2.1d — Staff deletion requests (owner confirmation)

- Staff "delete" on an assigned business creates a `deletion_requests` row
  (org, requester, timestamp, reason) and the business shows a
  "Deletion pending owner approval" badge. Nothing is destroyed.
- Owner approves (proceeds to V2.1e trash) or rejects (badge clears). Owner
  deleting directly skips the queue -- an owner should not confirm to
  themselves, but the action lands in the audit log either way.

### V2.1e — Recovery window ("trash") + purge — ✅ DELIVERED 2026-10-10

Commit 53ee36e. Delete, owner-approval, and the UI all trash now; restore is
a column write; the impact guard lives only at purge (`POST /agency/trash/{id}/purge`)
and in the nightly ARQ job (00:17, TRASH_RETENTION_DAYS=10), which skips
history-carrying businesses forever rather than destroying them on a timer.
Scoping is query-layer: get_organization_by_id (include_deleted=False default),
list_all_organizations, list_organizations_for_staff, get_organizations_for_user.
Member selections cleared at trash; memberships only at purge. The detail
page's stale pre-delete impact check was removed during live verification --
it wrongly blocked trashing businesses with history.

Still open on this workstream: **nightly `pg_dump` + MinIO snapshot with
tested restore** on the production host (V2.4 ops item) -- the trash protects
against deletes, the backup protects against everything else.

**Done when:** owner enters any business; staff see and touch only assigned
clients (verified at the API level, not just UI); a staff deletion request
needs owner approval; a deleted business is restorable within the window and
auto-purges after it; all of it covered by tests extending the two-tenant
suite.

## V2.2 — White-label completion pass (audit list)

`NEXT_PUBLIC_WHITELABEL` today hides: header Slack link, GitHub star badges,
"Hire an Expert", release nags, overview Dograh promo copy + Resources links.
Still Dograh-branded with the flag ON -- audit and gate each:

- Auth pages: "The open-source voice AI platform" side panel and the
  Enterprise Enquiry CTA ("We deploy Dograh inside your environment").
- Onboarding dialog ("Welcome to Dograh") shown after signup.
- Models page: any Dograh-managed / hosted / MPS-branded service options --
  agency runs BYOK; hosted options are noise or worse, an upsell.
- Chatwoot widget, GTM / Meta Pixel / PostHog / Reo.dev -- confirm all inert
  or explicitly disabled under white-label, not just blank env vars.
- Logo identity: replace `/public/dograh-*.png` + favicon with the agency's
  (asset swap, no code), and set `NEXT_PUBLIC_APP_NAME`.
- Email templates / password-reset mail if local auth sends any.
- Sweep for hardcoded "dograh" strings in user-visible UI (grep + eyeball).

**Done when:** a fresh signup, a hard reload on every page, and the auth flow
show zero upstream-brand references with the flag on.

## V2.3 — MCP / API-key verification pass on the customized fork

Current state (verified): MCP tools are authed by org-scoped API keys; the
key forces its org over the user's personal selection (pinned by isolation
tests 15/16), and every tool call filters by `selected_organization_id`. There
are NO organization-level MCP tools (create/list orgs are operator-UI work by
design).

What remains:

1. One end-to-end MCP test with a real org-scoped key: list agents, create an
   agent, fetch it, and prove a second org's agents are invisible (the TDD
   report already lists this as the known follow-up).
2. Decision recorded: do NOT add agency-level MCP tools (list all clients /
   create clients) until V2.1 roles exist -- an MCP key is a per-org
   credential, and giving it cross-org reach would recreate the operator gate
   outside the role system.
3. Re-run the MCP tool suite after any fork-specific change to
   `organization_context` / scoping helpers (several of those tests are in the
   known-environmental-failure set and must not silently stay red).

## V2.5 — Saved provider keys vault + key dropdown (agreed 2026-10-11)

The gap: dograh's Models page takes one API key per provider, and the
Override flow forces manual key re-entry every time. The PRD's
"multi-provider keys with alias save" was never built.

Scope:

1. **Vault is keys-only.** Model family, model, and every other
   configuration control stay exactly as they are. The API-key input gains a
   "use saved key" dropdown (filtered to the selected provider) beside the
   existing manual entry, which stays for one-off keys. Empty vault = page
   behaves exactly as today. Nothing hidden, nothing removed.
2. Backend: `provider_key_vault` table (organization_id, provider_type,
   provider_name, alias, api_key encrypted with the same mechanism the
   existing credentials store uses, is_active). Org-scoped CRUD routes;
   list responses mask keys -- raw keys are never returned after save.
3. Frontend: the key dropdown on the Models page and the Override dialog
   reads the vault; a small manage section saves/deletes aliases.
4. Tests: vault CRUD + isolation (another org's keys invisible), masked
   list responses, override flow accepting a vault key id.

Order: after V2.2 (white-label) or standalone on request.

## V2.6 — Failed-run monitoring & alerting (agreed 2026-10-11)

Must-have once businesses rely on agents: the agency must learn about a
broken agent before the client does.

Scope:

1. Failed-run detection already exists as data (workflow_runs carry failure
   state); what is missing is the agency-facing surface: a Creative-side
   health view (failures in the last 24h per business, error rates) and
   alerting.
2. Alerting v1: email (or webhook) to the owner when a business records
   N consecutive failed runs or an error-rate spike. Debounced per business
   so a dead phone number does not spam.
3. Detail: which agent, which business, the error, and a link to the run.

Order: after V2.5.

## V2.4 — Production hardening checklist (before first real client)

- `ENABLE_SIGNUP=false` until V2.1 (see boundary note) -- or immediately if
  the deployment leaves the office network.
- Email verification + stronger password policy for local auth.
- Postgres + MinIO backup schedule and a tested restore -- nightly, 10-day
  retention (pairs with the V2.1e recovery window: trash is the accidental-
  delete button, backups are the everything-else net).
- Telemetry: `ENABLE_TELEMETRY=false` (agency-privacy under white-label).
- HTTPS + `CORS_ALLOWED_ORIGINS` explicit allowlist (the `*` fallback is an
  OSS-dev convenience, not a production posture).
- Alembic discipline: every fork change that touches `db/models.py` ships a
  migration in the same commit; never hand-edit the client DBs.
- Fix the environmental test failures (npm install in
  `mcp_server/ts_validator/`) so "tests red" regains its meaning as "we broke
  something".

## Rule

One step at a time. Each step ends with: tests green → you see it working in the
running app → you say continue. No step starts until the previous one is verified.

---

## Step 0 — Commit the working org-switching work ✅ DONE

**Why first:** 19 uncommitted files on `main`, including 37 passing tests. One bad
`git` command and all of it was gone.

**Done:** created branch `feat/multi-tenant-org-switching`, reviewed the full diff
file by file, committed as `947ff8e`. Working tree clean.

Review notes recorded at commit time:
- `api/pyproject.toml` shows as modified but has an empty diff — a `core.autocrlf`
  stat-cache artifact against an LF-rewritten file. Nothing real to commit.
- `ui/package-lock.json` 1.45.0 → 1.46.0 is legitimate: `package.json` already said
  1.46.0 in a prior commit, the lockfile was stale and npm synced it.
- The two `fastmcp` import-path fixes are required by the 4.0.9 pin and are correct.

**Verified:** `37 passed` (28 isolation + 9 workflow list route), re-run immediately
before committing.

---

## Step 1 — `organizations.name` column + backfill

**Why:** today the sidebar renders `org_oss_1756200000_ab12cd34` as the org label.
`OrganizationModel` has no `name` column — `provider_id` is the only identifier.
Nothing downstream is usable for a real agency until a client has a name.

**Scope (9 required edits + 1 migration):**
1. `api/db/models.py` — add `name = Column(String, nullable=True)` to `OrganizationModel`
2. `api/alembic/versions/<new_rev>_add_organization_name.py` — `down_revision = "f3a1c47b9e02"`
   (current head), with backfill `UPDATE organizations SET name = provider_id WHERE name IS NULL`
3. `api/schemas/organization.py` — `name: str | None = None` on `OrganizationListItem`
4. `api/routes/organization.py:237` — pass `name=o.name`
5. `api/db/organization_client.py:45` — `name` param on `get_or_create_organization_by_provider_id`
6. `api/routes/auth.py:42` — pass the signup name (already available at line 38)
7. `api/services/auth/depends.py:104` — Stack path name, or `None`
8. `ui/src/components/layout/SidebarTeamSwitcher.tsx:136,143,145` — render `org.name ?? org.provider_id`
9. `pnpm generate-client` in `ui/` (backend must be running — it is)

Also worth doing, both are currently *lying*:
- `api/db/workflow_run_client.py:182` — `organization_name` is currently built from
  `provider_id`. Switch it to the real name.
- `api/services/organization_context.py` — add `organization_name` to
  `OrganizationContextResponse` so the single-active-org case needs no second fetch.

**Key design points:**
- `name` stays **nullable**. All 19 test sites construct `OrganizationModel(provider_id=...)`
  and stay green unchanged; a non-nullable column would touch all of them.
- `OrganizationListItem.name` needs a `None` default, because the existing isolation tests
  build orgs as `SimpleNamespace` without a `name` attribute and Pydantic would raise.
- The external `sdk/python` and `sdk/typescript` are **not** touched — `organization.py`
  has zero `@sdk_expose` decorators.

**Done when:** sidebar shows real names, a renamed org survives reload, 37 tests still pass.

**Estimate:** half a day.

---

## Step 2 — Org CRUD + member management

**Why it's the big one:** ~90% of it does not exist. There is no create/update/delete
org, no member list, no role column, no org-admin dependency, no member UI. What exists
is three endpoints (`/context`, `/mine`, `/switch`) and a two-column join table.

**Decisions locked with you:**
- **Add members by existing email.** No invite token table, no expiry, no email dispatch.
  Covers the real agency case (your own staff).
- **Two roles: Owner / Member.** Owner can manage members, Member cannot. The org
  creator is Owner.

**Build order:**
1. Migration — `organizations.name` (done in step 1), `role` on `organization_users`,
   index on `organization_id`
2. DB layer — ~8-10 methods: create/update/archive org, remove member, get member,
   member count, role get/set
3. Schemas — ~6 models: create/update/response, member response, role enum
4. **A real `get_organization_admin` dependency.** This is the design work.
5. Routes — ~8-10 endpoints, each re-deriving membership
6. UI — members section in `/settings`, table + add-by-email form
7. Tests — extend the two-tenant isolation suite

**The trap to avoid:** `get_user_with_selected_organization` **does not authorize**. It
raises if you have no org selected but never checks you are a *member* of it. Every
member endpoint must re-derive membership from scratch, copying the idiom at
`api/routes/organization.py:266-273` which already carries the comment explaining why.

**Done when:** an Owner can add and remove members, a Member cannot, a non-member gets
403 on every route, and all of it is covered by the two-tenant suite.

**Estimate:** 3-4 days.

---

## Step 3 — Creative / Organization mode switch

**Depends on step 2** — a mode toggle needs real orgs to switch between, and a dropdown
of `org_oss_9f2c…` cannot drive a mode toggle.

**Estimate:** 1 day.

---

## Step 4 — White-labeling

**Independent** of steps 1-3. Branding, not data. Slot it anywhere.

**Estimate:** 1-2 days.

---

## Total: ~6-8 working days

## Not started, out of scope

Nothing is pushed to a remote. `main` is untouched — all work is on
`feat/multi-tenant-org-switching`. Merging is your call.
