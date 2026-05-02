"""OpenAI-compatible async client factory and model configuration.

URLs and credentials are read from the environment so the same code
runs on host, in Docker, and in production unchanged.
"""

import os

from dotenv import load_dotenv
from openai import AsyncOpenAI

# Populate os.environ from a .env file if one is present.  In production
# (k8s, CI), env vars are injected by the orchestrator and this is a no-op.
load_dotenv()


MODEL_NAME = os.environ.get(
    "SOC_CLAW_LOCAL_MODEL",
    "phi4-mini:3.8b",
)


def get_client(route: str = "local") -> AsyncOpenAI:
    """Get an OpenAI-compatible async client for the given route.

    URLs and credentials are read from the environment so the same code
    runs on host, in NemoClaw, and in production unchanged.
    """
    if route == "local":
        return AsyncOpenAI(
            base_url=os.environ.get(
                "SOC_CLAW_DOCKER_INFERENCE_URL",
                "http://localhost:8000/v1",
            ),
            api_key=os.environ.get("OPENAI_API_KEY", "not-needed"),
        )

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Cloud route requested but OPENROUTER_API_KEY is not set. "
            "Either set it in your .env / orchestrator secrets, or "
            "constrain the privacy router so no prompt routes to cloud."
        )
    return AsyncOpenAI(
        base_url=os.environ.get(
            "SOC_CLAW_INFERENCE_URL",
            "https://openrouter.ai/api/v1",
        ),
        api_key=api_key,
    )


def guided_json_kwargs(schema_class, route: str) -> dict:
    """Build ``extra_body`` kwargs for vLLM guided-JSON decoding.

    Only applies on the ``local`` route where the backend is vLLM.
    Cloud endpoints (e.g. Nvidia API) don't support the ``guided_json``
    extension, so we return an empty dict and let the caller fall back
    to regex-based ``extract_json`` parsing.
    """
    if route != "local":
        return {}
    return {"extra_body": {"guided_json": schema_class.model_json_schema()}}
