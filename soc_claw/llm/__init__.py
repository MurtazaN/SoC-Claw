"""SOC-Claw LLM subsystem.

Provides the shared LLM call scaffold, OpenAI-compatible client factory,
guided-JSON helpers, and JSON extraction utilities.

Public API (re-exported here for convenience)::

    from soc_claw.llm import call_llm, get_client, extract_json
"""

from soc_claw.llm.caller import call_llm
from soc_claw.llm.client import MODEL_NAME, get_client, guided_json_kwargs
from soc_claw.llm.json_extract import extract_json

__all__ = [
    "call_llm",
    "extract_json",
    "get_client",
    "guided_json_kwargs",
    "MODEL_NAME",
]
