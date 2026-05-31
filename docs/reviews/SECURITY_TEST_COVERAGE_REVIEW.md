# Security Test Coverage Review

_Date: 2026-05-31 · Branch: feature/real-time-threat-intel_

## Verdict

**Partial.** The *infrastructure* is reasonably tested (11 files, ~72 cases), but the
components a security reviewer checks **first** — authentication, webhook signature
verification, and privacy/data-egress routing — have **zero** coverage. Two structural
gaps compound this: the SIEM fixture file is never loaded by pytest, and there is no CI
or coverage measurement.

## What is covered

SIEM mappers (Splunk/Sentinel/CrowdStrike — genuinely thorough), tools smoke tests,
cache (+Redis), Kafka/DLQ, GCP output, job manager, logging config, and the
rate-limit/IP-ban portion of `security.py`.

## Gaps — security boundaries with no tests

| Component | What is at risk | Tests |
|---|---|---|
| [auth.py](../../src/blue_lantern/backend/auth.py) | `authenticate()`, bcrypt verify, session create/expire/destroy, `BLUE_LANTERN_USERS` parsing, default-account fallback | **none** |
| [siem_webhook.py:50](../../src/blue_lantern/backend/routes/siem_webhook.py#L50) `verify_hmac()` | HMAC signature check + replay/timestamp window — the entire ingestion auth boundary | **none** |
| [routing.py:39](../../src/blue_lantern/config/routing.py#L39) `route_request()` | privacy routing — decides whether sensitive payloads / internal IPs / PII leave to the cloud LLM | **none** |
| [pipeline.py](../../src/blue_lantern/pipeline.py) | `merge_verdict()` decision tree, `_classify_indicator()`, `execute_approved_action()` dispatch + analyst attribution | **none** |
| agents (triage / verifier / response) | severity heuristics, fallback paths, `requires_approval` logic | **none** (need LLM mocking) |
| [json_extract.py](../../src/blue_lantern/llm/json_extract.py), [alert_parser.py](../../src/blue_lantern/connectors/alert_parser.py) | parsing untrusted LLM output / untrusted alert input | **none** |
| CSP + auth middleware in [server.py](../../src/blue_lantern/backend/server.py) | header / redirect behavior | **none** |

## Structural issues

- **`tests/conftest_siem.py` is never loaded.** pytest only auto-discovers files named
  exactly `conftest.py`, so its `redis_client` / `event_loop` fixtures are dead. There is
  no root `conftest.py`.
- **No CI and no coverage measurement** — nothing runs the suite automatically or reports
  a coverage number.

## Non-test findings (flagged for awareness)

- `verify_hmac` ([siem_webhook.py:64-68](../../src/blue_lantern/backend/routes/siem_webhook.py#L64-L68)) rejects *old* timestamps but has no lower bound — a timestamp far in the **future** passes. Its seconds-vs-minutes unit juggling is also confusing.

---

# Remediation Plan (critical controls + CI/coverage)

**In scope:** deterministic, no-mock unit tests for the four critical controls; fix the
dead conftest; add CI + coverage. All four targets are pure/synchronous (no network, no
LLM) — fast and deterministic, no mocking infrastructure required.

**Out of scope (follow-up):** agent LLM-mocked tests, `json_extract` / `alert_parser`
untrusted-input tests, FastAPI middleware (CSP / auth redirect) tests.

### 1. `tests/test_auth.py` (new)
**Design note:** `_users` and `_sessions` are module globals and `authenticate()`
lazy-loads `_users`; every test must start clean — use the `reset_auth_state` fixture (§5).

- `authenticate`: correct password → True; wrong password → False; unknown user → False.
- Hashing round-trip: `_verify_password(p, _hash_password(p))` True; wrong pw False; malformed hash → False, never raises (covers `except` at [auth.py:86](../../src/blue_lantern/backend/auth.py#L86)).
- `_load_users` parsing of `BLUE_LANTERN_USERS` (monkeypatch env): multi-user `"a:h1,b:h2"`, whitespace trimming, entries without `:` skipped; empty env → single default `analyst` account.
- Sessions: `create_session` → token; `get_session` resolves to username; `destroy_session` removes it; two sessions get distinct ids.
- Expiry: set a session's `created` to `now - (SESSION_MAX_AGE+1)s` → `get_session` returns None **and** evicts it ([auth.py:48-52](../../src/blue_lantern/backend/auth.py#L48-L52)).
- `get_current_user`: `starlette.requests.Request` with/without the `soc_session` cookie → username / None.

### 2. `tests/test_webhook_hmac.py` (new)
Sig helper: `hmac.new(secret.encode(), f"{ts}.{body.decode()}".encode(), sha256).hexdigest()`.

- Valid signature + fresh timestamp → True.
- Tampered body (sig unchanged) → False; wrong secret → False.
- Timestamp older than 5 min → False ([:68](../../src/blue_lantern/backend/routes/siem_webhook.py#L68)); non-numeric timestamp → False ([:71](../../src/blue_lantern/backend/routes/siem_webhook.py#L71)).
- **Future-timestamp gap:** add an `xfail`-marked test asserting the *desired* behavior (reject), so the gap is tracked rather than silently shipped.

### 3. `tests/test_privacy_routing.py` (new)
**Design note:** `load_privacy_routes` is `lru_cache`d — call `load_privacy_routes.cache_clear()`
in a fixture so tests reflect the shipped `config/privacy_routes.yaml`. Validate the *actual*
policy, since it gates what leaves to the cloud.

- Internal IP (`10.x`, `192.168.x`) → `("local", …)`; internal hostname prefix (`DC-`, `SRV-`, `FW-`, …) → `local`.
- Payload keyword (`payload` / `command_line` / `raw_log`) → `local`; PII keyword (`employee` / `user_id` / `email`) → `local`.
- Benign prompt → `("cloud", …)`; first-match-wins when two triggers present.

### 4. `tests/test_pipeline_logic.py` (new)
Pure functions only (no async, no agents).

- `merge_verdict`: `confirmed` → `verified_severity == triage severity`, flags False; `adjusted` → severity overridden, `was_adjusted` True; `flagged` → `was_flagged` + `pending_review` True; unknown decision → treated as confirmed ([:82-86](../../src/blue_lantern/pipeline.py#L82-L86)); `_meta` stripped.
- `_classify_indicator`: IPv4 & IPv6 → `ip`; digit-starting domain `1password.com` → `domain` (documented fix at [:167](../../src/blue_lantern/pipeline.py#L167)); 32/40/64-char → `hash`; other dotted → `domain`; empty/None → `unknown`.
- `execute_approved_action`: dispatches each `action_type` to the right `response_tools` fn (assert returned `action`, e.g. `host_isolated`); `block_ioc` passes the classified type through; unknown type → `{"status": "logged"}` ([:244](../../src/blue_lantern/pipeline.py#L244)); analyst name flows into the action (verify via `caplog`).

### 5. `tests/conftest.py` — fix the dead fixture file
Rename `tests/conftest_siem.py` → `tests/conftest.py` so pytest auto-loads it. Keep
`redis_client` (skips gracefully). **Remove** the manual `event_loop` override (deprecated
in current pytest-asyncio). Add a `reset_auth_state` fixture clearing
`blue_lantern.backend.auth._users` and `._sessions` per test.

### 6. `pyproject.toml` — coverage tooling
- Add `pytest-cov>=5` to `[project.optional-dependencies].dev`.
- Add `[tool.coverage.run] source = ["blue_lantern"]` and `[tool.coverage.report] show_missing = true`.
- Add `addopts = "--cov=blue_lantern --cov-report=term-missing"` (keep existing `pythonpath`/`testpaths`). No hard `--cov-fail-under` yet — establish a baseline first.

### 7. `.github/workflows/tests.yml` (new) — CI
On push + PR: checkout → install `uv` → `uv pip install -e ".[dev]"` → `uv run pytest`.
Redis-backed tests skip when no Redis is present; Kafka/GCP tests are already mocked, so
the suite runs green on a stock runner with no external services.

## Verification

1. `uv pip install -e ".[dev]"` (adds `pytest-cov`).
2. `uv run pytest -q` — all existing + new tests pass; the 4 new files are collected.
3. `uv run pytest --cov=blue_lantern --cov-report=term-missing` — `auth.py`,
   `siem_webhook.py`, `routing.py`, `pipeline.py` jump from 0% to high coverage; the
   future-timestamp test shows as `xfail`.
4. Confirm `tests/conftest.py` is auto-discovered (Redis tests still skip cleanly).
5. Push the branch / open a PR and confirm Actions runs `pytest` and reports coverage.
