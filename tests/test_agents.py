"""Tests for the agent fallback factories.

When the LLM output can't be parsed, each agent falls back to a deterministic
``default_factory`` so the pipeline degrades gracefully instead of crashing.
Those fallbacks are the part of the agents that runs without a model, so they
are the testable core:

* triage  — ``_default`` (closure): severity inferred from enrichment.
* verifier — ``_default`` (closure): fail-open "confirmed".
* response — ``_default_plan`` (module-level): a severity-tiered plan.

The triage/verifier closures are exercised by stubbing ``call_llm`` so it
returns the ``default_factory()`` result, mimicking an unparseable response.
Every fallback is asserted to be valid against its Pydantic output schema.
"""

import pytest

from blue_lantern.agents import triage_agent, verifier_agent, response_agent
from blue_lantern.llm.caller import LLMResult
from blue_lantern.schemas import ResponsePlan, TriageVerdict, VerificationDecision


def _force_default_path(monkeypatch, module):
    """Stub ``module.call_llm`` so it returns the agent's default fallback."""

    async def fake_call_llm(**kwargs):
        return LLMResult(
            result=kwargs["default_factory"](),
            inference_ms=0,
            route="test-default",
            raw_content="",
        )

    monkeypatch.setattr(module, "call_llm", fake_call_llm)


def _stub_enrichment(monkeypatch, enrichment):
    async def fake_run_enrichment(alert):
        return enrichment, []

    monkeypatch.setattr(triage_agent, "_run_enrichment", fake_run_enrichment)


# ──────────────────────── triage fallback ────────────────────────


class TestTriageFallback:
    @pytest.mark.asyncio
    async def test_malicious_ip_on_critical_asset_is_p1(self, monkeypatch):
        _stub_enrichment(
            monkeypatch,
            {
                "ip_reputation": {"dest_ip": {"verdict": "malicious", "threat_score": 88}},
                "asset_lookup": {"criticality": "critical"},
                "mitre_lookup": [{"technique_id": "T1071.001"}],
            },
        )
        _force_default_path(monkeypatch, triage_agent)

        verdict = await triage_agent.run_triage(
            {"id": "A1", "dest_ip": "185.220.101.42", "hostname": "DC-1"}
        )

        assert verdict["severity"] == "P1"
        assert verdict["recommended_urgency"] == "immediate"
        assert verdict["mitre_techniques"] == ["T1071.001"]
        assert verdict["iocs_found"][0]["threat_score"] == 88
        TriageVerdict.model_validate(verdict)  # schema-valid fallback

    @pytest.mark.asyncio
    async def test_malicious_ip_on_medium_asset_is_p2(self, monkeypatch):
        _stub_enrichment(
            monkeypatch,
            {
                "ip_reputation": {"dest_ip": {"verdict": "malicious", "threat_score": 70}},
                "asset_lookup": {"criticality": "medium"},
                "mitre_lookup": [],
            },
        )
        _force_default_path(monkeypatch, triage_agent)

        verdict = await triage_agent.run_triage({"id": "A2", "dest_ip": "1.2.3.4"})

        assert verdict["severity"] == "P2"
        assert verdict["recommended_urgency"] == "urgent"
        TriageVerdict.model_validate(verdict)

    @pytest.mark.asyncio
    async def test_clean_ip_defaults_to_p3_with_no_iocs(self, monkeypatch):
        _stub_enrichment(
            monkeypatch,
            {
                "ip_reputation": {"dest_ip": {"verdict": "clean", "threat_score": 0}},
                "asset_lookup": {"criticality": "medium"},
                "mitre_lookup": [],
            },
        )
        _force_default_path(monkeypatch, triage_agent)

        verdict = await triage_agent.run_triage({"id": "A3", "dest_ip": "8.8.8.8"})

        assert verdict["severity"] == "P3"
        assert verdict["iocs_found"] == []  # threat_score 0 → no IOC emitted
        TriageVerdict.model_validate(verdict)


# ──────────────────────── verifier fallback ────────────────────────


class TestVerifierFallback:
    @pytest.mark.asyncio
    async def test_fails_open_to_confirmed_mirroring_triage_severity(self, monkeypatch):
        _force_default_path(monkeypatch, verifier_agent)

        result = await verifier_agent.run_verification(
            {"id": "A1"}, {"severity": "P2"}
        )

        assert result["decision"] == "confirmed"
        assert result["original_severity"] == "P2"
        assert result["verified_severity"] == "P2"
        assert "verifier_json_parse_failure" in result["issues_found"]
        VerificationDecision.model_validate(result)

    @pytest.mark.asyncio
    async def test_missing_triage_severity_defaults_to_p3(self, monkeypatch):
        _force_default_path(monkeypatch, verifier_agent)

        result = await verifier_agent.run_verification({"id": "A1"}, {})

        assert result["verified_severity"] == "P3"
        VerificationDecision.model_validate(result)


# ──────────────────────── response fallback ────────────────────────


class TestResponseDefaultPlan:
    @pytest.mark.parametrize(
        "severity, expected_action_types",
        [
            ("P1", {"isolate_host", "block_ioc", "escalate", "create_ticket"}),
            ("P2", {"block_ioc", "create_ticket", "escalate"}),
            ("P3", {"create_ticket", "add_to_watchlist"}),
            ("P4", {"create_ticket"}),
        ],
    )
    def test_plan_shape_per_severity(self, severity, expected_action_types):
        alert = {"id": "ALT-7", "hostname": "WS-9", "dest_ip": "1.2.3.4"}
        plan = response_agent._default_plan(alert, severity, {"decision": "confirmed"})

        assert plan["severity_acted_on"] == severity
        action_types = {s["action_type"] for s in plan["response_plan"]}
        assert action_types == expected_action_types
        ResponsePlan.model_validate(plan)  # schema-valid fallback

    def test_was_adjusted_reflects_verifier_decision(self):
        alert = {"id": "ALT-7", "hostname": "WS-9"}
        adjusted = response_agent._default_plan(alert, "P1", {"decision": "adjusted"})
        confirmed = response_agent._default_plan(alert, "P1", {"decision": "confirmed"})
        assert adjusted["was_adjusted"] is True
        assert confirmed["was_adjusted"] is False

    @pytest.mark.asyncio
    async def test_run_response_fallback_uses_verified_severity(self, monkeypatch):
        _force_default_path(monkeypatch, response_agent)

        plan = await response_agent.run_response(
            {"id": "ALT-8", "hostname": "DC-2", "dest_ip": "9.9.9.9"},
            {"verified_severity": "P1", "decision": "adjusted"},
        )

        assert plan["severity_acted_on"] == "P1"
        assert plan["was_adjusted"] is True
        ResponsePlan.model_validate(plan)
