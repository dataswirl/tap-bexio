"""Bexio tap class."""

from __future__ import annotations

import typing as t
from functools import cached_property

from singer_sdk import Tap
from singer_sdk import typing as th

from tap_bexio.auth import make_authenticator
from tap_bexio.config import (
    DEFAULT_API_URL,
    DEFAULT_OAUTH_TOKEN_URL,
    DEFAULT_PAGE_SIZE,
    DEFAULT_TIMEZONE,
    MAX_PAGE_SIZE,
    BexioConfig,
    ForbiddenBehavior,
)
from tap_bexio.streams import STREAM_TYPES

if t.TYPE_CHECKING:
    from singer_sdk.authenticators import APIAuthenticatorBase

    from tap_bexio.client import BexioStream


#: The tap's own settings (the SDK adds its built-in ones to ``config_jsonschema``).
SETTINGS = th.PropertiesList(
    th.Property(
        "auth_token",
        th.StringType,
        secret=True,
        title="Access Token",
        description=(
            "Bexio Personal Access Token. Leave empty when using client_id, "
            "client_secret and refresh_token."
        ),
    ),
    th.Property(
        "client_id",
        th.StringType,
        title="OAuth Client ID",
        description="Client ID of the bexio developer portal app (OAuth).",
    ),
    th.Property(
        "client_secret",
        th.StringType,
        secret=True,
        title="OAuth Client Secret",
        description="Client secret of the bexio developer portal app (OAuth).",
    ),
    th.Property(
        "refresh_token",
        th.StringType,
        secret=True,
        title="OAuth Refresh Token",
        description=(
            "Offline refresh token, exchanged for an access token on every run. "
            "Get one with tap-bexio-auth."
        ),
    ),
    th.Property(
        "oauth_token_url",
        th.StringType,
        default=DEFAULT_OAUTH_TOKEN_URL,
        title="OAuth Token URL",
        description="bexio OpenID Connect token endpoint.",
    ),
    th.Property(
        "start_date",
        th.DateTimeType,
        title="Start Date",
        description=(
            "Earliest updated_at to sync for incremental streams, and lower bound for "
            "the journal and payroll absences. Without it, the first sync reads everything."
        ),
    ),
    th.Property(
        "api_url",
        th.StringType,
        default=DEFAULT_API_URL,
        title="API URL",
        description="Base URL of the Bexio API.",
    ),
    th.Property(
        "user_agent",
        th.StringType,
        title="User Agent",
        description="Optional User-Agent header sent with every request.",
    ),
    th.Property(
        "page_size",
        th.IntegerType(minimum=1, maximum=MAX_PAGE_SIZE),
        default=DEFAULT_PAGE_SIZE,
        title="Page Size",
        description="Records per request (capped per endpoint; 2000 max).",
    ),
    th.Property(
        "timezone",
        th.StringType,
        default=DEFAULT_TIMEZONE,
        title="Timezone",
        description=(
            "IANA timezone of Bexio's offset-less timestamps (company timezone). "
            "All timestamps are emitted in this timezone."
        ),
    ),
    th.Property(
        "forbidden_stream_behavior",
        th.StringType(allowed_values=list(ForbiddenBehavior)),
        default=ForbiddenBehavior.SKIP.value,
        title="Forbidden Stream Behavior",
        description=(
            "What to do when Bexio answers 403 (missing scope or inactive module): "
            "'skip' logs a warning and continues, 'fail' stops the sync."
        ),
    ),
)


class TapBexio(Tap):
    """Singer tap for the Bexio API."""

    name = "tap-bexio"

    config_jsonschema = SETTINGS.to_dict()

    @cached_property
    def settings(self) -> BexioConfig:
        """Return the parsed settings."""
        return BexioConfig.parse(self.config)

    @cached_property
    def authenticator(self) -> APIAuthenticatorBase:
        """Return the authenticator shared by all streams (one token refresh per run)."""
        return make_authenticator(self.settings.auth)

    def discover_streams(self) -> list[BexioStream]:
        """Return a list of discovered streams, after checking the settings."""
        _ = self.settings
        return [stream_type(self) for stream_type in STREAM_TYPES]


if __name__ == "__main__":
    TapBexio.cli()
