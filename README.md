# bank-agent — Computer-Use Automation System

An LLM discovers how to complete a task inside a legacy UI that has no API, the
successful run is recorded as a typed, versioned **capability artifact**, and that
artifact is **replayed deterministically with no model in the loop** — with a safety
policy and a real human-in-the-loop handoff throughout.

See [`REPORT.md`](./REPORT.md) for the design write-up and [`/evidence`](./evidence)
for logs and screenshots from real runs.

## What it does

- **Discovery** — an LLM drives a live legacy web app (observe → decide → act) to reach a
  goal, observing via the accessibility tree so the approach survives a no-clean-DOM surface.
- **Record** — the successful run becomes a typed, parameterized, versioned artifact
  (a reusable capability contract), decoupled from the raw model transcript.
- **Replay** — the artifact runs deterministically, no LLM: ordered locator resolution,
  checkpoints, typed outputs, and a four-way result taxonomy.
- **Safety** — one policy layer every action passes through (allowlist, risk gate,
  redaction of sensitive data).
- **Escalation** — on "stuck," the agent pauses on the *same* live session, hands control
  to a human, captures what they did, and resumes.

## Requirements

- Python 3.11+
- A Groq API key (free tier) from https://console.groq.com — used only for discovery.
  Replay and escalation need no API key.

## Setup

```bash
git clone https://github.com/RajaVarunKurapati/bank-agent.git
cd bank-agent

python -m venv venv
source venv/Scripts/activate      # Windows/Git Bash
# source venv/bin/activate        # macOS/Linux

pip install -r requirements.txt
playwright install chromium
```

Create a `.env` file in the repo root with your key (this file is gitignored):

GROQ_API_KEY=gsk_your_key_here


## Running it

The target app must be running first, in its own terminal:

```bash
python target_app/app.py        # serves the mock bank at http://127.0.0.1:5000
```

Leave that running. Use a second terminal (with the venv activated) for everything below.

### Demo path

**1. Discovery — an LLM completes the goal against the live app** (this is the only step
that uses the model):

```bash
python agent/discovery.py
# goal: "Look up member 12345 and read their current savings balance."
# writes evidence/discovery_<timestamp>/ (log + final screenshot)
```

**2. Record — turn the successful run into a typed capability artifact:**

```bash
python agent/record.py
# writes artifacts/lookup_member_balance.v1.json
```

**3. Replay — run the artifact deterministically, no LLM:**

```bash
# happy path -> SUCCESS with extracted outputs
python replay/run_replay.py artifacts/lookup_member_balance.v1.json member_id=12345

# business outcome: no such member -> BUSINESS_OUTCOME / NOT_FOUND (not a crash)
python replay/run_replay.py artifacts/lookup_member_balance.v1.json member_id=99999

# business outcome: restricted account -> BUSINESS_OUTCOME / PERMISSION_DENIED
python replay/run_replay.py artifacts/lookup_member_balance.v1.json member_id=33333
```

Each replay writes `evidence/replay_<timestamp>/` with a structured log (sensitive
inputs redacted) and, on non-success, a screenshot.

### Human-in-the-loop handoff

Force a stuck condition to exercise the escalation path:

```bash
python escalation/run_with_handoff.py artifacts/lookup_member_balance.v1.json member_id=12345 --stuck-at 2
```

The agent pauses at step 2 and prints an intervention request. Switch to the **same**
browser window it opened, click **Search** yourself, return to the terminal, and press
Enter. The agent resumes, verifies its checkpoint, and completes. Writes
`evidence/handoff_<timestamp>/` with before/after screenshots and the full
`AGENT → PAUSED → HUMAN → AGENT` control-transition trace.

## Running without the LLM

Only discovery (step 1) needs the Groq key. If you only want to see the deterministic
production path, a recorded artifact is already committed under `artifacts/` — start the
target app and run the replay and handoff commands above directly.

## Result taxonomy

Replay returns one of:

| Status | Meaning |
|---|---|
| `SUCCESS` | Success checkpoint met; typed outputs returned. |
| `BUSINESS_OUTCOME` | A legitimate non-success result (e.g. `NOT_FOUND`, `PERMISSION_DENIED`) — not a crash. |
| `HARD_FAILURE` | Could not proceed (locator unresolvable, checkpoint unmet); reported with debug detail. |
| `BLOCKED_BY_POLICY` | Action outside the safety policy; stops and surfaces the reason. Triggers escalation. |

## Layout

target_app/ mock legacy bank (Flask): tables, iframe, no test IDs — the surface
driver/ SurfaceDriver: accessibility-tree perception + iframe-aware actions
agent/ discovery loop (LLM) + recorder (artifact emitter)
replay/ deterministic replay engine + CLI
policy.py safety policy: allowlist, risk gate, redaction
escalation/ control-transfer state machine + handoff runner
schema.py typed capability artifact (Pydantic)
artifacts/ saved capability artifacts (versioned)
evidence/ logs + screenshots from discovery, replay, and handoff runs


## Notes

- Target is a deliberately legacy surface (table layout, an iframe, no test IDs) to
  exercise the "no clean DOM" case, not to be polished.
- The LLM is a pluggable component behind the discovery loop; replay depends on no
  provider. See `REPORT.md` for the full design and trade-offs.