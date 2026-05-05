"""Test fixtures for SIEM connector tests."""

import pytest
import asyncio
from redis.asyncio import Redis


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def redis_client():
    """Create Redis client for testing."""
    # Use localhost Redis for testing
    redis = Redis(host="localhost", port=6379, db=15, decode_responses=True)

    try:
        # Test connection
        await redis.ping()
        yield redis
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")
    finally:
        # Clean up test database
        try:
            await redis.flushdb()
        except Exception:
            pass
        await redis.close()
