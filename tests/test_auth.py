"""OAuth: the refresh token is traded for access tokens, shared by all streams."""

from __future__ import annotations

import datetime as dt
import logging
from urllib.parse import parse_qs

import pytest
from responses import matchers
from singer_sdk.exceptions import FatalAPIError

from tap_bexio import auth
from tap_bexio.auth import EXPIRY_MARGIN
from tests.conftest import API

TOKEN_URL = "https://idp.test/token"
OAUTH = {
    "auth_token": None,
    "client_id": "id",
    "client_secret": "secret",
    "refresh_token": "refresh",
    "oauth_token_url": TOKEN_URL,
}


def token(access: str = "access-1", **extra: object) -> dict:
    return {"access_token": access, "expires_in": 3600, "token_type": "Bearer", **extra}


def records(tap, name: str) -> list[dict]:
    return list(tap.streams[name].get_records(None))


def test_token_mode_sends_the_token_as_is(make_tap, mocked):
    mocked.get(
        f"{API}/2.0/country",
        json=[],
        match=[matchers.header_matcher({"Authorization": "Bearer token"})],
    )
    records(make_tap(), "countries")
    assert len(mocked.calls) == 1


def test_refresh_token_is_exchanged_and_sent_as_bearer(make_tap, mocked):
    mocked.post(TOKEN_URL, json=token())
    mocked.get(
        f"{API}/2.0/country",
        json=[{"id": 1}],
        match=[matchers.header_matcher({"Authorization": "Bearer access-1"})],
    )
    assert records(make_tap(**OAUTH), "countries") == [{"id": 1}]
    assert parse_qs(mocked.calls[0].request.body) == {
        "grant_type": ["refresh_token"],
        "refresh_token": ["refresh"],
        "client_id": ["id"],
        "client_secret": ["secret"],
    }


def test_streams_share_one_token_exchange(make_tap, mocked):
    mocked.post(TOKEN_URL, json=token())
    mocked.get(f"{API}/2.0/country", json=[])
    mocked.get(f"{API}/2.0/language", json=[])
    tap = make_tap(**OAUTH)
    records(tap, "countries")
    records(tap, "languages")
    assert [call.request.url for call in mocked.calls].count(TOKEN_URL) == 1


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

    def advance(self, seconds: float) -> None:
        self.now += dt.timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(auth, "_now", lambda: clock.now)
    return clock


def sent_tokens(mocked) -> list[str]:
    """Return the Authorization header of every API request, in order."""
    return [
        call.request.headers["Authorization"]
        for call in mocked.calls
        if call.request.url.startswith(API)
    ]


def sync_twice(tap, clock, seconds: float) -> None:
    """Read a stream, let ``seconds`` pass, and read it again."""
    records(tap, "countries")
    clock.advance(seconds)
    records(tap, "countries")


def refresh_bodies(mocked) -> list[dict]:
    return [parse_qs(c.request.body) for c in mocked.calls if c.request.url == TOKEN_URL]


def test_token_is_reused_until_just_before_the_refresh_time(make_tap, clock, mocked):
    mocked.post(TOKEN_URL, json=token("access-1"))
    mocked.get(f"{API}/2.0/country", json=[])
    sync_twice(make_tap(**OAUTH), clock, 3600 - EXPIRY_MARGIN - 1)
    assert sent_tokens(mocked) == ["Bearer access-1", "Bearer access-1"]


def test_token_is_refreshed_at_the_refresh_time(make_tap, clock, mocked):
    mocked.post(TOKEN_URL, json=token("access-1"))
    mocked.post(TOKEN_URL, json=token("access-2"))
    mocked.get(f"{API}/2.0/country", json=[])
    sync_twice(make_tap(**OAUTH), clock, 3600 - EXPIRY_MARGIN)
    assert sent_tokens(mocked) == ["Bearer access-1", "Bearer access-2"]


def test_missing_expires_in_assumes_one_hour(make_tap, clock, mocked):
    mocked.post(TOKEN_URL, json={"access_token": "access-1"})
    mocked.post(TOKEN_URL, json={"access_token": "access-2"})
    mocked.get(f"{API}/2.0/country", json=[])
    tap = make_tap(**OAUTH)
    sync_twice(tap, clock, 3600 - EXPIRY_MARGIN - 1)
    clock.advance(1)
    records(tap, "countries")
    assert sent_tokens(mocked) == ["Bearer access-1"] * 2 + ["Bearer access-2"]


def test_rotated_refresh_token_is_used_and_reported(make_tap, clock, mocked, caplog):
    mocked.post(TOKEN_URL, json=token("access-1", refresh_token="refresh-2"))
    mocked.post(TOKEN_URL, json=token("access-2"))
    mocked.get(f"{API}/2.0/country", json=[])
    with caplog.at_level(logging.WARNING):
        sync_twice(make_tap(**OAUTH), clock, 3600)
    assert [body["refresh_token"] for body in refresh_bodies(mocked)] == [
        ["refresh"],
        ["refresh-2"],
    ]
    assert "new refresh token" in caplog.text


def test_unchanged_refresh_token_is_not_reported(make_tap, mocked, caplog):
    mocked.post(TOKEN_URL, json=token(refresh_token="refresh"))
    mocked.get(f"{API}/2.0/country", json=[])
    with caplog.at_level(logging.WARNING):
        records(make_tap(**OAUTH), "countries")
    assert "new refresh token" not in caplog.text


def test_refused_refresh_token_is_fatal(make_tap, mocked):
    mocked.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    with pytest.raises(FatalAPIError, match=r"HTTP 400.*invalid_grant.*tap-bexio-auth"):
        records(make_tap(**OAUTH), "countries")


def test_unauthorized_names_oauth_settings(make_tap, mocked):
    mocked.post(TOKEN_URL, json=token())
    mocked.get(f"{API}/2.0/country", status=401)
    with pytest.raises(FatalAPIError, match="refresh_token"):
        records(make_tap(**OAUTH), "countries")
