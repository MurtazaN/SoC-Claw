"""Robustly extract JSON from LLM response text.

Handles markdown fences, bare JSON, and regex fallback.  Used by
``blue_lantern.llm.caller._parse_llm_output`` and available as a standalone
utility for any consumer that needs to pull structured data from
free-text LLM output.
"""

import json
import logging
import re

logger = logging.getLogger("blue-lantern.llm.json_extract")


def _first_json_value(text: str):
    """Return the first complete JSON object/array embedded in ``text``.

    Scans for an opening ``{`` or ``[`` and uses ``raw_decode``, which parses
    exactly one value and stops — so trailing prose or a second object
    (e.g. ``{...} note: {...}``) no longer breaks parsing the way a greedy
    ``{.*}`` regex did. Returns ``None`` if no parseable value is found.
    """
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                value, _ = decoder.raw_decode(text[i:])
                return value
            except json.JSONDecodeError:
                continue
    return None


def extract_json(text: str) -> dict:
    """Robustly extract JSON from LLM response text.

    Handles markdown fences, bare JSON, and a first-complete-value fallback.
    """
    # Strip markdown code fences
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.MULTILINE)
    stripped = re.sub(r"\n?```\s*$", "", stripped.strip(), flags=re.MULTILINE)

    # Try direct parse
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Fallback: pull out the first complete JSON value embedded in the text.
    value = _first_json_value(stripped)
    if value is not None:
        return value

    logger.debug("extract_json failed on full text:\n%s", text)
    head = text[:200]
    tail = text[-200:] if len(text) > 400 else ""
    preview = f"{head}...{tail}" if tail else head
    raise ValueError(f"Could not extract valid JSON from LLM response: {preview}")
