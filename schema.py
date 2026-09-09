"""
Capability artifact schema.

The artifact is the reusable CONTRACT emitted after a successful discovery run.
It is deliberately decoupled from the raw model transcript: a human reviewer or a
calling agent should be able to read it and know what the capability needs (inputs),
what it does (steps), what it returns (outputs), how it knows it succeeded (checkpoint),
and which non-success results are legitimate (business_outcomes).
Typed + versioned via Pydantic so it validates and serializes cleanly.
"""
from __future__ import annotations
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel

ARTIFACT_SCHEMA_VERSION = "1.0"


class LocatorStrategy(BaseModel):
    """One way to find a control. A step holds an ordered list of these."""
    kind: Literal["role_name", "role", "text", "label", "css", "xpath"]
    role: Optional[str] = None
    name: Optional[str] = None
    text: Optional[str] = None
    selector: Optional[str] = None  # for css / xpath


class Locator(BaseModel):
    """How a step's target is identified, most-robust-first. Replay tries each in order."""
    strategies: list[LocatorStrategy]
    rationale: str  # brief explicitly asks for robustness reasoning


class Checkpoint(BaseModel):
    """A condition asserted to confirm we actually reached the expected state."""
    kind: Literal["text_present", "text_absent", "url_matches", "element_present"]
    value: str


class Extraction(BaseModel):
    """Pull one typed output from page text via a single-capture-group regex."""
    output: str
    pattern: str


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    TYPE = "type"
    CLICK = "click"
    READ = "read"


class RiskClass(str, Enum):
    SAFE = "safe"    # reversible: navigate, read, type into a field, search
    RISKY = "risky"  # irreversible / state-changing: submit, confirm, delete, transfer


class Step(BaseModel):
    index: int
    action: ActionType
    locator: Optional[Locator] = None          # None for navigate / read
    url: Optional[str] = None                   # for navigate
    value_from_input: Optional[str] = None      # param name -> parameterized, no literal
    value_literal: Optional[str] = None         # only for non-sensitive constants
    extractions: list[Extraction] = []          # for read steps
    checkpoint: Optional[Checkpoint] = None     # per-step assertion
    risk: RiskClass = RiskClass.SAFE


class InputParam(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean"]
    required: bool = True
    sensitive: bool = False   # redact in logs/evidence (PII, secrets)
    description: str = ""


class OutputField(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean"]
    description: str = ""


class BusinessOutcome(BaseModel):
    """A legitimate non-success result the caller must know about (NOT a crash)."""
    code: str                 # e.g. NOT_FOUND, PERMISSION_DENIED
    detect: Checkpoint        # how replay recognizes it
    message: str


class Capability(BaseModel):
    schema_version: str = ARTIFACT_SCHEMA_VERSION
    id: str
    name: str
    description: str
    version: int = 1
    surface_type: Literal["web", "legacy_web", "desktop"] = "web"
    entry_url: str
    # the callable contract
    inputs: list[InputParam]
    outputs: list[OutputField]
    steps: list[Step]
    success: Checkpoint
    business_outcomes: list[BusinessOutcome] = []
    # provenance (reviewable + versioned)
    created_from_run: Optional[str] = None
    discovered_by_model: Optional[str] = None
    created_at: Optional[str] = None