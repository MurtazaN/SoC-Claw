# Blue Lantern — README & SETUP Accuracy Review

**Date:** 2026-05-31
**Scope:** [README.md](../../README.md) and [SETUP.md](../../SETUP.md), verified against the
committed source (`routing.yaml`, `.env.example`, `docker-compose.yml`, `pyproject.toml`,
`backend/`, `connectors/`, `mock_data/`).
**Complements:** [CODE_REVIEW.md](CODE_REVIEW.md), [CLEAN_CODE_SOLID_REVIEW.md](CLEAN_CODE_SOLID_REVIEW.md).
This document checks only whether the docs are **inline / up to date** with the code.

---

## Severity legend

| Icon | Meaning |
|------|---------|
| 🔴 | Broken — the documented command/path fails or describes something that doesn't exist |
| 🟠 | Misleading — contradicts the code's actual behavior or default |
| 🟡 | Incomplete / minor — accurate but thin, or low-impact wording |
| ✅ | Verified accurate |

---

## ✅ What's accurate (verified, keep as-is)

- **Data counts** — `alerts.json`=30, `threat_intel.json`=20, `asset_inventory.json`=15,
  `mitre_techniques.json`=20 all match the files in `src/blue_lantern/mock_data/`.
- **Webhook scheme** — headers `X-Signature` / `X-Timestamp` / `X-SIEM-Type`, HMAC-SHA256
  of `timestamp.body`, secret in `WEBHOOK_SECRET` — matches `backend/routes/siem_webhook.py`.
- **Auth** — `python -m blue_lantern.backend.auth <password>` exists, uses bcrypt (`$2b$`);
  env vars `BLUE_LANTERN_SECRET_KEY` / `BLUE_LANTERN_USERS` and the default `analyst`/`analyst`
  account match `backend/auth.py`.
- **Batch endpoints** — `POST /api/batch/upload`, `GET /api/batch/status/{job_id}`,
  `GET /api/batch/results/{job_id}` all exist as documented.
- **Dashboard buttons** — "Process Latest N" → `POST /api/process-batch`; "Process All" /
  "Run All 30" → SSE `GET /api/process-all` (default 30 via `BLUE_LANTERN_BATCH_SIZE`).
- **Kafka topics** — `blue-lantern-alerts` and `blue-lantern-alerts-dlq`, auto-created by the
  `kafka-init` container.
- **Python version** — `pyproject.toml` requires `>=3.11`, matching SETUP.
- **Top-level structure** — all listed files/dirs exist (`pyproject.toml`, `uv.lock`,
  `Dockerfile`, `docker-compose.yml`, `.env.example`, `AGENTS.md`, `assets/`, `data/`,
  `docs/`, `scripts/`, `tests/`, `src/`); subpackage names match.

---

## Findings

### 🔴 1. Clone command is broken — [README.md:154](../../README.md#L154)
```bash
git clone https://github.com/MurtazaN/Blue Lantern   # space in URL → fails
cd Blue Lantern                                       # wrong dir name
```
Actual repo is `SoC-Claw`. Should be:
```bash
git clone https://github.com/MurtazaN/SoC-Claw.git
cd SoC-Claw
```
(Consistent with the "repo root (rename pending)" note at [README.md:88](../../README.md#L88).)

### 🔴 2. Two documented health endpoints don't exist — [SETUP.md:274-283](../../SETUP.md#L274-L283)
`GET /api/health` and `GET /api/batch/health` are **not defined** anywhere in `backend/`.
Only `GET /api/siem/health` exists. The two bad `curl` examples should be removed; confirm
whether a root `/health`/`/healthz` exists in `server.py` and document that instead.

### 🔴 3. `privacy_routes.yaml` is referenced but never committed — [README.md:108](../../README.md#L108)
The `config/` description reads `routing.py + routing.yaml + privacy_routes.yaml`. Only
`routing.py` and `routing.yaml` exist on disk.

### 🔴 4. `vllm serve mistral:7b-instruct` is invalid — [README.md:186](../../README.md#L186), [SETUP.md:57](../../SETUP.md#L57)
`mistral:7b-instruct` is **Ollama tag syntax**, not a valid vLLM/HF model id, so the command
fails. It also contradicts the shipped default (see #5). If a vLLM example is kept, use a real
HF id and tell the reader to point the agents at the `vllm-local` provider (`:8000`) in
`routing.yaml`.

### 🟠 5. Model / privacy-routing narrative contradicts `routing.yaml` — [README.md:22](../../README.md#L22)
README prose: *"Sensitive SOC data … stays on local **Nemotron** inference via vLLM … Same
model, different locations."* Reality in [routing.yaml:31-48](../../src/blue_lantern/config/routing.yaml#L31-L48):
- All three agents default to provider `lm-studio-from-container`, model **`google/gemma-4-e4b`**
  (port **1234**, not vLLM on 8000). Nemotron/Mistral appear only as commented-out options.
- Cloud routes use a *different* model, not the same one — so "same model, different locations"
  is false.
- `content_routes: []` — the per-content privacy routing is **empty by default**, so nothing
  routes to cloud unless configured.

**Decision (product owner, 2026-05-31):** rewrite to **provider-agnostic framing** — pluggable
local (LM Studio / Ollama / vLLM) + cloud (OpenRouter / NVIDIA / HF / Vertex) providers set
per-agent in `routing.yaml`; name `google/gemma-4-e4b` via LM Studio as the shipped default;
state that keeping sensitive payloads local is *configurable via `content_routes`*, not always-on.

### 🟠 6. docker-compose service list is wrong — [README.md:92](../../README.md#L92)
`# app + benchmark + Kafka + Redis services` omits `zookeeper` and `kafka-init`, and lists
`benchmark` as if always-on — it's gated behind `--profile benchmark`. Actual services:
`app`, `redis`, `zookeeper`, `kafka`, `kafka-init`, and `benchmark` (profile-gated).

### 🟡 7. Production `.env` section is incomplete — [SETUP.md:75-101](../../SETUP.md#L75-L101)
SETUP documents 7 vars; `.env.example` defines ~30 (well annotated). Notable functional
omissions: **`BLUE_LANTERN_REDIS_URL`** (required in prod — `/api/batch/*` returns 503 without
it, [.env.example:125-129](../../.env.example#L125)) and **`GCS_LOG_BUCKET_NAME`** (the GCS
source the app fetches alerts from). Recommend adding those two plus a one-line pointer to
`.env.example` as the authoritative list, rather than duplicating all 30.

### 🟡 8. `data/` vs `mock_data/` not distinguished — [README.md:96,113](../../README.md#L96)
The Data Layer table's four JSON files live in `src/blue_lantern/mock_data/`. Top-level `data/`
holds *different* `.jsonl` reference datasets. A half-line clarifying the two are distinct would
prevent misreading the table as describing `data/`.

### 🟡 9. vLLM auto-connect URL is provider-specific — [README.md:189](../../README.md#L189), [SETUP.md:60](../../SETUP.md#L60)
"App auto-connects to `http://localhost:8000/v1`" is only true if the agents are pointed at the
`vllm-local` provider. The shipped default is LM Studio at `host.docker.internal:1234`; in
docker-compose the local URL is `host.docker.internal`, not `localhost`.

---

## Benchmark numbers — left as-is (product-owner decision)
For the record: the Key Results table ([README.md:31-33](../../README.md#L31)) shows triage ~78%
/ verified ~88% (+10%), while the screenshot caption ([README.md:81](../../README.md#L81)) shows
triage 76.7% / verified 63.3% (verified **worse**). These contradict each other, but per the
2026-05-31 decision **no change is being made** to the benchmark numbers or screenshots in this
pass. Noted here only so the discrepancy is on record.

---

## Out of scope (code/config issues, not doc fixes)
Surfaced during verification; track separately:
- Missing `__init__.py` in `src/blue_lantern/connectors/` and `backend/routes/`.
- `routing.yaml` `api_key_env: "dummy-key"` is a literal value, not an env-var name
  ([routing.yaml:8,11,14](../../src/blue_lantern/config/routing.yaml#L8)).
- `routing.yaml` references `GOOGLE_AI_API_KEY` but `.env.example` defines `VERTEX_AI_API_KEY`.
