"""Purchase streams: bills, expenses and purchase orders."""

from __future__ import annotations

import typing as t

from tap_bexio.client import BexioOffsetStream, BexioPageStream, BexioStream

if t.TYPE_CHECKING:
    from singer_sdk.helpers.types import Context


class BillsStream(BexioPageStream):
    """Purchase bills."""

    name = "bills"
    path = "/4.0/purchase/bills"
    max_page_size = 500
    child_context_key = "bill_id"


class BillOutgoingPaymentsStream(BexioPageStream):
    """Outgoing payments of a purchase bill."""

    name = "bill_outgoing_payments"
    path = "/4.0/purchase/outgoing-payments"
    max_page_size = 500
    parent_stream_type = BillsStream
    state_partitioning_keys = ()

    def get_url_params(
        self,
        context: Context | None,
        next_page_token: int | None,
    ) -> dict[str, t.Any]:
        """Filter by the parent bill."""
        params = super().get_url_params(context, next_page_token)
        params["bill_id"] = (context or {})["bill_id"]
        return params


class ExpensesStream(BexioPageStream):
    """Expenses."""

    name = "expenses"
    path = "/4.0/expenses"
    max_page_size = 500


class PurchaseOrdersStream(BexioOffsetStream):
    """Purchase orders."""

    name = "purchase_orders"
    path = "/3.0/purchase_orders"


STREAMS: list[type[BexioStream]] = [
    BillsStream,
    BillOutgoingPaymentsStream,
    ExpensesStream,
    PurchaseOrdersStream,
]
