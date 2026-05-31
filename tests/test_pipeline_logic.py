"""Tests for the pure (non-agent, synchronous) pipeline logic.

Targets ``merge_verdict``, ``_classify_indicator`` and
``execute_approved_action`` in ``blue_lantern.pipeline``. None of these call
agents, LLMs or the network — they are fully deterministic.
"""

import logging

import pytest

from blue_lantern import pipeline


# ──────────────────────── merge_verdict ────────────────────────


class TestMergeVerdict:
    def test_confirmed_keeps_triage_severity(self):
        triage = {"severity": "P2", "_meta": {"x": 1}}
        final = pipeline.merge_verdict(triage, {"decision": "confirmed"})
        assert final["verified_severity"] == "P2"
        assert final["was_adjusted"] is False
        assert final["was_flagged"] is False
        assert "_meta" not in final  # internal metadata is stripped

    def test_adjusted_overrides_severity(self):
        triage = {"severity": "P2"}
        verification = {"decision": "adjusted", "verified_severity": "P1"}
        final = pipeline.merge_verdict(triage, verification)
        assert final["verified_severity"] == "P1"
        assert final["was_adjusted"] is True
        assert final["was_flagged"] is False

    def test_flagged_marks_pending_review(self):
        final = pipeline.merge_verdict({"severity": "P3"}, {"decision": "flagged"})
        assert final["was_flagged"] is True
        assert final["pending_review"] is True
        assert final["verified_severity"] == "P3"

    def test_unknown_decision_treated_as_confirmed(self):
        final = pipeline.merge_verdict({"severity": "P2"}, {"decision": "bogus"})
        assert final["verified_severity"] == "P2"
        assert final["was_adjusted"] is False
        assert final["was_flagged"] is False


# ──────────────────────── _classify_indicator ────────────────────────


class TestClassifyIndicator:
    @pytest.mark.parametrize(
        "target, expected",
        [
            ("8.8.8.8", "ip"),
            ("2001:db8::1", "ip"),
            ("1password.com", "domain"),  # digit-leading domain, not an IP
            ("evil.example.com", "domain"),
            ("a" * 32, "hash"),  # MD5
            ("a" * 40, "hash"),  # SHA1
            ("a" * 64, "hash"),  # SHA256
            ("", "unknown"),
            (None, "unknown"),
            ("randomstring", "unknown"),
        ],
    )
    def test_classification(self, target, expected):
        assert pipeline._classify_indicator(target) == expected


# ──────────────────────── execute_approved_action ────────────────────────


class TestExecuteApprovedAction:
    def test_isolate_host(self):
        result = pipeline.execute_approved_action(
            {"action_type": "isolate_host", "target": "WS-1"}
        )
        assert result["action"] == "host_isolated"
        assert result["hostname"] == "WS-1"

    def test_block_ioc_passes_classified_type(self):
        result = pipeline.execute_approved_action(
            {"action_type": "block_ioc", "target": "8.8.8.8"}
        )
        assert result["action"] == "ioc_blocked"
        assert result["type"] == "ip"

    def test_create_ticket_maps_priority(self):
        result = pipeline.execute_approved_action(
            {"action_type": "create_ticket", "target": "do X", "_severity": "P1"},
            {"id": "ALT-9"},
        )
        assert result["action"] == "ticket_created"
        assert result["priority"] == "critical"

    def test_escalate_infers_tier(self):
        result = pipeline.execute_approved_action(
            {"action_type": "escalate", "target": "Tier 3 IR", "reasoning": "bad"}
        )
        assert result["action"] == "escalated"
        assert result["escalated_to"] == "Tier 3"

    def test_unknown_action_type_is_logged(self):
        result = pipeline.execute_approved_action(
            {"action_type": "collect_forensics", "target": "host-1"}
        )
        assert result["status"] == "logged"
        assert result["action"] == "collect_forensics"

    def test_analyst_attribution_in_audit_log(self, caplog):
        with caplog.at_level(logging.INFO, logger="blue-lantern.audit"):
            pipeline.execute_approved_action(
                {"action_type": "isolate_host", "target": "WS-1"},
                {"id": "ALT-9"},
                analyst="alice",
            )
        records = [r for r in caplog.records if r.getMessage() == "analyst_action"]
        assert records, "expected an analyst_action audit record"
        assert "(by alice)" in records[0].details
