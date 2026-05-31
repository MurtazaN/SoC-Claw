# Plan 04 — Cutover: Threat Intel (GCS dataset)

**Parent:** [production_data_architecture.md](production_data_architecture.md), step 4 (per-source cutover)
**Status:** Draft — GCS-sourced. VirusTotal live enrichment deferred to plan-04B (see "VT-later seam").

## Goal

Replace the bundled `mock_data/threat_intel.json` loader inside
[src/blue_lantern/tools/ip_reputation.py](../src/blue_lantern/tools/ip_reputation.py)
with the threat-intel dataset stored in GCS, loaded through the existing GCS
connector pattern and refreshed on a TTL. Keep `ip_reputation(ip)`'s return
shape identical (no caller changes). Reserve a documented hook for adding
VirusTotal as a cache-miss fallback later.

## Scope

- **In:** GCS bulk-dataset loader (reuse `get_gcs_client`/`download_as_text`),
  per-row `ThreatIntelEntry` validation, IP-indexed in-memory lookup with TTL
  refresh, `ipaddress`-based normalization + private-IP filtering, env vars,
  tests. A documented (code-free) seam for a future VT fallback.
- **Out:** The VirusTotal connector itself (httpx client, backoff, response
  mapping, respx tests) — deferred to **plan-04B**, only if a paid VT
  Enterprise key is provisioned. Multi-provider routing (MISP / Recorded
  Future) — deferred to v2.

## Why not VirusTotal now

VT's free public API forbids commercial use and is capped at 4 req/min /
500 req/day; the production tier is paid/enterprise-quoted. No VT key is
available, and a SOC enriching real alerts is commercial use. The GCS dataset
is free, has no rate limit or licensing constraint, and reuses connectors
already in the repo.

## Pinned decisions

| Decision | Choice | Rationale |
| :--- | :--- | :--- |
| Source | GCS bulk dataset, ADC auth via `get_gcs_client()` | Free, no rate limit, no ToS issue; reuses plan-03 GCS connectors |
| Dataset layout | Single bulk blob (JSON/JSONL/CSV) | Mirrors today's `threat_intel.json` |
| Dataset refresh | Process-local `cachetools.TTLCache(maxsize=1, ttl=24h)` | Avoid re-download per alert; threat intel changes slowly |
| Shared cache (plan-01) | Reserved for the VT-later per-IP fallback, NOT the bulk dataset | `get_or_compute` is sized for small per-key values; a multi-MB blob in Redis would be re-serialized per lookup |
| Lookup | IP→entry dict index, O(1) | Replaces today's linear scan |
| Validation | Each row validated vs `ThreatIntelEntry`; bad rows skipped + logged | Don't index garbage; mirrors `gcs_reader._normalize` |
| Internal-IP filter | `ipaddress.ip_address(ip).is_private`, applied to **both** source & dest | Correct RFC1918 (incl. 172.16/12) + loopback/link-local; mandatory hygiene before any paid-API fallback |
| Key normalization | `normalize_ip()` via `ipaddress` (collapse IPv6, strip IPv4 leading zeros) | Equivalent IPs match in index + lookup |
| GCS failure | Serve last-good index; cold-start failure → empty index (all `"unknown"`) | Pipeline must keep running |
| Return shape | Unchanged 6 keys + verdict thresholds (≥80 malicious, ≥40 suspicious, >0 low_risk, else unknown) | No call-site changes |

## Steps

1. **Config.** Add `GCS_THREAT_INTEL_BUCKET` + `GCS_THREAT_INTEL_OBJECT`
   (and optional `BLUE_LANTERN_THREAT_INTEL_TTL`, default 86_400) to
   `.env.example` + [config-reference.md](config-reference.md). Auth reuses the
   ADC already used by the alert GCS reader — no new credential.
2. **GCS loader.** Add `download_threat_intel(bucket, object_name) -> list[dict]`
   (in `connectors/`, alongside or inside `gcs_reader`): download the bulk blob
   via `get_gcs_client()` + `download_as_text()`, parse by suffix, validate each
   row against `ThreatIntelEntry`, skip+log bad rows. (`parse_blob` is
   alert-specific; reuse its format-splitting but validate to `ThreatIntelEntry`,
   not `Alert`.)
3. **Refactor `_load_threat_intel`** to build an IP→entry index from the loader,
   wrapped in a module-level `TTLCache(maxsize=1, ttl=THREAT_INTEL_TTL)`
   (replaces `@lru_cache`). On download failure: keep the last good index; on
   cold start with no prior index: empty index. Preserve a test injection seam
   (inject the fetcher / accept an override) so tests don't hit GCS — replacing
   today's `data_dir` parameter.
4. **`normalize_ip()` + private filter.** Add `normalize_ip(ip)` via
   `ipaddress`; use it for both index keys and lookups. Replace the prefix check
   at `IPReputationTool.run()` with `ipaddress.ip_address(ip).is_private`,
   applied to **both** `dest_ip` and `source_ip`; guard malformed IPs
   (`ValueError`) → skip/`"unknown"`.
5. **`ip_reputation(ip)`** becomes `index.get(normalize_ip(ip))` → same 6-key
   dict (or the `"unknown"` sentinel on miss). No caller changes.
6. **VT-later seam (no code).** Document that a dataset miss in `ip_reputation`
   is the single hook point for a future VT fallback:
   `cache.get_or_compute(f"ip_rep:{normalize_ip(ip)}", vt_lookup, 86_400)`
   (synchronous, matching the cache). Add `VIRUSTOTAL_API_KEY` to
   config-reference.md marked **reserved / not yet wired**. The connector,
   backoff, response→`ThreatIntelEntry` mapping, and respx tests are plan-04B.

## Acceptance criteria

- `ip_reputation(ip)` returns the same shape as today; existing
  `test_ip_reputation_*` pass.
- Dataset is loaded from GCS once per TTL window, not per alert.
- Private IPs (10/8, 172.16/12, 192.168/16, loopback) skipped for both source
  and dest.
- IPv6 + leading-zero IPv4 normalized consistently for index and lookup.
- GCS download failure → pipeline continues on stale/empty index, logged.
- VT fallback hook + `VIRUSTOTAL_API_KEY` documented but inert.

## Risks

- **Dataset freshness** — only as current as the GCS bucket; document the
  producer/refresh cadence.
- **In-memory size** — each worker holds its own copy; fine for a bounded
  dataset, revisit (shard or Redis-backed lookup) if it grows large.
- **Schema drift** — dataset must match `ThreatIntelEntry`; mismatches are
  skipped + logged, not fatal.
- **Cold-start GCS outage** — empty index → everything `"unknown"` until the
  next successful refresh.

## Open questions

- Exact bucket/object name + format (JSON / JSONL / CSV) of the dataset.
- Whether the dataset carries non-IP indicators (hashes/domains);
  `ip_reputation` only consumes `type == "ip"`, others ignored (as today).
- VT-later: confirm a paid VT Enterprise key is in scope before plan-04B.
