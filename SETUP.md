# SOC-Claw Setup

Two-terminal flow: vLLM on the host, app + benchmark in Docker.

## 1. Check prerequisites

- Linux host with NVIDIA GPU, driver ≥ 570.x (≥ 580 to use the latest vLLM). Tested on Ubuntu 22.04, A6000 / L4. CPU-only is not practical.
- Docker Engine + `docker compose` v2 plugin: `docker compose version`.
- `git`, `curl`, `bash`.

Mac dev (no GPU): run the container locally, point it at a remote vLLM via `ssh -L 8000:localhost:8000 <host>`. The container reaches it through `host.docker.internal:8000`.

## 2. Configure

```bash
git clone https://github.com/MurtazaN/SoC-Claw
cd SoC-Claw
cp .env.example .env
$EDITOR .env   # set HF_TOKEN
```

`.env` is gitignored. Auth, observability, and model-selection vars are documented in [docs/config-reference.md](docs/config-reference.md).

## 3. Install (GPU host only)

```bash
bash scripts/install-host.sh
```

Idempotent. Installs `uv`, Python 3.11, the venv at `.venv/`, app deps, and (on Linux + NVIDIA only) vLLM. Other hosts skip vLLM and exit cleanly. If `.env` is missing on first run, the script copies from `.env.example` and exits — populate it, then re-run.

For driver ≥ 580, replace the pinned vLLM line in [scripts/install-host.sh](scripts/install-host.sh) with `uv pip install vllm --torch-backend=auto`.

## 4. Start vLLM (terminal 1, GPU host only)

```bash
bash scripts/run-host-vllm.sh
```

Wait for `Uvicorn running on http://0.0.0.0:8000`, then:

```bash
curl http://localhost:8000/v1/models
```

The script reads `SOC_CLAW_MODEL` from `.env`.

## 5. Start the app (terminal 2)

```bash
bash scripts/setup.sh
```

Re-runs install, builds `soc-claw:dev`, runs `docker compose up -d`. Manual equivalent:

```bash
docker compose build
docker compose up -d
docker compose logs -f app
```

Open **http://localhost:7860**. The app reaches vLLM via `host.docker.internal:8000` (mapped via `extra_hosts:` on Linux; native on Docker Desktop).

## 6. Verify

```bash
curl -fsS http://localhost:7860/                            # 200
docker compose --profile benchmark run --rm benchmark 3     # 3-alert smoke run
ls soc_claw/benchmark/results/run_*.csv                     # CSV present on host
```

## 7. Run the benchmark

```bash
docker compose --profile benchmark run --rm benchmark 30    # all 30 alerts
docker compose --profile benchmark run --rm benchmark 5     # subset
```

CSV → `soc_claw/benchmark/results/run_<timestamp>.csv` on the host.

## 8. Enable observability (optional)

Logs are JSON to stderr by default; OTEL tracing is off until you point it at a collector.

Collect logs in a file:

```bash
echo "SOC_CLAW_LOG_FILE=/tmp/soc-claw.jsonl" >> .env
docker compose up -d
tail -f /tmp/soc-claw.jsonl
```

Capture traces in local Jaeger:

```bash
docker run -d --rm --name jaeger -p 4317:4317 -p 16686:16686 \
  jaegertracing/all-in-one:1.62
echo "OTEL_EXPORTER_OTLP_ENDPOINT=http://host.docker.internal:4317" >> .env
docker compose up -d
# Trigger one alert via the UI, then open http://localhost:16686
```

Make the harness verbose (defaults to `WARNING`):

```bash
SOC_CLAW_LOG_LEVEL=INFO docker compose --profile benchmark run --rm benchmark 30
```

## 9. Stop

```bash
docker compose down            # stop the app
docker compose down --rmi all  # also delete the image
# Ctrl+C in terminal 1 to stop vLLM
```

## 10. Troubleshoot

| Problem | Fix |
|---------|-----|
| `Connection refused` to vLLM from the container | `curl http://localhost:8000/v1/models` from the host. Confirm `extra_hosts:` is in `docker-compose.yml`. |
| `host.docker.internal` not resolving on Linux | Upgrade Docker to ≥ 20.10, or set `SOC_CLAW_LOCAL_VLLM_URL=http://172.17.0.1:8000/v1` in `.env`. |
| `CUDA out of memory` | Smaller model, or pass `--gpu-memory-utilization 0.85 --max-model-len 2048` to `vllm serve`. |
| `libcudart.so.13: not found` | vLLM 0.11+ needs CUDA 13. Upgrade the driver to ≥ 580 or stay on the pinned `vllm==0.10.2 --torch-backend=cu126` (default in `install-host.sh`). |
| Port 7860 already in use | `kill $(lsof -t -i:7860)` then `docker compose up -d`. |
| `docker compose: command not found` | Install the Compose v2 plugin (separate from legacy `docker-compose`). |
| 401 from cloud route | Set `NVIDIA_API_KEY` in `.env` and restart the container. |
