"""OpenAI-compatible async client factory driven by routing.yaml.

Loads provider definitions, per-agent defaults, content-based overrides,
and an optional force block — all from ``soc_claw/config/routing.yaml``.
"""

import os
import re
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

CONFIG_PATH = Path(__file__).parent.parent / "config" / "routing.yaml"


@lru_cache(maxsize=1)
def _load_config() -> dict:
    """Load and cache the routing config from disk."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _client_for(cfg: dict, provider_name: str) -> AsyncOpenAI:
    """Build an AsyncOpenAI client from a provider entry in the config."""
    provider = cfg["providers"][provider_name]
    base_url = provider["base_url"]
    api_key = os.environ.get(provider["api_key_env"], "dummy-key")
    return AsyncOpenAI(base_url=base_url, api_key=api_key)


def select_endpoint(agent: str, prompt: str) -> tuple[AsyncOpenAI, str, str]:
    """Return (client, model_name, reason) for the given agent and prompt.

    Resolution order:
      1. ``force`` block
      2. First matching ``content_routes`` rule
      3. Per-agent default from ``agents``
    """
    cfg = _load_config()

    # 1 — Force override
    force_provider = cfg["force"]["provider"]
    force_model = cfg["force"]["model"]
    if force_provider and force_model:
        return _client_for(cfg, force_provider), force_model, "force override"

    # 2 — Content-based rule (first match wins)
    for rule in cfg["content_routes"]:
        if re.search(rule["when"], prompt):
            return _client_for(cfg, rule["provider"]), rule["model"], f"content: {rule['when']}"

    # 3 — Agent default
    agent_cfg = cfg["agents"][agent]
    return _client_for(cfg, agent_cfg["provider"]), agent_cfg["model"], f"agent default: {agent}"


def guided_json_kwargs(schema_class, provider: str) -> dict:
    """Build ``extra_body`` kwargs for vLLM guided-JSON decoding.

    Only applies when the provider is a local vLLM instance.
    Cloud endpoints don't support the ``guided_json`` extension.
    """
    if "vllm" not in provider:
        return {}
    return {"extra_body": {"guided_json": schema_class.model_json_schema()}}
