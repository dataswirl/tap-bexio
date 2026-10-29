"""REST client handling, including the Bexio stream base classes."""

from __future__ import annotations

import datetime as dt
import re
import time
import typing as t
from functools import cached_property
from http import HTTPStatus
from importlib.resources import files
from zoneinfo import ZoneInfo

from singer_sdk import SchemaDirectory, StreamSchema
from singer_sdk.authenticators import BearerTokenAuthenticator
from singer_sdk.exceptions import FatalAPIError, RetriableAPIError
from singer_sdk.pagination import SinglePagePaginator
from singer_sdk.streams import RESTStream

from tap_bexio.pagination import BexioOffsetPaginator, BexioPagePaginator

if t.TYPE_CHECKING:
    from collections.abc import Generator, Iterable

    import requests
    from singer_sdk.helpers.types import Context, Record

DEFAULT_API_URL = "https://api.bexio.com"
DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 2000
DEFAULT_TIMEZONE = "Europe/Zurich"
DEFAULT_RATE_LIMIT_WAIT = 60
DEFAULT_RETRY_WAIT = 10
# Pause before the next request once the remaining quota drops to this many requests.
RATE_LIMIT_MIN_REMAINING = 1
FORBIDDEN_SKIP = "skip"
FORBIDDEN_FAIL = "fail"

# Bexio 2.0 timestamps are local (company) time without an offset, e.g. "2019-04-08 13:17:32".
BEXIO_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$")
BEXIO_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

SCHEMAS = SchemaDirectory(files("tap_bexio") / "schemas")


class StreamSkippedError(Exception):
    """Raised to end a stream (or one partition of it) early without failing the sync."""

    def __init__(self, message: str, *, whole_stream: bool) -> None:
        """Store whether the remaining partitions of the stream should be skipped too."""
        super().__init__(message)
        self.whole_stream = whole_stream


class BexioStream(RESTStream[t.Any]):
    """Base stream for the Bexio API."""

    schema = StreamSchema(SCHEMAS)
    records_jsonpath = "$[*]"
    primary_keys = ("id",)
    replication_key = None

    #: Max ``limit`` the endpoint accepts.
    max_page_size: t.ClassVar[int] = MAX_PAGE_SIZE
    #: Static query parameters sent with every request.
    extra_params: t.ClassVar[dict[str, t.Any]] = {}
    #: For parent streams: context key under which each record's ``id`` is passed to children.
    child_context_key: t.ClassVar[str | None] = None

    _skip_remaining = False

    @property
    def url_base(self) -> str:
        """Return the API base URL."""
        return self.config.get("api_url", DEFAULT_API_URL).rstrip("/")

    @cached_property
    def authenticator(self) -> BearerTokenAuthenticator:
        """Return a Bearer token authenticator."""
        return BearerTokenAuthenticator(token=self.config["auth_token"])

    @property
    def http_headers(self) -> dict[str, str]:
        """Return headers sent with every request."""
        headers = {"Accept": "application/json"}
        if user_agent := self.config.get("user_agent"):
            headers["User-Agent"] = user_agent
        return headers

    @property
    def page_size(self) -> int:
        """Return the page size, capped at the endpoint maximum."""
        return min(self.config.get("page_size", DEFAULT_PAGE_SIZE), self.max_page_size)

    @cached_property
    def timezone(self) -> ZoneInfo:
        """Return the timezone of Bexio's offset-less timestamps."""
        return ZoneInfo(self.config.get("timezone", DEFAULT_TIMEZONE))

    @cached_property
    def _datetime_fields(self) -> tuple[str, ...]:
        """Return the top-level properties declared as ``date-time``."""
        properties = self.schema.get("properties", {})
        return tuple(k for k, v in properties.items() if v.get("format") == "date-time")

    def get_url_params(
        self,
        context: Context | None,  # noqa: ARG002
        next_page_token: t.Any | None,  # noqa: ARG002, ANN401
    ) -> dict[str, t.Any]:
        """Return URL query parameters for the request."""
        return dict(self.extra_params)

    def validate_response(self, response: requests.Response) -> None:
        """Map Bexio error statuses to retry, skip or fail."""
        status = response.status_code
        if status != HTTPStatus.TOO_MANY_REQUESTS:
            self._throttle(response)
        if status == HTTPStatus.UNAUTHORIZED:
            msg = f"{self.response_error_message(response)}. Check that auth_token is valid."
            raise FatalAPIError(msg)
        if status == HTTPStatus.FORBIDDEN:
            msg = (
                f"Access to stream '{self.name}' is forbidden ({response.url}). The token "
                "lacks the required scope or the Bexio module is not active."
            )
            if self.config.get("forbidden_stream_behavior", FORBIDDEN_SKIP) == FORBIDDEN_SKIP:
                msg += " Skipping stream."
                raise StreamSkippedError(msg, whole_stream=True)
            msg += " Set forbidden_stream_behavior=skip to skip it."
            raise FatalAPIError(msg)
        if status == HTTPStatus.NOT_FOUND and self.parent_stream_type is not None:
            msg = f"{response.url} not found (deleted during sync?). Skipping."
            raise StreamSkippedError(msg, whole_stream=False)
        super().validate_response(response)

    def _throttle(self, response: requests.Response) -> None:
        """Wait for the rate-limit window to reset when the remaining quota is nearly used up.

        429s are left to the backoff, which already waits for ``RateLimit-Reset``.
        """
        remaining = response.headers.get("RateLimit-Remaining", "")
        reset = response.headers.get("RateLimit-Reset", "")
        if remaining.isdigit() and reset.isdigit() and int(remaining) <= RATE_LIMIT_MIN_REMAINING:
            wait = int(reset) + 1
            self.logger.info("Rate limit nearly used up (%s left), sleeping %ss.", remaining, wait)
            time.sleep(wait)

    def get_records(self, context: Context | None) -> Iterable[dict[str, t.Any]]:
        """Return records, ending early on a skipped stream or partition."""
        if self._skip_remaining:
            return
        try:
            yield from super().get_records(context)
        except StreamSkippedError as exc:
            self.logger.warning("%s", exc)
            self._skip_remaining = exc.whole_stream

    def post_process(self, row: Record, context: Context | None = None) -> Record | None:
        """Normalize local timestamps to ISO 8601 and add parent context keys."""
        for field in self._datetime_fields:
            value = row.get(field)
            if isinstance(value, str) and BEXIO_TIMESTAMP.match(value):
                parsed = dt.datetime.fromisoformat(value).replace(tzinfo=self.timezone)
                row[field] = parsed.isoformat()
        properties = self.schema.get("properties", {})
        for key, value in (context or {}).items():
            if key in properties and row.get(key) is None:
                row[key] = value
        return row

    def get_child_context(self, record: Record, context: Context | None) -> Context | None:
        """Pass the record ``id`` to child streams under ``child_context_key``."""
        if self.child_context_key is None:
            return super().get_child_context(record, context)
        return {self.child_context_key: record["id"]}

    def backoff_wait_generator(self) -> Generator[float, None, None]:
        """Honor Bexio's ``RateLimit-Reset`` header when throttled."""
        return self.backoff_runtime(value=_rate_limit_wait)

    def backoff_max_tries(self) -> int:
        """Return the number of attempts before giving up."""
        return 8


class BexioOffsetStream(BexioStream):
    """Stream for 2.0/3.0 list endpoints paged with ``limit``/``offset``."""

    #: Whether the endpoint accepts a ``limit`` parameter.
    send_limit: t.ClassVar[bool] = True

    def get_new_paginator(self) -> BexioOffsetPaginator:
        """Return a limit/offset paginator."""
        return BexioOffsetPaginator(self.page_size if self.send_limit else None)

    def get_url_params(
        self,
        context: Context | None,
        next_page_token: int | None,
    ) -> dict[str, t.Any]:
        """Return limit/offset query parameters."""
        params = super().get_url_params(context, next_page_token)
        if self.send_limit:
            params["limit"] = self.page_size
        params["offset"] = next_page_token or 0
        return params


class BexioPageStream(BexioStream):
    """Stream for 4.0 list endpoints paged by page number."""

    records_jsonpath = "$.data[*]"
    first_page: t.ClassVar[int] = 1
    page_param: t.ClassVar[str] = "page"
    size_param: t.ClassVar[str] = "limit"

    def get_new_paginator(self) -> BexioPagePaginator:
        """Return a page-number paginator."""
        return BexioPagePaginator(self.page_size, self.first_page)

    def get_url_params(
        self,
        context: Context | None,
        next_page_token: int | None,
    ) -> dict[str, t.Any]:
        """Return page-number query parameters."""
        params = super().get_url_params(context, next_page_token)
        params[self.page_param] = self.first_page if next_page_token is None else next_page_token
        params[self.size_param] = self.page_size
        return params


class BexioUnpagedStream(BexioStream):
    """Stream for endpoints that return everything in one response."""

    def get_new_paginator(self) -> SinglePagePaginator:
        """Return a paginator that stops after the first page."""
        return SinglePagePaginator()


class BexioSearchStream(BexioOffsetStream):
    """Incremental 2.0 stream filtered on ``updated_at`` via ``POST <path>/search``.

    Without a bookmark (no state and no ``start_date``) it reads the plain list endpoint.
    Results are ordered by ``id`` rather than ``updated_at`` so offsets stay stable while
    records change during the sync; the bookmark is therefore committed at the end.
    """

    replication_key = "updated_at"
    is_sorted = False

    _search_from: dt.datetime | None = None

    def get_records(self, context: Context | None) -> Iterable[dict[str, t.Any]]:
        """Resolve the bookmark, then search (POST) or list (GET) accordingly."""
        self._search_from = self.get_starting_timestamp(context)
        self.http_method = "POST" if self._search_from else "GET"
        yield from super().get_records(context)

    def get_url(self, context: Context | None) -> str:
        """Return the search URL when filtering by bookmark."""
        url = super().get_url(context)
        return f"{url}/search" if self._search_from else url

    def get_url_params(
        self,
        context: Context | None,
        next_page_token: int | None,
    ) -> dict[str, t.Any]:
        """Add a stable sort order."""
        return super().get_url_params(context, next_page_token) | {"order_by": "id"}

    def prepare_request_payload(
        self,
        context: Context | None,  # noqa: ARG002
        next_page_token: int | None,  # noqa: ARG002
    ) -> t.Any:  # noqa: ANN401 - a JSON array, which the SDK's JSONPayload alias omits
        """Return the ``updated_at >= bookmark`` search criteria."""
        if self._search_from is None:
            return None
        value = self._search_from.astimezone(self.timezone).strftime(BEXIO_TIMESTAMP_FORMAT)
        return [{"field": "updated_at", "value": value, "criteria": ">="}]


def _rate_limit_wait(exc: Exception) -> float:
    """Return seconds to wait: the ``RateLimit-Reset`` header on 429, else a short pause."""
    response = exc.response if isinstance(exc, RetriableAPIError) else None
    if response is None or response.status_code != HTTPStatus.TOO_MANY_REQUESTS:
        return DEFAULT_RETRY_WAIT
    reset = response.headers.get("RateLimit-Reset")
    return int(reset) + 1 if reset and reset.isdigit() else DEFAULT_RATE_LIMIT_WAIT
