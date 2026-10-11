# Ideas & Brainstorming

Capture ideas here the moment they come up — plan later, build at the right
time. An idea landing here is NOT a commitment; it graduates to the roadmap
(`.claude/plans/multi-tenant-roadmap.md`) only when we decide the timing is
right.

Rules of the list:
- One idea per entry: what it is, why it is valuable, and WHEN it is worth
  building (the timing matters more than the idea).
- No idea dies here — low-value ones just stay at the bottom.

---

## Ready when the timing is right

### Agent cloning / templates — "copy agent → another business"
- **What:** duplicate an existing agent (structure, tools, settings) into
  another business, then adjust prompts/numbers/keys.
- **Why:** the agency's biggest recurring cost is onboarding time. Clients
  repeat ~80% of each other's structure. Synergizes with the key vault
  (pick the client's saved key from a dropdown) and staff assignments.
- **Build when:** 3–5 real clients prove the repetition pattern. Caveat:
  prompts and numbers always differ per client — clone structure and
  settings, not the whole thing.

### Audit log
- **What:** who renamed/deleted/acknowledged what, and when (staff actions,
  owner actions, deletion approvals).
- **Why:** accountability once staff exist; pairs with the deletion
  approval flow. Cheap to add (a write-on-append table + a viewer on the
  Team page).
- **Build when:** the first real staff member starts working.

### Failure-alert delivery (email / webhook / WhatsApp)
- **What:** the alert rows and evaluator already exist (V2.6); add a
  notifier that pushes an open alert to the owner's email or a webhook.
- **Why:** the dashboard requires you to look; delivery comes to you.
  Needs SMTP or a provider (Twilio WhatsApp, Slack webhook) — that is the
  only missing piece.
- **Build when:** monitoring proves itself in production and you feel the
  "I only see it when I log in" gap.

### Client-facing monthly report
- **What:** a per-client summary (calls handled, outcomes/dispositions,
  minutes, top agents) as a shareable link or PDF.
- **Why:** retention. Clients that see value every month do not churn; the
  data already exists in usage/runs.
- **Build when:** the first client asks "what am I getting for this?" — or
  proactively after 2–3 clients are live.

### Credit-based client billing (owner request, 2026-10-11)
- **What:** replace the Dograh-cloud-style billing page with the agency's
  own credit system: prepaid credits per client, auto-decremented per
  successful run minute (usage data already exists per run), top-ups by the
  owner, low-balance warning. Credit-based is easier to manage and explain
  to clients than direct pricing.
- **Why:** the current billing page only makes sense for Dograh's cloud
  credits; an agency bills its own clients by its own metrics.
- **Build when:** the first client agreement defines the credit rate
  (credits per minute per agent type). Then the billing page is rewritten
  to show client balances, consumption, and top-up history.

## Parked (low priority / unclear value today)

### Provider allow-listing
- Curate which providers appear in the dropdowns (recorded in the roadmap
  as a V2.2 addendum). Do it when the provider list feels cluttered in
  daily use — it is a filter, not a feature.

### Per-client profitability view
- Usage/cost data exists; what is missing is YOUR pricing input per client
  (retainer vs per-minute) to show margin. Only meaningful once pricing
  models are consistent enough to encode.
