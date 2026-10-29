"""Payroll streams (require the Bexio payroll module)."""

from __future__ import annotations

import datetime as dt
import typing as t

from tap_bexio.client import BexioStream, BexioUnpagedStream

if t.TYPE_CHECKING:
    from collections.abc import Iterable

    from singer_sdk.helpers.types import Context

#: Business years read for absences when no ``start_date`` is configured.
DEFAULT_ABSENCE_YEARS = 2


class PayrollEmployeesStream(BexioUnpagedStream):
    """Payroll employees."""

    name = "payroll_employees"
    path = "/4.0/payroll/employees"
    records_jsonpath = "$.data[*]"
    child_context_key = "employee_id"


class PayrollAbsencesStream(BexioUnpagedStream):
    """Absences of an employee, one request per business year.

    Years run from the ``start_date`` year (or the last ``DEFAULT_ABSENCE_YEARS`` years)
    up to the current year.
    """

    name = "payroll_absences"
    path = "/4.0/payroll/employees/{employee_id}/absences"
    records_jsonpath = "$.data[*]"
    parent_stream_type = PayrollEmployeesStream
    state_partitioning_keys = ()

    def _business_years(self) -> range:
        current = dt.datetime.now(tz=self.timezone).year
        start_date = self.config.get("start_date")
        first = int(str(start_date)[:4]) if start_date else current - DEFAULT_ABSENCE_YEARS + 1
        return range(first, current + 1)

    def get_records(self, context: Context | None) -> Iterable[dict[str, t.Any]]:
        """Read absences for every business year in range."""
        for year in self._business_years():
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


STREAMS: list[type[BexioStream]] = [
    PayrollEmployeesStream,
    PayrollAbsencesStream,
]
