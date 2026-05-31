"""Tests for the GCS-sourced IP reputation tool (plan-04 cutover).

Covers normalization, the private-IP filter, dataset lookup, TTL refresh /
failure semantics, and the GCS connector. Tests inject a fake fetcher (or
monkeypatch the GCS client) so none of them touch GCS or the network.
"""

import pytest

from blue_lantern.connectors import threat_intel_gcs
from blue_lantern.tools import ip_reputation as mod
from blue_lantern.tools.ip_reputation import (
    IPReputationTool,
    ThreatIntelIndex,
    _is_private,
    ip_reputation,
    normalize_ip,
)


def _entry(indicator, score, type_="ip"):
    return {
        "indicator": indicator,
        "type": type_,
        "threat_score": score,
        "tags": ["t"],
        "campaigns": ["c"],
        "first_seen": "2026-01-01",
        "last_seen": "2026-02-01",
    }


def _index(entries):
    """Index built from a fixed row list — no GCS, no real TTL refresh."""
    return ThreatIntelIndex(lambda: list(entries))


# ── normalize_ip ─────────────────────────────────────────────────────


def test_normalize_ip_collapses_ipv6():
    assert normalize_ip("2001:0db8:0000:0000:0000:0000:0000:0001") == "2001:db8::1"


def test_normalize_ip_ipv4_unchanged():
    assert normalize_ip("8.8.8.8") == "8.8.8.8"


@pytest.mark.parametrize("bad", ["not-an-ip", "10.0.0.256", ""])
def test_normalize_ip_invalid_returns_none(bad):
    assert normalize_ip(bad) is None


# ── _is_private ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ip",
    ["10.1.2.3", "172.16.5.5", "172.31.255.1", "192.168.0.1", "127.0.0.1", "garbage"],
)
def test_is_private_true(ip):
    assert _is_private(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "185.220.101.42", "1.1.1.1"])
def test_is_private_false(ip):
    assert _is_private(ip) is False


# ── ip_reputation lookup ─────────────────────────────────────────────


def test_lookup_hit_returns_verdict_and_fields():
    result = ip_reputation("203.0.113.7", _index([_entry("203.0.113.7", 90)]))
    assert result["verdict"] == "malicious"
    assert result["threat_score"] == 90
    assert result["tags"] == ["t"]
    assert result["campaigns"] == ["c"]


def test_lookup_miss_returns_unknown():
    result = ip_reputation("8.8.8.8", _index([_entry("203.0.113.7", 90)]))
    assert result["verdict"] == "unknown"
    assert result["threat_score"] == 0


def test_lookup_matches_across_ipv6_forms():
    idx = _index([_entry("2001:db8::1", 50)])
    assert ip_reputation("2001:0db8:0000:0000:0000:0000:0000:0001", idx)["verdict"] == "suspicious"


def test_lookup_ignores_non_ip_rows():
    # A non-ip row whose indicator is IP-shaped must not be indexed.
    idx = _index([_entry("203.0.113.7", 90, type_="hash")])
    assert ip_reputation("203.0.113.7", idx)["verdict"] == "unknown"


def test_lookup_invalid_ip_returns_unknown():
    idx = _index([_entry("203.0.113.7", 90)])
    assert ip_reputation("not-an-ip", idx)["verdict"] == "unknown"


@pytest.mark.parametrize(
    "score,verdict",
    [
        (95, "malicious"),
        (80, "malicious"),
        (60, "suspicious"),
        (40, "suspicious"),
        (10, "low_risk"),
        (0, "unknown"),
    ],
)
def test_verdict_thresholds(score, verdict):
    idx = _index([_entry("203.0.113.7", score)])
    assert ip_reputation("203.0.113.7", idx)["verdict"] == verdict


# ── IPReputationTool: private filter on BOTH source and dest ─────────


def test_tool_skips_private_source_and_dest():
    tool = IPReputationTool(_index([_entry("203.0.113.7", 90)]))
    assert tool.run({"dest_ip": "10.0.0.5", "source_ip": "192.168.1.1"}) == {}


def test_tool_queries_both_public_ips():
    idx = _index([_entry("8.8.8.8", 90), _entry("1.1.1.1", 30)])
    results = IPReputationTool(idx).run({"dest_ip": "8.8.8.8", "source_ip": "1.1.1.1"})
    assert results["dest_ip"]["verdict"] == "malicious"
    assert results["source_ip"]["verdict"] == "low_risk"


def test_tool_skips_private_dest_keeps_public_source():
    idx = _index([_entry("1.1.1.1", 30)])
    results = IPReputationTool(idx).run({"dest_ip": "172.16.0.9", "source_ip": "1.1.1.1"})
    assert "dest_ip" not in results
    assert results["source_ip"]["verdict"] == "low_risk"


# ── TTL refresh / failure semantics ──────────────────────────────────


def test_serves_last_good_index_on_refresh_failure():
    clock = {"now": 1000.0}
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            return [_entry("203.0.113.7", 90)]
        raise RuntimeError("GCS down")

    idx = ThreatIntelIndex(flaky, ttl_seconds=10, timer=lambda: clock["now"])
    assert ip_reputation("203.0.113.7", idx)["verdict"] == "malicious"  # cold load

    clock["now"] = 1100  # past TTL → forces a refresh that fails
    assert ip_reputation("203.0.113.7", idx)["verdict"] == "malicious"  # last-good
    assert calls["n"] == 2


def test_empty_index_on_cold_start_failure():
    def always_fails():
        raise RuntimeError("GCS down")

    assert ip_reputation("203.0.113.7", ThreatIntelIndex(always_fails))["verdict"] == "unknown"


# ── _default_fetcher source selection ────────────────────────────────


def test_default_fetcher_uses_mock_when_unconfigured(monkeypatch):
    monkeypatch.delenv("GCS_THREAT_INTEL_BUCKET", raising=False)
    monkeypatch.delenv("GCS_THREAT_INTEL_OBJECT", raising=False)
    rows = mod._default_fetcher()
    assert any(r["indicator"] == "185.220.101.42" for r in rows)


def test_default_fetcher_uses_gcs_when_configured(monkeypatch):
    monkeypatch.setenv("GCS_THREAT_INTEL_BUCKET", "b")
    monkeypatch.setenv("GCS_THREAT_INTEL_OBJECT", "ti.json")
    sentinel = [_entry("203.0.113.7", 90)]
    monkeypatch.setattr(threat_intel_gcs, "download_threat_intel", lambda bucket, obj: sentinel)
    assert mod._default_fetcher() == sentinel


# ── GCS connector ────────────────────────────────────────────────────


class _FakeBlob:
    def __init__(self, text):
        self._text = text

    def download_as_text(self):
        return self._text


class _FakeBucket:
    def __init__(self, text):
        self._text = text

    def blob(self, name):
        return _FakeBlob(self._text)


class _FakeClient:
    def __init__(self, text):
        self._text = text

    def bucket(self, name):
        return _FakeBucket(self._text)


def test_download_validates_and_skips_bad_rows(monkeypatch):
    payload = (
        '[{"indicator": "203.0.113.7", "type": "ip", "threat_score": 90},'
        ' {"indicator": "no-score", "type": "ip"}]'  # missing required threat_score
    )
    monkeypatch.setattr(threat_intel_gcs, "get_gcs_client", lambda: _FakeClient(payload))
    rows = threat_intel_gcs.download_threat_intel("b", "threat_intel.json")
    assert len(rows) == 1
    assert rows[0]["indicator"] == "203.0.113.7"


def test_download_raises_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(threat_intel_gcs, "get_gcs_client", lambda: None)
    with pytest.raises(RuntimeError):
        threat_intel_gcs.download_threat_intel("b", "threat_intel.json")
