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

from tap_bexio.client import BexioStream
from tap_bexio.tap import TapBexio

DOCS_URL = "https://docs.bexio.com/"
REDOC_MARKER = "__redoc_state = "
SCHEMAS_DIR = Path(__file__).parent.parent / "src" / "tap_bexio" / "schemas"

# Record selectors: "list" -> array items or ``data`` items, "self" -> the response object
# itself, "positions" -> items of the ``positions`` array in a document detail response.
# They follow each stream's ``records_jsonpath``, except where the spec disagrees with the API.
SELECTORS = {"$": "self", "$.positions[*]": "positions"}
SELECTOR_OVERRIDES = {
    # Documented as a single payment object; the API returns a list under ``results``.
    "payments": "self",
}

# Streams whose endpoint is missing from the spec, or which need fields the tap adds.
STATIC_SCHEMAS: dict[str, dict[str, t.Any]] = {
    # Legacy endpoint, no longer in the OpenAPI spec.
    "contact_types": {"id": {"type": "integer"}, "name": {"type": "string"}},
}
# Fields the tap adds beyond the parent's context key (which is derived from the parent's id).
EXTRA_PROPERTIES: dict[str, dict[str, t.Any]] = {
    "currency_exchange_rates": {"exchange_currency_id": {"type": "integer"}},
    "payroll_absences": {"business_year": {"type": "integer"}},
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
# Date/date-time formats where the spec disagrees with live API responses. Keys are field
# paths ("." for nested objects, "[]" for array items); None drops the format. Overriding a
# field that is not in the schema is an error, so stale entries surface.
_DATE_TIME, _DATE = "date-time", "date"
FORMAT_OVERRIDES: dict[str, dict[str, str | None]] = {
    # Documented as dates, returned as date-times ("2026-10-28T12:35:15+01:00").
    "calendar_years": {"created_at": _DATE_TIME, "updated_at": _DATE_TIME},
    "purchase_orders": {"created_at": _DATE_TIME, "updated_at": _DATE_TIME},
    # Documented as dates; only null seen so far, assumed to match created_at on 3.0.
    "business_years": {"closed_at": _DATE_TIME},
    "vat_periods": {"closed_at": _DATE_TIME},
    # Documented with the invalid format "datetime", returned as "2026-10-28T15:49:46+01:00".
    "payments": {"created_at": _DATE_TIME},
    # Undocumented format, returned as local time ("2026-10-28 15:08:33").
    "invoice_comments": {"date": _DATE_TIME},
    "offer_comments": {"date": _DATE_TIME},
    "order_comments": {"date": _DATE_TIME},
    # Nested, so the converter drops the format; returned as local time ("2026-10-31 08:15:00").
    "timesheets": {"tracking.start": _DATE_TIME, "tracking.end": _DATE_TIME},
    # Undocumented format, returned as "2026-10-31".
    "currencies": {"exchange_rate_date": _DATE},
    "currency_exchange_rates": {"exchange_rate_date": _DATE},
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
        """Convert one schema node into a nullable Singer schema node.

        Any node with allOf/anyOf/oneOf variants converts as an object.
        """
        node = self.deref(node)
        if depth > 12:  # noqa: PLR2004 - guard against recursive schemas
            return {}
        properties = self.object_properties(node)
        if properties is not None:
            return self._convert_object(properties, depth)
        if node.get("type") == "array":
            return {"type": ["array", "null"], "items": self.convert(node.get("items", {}), depth)}
        return _convert_scalar(node, top=top)

    def _convert_object(self, properties: dict[str, t.Any], depth: int) -> dict[str, t.Any]:
        result: dict[str, t.Any] = {"type": ["object", "null"]}
        # Without declared properties, omit the key: ``"properties": {}`` drops every key.
        if properties:
            result["properties"] = {
                name: self.convert(value, depth + 1) for name, value in properties.items()
            }
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
        return {"type": "object", "properties": converted}


def _convert_scalar(node: dict[str, t.Any], *, top: bool) -> dict[str, t.Any]:
    """Convert a typed leaf node, keeping dates everywhere and date-times only at the top."""
    json_type = node.get("type")
    if json_type is None:
        return {}
    result: dict[str, t.Any] = {"type": [json_type, "null"]}
    fmt = node.get("format")
    if fmt == "date" or (fmt == "date-time" and top):
        result["format"] = fmt
    return result


def override_format(schema: dict[str, t.Any], path: str, fmt: str | None) -> None:
    """Set (or with ``None`` drop) the format of the property at ``path``."""
    node = schema
    for part in path.replace("[]", ".[]").split("."):
        if part == "[]":
            node = node["items"]
        elif part:
            node = node["properties"][part]
    if fmt is None:
        node.pop("format", None)
    else:
        node["format"] = fmt


def spec_path(spec: dict[str, t.Any], path: str) -> str:
    """Return the spec path that ``path`` (a stream path) is served under.

    Parameters match whatever the spec names them, and a spec parameter also matches a
    literal segment (``/2.0/{kb_document_type}/...``); exact literals win.
    """
    segments = path.split("/")
    scored = [
        (score, candidate)
        for candidate in spec["paths"]
        if (score := _match_score(segments, candidate.split("/"))) is not None
    ]
    if not scored:
        msg = f"{path} is not in the spec"
        raise SpecError(msg)
    # max() keeps the first of equal scores, as the spec lists them.
    return max(scored, key=lambda pair: pair[0])[1]


def _match_score(segments: list[str], parts: list[str]) -> int | None:
    """Count the literal segments ``parts`` shares with ``segments``; None if it cannot match."""
    if len(parts) != len(segments):
        return None
    score = 0
    for ours, theirs in zip(segments, parts, strict=True):
        if ours == theirs:
            score += 1
        elif not theirs.startswith("{"):
            return None
    return score


def tap_streams() -> list[BexioStream]:
    """Return the tap's streams, which define the paths, selectors and context keys."""
    tap = TapBexio(config={"auth_token": "unused"}, setup_mapper=False)
    return [stream for stream in tap.streams.values() if isinstance(stream, BexioStream)]


def endpoints(spec: dict[str, t.Any]) -> dict[str, tuple[str, str, str]]:
    """Return ``(method, spec path, selector)`` for every stream with a spec endpoint."""
    result = {}
    for stream in tap_streams():
        if stream.name in STATIC_SCHEMAS:
            continue
        selector = SELECTOR_OVERRIDES.get(
            stream.name, SELECTORS.get(stream.records_jsonpath, "list")
        )
        result[stream.name] = ("get", spec_path(spec, stream.path), selector)
    return result


def context_properties(schemas: dict[str, dict[str, t.Any]]) -> dict[str, dict[str, t.Any]]:
    """Return each child's context key, typed like its parent's ``id``."""
    result: dict[str, dict[str, t.Any]] = {}
    for parent in tap_streams():
        if parent.child_context_key is None:
            continue
        parent_id = schemas[parent.name]["properties"]["id"]
        for child in parent.child_streams:
            result[child.name] = {parent.child_context_key: {"type": parent_id["type"]}}
    return result


def build_schemas(spec: dict[str, t.Any]) -> dict[str, dict[str, t.Any]]:
    """Return every stream schema: converted from the spec, with context keys and corrections."""
    converter = Converter(spec)
    schemas = {
        name: converter.record_schema(*endpoint) for name, endpoint in endpoints(spec).items()
    } | {name: converter.wrap(properties) for name, properties in STATIC_SCHEMAS.items()}
    context = context_properties(schemas)
    for name, schema in schemas.items():
        schema["properties"].update(context.get(name, {}))
        apply_corrections(name, schema, converter)
    return schemas


def apply_corrections(name: str, schema: dict[str, t.Any], converter: Converter) -> None:
    """Apply the extra properties, patches, removals and format overrides for a stream."""
    properties = schema["properties"]
    for prop, prop_schema in EXTRA_PROPERTIES.get(name, {}).items():
        properties[prop] = converter.convert(prop_schema, top=True)
    properties.update(SCHEMA_PATCHES.get(name, {}))
    for prop in SCHEMA_REMOVALS.get(name, ()):
        del properties[prop]
    for prop, fmt in FORMAT_OVERRIDES.get(name, {}).items():
        override_format(schema, prop, fmt)


def write_schemas(schemas: dict[str, dict[str, t.Any]], directory: Path) -> None:
    """Write one JSON file per schema and delete files for streams that no longer exist."""
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("*.json"):
        if stale.stem not in schemas:
            stale.unlink()
    for name, schema in sorted(schemas.items()):
        path = directory / f"{name}.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    """Regenerate every stream schema file."""
    spec = load_spec(sys.argv[1] if len(sys.argv) > 1 else None)
    schemas = build_schemas(spec)
    write_schemas(schemas, SCHEMAS_DIR)
    sys.stdout.write(f"Wrote {len(schemas)} schemas to {SCHEMAS_DIR}\n")


if __name__ == "__main__":
    main()
