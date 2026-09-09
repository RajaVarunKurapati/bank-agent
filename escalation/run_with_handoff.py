"""
Escalation-aware runner: replay a capability, and when the agent gets STUCK
(HARD_FAILURE resolving a control, or a step BLOCKED_BY_POLICY), pause on the SAME
live session, hand control to a human, let them act, then resume and re-check.

Detection reuses the replay engine's own primitives. The browser is kept alive across
the handoff (unlike unattended replay, which tears it down) so the human operates the
exact window the agent was using.

Demo:
  python escalation/run_with_handoff.py artifacts/lookup_member_balance.v1.json member_id=12345 --stuck-at 2
The --stuck-at flag forces a stuck condition at a given step so the handoff is exercised
on demand (stands in for 'the agent couldn't resolve this control').
"""
import sys, os, re, json, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from driver.surface_driver import SurfaceDriver
from schema import Capability
from policy import DEFAULT_POLICY, check_navigation, check_action, PolicyViolation
from replay.replay import _check, _detect_business_outcome, _resolve_and_act, _redact
from escalation.session import HandoffSession


def run(artifact_path, params, stuck_at=None, policy=DEFAULT_POLICY):
    with open(artifact_path) as f:
        cap = Capability.model_validate_json(f.read())

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    evidence_dir = os.path.join("evidence", f"handoff_{stamp}")
    driver = SurfaceDriver(headless=False)      # headed: the human will use this window
    session = HandoffSession(driver, evidence_dir)

    log = {"capability": cap.id, "inputs": _redact(cap.inputs, params),
           "trace": [], "handoffs": []}

    driver.navigate(cap.entry_url)

    for step in cap.steps:
        if step.action.value == "read":
            bo = _detect_business_outcome(driver, cap)
            if bo:
                status = "BUSINESS_OUTCOME"; result = {"code": bo.code, "message": bo.message}
                break
            if step.checkpoint and not _check(driver, step.checkpoint):
                status = "HARD_FAILURE"; result = {"step": step.index}
                break
            outputs, page_text = {}, driver.read_text()
            for ex in step.extractions:
                m = re.search(ex.pattern, page_text)
                outputs[ex.output] = m.group(1).strip() if m else None
            status = "SUCCESS"; result = outputs
            break

        # policy gate (same as unattended replay)
        try:
            check_action(policy, step.action.value, step.risk.value)
            policy_stuck = None
        except PolicyViolation as pv:
            policy_stuck = (pv.reason_code, pv.detail)

        # decide if the agent is STUCK on this step
        stuck_reason = stuck_detail = None
        if policy_stuck:
            stuck_reason, stuck_detail = policy_stuck
        elif stuck_at and step.index == stuck_at:
            stuck_reason = "LOCATOR_UNRESOLVED"
            stuck_detail = f"agent could not resolve control for step {step.index}"

        # ESCALATE: pause -> human takes the same session -> resume
        if stuck_reason:
            info = session.escalate(cap.id, step.index, stuck_reason, stuck_detail)
            log["handoffs"].append(info)
            # after the human acted, re-evaluate: did they move the flow forward?
            bo = _detect_business_outcome(driver, cap)
            if bo:
                status = "BUSINESS_OUTCOME"; result = {"code": bo.code, "message": bo.message}
                break
            if _check(driver, cap.success):
                # human completed the goal during handoff; extract + succeed
                outputs, page_text = {}, driver.read_text()
                for ex in [e for s in cap.steps for e in s.extractions]:
                    m = re.search(ex.pattern, page_text)
                    outputs[ex.output] = m.group(1).strip() if m else None
                status = "SUCCESS (after human handoff)"; result = outputs
                break
            # otherwise fall through and let the agent retry this step now
            ok, err = _resolve_and_act(driver, step, params, log["trace"])
            if not ok:
                status = "HARD_FAILURE"; result = {"step": step.index, "error": err}
                break
            continue

        # normal agent action
        ok, err = _resolve_and_act(driver, step, params, log["trace"])
        if not ok:
            # locator genuinely failed -> escalate here too
            info = session.escalate(cap.id, step.index, "LOCATOR_UNRESOLVED", err)
            log["handoffs"].append(info)
            if _check(driver, cap.success):
                status = "SUCCESS (after human handoff)"; result = {}
                break
            status = "HARD_FAILURE"; result = {"step": step.index, "error": err}
            break
    else:
        status = "SUCCESS" if _check(driver, cap.success) else "HARD_FAILURE"
        result = {}

    log["controller_transitions"] = session.transitions
    log["status"] = status
    log["result"] = result
    with open(os.path.join(evidence_dir, "handoff_log.json"), "w") as f:
        json.dump(log, f, indent=2)
    driver.close()

    print("\n" + json.dumps({"status": status, "result": result,
                             "handoffs": len(log["handoffs"])}, indent=2))
    print(f"Evidence: {evidence_dir}")
    return status, result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: run_with_handoff.py <artifact> key=val ... [--stuck-at N]")
    artifact = sys.argv[1]
    params, stuck_at = {}, None
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--stuck-at":
            stuck_at = int(args[i + 1]); i += 2
        else:
            k, _, v = args[i].partition("="); params[k] = v; i += 1
    run(artifact, params, stuck_at=stuck_at)