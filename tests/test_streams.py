"""Request/response behaviour of the streams against a mocked API."""

from __future__ import annotations

import contextlib
import io
import json
import logging
import re

import pytest
import requests
from responses import matchers
from singer_sdk.exceptions import FatalAPIError, RetriableAPIError

from tap_bexio.client import _rate_limit_wait

from .conftest import API


def records(tap, name, context=None):
    return list(tap.streams[name].get_records(context))


def sync(tap, name):
    """Run a full stream sync and return the emitted Singer messages."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        tap.streams[name].sync()
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_offset_stream_pages_until_short_page(make_tap, mocked):
    tap = make_tap(page_size=2)
    page = {"limit": "2", "offset": "0"}
    mocked.get(
        f"{API}/2.0/country",
        json=[{"id": 1}, {"id": 2}],
        match=[matchers.query_param_matcher(page)],
    )
    mocked.get(
        f"{API}/2.0/country",
        json=[{"id": 3}],
        match=[matchers.query_param_matcher(page | {"offset": "2"})],
    )
    assert [r["id"] for r in records(tap, "countries")] == [1, 2, 3]
    assert mocked.calls[0].request.headers["Authorization"] == "Bearer token"


def test_v4_page_stream(make_tap, mocked):
    tap = make_tap()
    mocked.get(
        f"{API}/4.0/expenses",
        json={"data": [{"id": "a"}], "paging": {"page": 1, "page_count": 2}},
        match=[matchers.query_param_matcher({"page": "1", "limit": "500"})],
    )
    mocked.get(
        f"{API}/4.0/expenses",
        json={"data": [{"id": "b"}], "paging": {"page": 2, "page_count": 2}},
        match=[matchers.query_param_matcher({"page": "2", "limit": "500"})],
    )
    assert [r["id"] for r in records(tap, "expenses")] == ["a", "b"]


def test_banking_payments_read_results(make_tap, mocked):
    tap = make_tap()
    pagination = {"page": 1, "per-page": 500, "max-results": 1}
    body = {"query": None, "sort-by": None, "pagination": pagination, "results": [{"id": 1}]}
    mocked.get(
        f"{API}/4.0/banking/payments",
        json=body,
        match=[matchers.query_param_matcher({"page": "1", "per-page": "500"})],
    )
    assert [r["id"] for r in records(tap, "payments")] == [1]


def test_search_stream_without_bookmark_reads_list(make_tap, mocked):
    tap = make_tap()
    mocked.get(
        f"{API}/2.0/kb_invoice",
        json=[{"id": 1}],
        match=[matchers.query_param_matcher({"limit": "500", "offset": "0", "order_by": "id"})],
    )
    assert records(tap, "invoices") == [{"id": 1}]


def test_search_stream_with_start_date_posts_search(make_tap, mocked):
    tap = make_tap(start_date="2024-01-15T00:00:00Z")
    mocked.post(
        f"{API}/2.0/kb_invoice/search",
        json=[{"id": 1, "updated_at": "2024-02-01 08:00:00"}],
        match=[
            matchers.query_param_matcher({"limit": "500", "offset": "0", "order_by": "id"}),
            matchers.json_params_matcher(
                [{"field": "updated_at", "value": "2024-01-15 01:00:00", "criteria": ">="}]
            ),
        ],
    )
    mocked.get(re.compile(rf"{API}/2.0/kb_invoice/1(/.*)?"), json=[])  # child streams
    messages = sync(tap, "invoices")
    assert [m["record"]["id"] for m in messages if m["type"] == "RECORD"] == [1]


def test_contacts_sync_active_and_archived_partitions_from_own_bookmarks(make_tap, mocked):
    # show_archived=true returns only archived contacts, so each set is its own partition.
    active_bookmark = {
        "context": {"archived": False},
        "replication_key": "updated_at",
        "replication_key_value": "2024-07-01T10:00:00+02:00",
    }
    state = {"bookmarks": {"contacts": {"partitions": [active_bookmark]}}}
    tap = make_tap(state=state, start_date="2020-01-01T00:00:00Z")
    page = {"limit": "500", "offset": "0", "order_by": "id"}
    since = lambda value: matchers.json_params_matcher(  # noqa: E731
        [{"field": "updated_at", "value": value, "criteria": ">="}]
    )
    mocked.post(
        f"{API}/2.0/contact/search",
        json=[],
        match=[matchers.query_param_matcher(page), since("2024-07-01 10:00:00")],
    )
    mocked.post(
        f"{API}/2.0/contact/search",
        json=[],
        match=[
            matchers.query_param_matcher(page | {"show_archived": "true"}),
            since("2020-01-01 01:00:00"),  # start_date in Europe/Zurich
        ],
    )
    states = [m["value"] for m in sync(tap, "contacts") if m["type"] == "STATE"]
    partitions = states[-1]["bookmarks"]["contacts"]["partitions"]
    active = next(p for p in partitions if p["context"] == {"archived": False})
    assert active["replication_key_value"] == "2024-07-01T10:00:00+02:00"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2024-01-15 13:17:32", "2024-01-15T13:17:32+01:00"),
        ("2024-07-15 13:17:32", "2024-07-15T13:17:32+02:00"),
        ("2024-07-15T13:17:32+00:00", "2024-07-15T13:17:32+00:00"),  # already ISO: untouched
        (None, None),
    ],
)
def test_post_process_normalizes_local_timestamps(make_tap, value, expected):
    stream = make_tap().streams["invoices"]
    assert stream.post_process({"id": 1, "updated_at": value})["updated_at"] == expected


def test_positions_child_reads_detail_and_injects_document_id(make_tap, mocked):
    stream = make_tap().streams["invoice_positions"]
    positions = [{"id": 1, "type": "KbPositionArticle"}, {"id": 1, "type": "KbPositionText"}]
    mocked.get(f"{API}/2.0/kb_invoice/42", json={"id": 42, "positions": positions})
    rows = [
        stream.post_process(r, {"document_id": 42}) for r in stream.get_records({"document_id": 42})
    ]
    assert [(r["document_id"], r["type"], r["id"]) for r in rows] == [
        (42, "KbPositionArticle", 1),
        (42, "KbPositionText", 1),
    ]


def test_parent_passes_id_to_children(make_tap):
    stream = make_tap().streams["invoices"]
    assert stream.get_child_context({"id": 7}, None) == {"document_id": 7}


def test_outgoing_payments_filter_by_bill(make_tap, mocked):
    mocked.get(
        f"{API}/4.0/purchase/outgoing-payments",
        json={"data": [{"id": "p"}], "paging": {"page": 1, "page_count": 1}},
        match=[matchers.query_param_matcher({"bill_id": "b-1", "page": "1", "limit": "500"})],
    )
    assert records(make_tap(), "bill_outgoing_payments", {"bill_id": "b-1"}) == [{"id": "p"}]


def test_payroll_absences_loop_over_business_years(make_tap, mocked, monkeypatch):
    stream = make_tap(start_date="2023-06-01T00:00:00Z").streams["payroll_absences"]
    monkeypatch.setattr(type(stream), "_business_years", lambda _: range(2023, 2025))
    for year in (2023, 2024):
        mocked.get(
            f"{API}/4.0/payroll/employees/e1/absences",
            json={"data": [{"id": year}]},
            match=[matchers.query_param_matcher({"businessYear": str(year)})],
        )
    assert [r["id"] for r in stream.get_records({"employee_id": "e1"})] == [2023, 2024]


def test_exchange_rates_lift_exchange_currency_id(make_tap):
    stream = make_tap().streams["currency_exchange_rates"]
    row = stream.post_process({"exchange_currency": {"id": 3}}, {"currency_id": 1})
    assert (row["currency_id"], row["exchange_currency_id"]) == (1, 3)


def test_forbidden_skip_logs_and_stops_stream(make_tap, mocked, caplog):
    tap = make_tap()
    mocked.get(f"{API}/4.0/payroll/employees", status=403)
    with caplog.at_level(logging.WARNING):
        assert records(tap, "payroll_employees") == []
        assert records(tap, "payroll_employees") == []  # no second request
    assert "forbidden" in caplog.text
    assert len(mocked.calls) == 1


def test_forbidden_fail_raises(make_tap, mocked):
    tap = make_tap(forbidden_stream_behavior="fail")
    mocked.get(f"{API}/4.0/payroll/employees", status=403)
    with pytest.raises(FatalAPIError, match="forbidden"):
        records(tap, "payroll_employees")


def test_unauthorized_is_fatal(make_tap, mocked):
    mocked.get(f"{API}/2.0/country", status=401)
    with pytest.raises(FatalAPIError, match="auth_token"):
        records(make_tap(), "countries")


def test_not_found_on_child_skips_only_that_parent(make_tap, mocked):
    tap = make_tap()
    mocked.get(f"{API}/2.0/kb_invoice/1/payment", status=404)
    mocked.get(f"{API}/2.0/kb_invoice/2/payment", json=[{"id": 9}])
    assert records(tap, "invoice_payments", {"document_id": 1}) == []
    assert records(tap, "invoice_payments", {"document_id": 2}) == [{"id": 9}]


def test_not_found_on_top_level_stream_is_fatal(make_tap, mocked):
    mocked.get(f"{API}/2.0/country", status=404)
    with pytest.raises(FatalAPIError):
        records(make_tap(), "countries")


def _response(status: int, headers: dict[str, str]) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers)
    response._content = json.dumps({}).encode()  # noqa: SLF001
    return response


def test_rate_limit_is_retriable_and_waits_for_reset(make_tap):
    stream = make_tap().streams["countries"]
    response = _response(429, {"RateLimit-Reset": "7"})
    response.url = f"{API}/2.0/country"
    with pytest.raises(RetriableAPIError) as exc_info:
        stream.validate_response(response)
    assert _rate_limit_wait(exc_info.value) == 8
    assert _rate_limit_wait(RetriableAPIError("boom", _response(503, {}))) == 10


@pytest.mark.parametrize(
    ("status", "headers", "expected_sleeps"),
    [
        (200, {"RateLimit-Remaining": "1", "RateLimit-Reset": "7"}, [8]),
        (200, {"RateLimit-Remaining": "0", "RateLimit-Reset": "3"}, [4]),
        (200, {"RateLimit-Remaining": "2", "RateLimit-Reset": "7"}, []),
        (200, {"RateLimit-Remaining": "1"}, []),
        (200, {}, []),
    ],
)
def test_throttles_when_rate_limit_nearly_exhausted(
    make_tap, monkeypatch, status, headers, expected_sleeps
):
    sleeps = []
    monkeypatch.setattr("tap_bexio.client.time.sleep", sleeps.append)
    stream = make_tap().streams["countries"]
    stream.validate_response(_response(status, headers))
    assert sleeps == expected_sleeps


def test_rate_limited_response_is_not_throttled_twice(make_tap, monkeypatch):
    sleeps = []
    monkeypatch.setattr("tap_bexio.client.time.sleep", sleeps.append)
    stream = make_tap().streams["countries"]
    response = _response(429, {"RateLimit-Remaining": "0", "RateLimit-Reset": "7"})
    response.url = f"{API}/2.0/country"
    with pytest.raises(RetriableAPIError):
        stream.validate_response(response)
    assert sleeps == []
