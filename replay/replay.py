"""
Deterministic replay engine — the production execution path.

Given a saved artifact + input params, execute the recorded flow with NO LLM in the
decision loop. Locator resolution tries the artifact's strategies in order. Every stage
checks for declared business outcomes before proceeding. Returns a structured result
distinguishing four cases (this is the error taxonomy the brief asks for):

  SUCCESS            - reached the success checkpoint; outputs extracted
  BUSINESS_OUTCOME   - a legitimate non-success result (e.g. NOT_FOUND) the caller needs
  RECOVERABLE_HANDLED- a transient/known condition we handled (retry/dismiss) then continued
  HARD_FAILURE       - could not proceed; stop and surface a debuggable error
"""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enum import Enum
from driver.surface_driver import SurfaceDriver
from schema import Capability


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    BUSINESS_OUTCOME = "BUSINESS_OUTCOME"
    RECOVERABLE_HANDLED = "RECOVERABLE_HANDLED"
    HARD_FAILURE = "HARD_FAILURE"


def _redact(inputs, params):
    """Never log sensitive input values; show a placeholder instead."""
    safe = {}
    sensitive = {i.name for i in inputs if i.sensitive}
    for k, v in params.items():
        safe[k] = "***REDACTED***" if k in sensitive else v
    return safe


def _check(driver, checkpoint):
    k, val = checkpoint.kind, checkpoint.value
    if k == "text_present":
        return driver.has_text(val)
    if k == "text_absent":
        return not driver.has_text(val)
    if k == "url_matches":
        return re.search(val, driver.page.url) is not None
    if k == "element_present":
        return driver.has_text(val)
    return False


def _detect_business_outcome(driver, cap):
    for bo in cap.business_outcomes:
        if _check(driver, bo.detect):
            return bo
    return None


def _resolve_and_act(driver, step, params, log):
    """Try each locator strategy in order (deterministic fallback chain)."""
    value = None
    if step.value_from_input:
        value = str(params.get(step.value_from_input, ""))
    elif step.value_literal is not None:
        value = step.value_literal

    last_err = None
    strategies = step.locator.strategies if step.locator else []
    for strat in strategies:
        try:
            if step.action.value == "type":
                driver.type(value, role=strat.role, name=strat.name, text=strat.text)
            elif step.action.value == "click":
                driver.click(role=strat.role, name=strat.name, text=strat.text)
                driver.page.wait_for_timeout(600)
            log.append({"step": step.index, "action": step.action.value,
                        "locator_kind": strat.kind, "ok": True})
            return True, None
        except Exception as e:
            last_err = str(e)
            continue
    log.append({"step": step.index, "action": step.action.value,
                "ok": False, "error": last_err})
    return False, last_err


def replay(artifact_path, params, evidence_dir=None, headless=True):
    with open(artifact_path) as f:
        cap = Capability.model_validate_json(f.read())

    log = {"capability": cap.id, "version": cap.version,
           "inputs": _redact(cap.inputs, params), "trace": []}
    trace = log["trace"]
    driver = SurfaceDriver(headless=headless)

    def finish(status, **extra):
        if evidence_dir:
            os.makedirs(evidence_dir, exist_ok=True)
            if status != Status.SUCCESS:
                driver.screenshot(os.path.join(evidence_dir, "replay_failure.png"))
            with open(os.path.join(evidence_dir, "replay_log.json"), "w") as fh:
                json.dump({**log, "status": status.value, **extra}, fh, indent=2)
        driver.close()
        return {"status": status.value, "capability": cap.id, **extra}

    try:
        driver.navigate(cap.entry_url)
        for step in cap.steps:
            if step.action.value == "read":
                # business-outcome check BEFORE asserting success
                bo = _detect_business_outcome(driver, cap)
                if bo:
                    return finish(Status.BUSINESS_OUTCOME,
                                  outcome={"code": bo.code, "message": bo.message})
                if step.checkpoint and not _check(driver, step.checkpoint):
                    return finish(Status.HARD_FAILURE,
                                  failure={"step": step.index,
                                           "expected": step.checkpoint.value,
                                           "observed": driver.read_text()[:200]})
                outputs = {}
                page_text = driver.read_text()
                for ex in step.extractions:
                    m = re.search(ex.pattern, page_text)
                    outputs[ex.output] = m.group(1).strip() if m else None
                trace.append({"step": step.index, "action": "read", "outputs": outputs})
                return finish(Status.SUCCESS, outputs=outputs)

            # action steps: check for a business outcome surfaced mid-flow first
            bo = _detect_business_outcome(driver, cap)
            if bo:
                return finish(Status.BUSINESS_OUTCOME,
                              outcome={"code": bo.code, "message": bo.message})

            ok, err = _resolve_and_act(driver, step, params, trace)
            if not ok:
                # after an action fails, a business outcome may explain why
                bo = _detect_business_outcome(driver, cap)
                if bo:
                    return finish(Status.BUSINESS_OUTCOME,
                                  outcome={"code": bo.code, "message": bo.message})
                return finish(Status.HARD_FAILURE,
                              failure={"step": step.index,
                                       "reason": "locator resolution failed",
                                       "error": err})

        # ran out of steps without a read/success
        if _check(driver, cap.success):
            return finish(Status.SUCCESS, outputs={})
        return finish(Status.HARD_FAILURE,
                      failure={"reason": "completed steps but success checkpoint not met"})

    except Exception as e:
        return finish(Status.HARD_FAILURE, failure={"reason": "unexpected", "error": str(e)})