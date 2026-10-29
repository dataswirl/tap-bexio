"""Generate stream JSON schemas from the OpenAPI spec embedded in docs.bexio.com.

Usage:
    uv run scripts/generate_schemas.py                 # download https://docs.bexio.com/
    uv run scripts/generate_schemas.py path/to/docs.html
    uv run scripts/generate_schemas.py path/to/openapi.json
"""

from __future__ import annotations

import json
import sys
import typing as t
from pathlib import Path

import requests

DOCS_URL = "https://docs.bexio.com/"
REDOC_MARKER = "__redoc_state = "
SCHEMAS_DIR = Path(__file__).parent.parent / "src" / "tap_bexio" / "schemas"

# Endpoint definitions: (method, path, record selector).
# Selectors: "list" -> array items or ``data`` items, "self" -> the response object itself,
# "positions" -> items of the ``positions`` array in a document detail response.
ENDPOINTS: dict[str, tuple[str, str, str]] = {
    # Contacts
    "contacts": ("get", "/2.0/contact", "list"),
    "contact_relations": ("get", "/2.0/contact_relation", "list"),
    "contact_groups": ("get", "/2.0/contact_group", "list"),
    "contact_sectors": ("get", "/2.0/contact_branch", "list"),
    "salutations": ("get", "/2.0/salutation", "list"),
    "titles": ("get", "/2.0/title", "list"),
    "contact_additional_addresses": ("get", "/2.0/contact/{contact_id}/additional_address", "list"),
    # Sales
    "invoices": ("get", "/2.0/kb_invoice", "list"),
    "offers": ("get", "/2.0/kb_offer", "list"),
    "orders": ("get", "/2.0/kb_order", "list"),
    "deliveries": ("get", "/2.0/kb_delivery", "list"),
    "invoice_positions": ("get", "/2.0/kb_invoice/{invoice_id}", "positions"),
    "offer_positions": ("get", "/2.0/kb_offer/{quote_id}", "positions"),
    "order_positions": ("get", "/2.0/kb_order/{order_id}", "positions"),
    "delivery_positions": ("get", "/2.0/kb_delivery/{delivery_id}", "positions"),
    "invoice_payments": ("get", "/2.0/kb_invoice/{invoice_id}/payment", "list"),
    "invoice_reminders": ("get", "/2.0/kb_invoice/{invoice_id}/kb_reminder", "list"),
    "invoice_comments": ("get", "/2.0/{kb_document_type}/{document_id}/comment", "list"),
    "offer_comments": ("get", "/2.0/{kb_document_type}/{document_id}/comment", "list"),
    "order_comments": ("get", "/2.0/{kb_document_type}/{document_id}/comment", "list"),
    "document_settings": ("get", "/2.0/kb_item_setting", "list"),
    "document_templates": ("get", "/3.0/document_templates", "list"),
    # Items
    "articles": ("get", "/2.0/article", "list"),
    "stock_locations": ("get", "/2.0/stock_place", "list"),
    "stock_areas": ("get", "/2.0/stock", "list"),
    "units": ("get", "/2.0/unit", "list"),
    # Purchase
    "bills": ("get", "/4.0/purchase/bills", "list"),
    "bill_outgoing_payments": ("get", "/4.0/purchase/outgoing-payments", "list"),
    "expenses": ("get", "/4.0/expenses", "list"),
    "purchase_orders": ("get", "/3.0/purchase_orders", "list"),
    # Accounting
    "accounts": ("get", "/2.0/accounts", "list"),
    "account_groups": ("get", "/2.0/account_groups", "list"),
    "journal": ("get", "/3.0/accounting/journal", "list"),
    "manual_entries": ("get", "/3.0/accounting/manual_entries", "list"),
    "manual_entry_files": ("get", "/3.0/accounting/manual_entries/{manual_entry_id}/files", "list"),
    "business_years": ("get", "/3.0/accounting/business_years", "list"),
    "calendar_years": ("get", "/3.0/accounting/calendar_years", "list"),
    "vat_periods": ("get", "/3.0/accounting/vat_periods", "list"),
    "taxes": ("get", "/3.0/taxes", "list"),
    "currencies": ("get", "/3.0/currencies", "list"),
    "currency_exchange_rates": ("get", "/3.0/currencies/{currency_id}/exchange_rates", "list"),
    # Banking
    "bank_accounts": ("get", "/3.0/banking/accounts", "list"),
    "payments": ("get", "/4.0/banking/payments", "self"),
    "payment_types": ("get", "/2.0/payment_type", "list"),
    # Projects and time tracking
    "projects": ("get", "/2.0/pr_project", "list"),
    "project_states": ("get", "/2.0/pr_project_state", "list"),
    "project_types": ("get", "/2.0/pr_project_type", "list"),
    "project_milestones": ("get", "/3.0/projects/{project_id}/milestones", "list"),
    "project_packages": ("get", "/3.0/projects/{project_id}/packages", "list"),
    "timesheets": ("get", "/2.0/timesheet", "list"),
    "timesheet_statuses": ("get", "/2.0/timesheet_status", "list"),
    "business_activities": ("get", "/2.0/client_service", "list"),
    "tasks": ("get", "/2.0/task", "list"),
    "task_priorities": ("get", "/2.0/todo_priority", "list"),
    "task_statuses": ("get", "/2.0/todo_status", "list"),
    "notes": ("get", "/2.0/note", "list"),
    "communication_types": ("get", "/2.0/communication_kind", "list"),
    # Other
    "users": ("get", "/3.0/users", "list"),
    "fictional_users": ("get", "/3.0/fictional_users", "list"),
    "company_profile": ("get", "/2.0/company_profile", "list"),
    "countries": ("get", "/2.0/country", "list"),
    "languages": ("get", "/2.0/language", "list"),
    "files": ("get", "/3.0/files", "list"),
    "permissions": ("get", "/3.0/permissions", "self"),
    # Payroll
    "payroll_employees": ("get", "/4.0/payroll/employees", "list"),
    "payroll_absences": ("get", "/4.0/payroll/employees/{employeeId}/absences", "list"),
}

# Streams whose endpoint is missing from the spec, or which need fields the tap adds.
STATIC_SCHEMAS: dict[str, dict[str, t.Any]] = {
    # Legacy endpoint, no longer in the OpenAPI spec.
    "contact_types": {"id": {"type": "integer"}, "name": {"type": "string"}},
}
_DOC_ID = {"document_id": {"type": "integer"}}
EXTRA_PROPERTIES: dict[str, dict[str, t.Any]] = {
    "contact_additional_addresses": {"contact_id": {"type": "integer"}},
    "invoice_positions": _DOC_ID,
    "offer_positions": _DOC_ID,
    "order_positions": _DOC_ID,
    "delivery_positions": _DOC_ID,
    "invoice_payments": _DOC_ID,
    "invoice_reminders": _DOC_ID,
    "invoice_comments": _DOC_ID,
    "offer_comments": _DOC_ID,
    "order_comments": _DOC_ID,
    "bill_outgoing_payments": {"bill_id": {"type": "string"}},
    "manual_entry_files": {"manual_entry_id": {"type": "integer"}},
    "currency_exchange_rates": {
        "currency_id": {"type": "integer"},
        "exchange_currency_id": {"type": "integer"},
    },
    "project_milestones": {"project_id": {"type": "integer"}},
    "project_packages": {"project_id": {"type": "integer"}},
    "payroll_absences": {"employee_id": {"type": "string"}, "business_year": {"type": "integer"}},
}
# Corrections from live API responses: undocumented fields, and free-form objects
# (no ``properties``, so every key is kept). Applied verbatim after conversion.
_BOOL, _INT, _NUM, _STR = (
    {"type": ["boolean", "null"]},
    {"type": ["integer", "null"]},
    {"type": ["number", "null"]},
    {"type": ["string", "null"]},
)
# Documented fields the API never returns: spec typos and write-only request fields.
# Removing a field that is not in the schema is an error, so stale entries surface.
_DOCUMENT_WRITE_ONLY = ("pr_project_id", "contact_address_manual", "delivery_address_manual")
SCHEMA_REMOVALS: dict[str, tuple[str, ...]] = {
    "contacts": ("titel_id",),  # typo of title_id
    "countries": ("iso3166_alpha2",),  # returned as iso_3166_alpha2
    "currency_exchange_rates": ("exchange_rate_to_ratio",),  # returned as factor_nr_to_ratio
    "expenses": ("chargeable_contact_id",),  # returned as chargeable_customer_id
    "invoices": ("pr_project_id", "contact_address_manual"),
    "offers": _DOCUMENT_WRITE_ONLY,
    "orders": _DOCUMENT_WRITE_ONLY,
    "notes": ("pr_project_id",),  # returned as project_id
    "project_milestones": ("pr_parent_milestone_id",),  # returned as parent_milestone_id
    "project_packages": ("pr_milestone_id",),  # returned as milestone_id
    "projects": ("document_nr",),  # returned as nr
    "tasks": ("have_remember", "pr_project_id"),  # returned as project_id
}
SCHEMA_PATCHES: dict[str, dict[str, t.Any]] = {
    "bank_accounts": {"esr_bottom_line_include_amount": _BOOL},
    "bill_outgoing_payments": {"is_salary_payment": _BOOL},
    "bills": {
        "average_exchange_rate_enabled": _BOOL,
        "reference_type": _STR,
        "reference_no": _STR,
    },
    "calendar_years": {"default_tax_income_id": _INT, "default_tax_expense_id": _INT},
    "contact_groups": {"uuid": _STR},
    # Partition key added by the tap (``show_archived`` returns only archived contacts).
    "contacts": {"archived": {"type": ["boolean", "null"]}},
    "countries": {"iso_3166_alpha2": _STR},
    "currency_exchange_rates": {"factor_nr_to_ratio": _NUM},
    "expenses": {"average_exchange_rate_enabled": _BOOL, "chargeable_customer_id": _INT},
    "files": {"processing_source": _STR, "processing_status": _STR},
    # Documented as an integer, returned as text ("Payment receipt").
    "invoice_payments": {"title": _STR},
    "manual_entries": {"booking_type": _STR},
    "manual_entry_files": {"processing_source": _STR, "processing_status": _STR},
    # Documented as a date, returned as a date-time ("2026-10-28T00:00:00+01:00").
    "journal": {"date": {"type": ["string", "null"], "format": "date-time"}},
    "permissions": {"permissions": {"type": ["object", "null"]}},
    # Documented as a number, returned as a decimal string ("123.000000").
    "payments": {"amount": _STR, "message": _STR},
    "project_milestones": {"parent_milestone_id": _INT},
    # ``milestone`` (embedded object, only seen as null so far) next to ``milestone_id``.
    "project_packages": {"milestone": {"type": ["object", "null"]}, "milestone_id": _INT},
    "purchase_orders": {
        "date_format": {
            "type": ["object", "null"],
            "properties": {"date_format_id": _INT, "date_format": _STR},
        },
    },
    # Documented as strings, returned as numbers.
    "projects": {"pr_budget_type_amount": _NUM, "pr_invoice_type_amount": _NUM},
    "timesheet_statuses": {"translation_key": _STR},
    "timesheets": {"task_id": _INT},
}


class SpecError(Exception):
    """Raised when the spec does not have the expected shape."""


def load_spec(source: str | None) -> dict[str, t.Any]:
    """Load the OpenAPI spec from the docs URL, a saved docs page, or a JSON file."""
    if source and source.endswith(".json"):
        return json.loads(Path(source).read_text(encoding="utf-8"))
    if source:
        page = Path(source).read_text(encoding="utf-8")
    else:
        response = requests.get(DOCS_URL, timeout=60)
        response.raise_for_status()
        page = response.text
    start = page.index(REDOC_MARKER) + len(REDOC_MARKER)
    state, _ = json.JSONDecoder().raw_decode(page[start:])
    return state["spec"]["data"]


class Converter:
    """Converts OpenAPI response schemas to Singer JSON schemas."""

    def __init__(self, spec: dict[str, t.Any]) -> None:
        """Store the spec used to resolve references."""
        self.spec = spec

    def deref(self, node: t.Any) -> t.Any:  # noqa: ANN401
        """Follow ``$ref`` pointers until a concrete node is reached."""
        while isinstance(node, dict) and "$ref" in node:
            target: t.Any = self.spec
            for part in node["$ref"].removeprefix("#/").split("/"):
                target = target[part]
            node = target
        return node

    def object_properties(self, node: dict[str, t.Any]) -> dict[str, t.Any] | None:
        """Collect properties of an object node, merging allOf/anyOf/oneOf variants."""
        node = self.deref(node)
        variants = [*node.get("allOf", []), *node.get("anyOf", []), *node.get("oneOf", [])]
        if not variants and "properties" not in node and node.get("type") != "object":
            return None
        properties: dict[str, t.Any] = {}
        for variant in variants:
            properties.update(self.object_properties(variant) or {})
        properties.update(node.get("properties", {}))
        return properties

    def convert(self, node: t.Any, depth: int = 0, *, top: bool = False) -> dict[str, t.Any]:  # noqa: ANN401
        """Convert one schema node into a nullable Singer schema node."""
        node = self.deref(node)
        if depth > 12:  # noqa: PLR2004 - guard against recursive schemas
            return {}
        properties = self.object_properties(node)
        if properties is not None:
            result: dict[str, t.Any] = {"type": ["object", "null"]}
            # Without declared properties, omit the key: ``"properties": {}`` drops every key.
            if properties:
                result["properties"] = {
                    name: self.convert(value, depth + 1) for name, value in properties.items()
                }
            return result
        variants = node.get("anyOf") or node.get("oneOf")
        if variants:
            types = sorted({ty for v in variants for ty in self.convert(v, depth + 1)["type"]})
            return {"type": types} if types else {}
        json_type = node.get("type")
        if json_type is None:
            return {}
        if json_type == "array":
            return {"type": ["array", "null"], "items": self.convert(node.get("items", {}), depth)}
        result: dict[str, t.Any] = {"type": [json_type, "null"]}
        fmt = node.get("format")
        if fmt == "date" or (fmt == "date-time" and top):
            result["format"] = fmt
        return result

    def record_schema(self, method: str, path: str, selector: str) -> dict[str, t.Any]:
        """Return the record-level schema for an endpoint."""
        operation = self.spec["paths"][path][method]
        response = self.deref(operation["responses"]["200"])
        schema = self.deref(response["content"]["application/json"]["schema"])
        if selector == "positions":
            detail = self.object_properties(schema) or {}
            schema = self.deref(self.deref(detail["positions"])["items"])
        elif selector == "list":
            if schema.get("type") != "array":
                schema = self.deref(schema["properties"]["data"])
            if schema.get("type") == "array":
                schema = self.deref(schema["items"])
        properties = self.object_properties(schema)
        if properties is None:
            msg = f"{method.upper()} {path} does not return objects"
            raise SpecError(msg)
        return self.wrap(properties)

    def wrap(self, properties: dict[str, t.Any]) -> dict[str, t.Any]:
        """Build a top-level stream schema from OpenAPI properties."""
        converted = {name: self.convert(value, top=True) for name, value in properties.items()}
        for name, schema in converted.items():
            # The spec types some timestamps (e.g. calendar_years.created_at) as ``date``,
            # but the API returns full date-times.
            if name.endswith("_at") and schema.get("format") == "date":
                schema["format"] = "date-time"
        return {"type": "object", "properties": converted}


def main() -> None:
    """Regenerate every stream schema file."""
    spec = load_spec(sys.argv[1] if len(sys.argv) > 1 else None)
    converter = Converter(spec)
    schemas = {name: converter.record_schema(*endpoint) for name, endpoint in ENDPOINTS.items()} | {
        name: converter.wrap(properties) for name, properties in STATIC_SCHEMAS.items()
    }
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in SCHEMAS_DIR.glob("*.json"):
        if stale.stem not in schemas:
            stale.unlink()
    for name, schema in sorted(schemas.items()):
        for prop, prop_schema in EXTRA_PROPERTIES.get(name, {}).items():
            schema["properties"][prop] = converter.convert(prop_schema, top=True)
        schema["properties"].update(SCHEMA_PATCHES.get(name, {}))
        for prop in SCHEMA_REMOVALS.get(name, ()):
            del schema["properties"][prop]
        path = SCHEMAS_DIR / f"{name}.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(f"Wrote {len(schemas)} schemas to {SCHEMAS_DIR}\n")


if __name__ == "__main__":
    main()
