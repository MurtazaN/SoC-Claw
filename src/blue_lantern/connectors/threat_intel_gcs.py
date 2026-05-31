"""Threat-intel dataset reader.

Downloads the bulk threat-intelligence dataset blob from GCS and validates
each row against ``ThreatIntelEntry``. Mirrors the alert reader's pattern
(``get_gcs_client`` + ``download_as_text`` + skip-and-log validation) but
targets the threat-intel schema instead of ``Alert``.
"""

import logging

from pydantic import ValidationError

from blue_lantern.connectors.alert_parser import parse_blob
from blue_lantern.connectors.gcs_reader import get_gcs_client
from blue_lantern.schemas import ThreatIntelEntry

logger = logging.getLogger("blue-lantern.threat_intel_gcs")


def download_threat_intel(bucket_name: str, object_name: str) -> list[dict]:
    """Download and validate the bulk threat-intel dataset from GCS.

    Returns validated ``ThreatIntelEntry`` dicts. Rows that fail schema
    validation are logged and skipped so one bad row doesn't sink the whole
    dataset. Raises if the blob cannot be fetched at all, letting the caller
    fall back to its last-good index.
    """
    client = get_gcs_client()
    if client is None:
        raise RuntimeError("GCS client unavailable")

    content = client.bucket(bucket_name).blob(object_name).download_as_text()

    entries: list[dict] = []
    for i, row in enumerate(parse_blob(content, object_name)):
        try:
            entries.append(ThreatIntelEntry.model_validate(row).model_dump())
        except ValidationError as exc:
            logger.error(
                "Skipping invalid threat-intel row %s[%d]: %s", object_name, i, exc
            )

    logger.info(
        "Loaded %d threat-intel entries from gs://%s/%s",
        len(entries),
        bucket_name,
        object_name,
    )
    return entries
