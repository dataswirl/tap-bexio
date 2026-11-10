"""Tap settings, parsed once from the raw config."""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import typing as t
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if t.TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_API_URL = "https://api.bexio.com"
DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 2000
DEFAULT_TIMEZONE = "Europe/Zurich"
DEFAULT_OUTPUT_TIMEZONE = "UTC"
OIDC_BASE_URL = "https://auth.bexio.com/realms/bexio/protocol/openid-connect"
DEFAULT_OAUTH_TOKEN_URL = f"{OIDC_BASE_URL}/token"
#: Settings that together select OAuth instead of ``auth_token``.
OAUTH_KEYS = ("client_id", "client_secret", "refresh_token")


class ForbiddenBehavior(enum.StrEnum):
    """What to do when Bexio answers 403 for a stream."""

    SKIP = "skip"
    FAIL = "fail"


@dataclasses.dataclass(frozen=True)
class TokenAuth:
    """A static Bearer token (Personal Access Token)."""

    token: str


@dataclasses.dataclass(frozen=True)
class OAuthCredentials:
    """OAuth app credentials and the refresh token they exchange for access tokens."""

    client_id: str
    client_secret: str
    refresh_token: str
    token_url: str = DEFAULT_OAUTH_TOKEN_URL


@dataclasses.dataclass(frozen=True)
class BexioConfig:
    """Validated tap settings."""

    auth: TokenAuth | OAuthCredentials
    api_url: str = DEFAULT_API_URL
    user_agent: str | None = None
    page_size: int = DEFAULT_PAGE_SIZE
    #: Company timezone: Bexio's offset-less timestamps are in it, and it decides the day of dates.
    timezone: ZoneInfo = dataclasses.field(default_factory=lambda: ZoneInfo(DEFAULT_TIMEZONE))
    #: Timezone every ``date-time`` is emitted in.
    output_timezone: ZoneInfo = dataclasses.field(
        default_factory=lambda: ZoneInfo(DEFAULT_OUTPUT_TIMEZONE)
    )
    #: Timezone-aware; a value without an offset is taken as UTC.
    start_date: dt.datetime | None = None
    forbidden: ForbiddenBehavior = ForbiddenBehavior.SKIP

    @classmethod
    def parse(cls, config: Mapping[str, t.Any]) -> BexioConfig:
        """Return the settings in ``config`` (already checked against the JSON schema)."""
        return cls(
            auth=_auth(config),
            api_url=config.get("api_url", DEFAULT_API_URL).rstrip("/"),
            user_agent=config.get("user_agent") or None,
            page_size=config.get("page_size", DEFAULT_PAGE_SIZE),
            timezone=_zone(config.get("timezone", DEFAULT_TIMEZONE)),
            output_timezone=_zone(config.get("output_timezone", DEFAULT_OUTPUT_TIMEZONE)),
            start_date=_aware(config.get("start_date")),
            forbidden=ForbiddenBehavior(
                config.get("forbidden_stream_behavior", ForbiddenBehavior.SKIP)
            ),
        )


def _auth(config: Mapping[str, t.Any]) -> TokenAuth | OAuthCredentials:
    token = config.get("auth_token")
    oauth = {key: config.get(key) for key in OAUTH_KEYS}
    if token and any(oauth.values()):
        msg = f"Set either auth_token or {', '.join(OAUTH_KEYS)}, not both."
        raise ValueError(msg)
    if token:
        return TokenAuth(token)
    if missing := [key for key, value in oauth.items() if not value]:
        msg = f"Missing {', '.join(missing)}. Set auth_token, or all of {', '.join(OAUTH_KEYS)}."
        raise ValueError(msg)
    return OAuthCredentials(
        client_id=config["client_id"],
        client_secret=config["client_secret"],
        refresh_token=config["refresh_token"],
        token_url=config.get("oauth_token_url", DEFAULT_OAUTH_TOKEN_URL),
    )


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        msg = f"Unknown timezone {name!r}; use an IANA name such as {DEFAULT_TIMEZONE!r}."
        raise ValueError(msg) from exc


def _aware(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
