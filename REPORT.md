# Computer-Use Automation System — Design Report

A system that lets an LLM discover how to complete a task inside a legacy UI with no
API, records that run as a typed reusable capability, and replays it deterministically
with no model in the loop — with human escalation and safety guardrails throughout.

## 1. Architecture

**Stack:** Python, Playwright (browser surface), Groq (Qwen) for the discovery LLM,
Pydantic for the artifact schema. Single process with clean module boundaries:
`target_app/` (the surface), `driver/` (perception + action), `agent/` (discovery +
recording), `replay/` (deterministic execution), `policy.py` (safety), `escalation/`
(human handoff).

**Key decision — accessibility-tree-first perception.** The driver observes the page
through its ARIA accessibility tree (`aria_snapshot`), not raw HTML. This is the load-
bearing choice: the same abstraction (semantic *role + accessible name*) exists on
legacy web, and on desktop apps via OS accessibility APIs. It biases the whole system
toward the "no clean DOM" case that dominates the real environment, and it's what makes
the surface swappable later without touching artifacts.

**Key decision — the LLM is only in discovery.** Discovery runs an observe → decide →
act loop where the model picks one tool per turn. Replay is entirely model-free:
deterministic locator resolution, deterministic checkpoints. This is the core value
proposition — discover once (expensive, non-deterministic), replay many (cheap,
reliable).

**Key decision — provider-agnostic LLM.** The model sits behind the agent loop as a
pluggable component. During development I ran the same loop against three providers
(Anthropic, Gemini, Groq) by changing one file, absorbing real integration friction —
retired model names, account-level access gates, provider-specific tool-calling quirks
(a phantom `commentary`/`json` tool name) — with fallbacks and a salvage path. Replay
depends on no provider at all.

**Trade-off:** single process, synchronous. The brief explicitly discourages premature
scaling infrastructure; the module seams are drawn so a queue or service split *could*
be introduced without reshaping the core abstractions.

## 2. Artifact schema

The artifact (`schema.py`, Pydantic → JSON) is the reusable **contract**, deliberately
decoupled from the raw model transcript. A discovery log records what happened once; the
artifact declares what the capability *needs*, *does*, and *returns*.

Shape: a versioned `Capability` with typed `inputs` (each flagged `required` and
`sensitive`), typed `outputs`, an ordered list of `steps`, a `success` checkpoint, and
declared `business_outcomes`.

Design choices, each defensible:
- **Locators are an ordered list of strategies with a rationale**, most-robust-first
  (role+name → role → text). Replay tries them in order; the rationale is human-
  reviewable, as the brief asks. Example: the mock's search field has no linked
  `<label>`, so the artifact records role+name first and role-alone as fallback.
- **Inputs are parameterized, not literal.** The discovered value `12345` becomes
  `value_from_input: member_id`. The concrete run becomes a reusable capability.
- **`sensitive` flag on inputs** wires redaction into the type system — sensitive values
  never reach logs or evidence.
- **Business outcomes are first-class**, each with its own detector, so replay can return
  "no such member" as a legitimate result rather than a crash.
- **Versioned** via both a `version` field and the artifact filename
  (`lookup_member_balance.v1.json`), so a base capability can evolve or be overridden.

## 3. Determinism & error handling

**Determinism.** Replay resolves each control by walking the artifact's ordered locator
strategies until one matches; it waits on conditions (checkpoints / element state) rather
than fixed sleeps; and no model makes any decision. Same inputs → same steps → same
outputs.

**Error taxonomy** — the result contract distinguishes, cleanly:
- `SUCCESS` — success checkpoint met, typed outputs extracted.
- `BUSINESS_OUTCOME` — a legitimate non-success result the caller needs (demonstrated:
  `NOT_FOUND` for member 99999, `PERMISSION_DENIED` for the restricted member 33333).
  Detected *before* asserting success, so these never masquerade as failures.
- `RECOVERABLE_HANDLED` — transient/known conditions (retry a slow load, dismiss a known
  interstitial). Modelled in the taxonomy; see Cuts for current implementation depth.
- `HARD_FAILURE` — a locator unresolvable after all fallbacks, or a checkpoint
  unexpectedly unmet; stops and reports step, expectation, and observation for debugging.
- `BLOCKED_BY_POLICY` — an action outside the safety policy; stops and surfaces the
  reason (this is also the trigger for human escalation).

Distinguishing business outcomes from failures is the design mistake the brief calls out
most; it is handled structurally here, not with ad-hoc try/except.

## 4. Heterogeneity & multi-tenant (design)

**Surface abstraction.** The seam is the `SurfaceDriver` interface: `observe()` returns a
surface-neutral state (accessibility tree), `act()` performs a surface-neutral action.
Only the driver knows it's Playwright. Because the artifact targets elements by *role +
accessible name*, the same recorded flow can drive:
- a **legacy web app** — same driver, locators lean harder on a11y/text fallbacks;
- a **desktop app** — swap in a driver backed by an OS accessibility API (e.g. Windows
  UIAutomation), which exposes the same role+name model. The artifact does not change;
  only the driver does. That is the "perceive/act vs recorded flow" seam.

**Multi-tenant reuse.** Represent a capability as a **base artifact + per-tenant
overrides**. Many tenants run the same vendor product, branded/configured differently, so
concrete routes and values are canonicalized into patterns
(`/member/12345` → `/member/:id`) and a tenant overlay overrides only the locators/routes
that differ. **Drift** is detected by replay's own checkpoints: a base artifact whose
checkpoints start failing for one tenant flags that tenant for a scoped re-discovery
rather than a global rebuild. Confidence scoring could gate unattended replay per tenant.

## 5. Escalation & handoff

**Detecting "stuck"** reuses replay's own signals: a `HARD_FAILURE` (control unresolvable)
or a `BLOCKED_BY_POLICY` (risky step needs a person). No separate heuristic.

**Control-transfer model.** A `HandoffSession` owns an explicit state machine —
`AGENT → PAUSED → HUMAN → AGENT` — so who holds the session is always known and every
transition is timestamped in evidence. On stuck: the agent pauses on the **same headed
browser session** (not a fresh one), raises an **intervention request** carrying context
(capability, step, reason, current URL, a screenshot, timestamp), and cedes control. The
human operates the exact window the agent was using, then signals done; the agent captures
before/after screenshots, resumes, re-checks its checkpoint, and completes.

**Demonstrated** (`evidence/handoff_*`): agent typed the ID, hit a forced stuck at step 2,
paused, a human performed the manual step in the live session, and on resume the agent
finished with the correct outputs — with the full `PAUSED → HUMAN → AGENT` transition
trace and redacted inputs recorded.

**Mocked deliberately:** the operator *UI* is a console prompt (the brief permits this).
The mechanism — pause, same-session control transfer, capture, resume — is real.

## 6. Safety

One enforcement layer (`policy.py`) that **every action passes through before
execution** — not scattered checks. Three guarantees:
- **Allowlist** — permitted domains and permitted action types. The entry URL is checked
  up front; each action is checked at execution. Anything off-list → `BLOCKED_BY_POLICY`.
- **Risk gate** — steps are classed `safe` (reversible: navigate, read, type, search) vs
  `risky` (irreversible: submit, confirm, transfer). Unattended replay refuses risky
  steps unless explicitly approved. Conservative by default: in a regulated setting,
  refusing to act is safer than acting off-policy — and a blocked risky step is exactly
  what routes to human escalation.
- **Redaction** — inputs flagged `sensitive` are replaced with `***REDACTED***` in all
  logs and evidence; secrets live only in `.env`, which is gitignored. Proven across every
  replay and handoff log.

**Limits:** the allowlist is coarse (domains + action types), risk classification is
declared per step rather than inferred, and redaction covers declared-sensitive inputs
rather than scanning all output for incidental PII — see Cuts.

## 7. Cuts

Deliberately left thin or stubbed, at clean seams:
- **`RECOVERABLE_HANDLED` is modelled but lightly exercised.** The status and detection
  points exist; the mock doesn't inject transient states heavily. Next: wait/retry with
  backoff and known-interstitial dismissal, returning this status.
- **Operator UI is a console prompt.** The handoff mechanism is real; the surface is
  mocked, as permitted. Next: a minimal operator web view of the live session.
- **Multi-tenant and desktop are design-only** (Section 4), not built — as the brief
  scopes.
- **No assisted LLM fallback on replay failure.** Replay escalates to a human instead of
  attempting a bounded model recovery. That bounded, policy-checked recovery is a natural
  stretch.
- **No confidence/approval gating** (draft → approved) on artifacts yet.
- **The escalation runner duplicates some replay control flow** rather than the replay
  engine natively supporting pause/resume. With more time I'd unify them so one executor
  serves both unattended and supervised runs.
- **Single process, synchronous.** No queue/services — intentional per the brief.

## Evidence
See `/evidence/`: a real LLM discovery run, a successful replay, two business-outcome
replays (not-found, permission-denied), policy blocks, and a full human-handoff run —
each with structured logs and screenshots.