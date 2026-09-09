"""
Safety policy: one enforcement layer every action passes through before execution.

Three guarantees:
  1. Allowlist  - only permitted domains and action types may run; anything else is blocked.
  2. Risk gate  - risky/irreversible steps (submit, confirm, transfer) are blocked in
                  unattended replay unless explicitly approved; safe/reversible ones proceed.
  3. Redaction  - sensitive input values never reach logs/evidence (enforced in replay).

Blocking is conservative by design: in a regulated setting, refusing to act is safer than
acting outside policy. A blocked risky step is a candidate for human escalation (Phase 7).
"""
from urllib.parse import urlparse
from pydantic import BaseModel


class Policy(BaseModel):
    allowed_domains: list[str]
    allowed_actions: list[str]          # e.g. ["navigate","type","click","read"]
    allow_risky: bool = False           # unattended replay refuses risky steps by default


class PolicyViolation(Exception):
    """Raised when an action falls outside policy. Carries a machine-readable reason."""
    def __init__(self, reason_code, detail):
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}")


DEFAULT_POLICY = Policy(
    allowed_domains=["127.0.0.1", "localhost"],
    allowed_actions=["navigate", "type", "click", "read"],
    allow_risky=False,
)


def check_navigation(policy: Policy, url: str):
    host = urlparse(url).hostname or ""
    if host not in policy.allowed_domains:
        raise PolicyViolation("DOMAIN_NOT_ALLOWED",
                              f"{host} not in allowlist {policy.allowed_domains}")


def check_action(policy: Policy, action: str, risk: str):
    if action not in policy.allowed_actions:
        raise PolicyViolation("ACTION_NOT_ALLOWED",
                              f"action '{action}' not in {policy.allowed_actions}")
    if risk == "risky" and not policy.allow_risky:
        raise PolicyViolation("RISKY_ACTION_BLOCKED",
                              f"'{action}' is risky/irreversible and requires approval")