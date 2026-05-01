# Configuration reference

All runtime config is env-driven. Copy `.env.example` to `.env` and edit.

## Network ports

| Port | Service |
|------|---------|
| 8000 | vLLM OpenAI-compatible endpoint (host) |
| 7860 | SOC-Claw UI (container, published to host) |

## vLLM / model

- `HF_TOKEN` — HuggingFace token; consumed by `vllm serve` at startup to download weights. Not used by the soc-claw runtime.
- `SOC_CLAW_MODEL` — model name passed to both vLLM and the OpenAI client. Default `nvidia/Nemotron-Mini-4B-Instruct`.
- `SOC_CLAW_LOCAL_VLLM_URL` — default `http://localhost:8000/v1`; compose overrides to `http://host.docker.internal:8000/v1`.

## Cloud route

- `NVIDIA_API_KEY` — required only when the privacy router routes a prompt to cloud. The bundled alerts never trigger the cloud route.
- `SOC_CLAW_CLOUD_URL` — default `https://integrate.api.nvidia.com/v1`.

## Authentication

- `SOC_CLAW_SECRET_KEY` — session-cookie + CSRF signing key. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. Must be stable across restarts.
- `SOC_CLAW_USERS` — `username:bcrypt_hash` pairs (comma-separated). Generate hashes with `python -m soc_claw.backend.auth <password>`. Blank → default `analyst:analyst` with a startup warning.
- `SOC_CLAW_SESSION_MAX_AGE` — session lifetime in seconds. Default `28800` (8 hours).

## Observability

- `OTEL_EXPORTER_OTLP_ENDPOINT` — OTLP gRPC endpoint (e.g. `http://localhost:4317`). Blank → no-op tracing.
- `SOC_CLAW_LOG_LEVEL` — `DEBUG` / `INFO` / `WARNING` / `ERROR`. Server default `INFO`, harness default `WARNING`.
- `SOC_CLAW_LOG_FILE` — when set, JSON logs append to this path instead of stderr.

## Network security (FastAPI Guard)

Outermost middleware: rate limiting, IP whitelist, auto-banning, security headers, attack-pattern detection. Runtime order is `Guard → auth → CSRF → handler`.

- `SOC_CLAW_RATE_LIMIT` — per-IP request limit. Default `200`.
- `SOC_CLAW_RATE_WINDOW` — rate-limit window in seconds. Default `60`.
- `SOC_CLAW_AUTO_BAN_THRESHOLD` — consecutive 4xx / rejected requests before a temporary ban. Default `20`.
- `SOC_CLAW_AUTO_BAN_DURATION` — ban duration in seconds. Default `3600` (1 hour).
- `SOC_CLAW_IP_WHITELIST` — comma-separated IPs / CIDRs allowed past the firewall. Default `127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` (loopback + RFC1918). Empty string disables the whitelist; rate-limit + auto-ban remain active.
- `SOC_CLAW_REDIS_URL` — optional Redis backend for shared state (e.g. `redis://localhost:6379`). Blank → in-memory store, single-worker safe. Set when scaling to multi-worker uvicorn or multi-pod k8s.

## Benchmark

- `BENCHMARK_OUTPUT_DIR` — host dev: blank → `soc_claw/benchmark/results/`. Compose overrides to `/app/soc_claw/benchmark/results`.
- `SOC_CLAW_CONCURRENCY` — alerts processed in parallel by the harness and `/api/run-all`. Default `5`.

## Production target

For llm-d / k8s, the same image ships unchanged; secrets become a k8s `Secret` and config a `ConfigMap` mounted as env.
