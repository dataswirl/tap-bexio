"""Request/response behaviour of the streams against a mocked API."""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import logging
import re
from zoneinfo import ZoneInfo

import pytest
from responses import matchers
from singer_sdk.exceptions import FatalAPIError, RetriableAPIError

from tap_bexio.client import _rate_limit_wait
from tap_bexio.streams.payroll import business_years

from .conftest import API, make_response


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


@pytest.mark.parametrize(
    ("bookmark", "since"),
    [
        ("2024-07-01T08:00:00+00:00", "2024-07-01 10:00:00"),
        ("2024-07-01T10:00:00+02:00", "2024-07-01 10:00:00"),  # written before UTC output
        # Summer time starts: 01:00 UTC is 03:00 local.
        ("2024-03-31T00:59:59+00:00", "2024-03-31 01:59:59"),
        ("2024-03-31T01:00:00+00:00", "2024-03-31 03:00:00"),
        # Summer time ends: both 02:30 local map to the same, inclusive, filter value.
        ("2024-10-27T00:30:00+00:00", "2024-10-27 02:30:00"),
        ("2024-10-27T01:30:00+00:00", "2024-10-27 02:30:00"),
    ],
)
def test_search_filter_is_the_bookmark_in_the_company_timezone(make_tap, mocked, bookmark, since):
    state = {
        "bookmarks": {
            "invoices": {"replication_key": "updated_at", "replication_key_value": bookmark}
        }
    }
    mocked.post(
        f"{API}/2.0/kb_invoice/search",
        json=[],
        match=[
            matchers.json_params_matcher(
                [{"field": "updated_at", "value": since, "criteria": ">="}]
            )
        ],
    )
    assert [m for m in sync(make_tap(state=state), "invoices") if m["type"] == "RECORD"] == []


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
        ("2024-01-15 13:17:32", "2024-01-15T12:17:32+00:00"),
        ("2024-07-15 13:17:32", "2024-07-15T11:17:32+00:00"),
        ("2024-07-15 13:17", "2024-07-15T11:17:00+00:00"),
        ("2024-07-15T13:17:32+00:00", "2024-07-15T13:17:32+00:00"),
        ("2024-07-15T13:17:32+0000", "2024-07-15T13:17:32+00:00"),  # 4.0: no colon
        ("2024-07-15T13:17:32Z", "2024-07-15T13:17:32+00:00"),
        ("2024-07-15T13:17:32+02:00", "2024-07-15T11:17:32+00:00"),
        ("2024-07-15", "2024-07-14T22:00:00+00:00"),
        ("not a timestamp", "not a timestamp"),
        ("", ""),
        (None, None),
    ],
)
def test_post_process_emits_timestamps_in_utc(make_tap, value, expected):
    stream = make_tap().streams["invoices"]
    assert stream.post_process({"id": 1, "updated_at": value})["updated_at"] == expected


def test_post_process_reads_offsetless_timestamps_in_timezone_from_config(make_tap):
    stream = make_tap(timezone="Europe/Bucharest").streams["invoices"]
    row = stream.post_process({"id": 1, "updated_at": "2024-07-15 13:17:32"})
    assert row["updated_at"] == "2024-07-15T10:17:32+00:00"


def test_post_process_emits_timestamps_in_output_timezone_from_config(make_tap):
    stream = make_tap(output_timezone="Europe/Bucharest").streams["bills"]
    row = stream.post_process({"id": "b1", "created_at": "2024-07-15T13:17:32+0000"})
    assert row["created_at"] == "2024-07-15T16:17:32+03:00"


def test_timestamps_of_both_seasons_share_one_offset(make_tap):
    # Two offsets in one column break targets that load timestamps with pandas.
    stream = make_tap().streams["contacts"]
    values = ["2026-01-15 09:00:00", "2026-07-15 09:00:00", "2026-10-25 02:30:00"]
    rows = [stream.post_process({"id": i, "updated_at": v}) for i, v in enumerate(values)]
    assert [row["updated_at"] for row in rows] == [
        "2026-01-15T08:00:00+00:00",
        "2026-07-15T07:00:00+00:00",
        "2026-10-25T00:30:00+00:00",
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-03-29T00:00:00+01:00", "2026-03-29"),
        ("2026-07-15T00:00:00+02:00", "2026-07-15"),
        ("2026-10-25T00:00:00+02:00", "2026-10-25"),
        ("2026-10-26T00:00:00+01:00", "2026-10-26"),
    ],
)
def test_journal_booking_date_is_a_date(make_tap, value, expected):
    stream = make_tap().streams["journal"]
    assert stream.post_process({"id": 1, "date": value})["date"] == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2024-07-15", "2024-07-15"),
        ("2024-07-15 00:00:00", "2024-07-15"),
        ("2024-07-14T23:30:00+00:00", "2024-07-15"),  # local day in the company timezone
    ],
)
def test_post_process_conforms_dates(make_tap, value, expected):
    stream = make_tap().streams["invoices"]
    assert stream.post_process({"id": 1, "is_valid_from": value})["is_valid_from"] == expected


def test_post_process_conforms_nested_dates(make_tap):
    timesheet = (
        make_tap()
        .streams["timesheets"]
        .post_process(
            {
                "id": 1,
                "date": "2026-10-31",
                "tracking": {"type": "range", "start": "2026-10-31 08:15:00", "end": None},
            },
        )
    )
    assert timesheet["tracking"] == {
        "type": "range",
        "start": "2026-10-31T07:15:00+00:00",
        "end": None,
    }

    entry = (
        make_tap()
        .streams["manual_entries"]
        .post_process(
            {"id": 1, "date": "2026-10-31", "entries": [{"id": 2, "date": "2026-10-31"}]},
        )
    )
    assert entry["entries"] == [{"id": 2, "date": "2026-10-31"}]


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


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (None, range(2025, 2027)),  # the last DEFAULT_ABSENCE_YEARS years
        (dt.date(2023, 6, 1), range(2023, 2027)),
        (dt.date(2026, 1, 1), range(2026, 2027)),
    ],
)
def test_business_years(start, expected):
    assert business_years(dt.date(2026, 10, 31), start) == expected


def test_payroll_absences_read_each_business_year(make_tap, mocked):
    this_year = dt.datetime.now(tz=ZoneInfo("Europe/Zurich")).year
    stream = make_tap(start_date=f"{this_year - 1}-06-01T00:00:00Z").streams["payroll_absences"]
    for year in (this_year - 1, this_year):
        mocked.get(
            f"{API}/4.0/payroll/employees/e1/absences",
            json={"data": [{"id": year}]},
            match=[matchers.query_param_matcher({"businessYear": str(year)})],
        )
    rows = list(stream.get_records({"employee_id": "e1"}))
    assert [(r["id"], r["business_year"]) for r in rows] == [
        (this_year - 1, this_year - 1),
        (this_year, this_year),
    ]


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


def test_rate_limit_is_retriable_and_waits_for_reset(make_tap):
    stream = make_tap().streams["countries"]
    response = make_response({}, status=429, headers={"RateLimit-Reset": "7"})
    response.url = f"{API}/2.0/country"
    with pytest.raises(RetriableAPIError) as exc_info:
        stream.validate_response(response)
    assert _rate_limit_wait(exc_info.value) == 8
    assert _rate_limit_wait(RetriableAPIError("boom", make_response({}, status=503))) == 10


@pytest.mark.parametrize(
    ("status", "headers", "expected_sleeps"),
    [
        (200, {"RateLimit-Remaining": "1", "RateLimit-Reset": "7"}, [8]),
        (200, {"RateLimit-Remaining": "2", "RateLimit-Reset": "7"}, []),
    ],
)
def test_throttles_when_rate_limit_nearly_exhausted(
    make_tap, monkeypatch, status, headers, expected_sleeps
):
    sleeps = []
    monkeypatch.setattr("tap_bexio.client.time.sleep", sleeps.append)
    stream = make_tap().streams["countries"]
    stream.validate_response(make_response({}, status=status, headers=headers))
    assert sleeps == expected_sleeps


def test_rate_limited_response_is_not_throttled_twice(make_tap, monkeypatch):
    sleeps = []
    monkeypatch.setattr("tap_bexio.client.time.sleep", sleeps.append)
    stream = make_tap().streams["countries"]
    response = make_response(
        {}, status=429, headers={"RateLimit-Remaining": "0", "RateLimit-Reset": "7"}
    )
    response.url = f"{API}/2.0/country"
    with pytest.raises(RetriableAPIError):
        stream.validate_response(response)
    assert sleeps == []


@pytest.mark.parametrize(
    ("config", "query"),
    [
        ({"start_date": "2024-01-15T23:00:00+02:00"}, {"from": "2024-01-15"}),
        ({}, {}),
    ],
)
def test_journal_reads_from_start_date(make_tap, mocked, config, query):
    mocked.get(
        f"{API}/3.0/accounting/journal",
        json=[{"id": 1}],
        match=[matchers.query_param_matcher({"limit": "500", "offset": "0"} | query)],
    )
    assert records(make_tap(**config), "journal") == [{"id": 1}]
