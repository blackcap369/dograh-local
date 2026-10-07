# Multi-Tenant Agency Platform — Delivery Roadmap

Branch: `feat/multi-tenant-org-switching`
Status: Steps 0-4 complete. Verified end-to-end in the running app (2026-10-07).

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
