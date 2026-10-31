"""Payroll streams (require the Bexio payroll module)."""

from __future__ import annotations

import datetime as dt
import typing as t

from tap_bexio.client import BexioUnpagedStream

if t.TYPE_CHECKING:
    from collections.abc import Iterable

    from singer_sdk.helpers.types import Context

#: Business years read for absences when no ``start_date`` is configured.
DEFAULT_ABSENCE_YEARS = 2


class _PayrollStream(BexioUnpagedStream):
    """4.0 payroll endpoint: unpaged, records under ``data``."""

    records_jsonpath = "$.data[*]"


class PayrollEmployeesStream(_PayrollStream):
    """Payroll employees."""

    name = "payroll_employees"
    path = "/4.0/payroll/employees"
    child_context_key = "employee_id"


class PayrollAbsencesStream(_PayrollStream):
    """Absences of an employee, one request per business year.

    Years run from the ``start_date`` year (or the last ``DEFAULT_ABSENCE_YEARS`` years)
    up to the current year.
    """

    name = "payroll_absences"
    path = PayrollEmployeesStream.path + "/{employee_id}/absences"
    parent_stream_type = PayrollEmployeesStream

    def get_records(self, context: Context | None) -> Iterable[dict[str, t.Any]]:
        """Read absences for every business year in range."""
        today = dt.datetime.now(tz=self.timezone).date()
        start_date = self.settings.start_date
        for year in business_years(today, start_date.date() if start_date else None):
            # post_process runs later with the partition context, so set the year here.
            for row in super().get_records({**(context or {}), "business_year": year}):
                row["business_year"] = year
                yield row

    def get_url_params(
        self,
        context: Context | None,
        next_page_token: t.Any | None,  # noqa: ANN401
    ) -> dict[str, t.Any]:
        """Select the business year."""
        params = super().get_url_params(context, next_page_token)
        params["businessYear"] = (context or {})["business_year"]
        return params


def business_years(today: dt.date, start: dt.date | None) -> range:
    """Return the business years from ``start`` (or the last ``DEFAULT_ABSENCE_YEARS``) to now."""
    first = start.year if start else today.year - DEFAULT_ABSENCE_YEARS + 1
    return range(first, today.year + 1)
