"""Tests for batch API endpoint."""

import pytest
import json
import io
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from soc_claw.backend.server import app
from soc_claw.connectors.job_manager import JobStatus


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_redis():
    """Create mock Redis client."""
    redis = AsyncMock()
    redis.hset = AsyncMock()
    redis.hgetall = AsyncMock()
    redis.hincrby = AsyncMock()
    return redis


@pytest.fixture
def mock_job_manager(mock_redis):
    """Create mock job manager."""
    job_manager = AsyncMock()
    job_manager.create_job = AsyncMock(return_value="job-123")
    job_manager.get_job = AsyncMock()
    job_manager.update_job_status = AsyncMock()
    job_manager.increment_processed = AsyncMock()
    job_manager.increment_failed = AsyncMock()
    job_manager.set_results_path = AsyncMock()
    return job_manager


@pytest.fixture
def mock_kafka_producer():
    """Create mock Kafka producer."""
    producer = AsyncMock()
    producer.send_and_wait = AsyncMock()
    return producer


class TestBatchAPI:
    """Tests for batch API endpoint."""

    def test_upload_jsonl_success(self, client, mock_job_manager, mock_kafka_producer):
        """Test successful JSONL upload."""
        jsonl_content = """{"id":"ALT-001","timestamp":"2026-04-25T14:32:00Z","hostname":"DC-FINANCE-01","rule_name":"Test Rule"}
{"id":"ALT-002","timestamp":"2026-04-25T14:33:00Z","hostname":"DC-FINANCE-02","rule_name":"Test Rule"}"""

        file = io.BytesIO(jsonl_content.encode())

        with patch("soc_claw.backend.routes.batch_api.get_job_manager", return_value=mock_job_manager):
            with patch("soc_claw.backend.routes.batch_api.get_kafka_producer", return_value=mock_kafka_producer):
                response = client.post(
                    "/api/batch/upload",
                    files={"file": ("test.jsonl", file, "application/jsonl")}
                )

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "success"
                assert "job_id" in data
                assert data["job_id"] == "job-123"

    def test_upload_jsonl_invalid_json(self, client, mock_job_manager):
        """Test JSONL upload with invalid JSON."""
        jsonl_content = """{"id":"ALT-001","timestamp":"2026-04-25T14:32:00Z","hostname":"DC-FINANCE-01","rule_name":"Test Rule"}
invalid json line"""

        file = io.BytesIO(jsonl_content.encode())

        with patch("soc_claw.backend.routes.batch_api.get_job_manager", return_value=mock_job_manager):
            response = client.post(
                "/api/batch/upload",
                files={"file": ("test.jsonl", file, "application/jsonl")}
            )

            assert response.status_code == 400
            data = response.json()
            assert data["status"] == "error"

    def test_upload_jsonl_empty_file(self, client):
        """Test JSONL upload with empty file."""
        file = io.BytesIO(b"")

        response = client.post(
            "/api/batch/upload",
            files={"file": ("test.jsonl", file, "application/jsonl")}
        )

        assert response.status_code == 400
        data = response.json()
        assert data["status"] == "error"

    def test_get_job_status(self, client, mock_job_manager):
        """Test getting job status."""
        mock_job_manager.get_job.return_value = {
            "status": "processing",
            "filename": "test.jsonl",
            "total_alerts": 10,
            "processed_alerts": 5,
            "failed_alerts": 0,
        }

        with patch("soc_claw.backend.routes.batch_api.get_job_manager", return_value=mock_job_manager):
            response = client.get("/api/batch/status/job-123")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "processing"
            assert data["total_alerts"] == 10
            assert data["processed_alerts"] == 5

    def test_get_job_status_not_found(self, client, mock_job_manager):
        """Test getting non-existent job status."""
        mock_job_manager.get_job.return_value = None

        with patch("soc_claw.backend.routes.batch_api.get_job_manager", return_value=mock_job_manager):
            response = client.get("/api/batch/status/non-existent")

            assert response.status_code == 404
            data = response.json()
            assert data["status"] == "error"

    def test_get_job_results(self, client, mock_job_manager):
        """Test getting job results."""
        mock_job_manager.get_job.return_value = {
            "status": "completed",
            "results_path": "gs://bucket/results/job-123.json",
        }

        with patch("soc_claw.backend.routes.batch_api.get_job_manager", return_value=mock_job_manager):
            response = client.get("/api/batch/results/job-123")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"
            assert "results_path" in data

    def test_get_job_results_not_completed(self, client, mock_job_manager):
        """Test getting results for incomplete job."""
        mock_job_manager.get_job.return_value = {
            "status": "processing",
        }

        with patch("soc_claw.backend.routes.batch_api.get_job_manager", return_value=mock_job_manager):
            response = client.get("/api/batch/results/job-123")

            assert response.status_code == 400
            data = response.json()
            assert data["status"] == "error"

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/api/batch/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
