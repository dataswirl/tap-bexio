"""Config is parsed once, at the tap boundary."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from tap_bexio.config import (
    DEFAULT_OAUTH_TOKEN_URL,
    BexioConfig,
    ForbiddenBehavior,
    OAuthCredentials,
    TokenAuth,
)


def test_defaults():
    config = BexioConfig.parse({"auth_token": "t"})
    assert config == BexioConfig(
        auth=TokenAuth("t"),
        api_url="https://api.bexio.com",
        user_agent=None,
        page_size=500,
        timezone=ZoneInfo("Europe/Zurich"),
        start_date=None,
        forbidden=ForbiddenBehavior.SKIP,
    )


def test_parses_every_setting():
    config = BexioConfig.parse(
        {
            "auth_token": "t",
            "api_url": "https://example.test/",
            "user_agent": "me",
            "page_size": 50,
            "timezone": "Europe/Bucharest",
            "start_date": "2024-01-15T00:00:00Z",
            "forbidden_stream_behavior": "fail",
        }
    )
    assert config.api_url == "https://example.test"
    assert config.user_agent == "me"
    assert config.page_size == 50
    assert config.timezone == ZoneInfo("Europe/Bucharest")
    assert config.start_date == dt.datetime(2024, 1, 15, tzinfo=dt.UTC)
    assert config.forbidden is ForbiddenBehavior.FAIL


def test_start_date_without_offset_is_utc():
    config = BexioConfig.parse({"auth_token": "t", "start_date": "2024-01-15"})
    assert config.start_date == dt.datetime(2024, 1, 15, tzinfo=dt.UTC)


def test_unknown_timezone_is_rejected():
    with pytest.raises(ValueError, match="Mars/Olympus"):
        BexioConfig.parse({"auth_token": "t", "timezone": "Mars/Olympus"})


def test_tap_rejects_unknown_timezone_at_startup(make_tap):
    with pytest.raises(ValueError, match="Mars/Olympus"):
        make_tap(timezone="Mars/Olympus")


OAUTH = {"client_id": "id", "client_secret": "secret", "refresh_token": "refresh"}


def test_oauth_credentials():
    config = BexioConfig.parse(OAUTH)
    assert config.auth == OAuthCredentials("id", "secret", "refresh", DEFAULT_OAUTH_TOKEN_URL)


def test_oauth_token_url_can_be_overridden():
    config = BexioConfig.parse({**OAUTH, "oauth_token_url": "https://idp.test/token"})
    assert isinstance(config.auth, OAuthCredentials)
    assert config.auth.token_url == "https://idp.test/token"


def test_token_and_oauth_together_are_rejected():
    with pytest.raises(ValueError, match="not both"):
        BexioConfig.parse({"auth_token": "t", **OAUTH})


def test_no_credentials_are_rejected():
    with pytest.raises(ValueError, match="Missing client_id, client_secret, refresh_token"):
        BexioConfig.parse({})


def test_incomplete_oauth_names_missing_keys():
    with pytest.raises(ValueError, match="Missing refresh_token\\."):
        BexioConfig.parse({"client_id": "id", "client_secret": "secret"})


def test_tap_rejects_missing_credentials_at_startup(make_tap):
    with pytest.raises(ValueError, match="Missing"):
        make_tap(auth_token=None)
