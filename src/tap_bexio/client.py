"""REST client handling, including the Bexio stream base classes."""

from __future__ import annotations

import time
import typing as t
from functools import cached_property
from importlib.resources import files

from singer_sdk import SchemaDirectory, StreamSchema
from singer_sdk.exceptions import FatalAPIError, RetriableAPIError
from singer_sdk.pagination import SinglePagePaginator
from singer_sdk.streams import RESTStream

from tap_bexio import dates
from tap_bexio.config import MAX_PAGE_SIZE, TokenAuth
from tap_bexio.http_policy import Action, classify, retry_wait, throttle_wait
from tap_bexio.pagination import BexioOffsetPaginator, BexioPagePaginator

if t.TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Generator, Iterable
    from zoneinfo import ZoneInfo

    import requests
    from singer_sdk.authenticators import APIAuthenticatorBase
    from singer_sdk.helpers.types import Context, Record

    from tap_bexio.config import BexioConfig
    from tap_bexio.tap import TapBexio

# Bexio 2.0 timestamps are local (company) time without an offset, e.g. "2019-04-08 13:17:32".
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

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:  # noqa: ANN401
        """Create the stream; child streams keep one bookmark, not one per parent record."""
        super().__init__(*args, **kwargs)
        self._skip_remaining = False
        if self.parent_stream_type is not None:
            self.state_partitioning_keys = ()

    @property
    def settings(self) -> BexioConfig:
        """Return the tap's parsed settings."""
        return t.cast("TapBexio", self._tap).settings

    @property
    def url_base(self) -> str:
        """Return the API base URL."""
        return self.settings.api_url

    @property
    def authenticator(self) -> APIAuthenticatorBase:
        """Return the tap's authenticator, shared by all streams."""
        return t.cast("TapBexio", self._tap).authenticator

    @property
    def http_headers(self) -> dict[str, str]:
        """Return headers sent with every request."""
        headers = {"Accept": "application/json"}
        if user_agent := self.settings.user_agent:
            headers["User-Agent"] = user_agent
        return headers

    @property
    def page_size(self) -> int:
        """Return the page size, capped at the endpoint maximum."""
        return min(self.settings.page_size, self.max_page_size)

    @property
    def timezone(self) -> ZoneInfo:
        """Return the timezone of Bexio's offset-less timestamps and of emitted timestamps."""
        return self.settings.timezone

    @cached_property
    def _date_fields(self) -> dates.FormatTree:
        """Return the ``date``/``date-time`` properties as a tree of formats."""
        return dates.date_tree(self.schema)

    def get_url_params(
        self,
        context: Context | None,  # noqa: ARG002
        next_page_token: t.Any | None,  # noqa: ARG002, ANN401
    ) -> dict[str, t.Any]:
        """Return URL query parameters for the request."""
        return dict(self.extra_params)

    def validate_response(self, response: requests.Response) -> None:
        """Map Bexio error statuses to skip or fail; leave retries to the SDK."""
        if wait := throttle_wait(response.status_code, response.headers):
            self.logger.info("Rate limit nearly used up, sleeping %ss.", wait)
            time.sleep(wait)
        action = classify(
            response.status_code,
            is_child=self.parent_stream_type is not None,
            forbidden=self.settings.forbidden,
        )
        if action is not Action.CONTINUE:
            raise self._action_error(action, response)
        super().validate_response(response)

    def _action_error(self, action: Action, response: requests.Response) -> Exception:
        """Return the exception that carries out ``action``."""
        if action is Action.FAIL_UNAUTHORIZED:
            return FatalAPIError(
                f"{self.response_error_message(response)}. Check that "
                f"{self._credential_name} is valid."
            )
        if action is Action.SKIP_PARTITION:
            msg = f"{response.url} not found (deleted during sync?). Skipping."
            return StreamSkippedError(msg, whole_stream=False)
        msg = (
            f"Access to stream '{self.name}' is forbidden ({response.url}). The token "
            "lacks the required scope or the Bexio module is not active."
        )
        if action is Action.SKIP_STREAM:
            return StreamSkippedError(f"{msg} Skipping stream.", whole_stream=True)
        return FatalAPIError(f"{msg} Set forbidden_stream_behavior=skip to skip it.")

    @property
    def _credential_name(self) -> str:
        """Return the setting to blame for a 401."""
        if isinstance(self.settings.auth, TokenAuth):
            return "auth_token"
        return "the OAuth token (client_id, client_secret, refresh_token)"

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
        """Conform dates and timestamps to ISO 8601 and add parent context keys."""
        dates.conform(row, self._date_fields, self.timezone)
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
    """Return seconds to wait before retrying the request that raised ``exc``."""
    response = exc.response if isinstance(exc, RetriableAPIError) else None
    if response is None:
        return retry_wait(None, {})
    return retry_wait(response.status_code, response.headers)
