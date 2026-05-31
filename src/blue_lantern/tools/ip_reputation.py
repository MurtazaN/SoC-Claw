"""IP reputation enrichment tool.

Looks up an IP against a threat-intelligence dataset. In production the
dataset is sourced from GCS (set ``GCS_THREAT_INTEL_BUCKET`` +
``GCS_THREAT_INTEL_OBJECT``); without those it falls back to the bundled
``mock_data/threat_intel.json`` for dev/test. The dataset is loaded into an
IP-keyed index and refreshed on a TTL rather than re-read per lookup.
"""

import ipaddress
import logging
import os
import time
from pathlib import Path
from typing import Callable

from cachetools import TTLCache

from blue_lantern.schemas import ThreatIntelEntry
from blue_lantern.tools.registry import register
from blue_lantern.utils import load_validated_json

_logger = logging.getLogger("blue-lantern.tools.ip_reputation")

DATA_DIR = Path(__file__).parent.parent / "mock_data"
THREAT_INTEL_TTL = int(os.environ.get("BLUE_LANTERN_THREAT_INTEL_TTL", "86400"))

# A fetcher returns the validated threat-intel rows. Injecting one is the
# test seam — tests pass a fake fetcher so they never touch GCS.
Fetcher = Callable[[], list[dict]]


def normalize_ip(ip: str) -> str | None:
    """Return the canonical string form of ``ip``, or ``None`` if invalid.

    Collapses IPv6 (e.g. ``2001:0db8:0000:0000:0000:0000:0000:0001`` →
    ``2001:db8::1``) so the same address indexes and looks up identically
    regardless of the form it arrives in. Unparseable or ambiguous input
    (including leading-zero octets, which ``ipaddress`` rejects) returns
    ``None`` so callers fall through to the ``"unknown"`` verdict instead
    of indexing garbage.
    """
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        return None


def _is_private(ip: str) -> bool:
    """True if ``ip`` is private/loopback/link-local — or unparseable.

    RFC1918 ranges (10/8, 172.16/12, 192.168/16), loopback and link-local
    are skipped: no point spending a lookup (or, once the VT-later fallback
    lands, a paid API call) on internal addresses. Unparseable input is
    skipped too.
    """
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return True


def _default_fetcher() -> list[dict]:
    """Load threat-intel rows from GCS when configured, else the mock file."""
    bucket = os.environ.get("GCS_THREAT_INTEL_BUCKET", "").strip()
    obj = os.environ.get("GCS_THREAT_INTEL_OBJECT", "").strip()
    if bucket and obj:
        # Imported lazily so dev/test (no bucket) never pulls in the GCS SDK.
        from blue_lantern.connectors.threat_intel_gcs import download_threat_intel

        return download_threat_intel(bucket, obj)

    _logger.info("No GCS threat-intel bucket configured; using bundled mock dataset")
    return list(
        load_validated_json(DATA_DIR / "threat_intel.json", ThreatIntelEntry, _logger)
    )


class ThreatIntelIndex:
    """IP→entry index over the threat-intel dataset, refreshed on a TTL.

    The whole dataset is loaded once and indexed by canonical IP for O(1)
    lookups, then reloaded when the TTL lapses. A refresh failure keeps the
    last good index so the pipeline keeps enriching; a cold-start failure
    leaves an empty index (every lookup returns ``"unknown"``).
    """

    def __init__(
        self,
        fetcher: Fetcher,
        ttl_seconds: float = THREAT_INTEL_TTL,
        timer: Callable[[], float] | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._cache: TTLCache[str, dict] = TTLCache(
            maxsize=1, ttl=ttl_seconds, timer=timer or time.monotonic
        )
        self._last_good: dict[str, dict] = {}

    def get(self) -> dict[str, dict]:
        index = self._cache.get("index")
        if index is not None:
            return index
        try:
            index = self._build()
            self._last_good = index
        except Exception:  # GCS / network / parse failure
            _logger.exception(
                "Threat-intel refresh failed; serving last-good index (%d entries)",
                len(self._last_good),
            )
            return self._last_good
        self._cache["index"] = index
        return index

    def _build(self) -> dict[str, dict]:
        index: dict[str, dict] = {}
        for entry in self._fetcher():
            if entry.get("type") != "ip":
                continue
            key = normalize_ip(entry.get("indicator", ""))
            if key:
                index[key] = entry
        return index


_default_index = ThreatIntelIndex(_default_fetcher)


def _verdict(score: int) -> str:
    if score >= 80:
        return "malicious"
    if score >= 40:
        return "suspicious"
    if score > 0:
        return "low_risk"
    return "unknown"


def ip_reputation(ip: str, index: ThreatIntelIndex | None = None) -> dict:
    """Look up an IP address against the threat-intelligence dataset."""
    key = normalize_ip(ip)
    entry = (index or _default_index).get().get(key) if key else None
    if entry is not None:
        score = entry["threat_score"]
        return {
            "threat_score": score,
            "tags": entry["tags"],
            "campaigns": entry["campaigns"],
            "first_seen": entry["first_seen"],
            "last_seen": entry["last_seen"],
            "verdict": _verdict(score),
        }

    # ── VT-later seam (plan-04B) ─────────────────────────────────────────
    # A dataset miss is the single hook point for a future VirusTotal
    # fallback. It would resolve the miss through the shared plan-01 cache:
    #     from blue_lantern.cache import get_cache
    #     return get_cache().get_or_compute(
    #         f"ip_rep:{key}", lambda: virustotal_lookup(ip), 86_400)
    # The VT connector, response→ThreatIntelEntry mapping, and respx tests
    # are deferred to plan-04B; VIRUSTOTAL_API_KEY is reserved, not wired.
    return {
        "threat_score": 0,
        "tags": [],
        "campaigns": [],
        "first_seen": None,
        "last_seen": None,
        "verdict": "unknown",
    }


class IPReputationTool:
    name = "ip_reputation"
    description = "Provides threat intelligence scores, tags, and known campaigns for IP addresses."

    def __init__(self, index: ThreatIntelIndex | None = None):
        self._index = index

    def run(self, alert: dict) -> dict:
        results = {}
        for field in ("dest_ip", "source_ip"):
            ip = alert.get(field)
            if ip and not _is_private(ip):
                results[field] = ip_reputation(ip, self._index)
        return results


register(IPReputationTool())
