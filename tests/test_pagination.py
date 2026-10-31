"""Paginator stop conditions."""

from __future__ import annotations

import pytest

from tap_bexio.pagination import BexioOffsetPaginator, BexioPagePaginator

from .conftest import make_response


@pytest.mark.parametrize(
    ("page_size", "rows", "headers", "expected"),
    [
        (2, 2, {}, 2),  # full page -> continue
        (2, 1, {}, None),  # short page -> stop
        (2, 2, {"X-Total-Count": "2"}, None),  # header says everything was read
        (2, 2, {"X-Total-Count": "5"}, 2),
        (None, 3, {}, 3),  # no limit: continue while rows come back
        (None, 0, {}, None),
        (2, 0, {"X-Total-Count": "5"}, None),  # empty page although the header says more
        (None, 3, {"X-Total-Count": "3"}, None),
    ],
)
def test_offset_paginator(page_size, rows, headers, expected):
    paginator = BexioOffsetPaginator(page_size)
    assert paginator.get_next(make_response([{}] * rows, headers=headers)) == expected


def test_offset_paginator_stops_on_repeated_page():
    paginator = BexioOffsetPaginator(None)
    page = make_response([{"id": 1}, {"id": 2}])
    paginator.advance(page)
    assert paginator.get_next(page) is None  # endpoint ignored offset
    assert paginator.get_next(make_response([{"id": 3}])) == 3


@pytest.mark.parametrize(
    ("body", "headers", "first_page", "expected"),
    [
        ({"data": [{}], "paging": {"page": 1, "page_count": 3}}, {}, 1, 2),
        ({"data": [{}], "paging": {"page": 3, "page_count": 3}}, {}, 1, None),
        ([{}, {}], {"X-Total-Count": "5"}, 0, 1),  # 0-based pages, 2 of 5 read
        ([{}, {}], {}, 1, 2),
        ([{}], {}, 1, None),
        ([], {"X-Total-Count": "5"}, 1, None),  # empty page although the header says more
        ({"data": [{}], "paging": {"page_count": 2}}, {}, 1, 2),  # page defaults to current
        ({"paging": {"page": 1}, "data": [{}, {}]}, {}, 1, 2),  # no page_count: count rows
        ({"pagination": {"max-results": 5}, "results": [{}]}, {}, 1, 2),  # per-page = size
        (
            {"pagination": {"page": 1, "per-page": 2, "max-results": 5}, "results": [{}]},
            {},
            1,
            2,
        ),
        (
            {"pagination": {"page": 3, "per-page": 2, "max-results": 5}, "results": [{}]},
            {},
            1,
            None,
        ),
        (
            {"pagination": {"page": 1, "per-page": 2, "max-results": 0}, "results": []},
            {},
            1,
            None,
        ),
    ],
)
def test_page_paginator(body, headers, first_page, expected):
    paginator = BexioPagePaginator(page_size=2, first_page=first_page)
    assert paginator.get_next(make_response(body, headers=headers)) == expected


@pytest.mark.parametrize(
    ("page_size", "pages"),
    [
        (2, [2, 2, 1]),  # 5 records in pages of 2
        (4, [2, 2, 1]),  # server caps pages at 2 although 4 were requested
    ],
)
def test_page_paginator_total_count(page_size, pages):
    paginator = BexioPagePaginator(page_size=page_size, first_page=0)
    for rows in pages:
        assert not paginator.finished
        paginator.advance(make_response([{}] * rows, headers={"X-Total-Count": "5"}))
    assert paginator.finished
    assert paginator.current_value == len(pages) - 1
