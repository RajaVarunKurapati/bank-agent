"""
Control-transfer model for human-in-the-loop handoff.

A single live session (one headed browser) is operated by exactly one controller at a
time. The state machine makes 'who is in control' explicit and auditable:

    AGENT --detect stuck--> PAUSED --hand off--> HUMAN --resume--> AGENT

Detection reuses the replay engine's own signals: a HARD_FAILURE (can't resolve a
control) or a BLOCKED_BY_POLICY (a risky step needs a person) is what 'stuck' means.
The operator UI is intentionally mocked (a console prompt); the mechanism -- pause on
the SAME session, capture the human's actions, resume -- is real.
"""
import os
import datetime
from enum import Enum


class Controller(str, Enum):
    AGENT = "AGENT"
    PAUSED = "PAUSED"
    HUMAN = "HUMAN"


class InterventionRequest:
    """Context handed to the operator so they can act. This is what would be routed to
    an operator queue in production; here we print it and capture it as evidence."""
    def __init__(self, capability, step_index, reason, detail, url, screenshot_path):
        self.capability = capability
        self.step_index = step_index
        self.reason = reason
        self.detail = detail
        self.url = url
        self.screenshot_path = screenshot_path
        self.raised_at = datetime.datetime.now().isoformat(timespec="seconds")

    def to_dict(self):
        return {
            "capability": self.capability, "step": self.step_index,
            "reason": self.reason, "detail": self.detail,
            "url": self.url, "screenshot": self.screenshot_path,
            "raised_at": self.raised_at,
        }


class HandoffSession:
    """Owns the controller state and performs the pause -> human -> resume transfer on the
    SAME driver/session. Records every transition for the evidence log."""
    def __init__(self, driver, evidence_dir):
        self.driver = driver
        self.evidence_dir = evidence_dir
        self.controller = Controller.AGENT
        self.transitions = []
        os.makedirs(evidence_dir, exist_ok=True)

    def _record(self, to_state, note=""):
        self.transitions.append({
            "at": datetime.datetime.now().isoformat(timespec="seconds"),
            "controller": to_state.value, "note": note,
        })
        self.controller = to_state

    def escalate(self, capability, step_index, reason, detail, prompt_fn=input):
        """Pause the agent, hand the live session to a human, capture, then resume.
        prompt_fn is injectable so tests can auto-resume without a real keypress."""
        # 1. PAUSE + snapshot the state the human inherits
        self._record(Controller.PAUSED, f"stuck: {reason}")
        before = os.path.join(self.evidence_dir, "handoff_before.png")
        self.driver.screenshot(before)
        req = InterventionRequest(
            capability, step_index, reason, detail,
            self.driver.page.url, before)

        # 2. Route the intervention request (mock operator UI = console)
        print("\n" + "=" * 60)
        print("  HUMAN INTERVENTION REQUESTED")
        print("=" * 60)
        for k, v in req.to_dict().items():
            print(f"  {k}: {v}")
        print("  The SAME browser window is now yours. Do the manual step,")
        print("  then return here to hand control back.")
        print("=" * 60)

        # 3. HUMAN controls the same live session
        self._record(Controller.HUMAN, "operator took control of live session")
        prompt_fn("\n  >>> Press Enter when done to return control to the agent... ")

        # 4. Capture what changed, resume the agent
        after = os.path.join(self.evidence_dir, "handoff_after.png")
        self.driver.screenshot(after)
        self._record(Controller.AGENT, "control returned to agent")
        return {
            "intervention": req.to_dict(),
            "after_url": self.driver.page.url,
            "after_screenshot": after,
        }