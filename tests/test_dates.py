"""Which schema properties hold dates, and how their values are conformed."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from tap_bexio.dates import FormatTree, conform, conform_date, date_tree

ZURICH = ZoneInfo("Europe/Zurich")
UTC = ZoneInfo("UTC")
NEW_YORK = ZoneInfo("America/New_York")


def test_date_tree_maps_nested_objects_and_arrays():
    schema = {
        "properties": {
            "id": {"type": "integer"},
            "day": {"type": "string", "format": "date"},
            "at": {"type": "string", "format": "date-time"},
            "email": {"type": "string", "format": "email"},
            "tracking": {"properties": {"start": {"format": "date-time"}, "n": {}}},
            "entries": {"items": {"properties": {"date": {"format": "date"}}}},
            "days": {"items": {"format": "date"}},
            "plain": {"properties": {"n": {"type": "integer"}}},
        }
    }
    assert date_tree(schema) == {
        "day": "date",
        "at": "date-time",
        "tracking": {"start": "date-time"},
        "entries": {"date": "date"},
        "days": "date",
    }


def test_conform_walks_the_tree_and_leaves_other_values():
    row = {
        "at": "2024-07-15 13:17:32",
        "days": ["2024-07-15", "2024-07-16 00:00:00"],
        "tracking": {"start": "2024-01-15 08:00:00", "n": 1},
        "entries": [{"date": "2024-07-14T23:30:00+00:00"}],
        "other": "2024-07-15 13:17:32",
    }
    tree: FormatTree = {
        "at": "date-time",
        "days": "date",
        "tracking": {"start": "date-time"},
        "entries": {"date": "date"},
        "missing": "date",
    }
    assert conform(row, tree, ZURICH, UTC) == {
        "at": "2024-07-15T11:17:32+00:00",
        "days": ["2024-07-15", "2024-07-16"],
        "tracking": {"start": "2024-01-15T07:00:00+00:00", "n": 1},
        "entries": [{"date": "2024-07-15"}],
        "other": "2024-07-15 13:17:32",
    }


def test_conform_ignores_shape_mismatches():
    assert conform({"at": {"x": 1}}, {"at": "date-time"}, ZURICH, UTC) == {"at": {"x": 1}}
    assert conform({"at": "2024-01-01"}, {"at": {"x": "date"}}, ZURICH, UTC) == {"at": "2024-01-01"}
    assert conform(None, {"at": "date"}, ZURICH, UTC) is None


# Europe/Zurich in 2024: summer time starts on 31 March at 02:00 (clocks go to 03:00) and
# ends on 27 October at 03:00 (clocks go back to 02:00).
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Offset-less 2.0 values around the start of summer time.
        ("2024-03-31 01:59:59", "2024-03-31T00:59:59+00:00"),
        ("2024-03-31 03:00:00", "2024-03-31T01:00:00+00:00"),
        # 02:30 does not exist that night; it is read with the winter offset.
        ("2024-03-31 02:30:00", "2024-03-31T01:30:00+00:00"),
        # Around the end of summer time.
        ("2024-10-27 01:59:59", "2024-10-26T23:59:59+00:00"),
        ("2024-10-27 03:00:00", "2024-10-27T02:00:00+00:00"),
        # 02:30 happens twice that night; it is read as the first (summer time) one.
        ("2024-10-27 02:30:00", "2024-10-27T00:30:00+00:00"),
        # With an offset (3.0) both occurrences are told apart.
        ("2024-10-27T02:30:00+02:00", "2024-10-27T00:30:00+00:00"),
        ("2024-10-27T02:30:00+01:00", "2024-10-27T01:30:00+00:00"),
        ("2024-03-31T01:59:59+01:00", "2024-03-31T00:59:59+00:00"),
        ("2024-03-31T03:00:00+02:00", "2024-03-31T01:00:00+00:00"),
    ],
)
def test_timestamps_around_summer_time_changes_are_emitted_in_utc(value, expected):
    assert conform_date(value, "date-time", ZURICH, UTC) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # The journal's booking date is local midnight, with the offset of that midnight.
        ("2026-01-15T00:00:00+01:00", "2026-01-15"),
        ("2026-03-29T00:00:00+01:00", "2026-03-29"),  # summer time starts later that day
        ("2026-03-30T00:00:00+02:00", "2026-03-30"),
        ("2026-07-15T00:00:00+02:00", "2026-07-15"),
        ("2026-10-25T00:00:00+02:00", "2026-10-25"),  # summer time ends later that day
        ("2026-10-26T00:00:00+01:00", "2026-10-26"),
        # UTC values just before and after local midnight.
        ("2024-03-30T23:30:00+00:00", "2024-03-31"),
        ("2024-10-26T22:30:00+00:00", "2024-10-27"),
        ("2024-10-26T21:59:59+00:00", "2024-10-26"),
        ("2024-10-27 00:00:00", "2024-10-27"),
    ],
)
def test_dates_take_the_day_in_the_company_timezone(value, expected):
    assert conform_date(value, "date", ZURICH, UTC) == expected
    assert conform_date(value, "date", ZURICH, NEW_YORK) == expected


@pytest.mark.parametrize(
    ("value", "output_tz", "expected"),
    [
        ("2024-03-31 01:59:59", ZURICH, "2024-03-31T01:59:59+01:00"),
        ("2024-03-31 03:00:00", ZURICH, "2024-03-31T03:00:00+02:00"),
        ("2024-10-27T00:30:00+00:00", ZURICH, "2024-10-27T02:30:00+02:00"),
        ("2024-10-27T01:30:00+00:00", ZURICH, "2024-10-27T02:30:00+01:00"),
        # New York changes on other days: 10 March and 3 November in 2024.
        ("2024-03-20 12:00:00", NEW_YORK, "2024-03-20T07:00:00-04:00"),
        ("2024-10-30 12:00:00", NEW_YORK, "2024-10-30T07:00:00-04:00"),
        ("2024-11-05 12:00:00", NEW_YORK, "2024-11-05T06:00:00-05:00"),
    ],
)
def test_timestamps_follow_the_output_timezone(value, output_tz, expected):
    assert conform_date(value, "date-time", ZURICH, output_tz) == expected
