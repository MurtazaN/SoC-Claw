"""Tests for session/password authentication.

Targets ``blue_lantern.backend.auth``. The module keeps ``_users`` and
``_sessions`` as globals; the autouse ``reset_auth_state`` fixture in
``conftest.py`` clears them before/after every test, so each test starts clean.
"""

from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from blue_lantern.backend import auth


def _make_request(cookies: dict | None = None) -> Request:
    """Build a minimal Starlette Request, optionally carrying cookies."""
    headers = []
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers.append((b"cookie", cookie_str.encode()))
    return Request({"type": "http", "headers": headers})


# ──────────────────────── authenticate ────────────────────────


class TestAuthenticate:
    def test_correct_password_default_account(self):
        # Empty BLUE_LANTERN_USERS → lazy-loads the default analyst/analyst account.
        assert auth.authenticate("analyst", "analyst") is True

    def test_wrong_password(self):
        assert auth.authenticate("analyst", "wrong-password") is False

    def test_unknown_user(self):
        assert auth.authenticate("nobody", "analyst") is False


# ──────────────────────── password hashing ────────────────────────


class TestPasswordHashing:
    def test_round_trip(self):
        h = auth._hash_password("s3cret")
        assert auth._verify_password("s3cret", h) is True

    def test_wrong_password_fails(self):
        h = auth._hash_password("s3cret")
        assert auth._verify_password("not-it", h) is False

    def test_malformed_hash_returns_false_not_raises(self):
        # A non-bcrypt string makes checkpw raise; _verify_password must swallow it.
        assert auth._verify_password("anything", "not-a-valid-bcrypt-hash") is False


# ──────────────────────── _load_users ────────────────────────


class TestLoadUsers:
    def test_parses_multiple_users(self, monkeypatch):
        monkeypatch.setenv("BLUE_LANTERN_USERS", "alice:hash1,bob:hash2")
        auth._load_users()
        assert auth._users == {"alice": "hash1", "bob": "hash2"}

    def test_trims_whitespace_and_skips_malformed_entries(self, monkeypatch):
        monkeypatch.setenv("BLUE_LANTERN_USERS", "  alice : hash1 , garbage , bob:hash2")
        auth._load_users()
        assert auth._users == {"alice": "hash1", "bob": "hash2"}

    def test_empty_env_creates_default_account(self, monkeypatch):
        monkeypatch.delenv("BLUE_LANTERN_USERS", raising=False)
        auth._load_users()
        assert "analyst" in auth._users
        assert auth._verify_password("analyst", auth._users["analyst"]) is True


# ──────────────────────── sessions ────────────────────────


class TestSessions:
    def test_create_and_get(self):
        sid = auth.create_session("alice")
        session = auth.get_session(sid)
        assert session is not None
        assert session["username"] == "alice"

    def test_distinct_ids(self):
        assert auth.create_session("alice") != auth.create_session("alice")

    def test_destroy(self):
        sid = auth.create_session("alice")
        auth.destroy_session(sid)
        assert auth.get_session(sid) is None

    def test_unknown_session(self):
        assert auth.get_session("does-not-exist") is None

    def test_expired_session_is_none_and_evicted(self):
        sid = auth.create_session("alice")
        # Backdate creation past the max age so get_session treats it as expired.
        auth._sessions[sid]["created"] = datetime.now(timezone.utc) - timedelta(
            seconds=auth.SESSION_MAX_AGE + 1
        )
        assert auth.get_session(sid) is None
        assert sid not in auth._sessions  # expired sessions are purged


# ──────────────────────── get_current_user ────────────────────────


class TestGetCurrentUser:
    def test_no_cookie_returns_none(self):
        assert auth.get_current_user(_make_request()) is None

    def test_valid_cookie_returns_username(self):
        sid = auth.create_session("alice")
        request = _make_request({auth.SESSION_COOKIE: sid})
        assert auth.get_current_user(request) == "alice"

    def test_bogus_cookie_returns_none(self):
        request = _make_request({auth.SESSION_COOKIE: "not-a-real-session"})
        assert auth.get_current_user(request) is None
