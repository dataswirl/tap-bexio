"""Purchase streams: bills, expenses and purchase orders."""

from __future__ import annotations

import typing as t

from tap_bexio.client import BexioOffsetStream, BexioPageStream

if t.TYPE_CHECKING:
    from singer_sdk.helpers.types import Context


class _PurchasePageStream(BexioPageStream):
    """4.0 purchase and expense endpoint, which accepts at most 500 records per page."""

    max_page_size = 500


class BillsStream(_PurchasePageStream):
    """Purchase bills."""

    name = "bills"
    path = "/4.0/purchase/bills"
    child_context_key = "bill_id"


class BillOutgoingPaymentsStream(_PurchasePageStream):
    """Outgoing payments of a purchase bill."""

    name = "bill_outgoing_payments"
    path = "/4.0/purchase/outgoing-payments"
    parent_stream_type = BillsStream

    def get_url_params(
        self,
        context: Context | None,
        next_page_token: int | None,
    ) -> dict[str, t.Any]:
        """Filter by the parent bill."""
        params = super().get_url_params(context, next_page_token)
        params["bill_id"] = (context or {})["bill_id"]
        return params


class ExpensesStream(_PurchasePageStream):
    """Expenses."""

    name = "expenses"
    path = "/4.0/expenses"


class PurchaseOrdersStream(BexioOffsetStream):
    """Purchase orders."""

    name = "purchase_orders"
    path = "/3.0/purchase_orders"
