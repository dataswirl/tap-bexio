"""Paginators for the different Bexio API generations."""

from __future__ import annotations

import typing as t

from singer_sdk.pagination import BaseAPIPaginator

if t.TYPE_CHECKING:
    import requests

TOTAL_COUNT_HEADER = "X-Total-Count"


RECORD_KEYS = ("data", "results")


def _page_records(response: requests.Response) -> list[t.Any]:
    """Return the records of a page: a bare array, or ``data``/``results`` in an object."""
    body = response.json()
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in RECORD_KEYS:
            if isinstance(body.get(key), list):
                return body[key]
    return []


def _total_count(response: requests.Response) -> int | None:
    """Return the ``X-Total-Count`` header value, if present."""
    value = response.headers.get(TOTAL_COUNT_HEADER)
    return int(value) if value and value.isdigit() else None


class BexioOffsetPaginator(BaseAPIPaginator[int]):
    """``limit``/``offset`` paginator for the 2.0 and 3.0 APIs.

    The offset advances by the number of records received. Paging stops when the
    ``X-Total-Count`` header (3.0 endpoints) says everything was read, or else when a
    page is shorter than ``page_size``. Without a ``page_size`` (endpoints that take no
    ``limit``), paging stops at the first empty page. Paging also stops when a page
    starts with the same record ID as the previous one, in case an endpoint ignores
    ``offset`` (the offset keeps growing, so the SDK's loop detection misses it).
    """

    def __init__(self, page_size: int | None) -> None:
        """Create a paginator starting at offset 0."""
        super().__init__(0)
        self.page_size = page_size
        self._first_id: t.Any = None

    def get_next(self, response: requests.Response) -> int | None:  # noqa: D102
        records = _page_records(response)
        if self._repeats(records):
            return None
        received = len(records)
        next_offset = self.current_value + received
        return next_offset if received and self._more(received, next_offset, response) else None

    def _repeats(self, records: list[t.Any]) -> bool:
        """Return whether the page starts with the previous page's first ID, and remember it."""
        first = records[0] if records else None
        first_id = first.get("id") if isinstance(first, dict) else None
        repeated = first_id is not None and first_id == self._first_id
        self._first_id = first_id
        return repeated

    def _more(self, received: int, next_offset: int, response: requests.Response) -> bool:
        """Return whether records remain after a non-empty page."""
        total = _total_count(response)
        if total is not None:
            return next_offset < total
        return self.page_size is None or received >= self.page_size


class BexioPagePaginator(BaseAPIPaginator[int]):
    """Page-number paginator for the 4.0 APIs.

    Uses the ``paging`` object in the body when present (``page``/``page_count``), or the
    ``pagination`` object (``page``/``per-page``/``max-results``, banking payments), else
    the ``X-Total-Count`` header (compared with the records received so far, in case the
    server caps the page size), else stops on a short page.
    """

    def __init__(self, page_size: int, first_page: int = 1) -> None:
        """Create a paginator starting at ``first_page``."""
        super().__init__(first_page)
        self.page_size = page_size
        self.first_page = first_page
        self._received = 0

    def get_next(self, response: requests.Response) -> int | None:  # noqa: D102
        body = response.json()
        if paging := _section(body, "paging", "page_count"):
            page = int(paging.get("page", self.current_value))
            return _next_page(page, more=page < int(paging["page_count"]))
        if pagination := _section(body, "pagination", "max-results"):
            page = int(pagination.get("page", self.current_value))
            per_page = int(pagination.get("per-page", self.page_size))
            return _next_page(page, more=page * per_page < int(pagination["max-results"]))
        return self._next_by_count(response)

    def _next_by_count(self, response: requests.Response) -> int | None:
        """Continue while ``X-Total-Count`` says more remain, else while pages are full."""
        received = len(_page_records(response))
        self._received += received
        total = _total_count(response)
        more = self._received < total if total is not None else received >= self.page_size
        return _next_page(self.current_value, more=received > 0 and more)


def _section(body: t.Any, key: str, required: str) -> dict[str, t.Any] | None:  # noqa: ANN401
    """Return ``body[key]`` when it is an object holding ``required``."""
    section = body.get(key) if isinstance(body, dict) else None
    return section if isinstance(section, dict) and required in section else None


def _next_page(page: int, *, more: bool) -> int | None:
    return page + 1 if more else None
