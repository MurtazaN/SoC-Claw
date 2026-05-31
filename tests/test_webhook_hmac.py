"""Tests for the SIEM webhook HMAC signature verification.

Targets ``verify_hmac`` in
``blue_lantern.backend.routes.siem_webhook`` — the ingestion auth boundary.
"""

import hashlib
import hmac
from datetime import datetime, timezone

import pytest

from blue_lantern.backend.routes.siem_webhook import verify_hmac

SECRET = "test-shared-secret"


def _now_ts() -> str:
    return str(int(datetime.now(timezone.utc).timestamp()))


def _sign(body: bytes, secret: str, ts: str) -> str:
    """Compute the signature exactly as verify_hmac expects it."""
    return hmac.new(
        secret.encode(), f"{ts}.{body.decode()}".encode(), hashlib.sha256
    ).hexdigest()


class TestVerifyHmac:
    def test_valid_signature_passes(self):
        body = b'{"alert": "x"}'
        ts = _now_ts()
        sig = _sign(body, SECRET, ts)
        assert verify_hmac(body, sig, SECRET, ts) is True

    def test_tampered_body_fails(self):
        ts = _now_ts()
        sig = _sign(b'{"alert": "x"}', SECRET, ts)
        # Same signature, different body → mismatch.
        assert verify_hmac(b'{"alert": "TAMPERED"}', sig, SECRET, ts) is False

    def test_wrong_secret_fails(self):
        body = b'{"alert": "x"}'
        ts = _now_ts()
        sig = _sign(body, "the-wrong-secret", ts)
        assert verify_hmac(body, sig, SECRET, ts) is False

    def test_old_timestamp_fails(self):
        body = b'{"alert": "x"}'
        # 10 minutes old — beyond the 5-minute replay window.
        ts = str(int(datetime.now(timezone.utc).timestamp()) - 600)
        sig = _sign(body, SECRET, ts)
        assert verify_hmac(body, sig, SECRET, ts) is False

    def test_non_numeric_timestamp_fails(self):
        body = b'{"alert": "x"}'
        assert verify_hmac(body, "anything", SECRET, "not-a-number") is False

    @pytest.mark.xfail(
        strict=True,
        reason="verify_hmac has no lower bound on timestamp age; far-future "
        "timestamps are currently accepted. Remove this marker once fixed.",
    )
    def test_future_timestamp_should_be_rejected(self):
        body = b'{"alert": "x"}'
        # 1 hour in the future — a valid signature here should still be refused.
        ts = str(int(datetime.now(timezone.utc).timestamp()) + 3600)
        sig = _sign(body, SECRET, ts)
        assert verify_hmac(body, sig, SECRET, ts) is False
