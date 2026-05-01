"""SOC-Claw Pydantic schemas.

Two halves:
  Half A — Input schemas:   Validate data files at load time.
                            Permissive (extra="allow") so unknown fields
                            from future SIEM integrations don't break.
  Half B — Output schemas:  Constrain LLM outputs.  Used for
                            vLLM ``guided_json`` decode-time enforcement
                            (local route) and post-hoc validation (all routes).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Half A: Input schemas (permissive) ────────────────────────────────


class GroundTruth(BaseModel):
    """Dev-only ground truth embedded in each alert."""

    model_config = ConfigDict(extra="allow")

    severity: str
    is_malicious: bool
    expected_actions: list[str] = []


class Alert(BaseModel):
    """A raw security alert from the SIEM / data file."""

    model_config = ConfigDict(extra="allow")

    id: str
    timestamp: str
    hostname: str
    rule_name: str
    source_ip: str | None = None
    dest_ip: str | None = None
    payload: str = ""
    ground_truth: GroundTruth | None = None


class ThreatIntelEntry(BaseModel):
    """One row from ``threat_intel.json``."""

    model_config = ConfigDict(extra="allow")

    indicator: str
    type: str
    threat_score: int
    tags: list[str] = []
    campaigns: list[str] = []
    first_seen: str | None = None
    last_seen: str | None = None


class Asset(BaseModel):
    """One row from ``asset_inventory.json``."""

    model_config = ConfigDict(extra="allow")

    hostname: str
    criticality: str
    business_function: str
    owner: str | None = None
    os: str | None = None
    last_patch: str | None = None
    network_zone: str | None = None


class MitreTechnique(BaseModel):
    """One row from ``mitre_techniques.json``."""

    model_config = ConfigDict(extra="allow")

    technique_id: str
    name: str
    tactic: str
    keywords: list[str]
    description: str = ""


# ── Half B: Output schemas (strict, for guided_json) ──────────────────


class IOCFound(BaseModel):
    """Single IOC identified during triage."""

    indicator: str
    type: Literal["ip", "domain", "hash"]
    threat_score: int = 0


class TriageVerdict(BaseModel):
    """Expected output from the Triage Agent."""

    severity: Literal["P1", "P2", "P3", "P4"]
    confidence: int = Field(ge=0, le=100)
    reasoning: str
    mitre_techniques: list[str] = []
    iocs_found: list[IOCFound] = []
    asset_criticality: Literal["critical", "high", "medium", "low"]
    recommended_urgency: Literal["immediate", "urgent", "standard", "monitor"]


class VerificationDecision(BaseModel):
    """Expected output from the Verifier Agent."""

    decision: Literal["confirmed", "adjusted", "flagged"]
    original_severity: Literal["P1", "P2", "P3", "P4"]
    verified_severity: Literal["P1", "P2", "P3", "P4"]
    confidence_in_verification: int = Field(ge=0, le=100)
    reasoning: str
    issues_found: list[str] = []
    checks_passed: list[str] = []
    checks_failed: list[str] = []
    recommendation: str = ""


class ResponseStep(BaseModel):
    """A single step in a response plan."""

    step: int
    action: str
    action_type: Literal[
        "isolate_host",
        "block_ioc",
        "create_ticket",
        "escalate",
        "collect_forensics",
        "add_to_watchlist",
        "notify_owner",
        "tune_rule",
    ]
    target: str
    reasoning: str
    urgency: Literal["immediate", "within_30min", "within_24hrs", "when_convenient"]
    requires_approval: bool


class ResponsePlan(BaseModel):
    """Expected output from the Response Agent."""

    alert_id: str
    severity_acted_on: Literal["P1", "P2", "P3", "P4"]
    was_adjusted: bool
    response_plan: list[ResponseStep]
    incident_summary: str
    analyst_notes: str = ""
    estimated_mttr_impact: str = ""
