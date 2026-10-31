"""Offline tests for tap-bexio."""

from __future__ import annotations

from pathlib import Path

from tap_bexio.client import BexioStream
from tap_bexio.tap import TapBexio

SCHEMAS_DIR = Path(__file__).parent.parent / "src" / "tap_bexio" / "schemas"
INCREMENTAL = {"contacts", "contact_relations", "invoices", "offers", "orders"}


def test_every_stream_has_a_schema_file_and_vice_versa():
    tap = TapBexio(config={"auth_token": "dummy"})
    assert set(tap.streams) == {p.stem for p in SCHEMAS_DIR.glob("*.json")}


def test_primary_and_replication_keys_exist_in_schemas():
    tap = TapBexio(config={"auth_token": "dummy"})
    for stream in tap.streams.values():
        properties = stream.schema["properties"]
        for key in stream.primary_keys or ():
            assert key in properties, f"{stream.name}: {key}"
        if stream.replication_key:
            assert properties[stream.replication_key]["format"] == "date-time"


def test_incremental_streams():
    tap = TapBexio(config={"auth_token": "dummy"})
    assert {n for n, s in tap.streams.items() if s.replication_key} == INCREMENTAL


def test_default_api_url():
    tap = TapBexio(config={"auth_token": "dummy"})
    stream = tap.streams["countries"]
    assert isinstance(stream, BexioStream)
    assert stream.url_base == "https://api.bexio.com"


def test_child_streams_keep_one_bookmark_not_one_per_parent():
    tap = TapBexio(config={"auth_token": "dummy"})
    children = {n: s for n, s in tap.streams.items() if s.parent_stream_type}
    assert len(children) == 16
    assert {n: s.state_partitioning_keys for n, s in children.items()} == dict.fromkeys(
        children, ()
    )


def test_stream_order_and_paths_are_stable():
    tap = TapBexio(config={"auth_token": "dummy"})
    streams = [s for s in tap.streams.values() if isinstance(s, BexioStream)]
    assert [(s.name, s.path) for s in streams] == STREAM_PATHS


STREAM_PATHS = [
    ("account_groups", "/2.0/account_groups"),
    ("accounts", "/2.0/accounts"),
    ("articles", "/2.0/article"),
    ("bank_accounts", "/3.0/banking/accounts"),
    ("bill_outgoing_payments", "/4.0/purchase/outgoing-payments"),
    ("bills", "/4.0/purchase/bills"),
    ("business_activities", "/2.0/client_service"),
    ("business_years", "/3.0/accounting/business_years"),
    ("calendar_years", "/3.0/accounting/calendar_years"),
    ("communication_types", "/2.0/communication_kind"),
    ("company_profile", "/2.0/company_profile"),
    ("contact_additional_addresses", "/2.0/contact/{contact_id}/additional_address"),
    ("contact_groups", "/2.0/contact_group"),
    ("contact_relations", "/2.0/contact_relation"),
    ("contact_sectors", "/2.0/contact_branch"),
    ("contact_types", "/2.0/contact_type"),
    ("contacts", "/2.0/contact"),
    ("countries", "/2.0/country"),
    ("currencies", "/3.0/currencies"),
    ("currency_exchange_rates", "/3.0/currencies/{currency_id}/exchange_rates"),
    ("deliveries", "/2.0/kb_delivery"),
    ("delivery_positions", "/2.0/kb_delivery/{document_id}"),
    ("document_settings", "/2.0/kb_item_setting"),
    ("document_templates", "/3.0/document_templates"),
    ("expenses", "/4.0/expenses"),
    ("fictional_users", "/3.0/fictional_users"),
    ("files", "/3.0/files"),
    ("invoice_comments", "/2.0/kb_invoice/{document_id}/comment"),
    ("invoice_payments", "/2.0/kb_invoice/{document_id}/payment"),
    ("invoice_positions", "/2.0/kb_invoice/{document_id}"),
    ("invoice_reminders", "/2.0/kb_invoice/{document_id}/kb_reminder"),
    ("invoices", "/2.0/kb_invoice"),
    ("journal", "/3.0/accounting/journal"),
    ("languages", "/2.0/language"),
    ("manual_entries", "/3.0/accounting/manual_entries"),
    ("manual_entry_files", "/3.0/accounting/manual_entries/{manual_entry_id}/files"),
    ("notes", "/2.0/note"),
    ("offer_comments", "/2.0/kb_offer/{document_id}/comment"),
    ("offer_positions", "/2.0/kb_offer/{document_id}"),
    ("offers", "/2.0/kb_offer"),
    ("order_comments", "/2.0/kb_order/{document_id}/comment"),
    ("order_positions", "/2.0/kb_order/{document_id}"),
    ("orders", "/2.0/kb_order"),
    ("payment_types", "/2.0/payment_type"),
    ("payments", "/4.0/banking/payments"),
    ("payroll_absences", "/4.0/payroll/employees/{employee_id}/absences"),
    ("payroll_employees", "/4.0/payroll/employees"),
    ("permissions", "/3.0/permissions"),
    ("project_milestones", "/3.0/projects/{project_id}/milestones"),
    ("project_packages", "/3.0/projects/{project_id}/packages"),
    ("project_states", "/2.0/pr_project_state"),
    ("project_types", "/2.0/pr_project_type"),
    ("projects", "/2.0/pr_project"),
    ("purchase_orders", "/3.0/purchase_orders"),
    ("salutations", "/2.0/salutation"),
    ("stock_areas", "/2.0/stock"),
    ("stock_locations", "/2.0/stock_place"),
    ("task_priorities", "/2.0/todo_priority"),
    ("task_statuses", "/2.0/todo_status"),
    ("tasks", "/2.0/task"),
    ("taxes", "/3.0/taxes"),
    ("timesheet_statuses", "/2.0/timesheet_status"),
    ("timesheets", "/2.0/timesheet"),
    ("titles", "/2.0/title"),
    ("units", "/2.0/unit"),
    ("users", "/3.0/users"),
    ("vat_periods", "/3.0/accounting/vat_periods"),
]
