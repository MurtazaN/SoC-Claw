"""
GCS Reader Module

Reads SIEM log files from GCS Bucket via GCS API.
"""

import json
import logging
from typing import Optional

from google.cloud import storage
from google.cloud.storage import Client

logger = logging.getLogger("soc-claw.gcs_reader")


def get_gcs_client() -> Optional[Client]:
    """Get GCS client using Application Default Credentials.

    Returns:
        GCS client instance or None if authentication fails
    """
    try:
        return storage.Client()
    except Exception as e:
        logger.error(f"Failed to create GCS client: {e}")
        return None


def list_alerts(bucket_name: str, max_results: int = 30) -> list[dict]:
    """List most recent alert objects from GCS bucket.

    Args:
        bucket_name: GCS bucket name
        max_results: Maximum number of objects to return (default: 30)

    Returns:
        List of object metadata (name, updated, size)
    """
    client = get_gcs_client()
    if not client:
        logger.error("GCS client not available")
        return []

    try:
        bucket = client.bucket(bucket_name)
        blobs = bucket.list_blobs(max_results=max_results, order_by='time_created desc')
        return [{'name': blob.name, 'updated': blob.updated.isoformat(), 'size': blob.size} for blob in blobs]
    except Exception as e:
        logger.error(f"Failed to list alerts from GCS bucket {bucket_name}: {e}")
        return []


def download_alert(bucket_name: str, object_name: str) -> Optional[dict]:
    """Download and parse a single alert from GCS.

    Args:
        bucket_name: GCS bucket name
        object_name: GCS object name

    Returns:
        Parsed alert dict or None if download fails
    """
    client = get_gcs_client()
    if not client:
        logger.error("GCS client not available")
        return None

    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        content = blob.download_as_text()
        return json.loads(content)
    except Exception as e:
        logger.error(f"Failed to download alert {object_name} from GCS bucket {bucket_name}: {e}")
        return None


def download_batch(bucket_name: str, max_results: int = 30) -> list[dict]:
    """Download and parse a batch of alerts from GCS.

    Args:
        bucket_name: GCS bucket name
        max_results: Maximum number of alerts to download (default: 30)

    Returns:
        List of parsed alert dicts
    """
    objects = list_alerts(bucket_name, max_results)
    alerts = []
    for obj in objects:
        alert = download_alert(bucket_name, obj['name'])
        if alert:
            alerts.append(alert)
    logger.info(f"Downloaded {len(alerts)} alerts from GCS bucket {bucket_name}")
    return alerts
