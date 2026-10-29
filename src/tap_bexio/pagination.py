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
        first_id = records[0].get("id") if records and isinstance(records[0], dict) else None
        if first_id is not None and first_id == self._first_id:
            return None
        self._first_id = first_id
        received = len(records)
        next_offset = self.current_value + received
        total = _total_count(response)
        if total is not None:
            return next_offset if received and next_offset < total else None
        if self.page_size is None:
            return next_offset if received else None
        return next_offset if received >= self.page_size else None


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
        paging = body.get("paging") if isinstance(body, dict) else None
        if isinstance(paging, dict) and "page_count" in paging:
            page = int(paging.get("page", self.current_value))
            return page + 1 if page < int(paging["page_count"]) else None
        pagination = body.get("pagination") if isinstance(body, dict) else None
        if isinstance(pagination, dict) and "max-results" in pagination:
            page = int(pagination.get("page", self.current_value))
            per_page = int(pagination.get("per-page", self.page_size))
            return page + 1 if page * per_page < int(pagination["max-results"]) else None
        received = len(_page_records(response))
        self._received += received
        total = _total_count(response)
        if total is not None:
            return self.current_value + 1 if received and self._received < total else None
        return self.current_value + 1 if received >= self.page_size else None
