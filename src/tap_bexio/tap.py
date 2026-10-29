"""Bexio tap class."""

from __future__ import annotations

from singer_sdk import Tap
from singer_sdk import typing as th

from tap_bexio.client import (
    DEFAULT_API_URL,
    DEFAULT_PAGE_SIZE,
    DEFAULT_TIMEZONE,
    FORBIDDEN_FAIL,
    FORBIDDEN_SKIP,
    MAX_PAGE_SIZE,
    BexioStream,
)
from tap_bexio.streams import STREAM_TYPES


class TapBexio(Tap):
    """Singer tap for the Bexio API."""

    name = "tap-bexio"

    config_jsonschema = th.PropertiesList(
        th.Property(
            "auth_token",
            th.StringType,
            required=True,
            secret=True,
            title="Access Token",
            description="Bexio Personal Access Token or OAuth access token.",
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
            description="IANA timezone of Bexio's offset-less timestamps (company timezone).",
        ),
        th.Property(
            "forbidden_stream_behavior",
            th.StringType(allowed_values=[FORBIDDEN_SKIP, FORBIDDEN_FAIL]),
            default=FORBIDDEN_SKIP,
            title="Forbidden Stream Behavior",
            description=(
                "What to do when Bexio answers 403 (missing scope or inactive module): "
                "'skip' logs a warning and continues, 'fail' stops the sync."
            ),
        ),
    ).to_dict()

    def discover_streams(self) -> list[BexioStream]:
        """Return a list of discovered streams."""
        return [stream_type(self) for stream_type in STREAM_TYPES]


if __name__ == "__main__":
    TapBexio.cli()
