"""Tests for ``blue_lantern.llm.caller._parse_llm_output``.

``_parse_llm_output`` is the shared parse/validate step behind all three
agents: it tries a direct Pydantic JSON parse, falls back to ``extract_json``
+ validate, and returns ``None`` when both fail (which is what triggers the
retry / default-factory paths in ``call_llm``). These tests use the real
``TriageVerdict`` schema so the validation contract is exercised end to end.
"""

import json

from blue_lantern.llm.caller import _parse_llm_output
from blue_lantern.schemas import TriageVerdict

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
