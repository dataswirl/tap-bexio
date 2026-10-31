"""Sales document streams: invoices, offers, orders and deliveries."""

from __future__ import annotations

from tap_bexio.client import (
    BexioOffsetStream,
    BexioSearchStream,
    BexioUnpagedStream,
)

POSITION_KEYS = ("document_id", "type", "id")


class InvoicesStream(BexioSearchStream):
    """Invoices (incremental)."""

    name = "invoices"
    path = "/2.0/kb_invoice"
    child_context_key = "document_id"


class OffersStream(BexioSearchStream):
    """Offers / quotes (incremental)."""

    name = "offers"
    path = "/2.0/kb_offer"
    child_context_key = "document_id"


class OrdersStream(BexioSearchStream):
    """Orders (incremental)."""

    name = "orders"
    path = "/2.0/kb_order"
    child_context_key = "document_id"


class DeliveriesStream(BexioOffsetStream):
    """Deliveries (no search endpoint, so full table)."""

    name = "deliveries"
    path = "/2.0/kb_delivery"
    child_context_key = "document_id"


class _PositionsStream(BexioUnpagedStream):
    """All positions of one document, read from the document detail endpoint.

    The detail response embeds every position type (custom, article, text, subtotal,
    discount, pagebreak, subposition), which saves one request per position type.
    """

    records_jsonpath = "$.positions[*]"
    primary_keys = POSITION_KEYS


class InvoicePositionsStream(_PositionsStream):
    """Invoice positions."""

    name = "invoice_positions"
    path = InvoicesStream.path + "/{document_id}"
    parent_stream_type = InvoicesStream


class OfferPositionsStream(_PositionsStream):
    """Offer positions."""

    name = "offer_positions"
    path = OffersStream.path + "/{document_id}"
    parent_stream_type = OffersStream


class OrderPositionsStream(_PositionsStream):
    """Order positions."""

    name = "order_positions"
    path = OrdersStream.path + "/{document_id}"
    parent_stream_type = OrdersStream


class DeliveryPositionsStream(_PositionsStream):
    """Delivery positions."""

    name = "delivery_positions"
    path = DeliveriesStream.path + "/{document_id}"
    parent_stream_type = DeliveriesStream


class InvoicePaymentsStream(BexioOffsetStream):
    """Payments received for an invoice."""

    name = "invoice_payments"
    path = InvoicesStream.path + "/{document_id}/payment"
    parent_stream_type = InvoicesStream


class InvoiceRemindersStream(BexioUnpagedStream):
    """Payment reminders of an invoice."""

    name = "invoice_reminders"
    path = InvoicesStream.path + "/{document_id}/kb_reminder"
    parent_stream_type = InvoicesStream


class InvoiceCommentsStream(BexioOffsetStream):
    """Comments on an invoice."""

    name = "invoice_comments"
    path = InvoicesStream.path + "/{document_id}/comment"
    parent_stream_type = InvoicesStream


class OfferCommentsStream(BexioOffsetStream):
    """Comments on an offer."""

    name = "offer_comments"
    path = OffersStream.path + "/{document_id}/comment"
    parent_stream_type = OffersStream


class OrderCommentsStream(BexioOffsetStream):
    """Comments on an order."""

    name = "order_comments"
    path = OrdersStream.path + "/{document_id}/comment"
    parent_stream_type = OrdersStream


class DocumentSettingsStream(BexioUnpagedStream):
    """Document settings per document type."""

    name = "document_settings"
    path = "/2.0/kb_item_setting"


class DocumentTemplatesStream(BexioUnpagedStream):
    """Document templates."""

    name = "document_templates"
    path = "/3.0/document_templates"
    primary_keys = ("template_slug",)
