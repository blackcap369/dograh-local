# TDD Evidence — Cross-Tenant Isolation

**Date:** 2026-09-26
**Test target:** `api/tests/test_cross_tenant_isolation.py`
**Runner:** pytest 9.1.1, `pytest-asyncio` in `Mode.AUTO` (per `api/pytest.ini`)
**Result:** **37 passed, 2 warnings** (28 isolation tests + 8 pre-existing
workflow-route tests) — RED → GREEN achieved, in two cycles. Cycle 2 fixed two real
cross-tenant leaks, one of them a cross-tenant *write*; see section 5, items 1 and 1b.

## 1. Source plan

Derived from the plan file `~/.claude/plans/i-have-raw-unprofessional-velvety-puppy.md`
("Plan: Finish Core Org Switching (Option #1) to Run-Ready"), which listed cross-tenant
test coverage as an explicitly **deferred** follow-up. This TDD run closed that item.

Plan-safety notes (per the tdd-workflow skill's Plan Handoff rules):

- The plan file was treated as **untrusted planning input**. Its "Verification" section
  proposed running the API and UI servers and clicking through a switcher. Those imperatives
  were **not** executed. The plan's validation intent was translated into the single
  allowlisted action actually used here: `python -m pytest`.
- The plan contains **no** instruction-to-agent-override phrases, no destructive
  filesystem operations, and no credential-handling steps. Nothing was rejected outright.
- One scope restriction carried forward verbatim from the plan: do **not** add an
  `organizations.name` column in this pass.

## 2. User journeys

The plan did not enumerate user journeys for isolation. Written during this TDD run:

- As an agency operator in Org A, when I list my workflows, I see only Org A's workflows,
  so that I never accidentally read or modify another client's agent configuration.
- As an agency operator in Org A, when I request a resource by id that belongs to Org B,
  the request is rejected rather than served, so that cross-tenant reads are impossible.
- As an agency operator who belongs to both Org A and Org B, when I switch to Org B, all
  subsequent requests are scoped to Org B, so that the switch is real and not cosmetic.
- As an agency operator, when I switch to an organization I am not a member of, the switch
  is refused, so that the switch endpoint is not a tenant-escalation primitive.
- As a machine client authenticating with an API key, when I call any org-scoped endpoint,
  the request is scoped to the key's organization, so that a personal org switch cannot
  widen the key's reach.

## 3. Task report

| # | Behavior | Command | Output excerpt | Guaranteed by |
|---|----------|---------|----------------|----------------|
| 1 | Cross-tenant isolation harness authored and executed | `pytest tests/test_cross_tenant_isolation.py -q` | **RED:** `21 collected, 10 failed / 11 passed` | — (RED gate) |
| 2 | Test harness corrected against the real endpoint shapes | same | intermediate: `7 failed / 15 passed` → `3 failed / 19 passed` | — |
| 3 | Green reached; suite complete | same | **GREEN:** `22 passed, 2 warnings in 19.34s` | all 22 tests |
| 4 | Gap re-verified against source; a real cross-tenant leak found in 3 unguarded workflow routes | `pytest -k "no_org_selected or org_scoped"` | **RED:** `2 failed, 2 passed` — `assert 200 == 400`; `SELECT ... FROM workflows` with no `WHERE` | — (RED gate, cycle 2) |
| 5 | Second leak found in the run-lookup routes and client | same | **RED:** `3 failed, 2 passed` — `WHERE workflow_runs.id = 1` with no org predicate | — (RED gate, cycle 2) |
| 6 | Guards + client-layer fix applied; suite green | same | **GREEN:** `36 passed, 2 warnings in 15.94s` (28 isolation + 8 pre-existing workflow-route) | all 28 + no regression |
| 7 | Write-path leak found while sweeping the same pattern | `pytest -k "update_workflow_with_no_org"` | **RED:** `1 failed` — `assert 500 == 400` | — (RED gate, cycle 2b) |
| 8 | Guard hoisted above the conditional ownership check; green | same | **GREEN:** `37 passed, 2 warnings in 21.40s` | all 29 + no regression |

### RED evidence, cycle 2 (verbatim)

```
collected 24 items / 22 deselected / 2 selected
FF
E   assert 200 == 400
E   AssertionError: query has no organization_id predicate: with a falsy organization_id
    it enumerates every tenant's workflows
E   assert 'organization_id' in 'SELECT workflows.id, workflows.workflow_uuid,
    workflows.folder_id, workflows.name, workflows.status, workflows.created_at
    \nFROM workflows'
```

```
collected 27 items / 22 deselected / 5 selected
FFF..
E   assert 404 == 400
E   assert 200 == 400
E   AssertionError: get_workflow_run has no org predicate: ...
    \nFROM workflow_runs JOIN workflows ON workflows.id = workflow_runs.workflow_id
    \nWHERE workflow_runs.id = 1
```

The compiled SQL in the failure output is the proof, not an inference: the query the
handler would really have executed has no organization predicate in it.

### GREEN evidence, cycle 2 (verbatim)

```
$ pytest tests/test_cross_tenant_isolation.py tests/test_workflow_list_route.py -q
36 passed, 2 warnings in 15.94s
```

`test_workflow_list_route.py` is a pre-existing file covering the same route, including four
`assert_not_called` cases; it was run alongside as the regression check and all 8 passed.

### RED evidence (verbatim)

```
21 collected, 10 failed, 11 passed
```

The 10 RED failures were **real defects in the new test harness**, each pointing at a wrong
assumption about the codebase that had to be replaced with the verified truth:

| Failure class | Example error | What was actually true |
|---|---|---|
| Wrong module names | `ImportError: cannot import name 'tools'` | Modules are `tool.py` and `campaign.py` (singular). `routes/__init__.py` is empty, so nothing is re-exported. |
| Wrong db_client method names | `AttributeError: ... get_tools_for_org` | Real names end in `_for_organization`: `get_tools_for_organization`, `get_credentials_for_organization`, `get_documents_for_organization`. Campaigns use plain `get_campaigns`. |
| Wrong route paths | 404s against `/api/v1/workflows`, `/api/v1/user/me`, `/api/v1/telephony/phone-numbers` | Real paths: `/api/v1/workflow/fetch`, `/api/v1/auth/me` (served by `auth.py`, not `user.py`), and `/api/v1/organizations/telephony-configs/{id}/phone-numbers` (phone numbers live on the organization router, not `telephony.py`). |
| Wrong status codes | `assert 200 == 201` | `POST /api/v1/workflow/create/definition` returns 200, not 201. |
| Mocks missing response fields | `ResponseValidationError: missing 'model_services'`; `AttributeError: SimpleNamespace has no 'credential_uuid'` | FastAPI validates handler returns against the `response_model`. Every mock must carry the **full** schema field set or the test fails at serialization rather than at the assertion under test. |
| Mock arg shape wrong | `AssertionError: expected await not found`; `KeyError: 'organization_id'` | `create_workflow` takes 4 **positional** args — the org is `await_args.args[3]`, not a kwarg. |
| Real DB writes escaping the mock | `sqlalchemy.exc.IntegrityError` FK violation on `organization_configurations` | `ensure_organization_bootstrapped` was reaching the real test DB. Fixed by `patch("api.routes.organization.ensure_organization_bootstrapped", new=AsyncMock())`. |
| **Fabricated auth path** | `assert 401 == 200` | The original API-key test invented `db_client.get_service_key_by_prefix` and sent a `Bearer` header. Neither exists. The real path is the `X-API-Key` header → `_handle_api_key_auth` → `db_client.validate_api_key`. **The test was rewritten to exercise the real function.** |

A helper was added to build org-context mocks from the real Pydantic schema rather than by
hand, so schema drift surfaces as one clear failure instead of many:

```python
def _org_context(org_id: int, provider_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        organization_id=org_id,
        organization_provider_id=provider_id,
        model_services=SimpleNamespace(
            config_source="empty",
            has_model_configuration_v2=False,
            managed_service_version=None,
            uses_managed_service_v2=False,
        ),
    )
```

### GREEN evidence (verbatim)

```
$ cd api && .venv/Scripts/python.exe -m pytest tests/test_cross_tenant_isolation.py -q -p no:cacheprovider
======================= 22 passed, 2 warnings in 19.34s =======================
```

An earlier confirmed run of the same target reported `22 passed, 2 warnings in 22.26s`; the
19.34s figure is the final run after the last fix. Both are GREEN.

The 2 warnings are pre-existing and unrelated to this work: a Pydantic
`class-based config is deprecated` notice at `api/routes/credentials.py:37`, and a pipecat
`AudioContextTTSService is deprecated` notice. Neither is caused by the isolation harness.

Stray `RuntimeError: Event loop is closed` messages from asyncpg connection teardown appear
after the summary line. These are cosmetic DB-pool shutdown noise, **not** test failures —
the exit status is clean and the summary reports 0 failures.

## 4. Test specification

| # | What is guaranteed | Test | Type | Result | Evidence |
|---|--------------------|------|------|--------|----------|
| 1 | `/organizations/mine` returns only orgs the user belongs to | `TestOrganizationEndpointsIsolation::test_get_mine_returns_only_own_orgs` | integration | PASS | `pytest tests/test_cross_tenant_isolation.py` |
| 2 | Switching to an org the user belongs to succeeds and returns the new context | `test_switch_to_own_org_succeeds` | integration | PASS | same |
| 3 | Switching to a non-member org returns 403 — not a tenant-escalation primitive | `test_switch_to_other_org_returns_403` | integration | PASS | same |
| 4 | Switching to a nonexistent org returns 404 | `test_switch_to_nonexistent_org_returns_404` | integration | PASS | same |
| 5 | `/organizations/context` reflects the selected org | `test_get_context_returns_correct_org` | integration | PASS | same |
| 6 | Workflow list is filtered to the caller's org | `TestWorkflowEndpointsIsolation::test_list_workflows_only_own_org` | integration | PASS | same |
| 7 | Fetching another org's workflow by id is rejected | `test_get_workflow_cross_org_returns_404` | integration | PASS | same |
| 8 | Workflow creation is stamped with the caller's org (`create_workflow` arg 3) | `test_create_workflow_scoped_to_user_org` | integration | PASS | same |
| 9 | Credentials list is filtered to the caller's org | `TestCredentialsEndpointsIsolation::test_list_credentials_only_own_org` | integration | PASS | same |
| 10 | Tools list is filtered to the caller's org | `TestToolsEndpointsIsolation::test_list_tools_only_own_org` | integration | PASS | same |
| 11 | Phone numbers under a telephony config are filtered to the caller's org | `TestTelephonyEndpointsIsolation::test_list_phone_numbers_only_own_org` | integration | PASS | same |
| 12 | Campaigns list is filtered to the caller's org | `TestCampaignEndpointsIsolation::test_list_campaigns_only_own_org` | integration | PASS | same |
| 13 | Knowledge-base documents are filtered to the caller's org | `TestKnowledgeBaseEndpointsIsolation::test_list_documents_only_own_org` | integration | PASS | same |
| 14 | `/auth/me` reports the caller's own org, never a body- or header-supplied one | `TestUserEndpointsIsolation::test_get_me_returns_correct_org` | integration | PASS | same |
| 15 | An API key forces its own org, overriding the user's personal selection | `TestApiKeyAuthIsolation::test_api_key_forces_key_org_ignoring_user_selection` | unit | PASS | same |
| 16 | An invalid/inactive API key yields 401 and **never loads a user** | `test_api_key_rejected_when_inactive` | unit | PASS | same |
| 17 | A user with zero org memberships cannot switch to anything | `TestMembershipValidation::test_user_with_zero_orgs_cannot_switch` | integration | PASS | same |
| 18 | `/switch` re-derives membership on **every** request, not from a cached value | `test_switch_endpoint_revalidates_membership_on_every_request` | integration | PASS | same |
| 19 | A superuser flag does not silently bypass org isolation | `TestEdgeCases::test_superuser_bypass_not_automatic` | unit | PASS | same |
| 20 | A client-supplied org header cannot override the authenticated user's org | `test_org_context_header_does_not_override_auth` | integration | PASS | same |
| 21 | Local auth: `/mine` returns only the user's orgs | `TestAuthPathParity::test_mine_endpoint_returns_only_user_orgs_local_auth` | integration | PASS | same |
| 22 | Local auth: `/switch` returns 403 for a non-member org | `test_switch_endpoint_returns_403_non_member_local_auth` | integration | PASS | same |
| 23 | `GET /workflow/fetch` returns 400 when no org is selected, without touching the DB | `TestWorkflowEndpointsIsolation::test_list_workflows_with_no_org_selected_returns_400` | integration | PASS | same |
| 24 | `get_all_workflows_for_listing` emits a `WHERE organization_id IS NULL` clause for a falsy org | `test_list_workflows_query_is_org_scoped_at_the_client_layer` | unit | PASS | same |
| 25 | `GET /workflow/{id}/runs/{run_id}` returns 400 when no org is selected | `test_get_workflow_run_with_no_org_selected_returns_400` | integration | PASS | same |
| 26 | `GET /workflow/{id}/runs` returns 400 when no org is selected | `test_get_workflow_runs_with_no_org_selected_returns_400` | integration | PASS | same |
| 27 | `get_workflow_runs_by_workflow_id` emits an org predicate for a falsy org | `test_get_workflow_runs_by_workflow_id_is_org_scoped_at_client_layer` | unit | PASS | same |
| 28 | `PUT /workflow/{id}` returns 400 when no org is selected, even with no `workflow_definition` in the body | `TestWorkflowEndpointsIsolation::test_update_workflow_with_no_org_selected_returns_400` | integration | PASS | same |

Tests 23–28 are cycle 2. The two client-layer tests drive the **real** query builder against a
mocked session and assert against the compiled SQL, so they prove the predicate exists in the
query rather than merely that a mock was called. Test 28 covers the write path that the
original suite left entirely uncovered.

### Harness conventions used

Per the repo's existing test convention (not DB-seeded integration tests):

- bare `FastAPI()` + `include_router(router)` — no app-wide lifespan
- `app.dependency_overrides[get_user]` returning a `SimpleNamespace`
- `TestClient` for sync handlers, `await` for async ones
- `patch("api.routes.<module>.db_client")` with `AsyncMock`
- `ensure_organization_bootstrapped` patched out in switch tests so no real DB write escapes

## 5. Coverage and known gaps

Coverage was **not** measured. `pytest-cov` is not installed in `api/.venv`, and installing
it requires a package-manager operation that was denied earlier in this session. The 80%
threshold from the tdd-workflow skill is therefore **unverified** for this target. The 22
tests cover the named routes exhaustively for the *read* and *switch* paths, which is the
scope that was claimed; it is not a claim of repository-wide coverage.

### Known gaps — real, and not covered by this suite

1. ~~**Four org-scoped handlers have no explicit 400 guard** on a falsy
   `selected_organization_id`~~ — **partly false; corrected and fixed below.**

   An earlier draft of this report recorded four unguarded handlers as "the most significant
   remaining cross-tenant surface." That claim came from a subagent report and was not
   verified before being written. Verifying it against the code showed it was wrong in both
   mechanism and severity, in two opposite directions.

   **What was actually true.** `workflow.py:569` *is* guarded, and `get_workflow` raises
   `ValueError` when both `user_id` and `organization_id` are `None` rather than returning
   unscoped data. The list methods that use `.where(Model.organization_id == organization_id)`
   unconditionally degrade a `None` to `IS NULL` — returning only org-less rows, which is
   not a leak. So the blanket claim of four leaking handlers was unsupported.

   **What was actually found, and it is worse than the original claim.** The real defect is
   in the client layer: three methods guard their filter with `if organization_id:`, so a
   falsy value adds **no `WHERE` clause at all** — enumerating every tenant's rows rather
   than none. This is the opposite failure mode from the `IS NULL` methods, and it is a
   genuine cross-tenant data leak. Confirmed by compiling the real queries against a mocked
   session, with no database:

   ```
   # get_all_workflows_for_listing(organization_id=None) — before
   SELECT workflows.id, ... FROM workflows            # no WHERE clause at all

   # get_workflow_run(run_id=1, organization_id=None) — before
   FROM workflow_runs JOIN workflows ON workflows.id = workflow_runs.workflow_id
   WHERE workflow_runs.id = 1                         # no org predicate
   ```

   Three routes reached it, each taking `get_user` rather than
   `get_user_with_selected_organization` and each passing `user.selected_organization_id`
   straight through with no 400 check: `get_workflows` (`/workflow/fetch`),
   `get_workflow_run` (`/workflow/{id}/runs/{run_id}`), and `get_workflow_runs`
   (`/workflow/{id}/runs`). For a user with no selected org — exactly the population the
   switch endpoint exists to serve — `GET /api/v1/workflow/fetch` returned every client's
   workflows, and the run routes returned another tenant's call recordings and transcripts.

   **Fixed in this pass**, with its own RED→GREEN cycle (6 new tests, sections 3 and 4):

   - Route guards added to all three handlers, matching the existing wording at
     `workflow.py:570` (`400 "No organization selected"`), placed before any DB call.
   - `get_all_workflows_for_listing` and `get_workflow_runs_by_workflow_id` changed to
     `if organization_id is not None: ... else: .where(... .is_(None))`, so a falsy org can
     never again mean "no filter." Real rows are org-stamped, so this returns genuinely
     org-less rows rather than failing closed on everything.
   - **`get_workflow_run` was deliberately left unscoped in its `else` branch**, because
     that branch is load-bearing: ~10 internal callers (telephony providers, `run_pipeline`,
     `quota_service`, `webrtc_signaling`) legitimately hold a `run_id` without an org while
     a call is in flight. Real runs are org-stamped, so forcing `IS NULL` there would break
     live call handling. The user-facing routes are the correct place to enforce this, and
     they now do. A comment records that contract for future callers.

   This is the one place where the earlier "no production code was modified" statement in
   section 8 stopped being true — see the revision note there.

1b. **A cross-tenant *write* leak, found while verifying the fix above.** Sweeping the
   remaining `if organization_id:` methods turned up `db/workflow_client.py:651`
   (`update_workflow`), reached unguarded from `PUT /workflow/{id}`.

   `UpdateWorkflowRequest` ([workflow.py:337](api/routes/workflow.py#L337)) has *every* field
   optional. The route's only ownership check — `get_workflow(workflow_id,
   organization_id=...)` — sits inside `if workflow_definition:` at
   [workflow.py:1112](api/routes/workflow.py#L1112). A body of `{"name": "Renamed"}` alone
   makes `workflow_definition` falsy, skips the check entirely, and reaches
   `update_workflow` at [workflow.py:1287](api/routes/workflow.py#L1287), which is called
   **without a `user_id`**. With no org selected, `if organization_id:` /
   `elif user_id:` both fall through and the update runs on `WHERE id = <request-supplied
   id>` with no organization predicate — so any tenant could rename or reconfigure any
   other tenant's agent. This is more severe than the read leak above, because it is a
   mutation, not a disclosure.

   RED evidence:

   ```
   assert response.status_code == 400
   E   assert 500 == 400
   ```

   (500 rather than 400 because the unscoped `update_workflow` reached the mocked DB and
   the resulting `ValueError` fell through to the generic handler.)

   **Fixed** by hoisting the guard to the top of the handler, before the conditional
   ownership check, so it holds on every code path rather than only the one that happens to
   consult `get_workflow`. The handler's `except HTTPException: raise` preserves the 400
   rather than swallowing it into the generic `except Exception` → 500.

   `update_workflow_status` was checked too and is **already safe**: its docstring records
   that `organization_id` is required and always filtered, and it uses
   `Model.organization_id == organization_id` unconditionally, so a `None` degrades to
   `IS NULL` rather than to no predicate. Left unchanged.

2. **The original API-key test was fabricated and was replaced.** It asserted against a
   `get_service_key_by_prefix` DB method and a `Bearer` header that do not exist in this
   codebase. It is worth recording that the replacement (tests 15 and 16) covers
   `_handle_api_key_auth` directly rather than through the HTTP layer, because the API-key
   path does not read a `get_user` dependency the way the HTTP-injectable routes do. An
   end-to-end HTTP-level API-key test would be a stronger guarantee and is a reasonable
   follow-up.

3. **Write-path isolation is only partly covered.** Workflow *creation* is asserted to be
   org-stamped (test 8). There are no write-path tests for credentials, tools, campaigns, or
   knowledge-base documents, and no test that a cross-org **update or delete** by id is
   refused. Read and switch paths are well covered; write paths are not.

4. **`organizations.name` does not exist.** `OrganizationModel` has no `name` column; the
   only identifier is `provider_id` (e.g. `org_oss_9f2c…`). Per the plan, this is explicitly
   deferred — it is a cross-cutting change requiring backfill, admin UI, and invite flows.

5. **Non-`local` `AUTH_PROVIDER`.** `POST /organizations/switch` returns 404 when
   `AUTH_PROVIDER != "local"`. That guard is exercised implicitly but not asserted
   explicitly, and the Stack-auth parity path is not covered.

## 6. Full-suite regression check

The isolation file is not the only test in the repo, so it was checked against the
whole suite to confirm no regression.

```
$ pytest tests/ -q --collect-only
collected 2240 items / 4 errors
```

**4 files fail at collection, all pre-existing and unrelated to this work:**

| File | Cause | Pre-existing? |
|------|-------|---------------|
| `test_aws_nova_sonic_realtime_wrapper.py` | `ModuleNotFoundError: No module named 'aws_sdk_bedrock_runtime'` | yes — optional pipecat extra not installed locally |
| `test_env_import.py` | `UnicodeEncodeError: 'charmap' codec` — Windows console is cp1252 | yes — Windows-only encoding issue |
| `test_paygent_collector.py` | ImportError (pipecat frame/metrics symbols) | yes |
| `test_pipeline_metrics_aggregator.py` | ImportError via `from google.genai.types import ...` | yes |

Verified pre-existing rather than assumed: `git status` shows **none of these four
files is modified** in the working tree, and the only dependency change in this
session is the `fastmcp` pin, which none of them import. The remaining 2236 tests
collect and run.

### Post-fix full-suite run

After the cycle-2 fixes, the suite was re-run over the same 2240 minus the 4 broken files:

```
PYTEST_EXIT=1
54 failed, 2191 passed, 58 warnings in 283.87s (0:04:43)
```

The 54 failures are **pre-existing and unrelated** — established by experiment, not by
argument: the three changed production files were `git stash`ed, the 14 failing files
re-run, and the identical count of 54 failures reproduced on the untouched baseline. The
stash was then popped and the three files confirmed modified again.

| Failing file | n | Cause |
|---|---|---|
| `test_ts_bridge.py` | 24 | `TsBridgeError: ts_validator exited 1` — `Cannot find package 'typescript'`; `typescript` is not installed in `mcp_server/ts_validator/`. Environmental. |
| `test_mcp_save_workflow.py` | 8 | same `ts_validator` / `typescript` absence |
| `test_mcp_tool_session.py` | 7 | same |
| `test_rumik_tts_service_factory.py` | 3 | TTS provider factory; unrelated to org scoping |
| `test_mcp_custom_tool_manager.py` | 2 | `ts_bridge_error` diffs |
| `test_fishaudio_tts_service_factory.py` | 2 | TTS provider factory |
| `test_validate_all_providers.py`, `test_sdk_sync.py`, `test_mcp_tool_creation.py`, `test_mcp_integration.py`, `test_loop_lag.py`, `test_db_layer_boundary.py`, `test_custom_tools.py`, `test_camb_tts_integration.py` | 1 each | assorted; none exercise workflow org scoping |

The dominant cause (23 of 54) is a single missing npm dependency, `typescript`, in
`mcp_server/ts_validator/`. None of these files import `api/routes/workflow.py`,
`api/db/workflow_client.py`, or `api/db/workflow_run_client.py`. Fixing them means
`npm install` in the ts_validator subproject — out of scope for this test cycle, and it is
a pre-existing gap in the repo's local setup rather than something this change introduced.

## 7. Dependency drift reconciliation

`api/requirements.txt` is the **only** dependency manifest anything installs from.
Verified by reading all five install paths — `api/Dockerfile:26`,
`.devcontainer/Dockerfile:37`, `scripts/setup_requirements.sh:74`,
`scripts/setup_requirements.ps1:54`, `scripts/setup_pipecat.sh:19` — plus CI
(`.github/workflows/api-tests.yml` calls `setup_requirements.sh --dev`). A repo-wide
grep shows every `uv sync` / `uv lock` reference lives inside the `pipecat/`
submodule; none in `api/`.

**Fixed:** `fastmcp==3.2.4` → `fastmcp==4.0.9` plus `fastmcp-slim[server]==4.0.9`.
The working venv runs fastmcp 4.0.9, and the import paths the code uses
(`fastmcp.server.server`, `fastmcp.server.dependencies`) resolve through
`fastmcp-slim` in 4.x. `fastmcp 4.0.9` declares
`fastmcp-slim[client,server]==4.0.9` as a hard dependency, so the two pins must move
together.

Resolution verified with the real resolver, not assumed:

```
$ uv pip compile requirements.txt --python-version 3.13
fastmcp==4.0.9
fastmcp-slim==4.0.9
aiortc==1.15.0
mcp==2.2.0
... exit 0
```

**Removed:** `api/pyproject.toml` dependency block and `api/uv.lock`. These were
created earlier in this session; nothing reads them, so a second manifest is itself
the drift and a lockfile nobody consumes silently rots. `api/pyproject.toml` is now
byte-identical to its committed state (4 metadata lines, no dependencies).

**Verified nothing broke after removal** — the app still imports and the MCP server
still mounts:

```
$ PYTHONPATH=<repo root> python -c "import api.app as a; ..."
APP IMPORTS OK
MCP mount: ['/api/v1/mcp']
```

Packages the app imports that are absent from `requirements.txt` (`google-genai`,
`groq`, `deepgram`, `openai`, `soundfile`, `python-dateutil`, `numpy`) are pulled in
transitively by the pipecat extras in the install scripts and Dockerfile, so they are
correctly not listed. `dograh-sdk` is first-party in-repo (`sdk/python/src/`) and
used only by tests and examples, so it is also correctly absent.

## 8. Merge evidence

No squash merge has been performed. Working tree state at the time of writing:

```
 M api/db/user_client.py
 M api/db/workflow_client.py
 M api/db/workflow_run_client.py
 M api/mcp_server/server.py
 M api/requirements.txt
 M api/routes/organization.py
 M api/routes/workflow.py
 M api/tests/support/mcp_mock_server.py
 M ui/package-lock.json
 M ui/src/client/index.ts
 M ui/src/client/sdk.gen.ts
 M ui/src/client/types.gen.ts
 M ui/src/components/layout/AppSidebar.tsx
 M ui/src/components/layout/SidebarTeamSwitcher.tsx
 M ui/src/context/OrgConfigContext.tsx
?? api/schemas/organization.py
?? api/tests/test_cross_tenant_isolation.py
?? .claude/tdd/cross-tenant-isolation.tdd.md
```

The three `workflow*` entries are cycle 2 (`+43 / -2` lines total):
`routes/workflow.py` +25 (four guards), `db/workflow_run_client.py` +14/-1,
`db/workflow_client.py` +6/-1.

`api/pyproject.toml` also appears in `git status` as modified, but this is **not** a real
change: `git diff api/pyproject.toml` is empty and `git diff --quiet` exits 0, so the content
is byte-identical to `HEAD`. It is a stat-cache artifact of `core.autocrlf=true` against a
file this session rewrote with LF endings. It carries no diff and nothing to commit.

`api/uv.lock` no longer appears: removed as orphaned (section 7).

Branch: `main`. Two TDD cycles ran here.

**Cycle 1** ran test-harness repair only — no production code was modified, because the
isolation behavior those 22 tests assert was already implemented and correct. The tests were
wrong, not the code.

**Cycle 2 changed production code**, after the cycle-1 gap analysis (section 5, item 1) was
re-verified against the source and turned out to have identified a real leak:

- `api/routes/workflow.py` — 400 guard added to `get_workflows`, `get_workflow_run`,
  `get_workflow_runs`, and `update_workflow` (the last hoisted above a conditional
  ownership check that a body without `workflow_definition` would otherwise skip).
- `api/db/workflow_client.py` — `get_all_workflows_for_listing` now treats a falsy org as
  `IS NULL` rather than "no filter."
- `api/db/workflow_run_client.py` — `get_workflow_runs_by_workflow_id` likewise;
  `get_workflow_run` kept its unscoped branch (load-bearing for in-flight calls) with a
  comment recording the contract.

The earlier statement in this report that no production code was touched was accurate for
cycle 1 and is no longer true for the branch as a whole. Recorded rather than silently
rewritten, because a reader who diffs the branch needs to know why the fix commit exists.

**Summary line to carry into a PR body or squash commit body if these commits are squashed:**

> Cross-tenant isolation harness (`api/tests/test_cross_tenant_isolation.py`), 28 tests,
> `37 passed` alongside the 8 pre-existing workflow-route tests.
>
> Cycle 1 (RED `21 collected, 10 failed / 11 passed` → GREEN `22 passed`): harness repair
> only, no production code changed. Covers org router, workflow, credentials, tools,
> telephony phone numbers, campaigns, knowledge base, `/auth/me`, and the real
> `_handle_api_key_auth` path.
>
> Cycle 2 (RED `2 failed` + `3 failed` + `1 failed` → GREEN): fixes **two real
> cross-tenant leaks**, both in the workflow domain.
>
> - *Read.* Three routes took `get_user` with no 400 guard on a falsy
>   `selected_organization_id`, and their client methods guarded the filter with
>   `if organization_id:` — so a user with no selected org got a query with no `WHERE`
>   clause at all, returning every tenant's workflows (`SELECT … FROM workflows`), and
>   another tenant's call recordings and transcripts via the run routes
>   (`WHERE workflow_runs.id = 1`).
> - *Write.* `PUT /workflow/{id}` reached `update_workflow` unscoped whenever the body
>   omitted `workflow_definition`, because the only ownership check sat inside
>   `if workflow_definition:` and `update_workflow` is called without a `user_id`. Any
>   tenant could rewrite any other tenant's agent.
>
> Adds 400 guards to all four routes, makes the two reachable client methods emit
> `IS NULL` instead of dropping the predicate, and hoists the write guard above the
> conditional check. `get_workflow_run`'s unscoped branch is deliberately preserved: ~10
> internal callers hold a bare `run_id` during live call processing, so the user-facing
> routes are where that is enforced.
>
> Full suite: `54 failed, 2191 passed`. The 54 were confirmed pre-existing by stashing the
> three changed files and reproducing the identical count on the untouched baseline; the
> dominant cause is `typescript` not being installed in `mcp_server/ts_validator/`.
