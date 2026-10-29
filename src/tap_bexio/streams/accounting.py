"""Accounting streams."""

from __future__ import annotations

import typing as t

from tap_bexio.client import BexioOffsetStream, BexioStream, BexioUnpagedStream

if t.TYPE_CHECKING:
    from singer_sdk.helpers.types import Context, Record


class AccountsStream(BexioOffsetStream):
    """Chart of accounts."""

    name = "accounts"
    path = "/2.0/accounts"


class AccountGroupsStream(BexioOffsetStream):
    """Account groups."""

    name = "account_groups"
    path = "/2.0/account_groups"


class JournalStream(BexioOffsetStream):
    """Accounting journal bookings, from ``start_date`` when set."""

    name = "journal"
    path = "/3.0/accounting/journal"

    def get_url_params(
        self,
        context: Context | None,
        next_page_token: int | None,
    ) -> dict[str, t.Any]:
        """Limit bookings to ``start_date`` onwards."""
        params = super().get_url_params(context, next_page_token)
        if start_date := self.config.get("start_date"):
            params["from"] = str(start_date)[:10]
        return params


class ManualEntriesStream(BexioOffsetStream):
    """Manual journal entries."""

    name = "manual_entries"
    path = "/3.0/accounting/manual_entries"
    child_context_key = "manual_entry_id"


class ManualEntryFilesStream(BexioOffsetStream):
    """Files attached to a manual entry."""

    name = "manual_entry_files"
    path = "/3.0/accounting/manual_entries/{manual_entry_id}/files"
    parent_stream_type = ManualEntriesStream
    state_partitioning_keys = ()


class BusinessYearsStream(BexioOffsetStream):
    """Business years."""

    name = "business_years"
    path = "/3.0/accounting/business_years"


class CalendarYearsStream(BexioOffsetStream):
    """Calendar years."""

    name = "calendar_years"
    path = "/3.0/accounting/calendar_years"


class VatPeriodsStream(BexioOffsetStream):
    """VAT periods."""

    name = "vat_periods"
    path = "/3.0/accounting/vat_periods"


class TaxesStream(BexioOffsetStream):
    """Taxes."""

    name = "taxes"
    path = "/3.0/taxes"


class CurrenciesStream(BexioOffsetStream):
    """Currencies, with their current exchange rate."""

    name = "currencies"
    path = "/3.0/currencies"
    extra_params: t.ClassVar[dict[str, t.Any]] = {"embed": "exchange_rate"}
    child_context_key = "currency_id"


class CurrencyExchangeRatesStream(BexioUnpagedStream):
    """Current exchange rates of a currency against the other currencies."""

    name = "currency_exchange_rates"
    path = "/3.0/currencies/{currency_id}/exchange_rates"
    primary_keys = ("currency_id", "exchange_currency_id")
    parent_stream_type = CurrenciesStream
    state_partitioning_keys = ()

    def post_process(self, row: Record, context: Context | None = None) -> Record | None:
        """Lift the exchange currency id to the top level for the primary key."""
        row["exchange_currency_id"] = (row.get("exchange_currency") or {}).get("id")
        return super().post_process(row, context)


STREAMS: list[type[BexioStream]] = [
    AccountsStream,
    AccountGroupsStream,
    JournalStream,
    ManualEntriesStream,
    ManualEntryFilesStream,
    BusinessYearsStream,
    CalendarYearsStream,
    VatPeriodsStream,
    TaxesStream,
    CurrenciesStream,
    CurrencyExchangeRatesStream,
]
