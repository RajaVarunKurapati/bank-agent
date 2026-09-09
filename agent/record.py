"""
Recorder: convert a real discovery run into a typed, versioned capability artifact.
The model discovered the FLOW; here we emit the reviewable CONTRACT a caller invokes.
Parameterization, typing, success condition, and known business outcomes are declared
here (human-reviewable) rather than guessed from the transcript.
"""
import sys, os, json, glob, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schema import (
    Capability, Step, Locator, LocatorStrategy, Checkpoint, Extraction,
    InputParam, OutputField, BusinessOutcome, ActionType, RiskClass,
)

# --- Declared contract (the human-reviewed part) ---
CAPABILITY_ID = "lookup_member_balance"
CAPABILITY_NAME = "Look up member and read savings balance"
DESCRIPTION = "Given a member ID, open the member record and return the savings balance. Read-only."
ENTRY_URL = "http://127.0.0.1:5000"

INPUTS = [
    InputParam(name="member_id", type="string", required=True, sensitive=True,
               description="Member/account identifier to look up (PII; redacted in logs)."),
]
OUTPUTS = [
    OutputField(name="savings_balance", type="string",
                description="Current savings balance as displayed, e.g. $4,210.55."),
    OutputField(name="member_name", type="string", description="Account holder name."),
]
# The value the discovery run used, so we can parameterize it out of the steps.
DISCOVERED_INPUT_VALUE = "12345"

SUCCESS = Checkpoint(kind="text_present", value="Savings Balance")

BUSINESS_OUTCOMES = [
    BusinessOutcome(code="NOT_FOUND",
        detect=Checkpoint(kind="text_present", value="No such member"),
        message="No member exists with the supplied ID."),
    BusinessOutcome(code="PERMISSION_DENIED",
        detect=Checkpoint(kind="text_present", value="Permission denied"),
        message="The member record exists but is restricted."),
]


def build_steps(log):
    steps, idx = [], 0
    for raw in log["steps"]:
        act, args = raw.get("action"), raw.get("args", {})
        if act == "type_text":
            idx += 1
            role, name, val = args.get("role"), args.get("name"), args.get("value")
            vfi = "member_id" if val == DISCOVERED_INPUT_VALUE else None
            steps.append(Step(
                index=idx, action=ActionType.TYPE,
                locator=Locator(strategies=[
                    LocatorStrategy(kind="role_name", role=role, name=name),
                    LocatorStrategy(kind="role", role=role),
                ], rationale="Prefer role+accessible-name; fall back to role alone because "
                             "this legacy input has no linked <label>."),
                value_from_input=vfi, value_literal=None if vfi else val,
                risk=RiskClass.SAFE))
        elif act == "click":
            idx += 1
            name, role = args.get("name"), args.get("role") or "button"
            steps.append(Step(
                index=idx, action=ActionType.CLICK,
                locator=Locator(strategies=[
                    LocatorStrategy(kind="role_name", role=role, name=name),
                    LocatorStrategy(kind="text", text=name),
                ], rationale="Buttons expose a stable accessible name; text match is the "
                             "fallback if the role is misreported in legacy markup."),
                risk=RiskClass.SAFE))  # search is reversible
        # 'finish'/'read' from discovery are dropped; replay uses an explicit extract step
    # synthesized deterministic extraction step (discovery read data from returned state;
    # replay needs an explicit, deterministic read + success checkpoint)
    idx += 1
    steps.append(Step(
        index=idx, action=ActionType.READ,
        extractions=[
            Extraction(output="savings_balance",
                       pattern=r"Savings Balance\s*(\$[\d,]+\.\d{2})"),
            Extraction(output="member_name",
                       pattern=r"Name\s+([A-Za-z][A-Za-z .'-]+?)\s+Member ID"),
        ],
        checkpoint=SUCCESS, risk=RiskClass.SAFE))
    return steps


def latest_log():
    dirs = sorted(glob.glob(os.path.join("evidence", "discovery_*")))
    if not dirs:
        raise SystemExit("No discovery run in evidence/. Run agent/discovery.py first.")
    with open(os.path.join(dirs[-1], "discovery_log.json")) as f:
        return json.load(f), os.path.basename(dirs[-1])


if __name__ == "__main__":
    log, run_name = latest_log()
    cap = Capability(
        id=CAPABILITY_ID, name=CAPABILITY_NAME, description=DESCRIPTION, version=1,
        surface_type="legacy_web", entry_url=ENTRY_URL,
        inputs=INPUTS, outputs=OUTPUTS, steps=build_steps(log),
        success=SUCCESS, business_outcomes=BUSINESS_OUTCOMES,
        created_from_run=run_name,
        discovered_by_model=log.get("model", "groq (see discovery run)"),
        created_at=datetime.datetime.now().isoformat(timespec="seconds"))
    os.makedirs("artifacts", exist_ok=True)
    out = os.path.join("artifacts", f"{CAPABILITY_ID}.v{cap.version}.json")
    with open(out, "w") as f:
        f.write(cap.model_dump_json(indent=2))
    print(f"Artifact written: {out}\n")
    print(cap.model_dump_json(indent=2))