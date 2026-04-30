# syntax=docker/dockerfile:1.6
# =============================================================================
# SOC-Claw — application image.
#
# Plain Python base. vLLM is NOT bundled here; it runs on the host (or as a
# separate compose service in a follow-up). Everything routing-related is
# read from env at runtime — see soc_claw/utils.py:get_client.
#
# Builds use uv with a frozen lockfile so dep versions are reproducible.
# =============================================================================

FROM python:3.11-slim

# Pull uv from its official image — small static binary, no Python deps to manage.
COPY --from=ghcr.io/astral-sh/uv:0.5.5 /uv /usr/local/bin/uv

WORKDIR /app

# Deps layer first (cache-stable across source changes). uv.lock pins every
# transitive dep; uv export emits a pip-installable requirements list.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-hashes --no-emit-project --format requirements-txt > /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Application source.
COPY soc_claw/ /app/soc_claw/

# Install the package itself (so `python -m soc_claw.backend.server` resolves
# without sys.path tricks; --no-deps because deps were installed above) and
# set up a non-root runtime user, in one layer.
RUN uv pip install --system --no-cache --no-deps -e . \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /app/soc_claw/benchmark/results \
    && chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1 \
    SOC_CLAW_MODEL=nvidia/Nemotron-Mini-4B-Instruct \
    BENCHMARK_OUTPUT_DIR=/app/soc_claw/benchmark/results

EXPOSE 7860

CMD ["python", "-m", "soc_claw.backend.server"]
