"""Tests for ``blue_lantern.llm.caller._parse_llm_output``.

``_parse_llm_output`` is the shared parse/validate step behind all three
agents: it tries a direct Pydantic JSON parse, falls back to ``extract_json``
+ validate, and returns ``None`` when both fail (which is what triggers the
retry / default-factory paths in ``call_llm``). These tests use the real
``TriageVerdict`` schema so the validation contract is exercised end to end.
"""

import json
from types import SimpleNamespace

import pytest
from openai import OpenAIError

from blue_lantern.llm.caller import _create_completion, _parse_llm_output, call_llm
from blue_lantern.schemas import TriageVerdict


class _BoomCompletions:
    """A chat.completions stub whose create() always raises an SDK error."""

    async def create(self, **kwargs):
        raise OpenAIError("simulated LLM outage")


def _boom_client():
    return SimpleNamespace(chat=SimpleNamespace(completions=_BoomCompletions()))

_VALID = {
    "severity": "P1",
    "confidence": 90,
    "reasoning": "Confirmed malicious C2 on a critical asset.",
    "mitre_techniques": ["T1059.001"],
    "iocs_found": [],
    "asset_criticality": "critical",
    "recommended_urgency": "immediate",
}


class TestParseSucceeds:
    def test_direct_valid_json(self):
        result = _parse_llm_output(TriageVerdict, json.dumps(_VALID))
        assert result is not None
        assert result["severity"] == "P1"
        assert result["asset_criticality"] == "critical"

    def test_fenced_json_recovered_via_extract(self):
        content = f"```json\n{json.dumps(_VALID)}\n```"
        result = _parse_llm_output(TriageVerdict, content)
        assert result is not None
        assert result["severity"] == "P1"

    def test_object_embedded_in_prose_recovered(self):
        content = f"Sure, here you go: {json.dumps(_VALID)} Hope that helps!"
        result = _parse_llm_output(TriageVerdict, content)
        assert result is not None
        assert result["confidence"] == 90

    def test_defaults_applied_for_optional_fields(self):
        minimal = {
            "severity": "P3",
            "confidence": 40,
            "reasoning": "Suspicious but unconfirmed.",
            "asset_criticality": "medium",
            "recommended_urgency": "standard",
        }
        result = _parse_llm_output(TriageVerdict, json.dumps(minimal))
        assert result is not None
        assert result["mitre_techniques"] == []
        assert result["iocs_found"] == []


class TestParseReturnsNone:
    def test_garbage_returns_none(self):
        assert _parse_llm_output(TriageVerdict, "I could not comply.") is None

    def test_empty_returns_none(self):
        assert _parse_llm_output(TriageVerdict, "") is None

    def test_missing_required_field_returns_none(self):
        bad = {k: v for k, v in _VALID.items() if k != "severity"}
        assert _parse_llm_output(TriageVerdict, json.dumps(bad)) is None

    def test_invalid_enum_value_returns_none(self):
        bad = {**_VALID, "severity": "P9"}
        assert _parse_llm_output(TriageVerdict, json.dumps(bad)) is None

    def test_out_of_range_confidence_returns_none(self):
        bad = {**_VALID, "confidence": 150}
        assert _parse_llm_output(TriageVerdict, json.dumps(bad)) is None


class TestApiErrorHandling:
    """An LLM endpoint outage must degrade to the default, never crash (finding #2)."""

    @pytest.mark.asyncio
    async def test_create_completion_returns_none_on_openai_error(self):
        out = await _create_completion(_boom_client(), "m", [], {}, "triage")
        assert out is None

    @pytest.mark.asyncio
    async def test_call_llm_falls_back_to_default_on_outage(self):
        out = await call_llm(
            agent_name="triage",
            system_prompt="s",
            user_content="u",
            schema_class=TriageVerdict,
            retry_hint="please output JSON",
            default_factory=lambda: dict(_VALID, severity="P3", reasoning="fallback"),
            client=_boom_client(),
        )
        # Both the first call and the retry raised → default factory used.
        assert out.result["severity"] == "P3"
        assert out.result["reasoning"] == "fallback"
        assert out.raw_content == ""
