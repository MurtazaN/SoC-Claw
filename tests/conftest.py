"""Shared pytest fixtures for the Blue Lantern test suite.

Renamed from ``conftest_siem.py`` so pytest auto-discovers it (only files
named exactly ``conftest.py`` are loaded). The manual ``event_loop`` override
was dropped — current ``pytest-asyncio`` supplies its own.
"""

import pytest


@pytest.fixture(autouse=True)
def reset_auth_state():
    """Clear the auth module's in-memory user/session stores around each test.

    ``blue_lantern.backend.auth`` keeps ``_users`` and ``_sessions`` as module
    globals, and ``authenticate()`` lazy-loads ``_users`` on first use. Without
    this reset, state would leak across tests. Imported lazily so non-auth tests
    don't pay the bcrypt import cost at collection time.
    """
    from blue_lantern.backend import auth

    auth._users.clear()
    auth._sessions.clear()
    yield
    auth._users.clear()
    auth._sessions.clear()
