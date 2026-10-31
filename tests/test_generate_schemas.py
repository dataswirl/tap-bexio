"""Tests for the schema generator script."""

from __future__ import annotations

import json
import typing as t
from types import SimpleNamespace

import pytest

from scripts import generate_schemas as gen
from scripts.generate_schemas import Converter, SpecError

NULLABLE_INT = {"type": ["integer", "null"]}
NULLABLE_STR = {"type": ["string", "null"]}


def ok(schema: dict[str, t.Any]) -> dict[str, t.Any]:
    """Wrap a schema as a 200 JSON response."""
    return {"responses": {"200": {"content": {"application/json": {"schema": schema}}}}}


def obj(**properties: t.Any) -> dict[str, t.Any]:
    return {"type": "object", "properties": properties}


INT = {"type": "integer"}
STR = {"type": "string"}


# -- deref -------------------------------------------------------------------


def test_deref_follows_a_chain_of_refs():
    spec = {"components": {"a": {"$ref": "#/components/b"}, "b": INT}}
    assert Converter(spec).deref({"$ref": "#/components/a"}) == INT


def test_deref_returns_non_ref_nodes_unchanged():
    assert Converter({}).deref(INT) is INT
    assert Converter({}).deref([1]) == [1]


# -- object_properties -------------------------------------------------------


def test_object_properties_merges_variants_then_own_properties():
    node = {
        "allOf": [obj(a=INT)],
        "anyOf": [obj(b=INT)],
        "oneOf": [obj(c=INT), STR],
        "properties": {"a": STR},
    }
    assert Converter({}).object_properties(node) == {"a": STR, "b": INT, "c": INT}


def test_object_properties_is_none_for_non_objects():
    assert Converter({}).object_properties(INT) is None


def test_object_properties_is_empty_for_a_bare_object():
    assert Converter({}).object_properties({"type": "object"}) == {}


def test_object_properties_resolves_refs():
    spec = {"s": obj(a=INT)}
    assert Converter(spec).object_properties({"$ref": "#/s"}) == {"a": INT}


# -- convert -----------------------------------------------------------------


def test_convert_object_with_properties():
    assert Converter({}).convert(obj(a=INT)) == {
        "type": ["object", "null"],
        "properties": {"a": NULLABLE_INT},
    }


def test_convert_object_without_properties_omits_the_key():
    assert Converter({}).convert({"type": "object"}) == {"type": ["object", "null"]}


def test_convert_treats_every_union_as_an_object():
    # object_properties accepts any node with variants, so scalar unions become objects.
    assert Converter({}).convert({"anyOf": [STR, INT]}) == {"type": ["object", "null"]}
    assert Converter({}).convert({"oneOf": [STR, obj(a=INT)]}) == {
        "type": ["object", "null"],
        "properties": {"a": NULLABLE_INT},
    }


def test_convert_untyped_node_is_empty():
    assert Converter({}).convert({"description": "anything"}) == {}


def test_convert_array():
    assert Converter({}).convert({"type": "array", "items": INT}) == {
        "type": ["array", "null"],
        "items": NULLABLE_INT,
    }
    assert Converter({}).convert({"type": "array"}) == {"type": ["array", "null"], "items": {}}


def test_convert_keeps_date_everywhere_and_date_time_only_at_top():
    converter = Converter({})
    date = {"type": "string", "format": "date"}
    date_time = {"type": "string", "format": "date-time"}
    assert converter.convert(date)["format"] == "date"
    assert "format" not in converter.convert(date_time)
    assert converter.convert(date_time, top=True)["format"] == "date-time"
    assert "format" not in converter.convert({"type": "string", "format": "email"}, top=True)


def test_convert_stops_at_recursion_depth():
    spec = {"node": obj(child={"$ref": "#/node"})}
    schema = Converter(spec).convert({"$ref": "#/node"})
    for _ in range(13):
        schema = schema["properties"]["child"]
    assert schema == {}


# -- record_schema -----------------------------------------------------------


def spec_with(schema: dict[str, t.Any]) -> dict[str, t.Any]:
    return {"paths": {"/x": {"get": ok(schema)}}}


WRAPPED = {"type": "object", "properties": {"a": NULLABLE_INT}}


def test_record_schema_self():
    assert Converter(spec_with(obj(a=INT))).record_schema("get", "/x", "self") == WRAPPED


def test_record_schema_list_of_items():
    schema = {"type": "array", "items": obj(a=INT)}
    assert Converter(spec_with(schema)).record_schema("get", "/x", "list") == WRAPPED


def test_record_schema_list_under_data():
    schema = obj(data={"type": "array", "items": obj(a=INT)})
    assert Converter(spec_with(schema)).record_schema("get", "/x", "list") == WRAPPED


def test_record_schema_positions():
    schema = obj(positions={"type": "array", "items": obj(a=INT)})
    assert Converter(spec_with(schema)).record_schema("get", "/x", "positions") == WRAPPED


def test_record_schema_follows_refs_to_response_and_schema():
    spec = {
        "paths": {"/x": {"get": {"responses": {"200": {"$ref": "#/r"}}}}},
        "r": {"content": {"application/json": {"schema": {"$ref": "#/s"}}}},
        "s": obj(a=INT),
    }
    assert Converter(spec).record_schema("get", "/x", "self") == WRAPPED


def test_wrap_keeps_top_level_date_times():
    schema = Converter({}).wrap({"at": {"type": "string", "format": "date-time"}})
    assert schema["properties"]["at"]["format"] == "date-time"


def test_record_schema_rejects_non_objects():
    with pytest.raises(SpecError, match="GET /x does not return objects"):
        Converter(spec_with(STR)).record_schema("get", "/x", "self")


# -- override_format ---------------------------------------------------------


def schema_for_overrides() -> dict[str, t.Any]:
    return {
        "type": "object",
        "properties": {
            "a": {"type": ["string", "null"], "format": "date"},
            "b": {"type": ["object", "null"], "properties": {"c": NULLABLE_STR}},
            "d": {"type": ["array", "null"], "items": {"type": ["string", "null"]}},
        },
    }


def test_override_format_sets_top_level_nested_and_array_items():
    schema = schema_for_overrides()
    gen.override_format(schema, "a", "date-time")
    gen.override_format(schema, "b.c", "date")
    gen.override_format(schema, "d[]", "date")
    properties = schema["properties"]
    assert properties["a"]["format"] == "date-time"
    assert properties["b"]["properties"]["c"]["format"] == "date"
    assert properties["d"]["items"]["format"] == "date"


def test_override_format_none_drops_the_format():
    schema = schema_for_overrides()
    gen.override_format(schema, "a", None)
    gen.override_format(schema, "b.c", None)
    assert "format" not in schema["properties"]["a"]
    assert "format" not in schema["properties"]["b"]["properties"]["c"]


def test_override_format_rejects_unknown_fields():
    with pytest.raises(KeyError):
        gen.override_format(schema_for_overrides(), "missing", "date")


# -- spec_path ---------------------------------------------------------------


def paths(*names: str) -> dict[str, t.Any]:
    return {"paths": {name: {} for name in names}}


def test_spec_path_exact_match():
    assert gen.spec_path(paths("/2.0/a", "/2.0/b"), "/2.0/b") == "/2.0/b"


def test_spec_path_parameters_match_any_name():
    spec = paths("/2.0/contact/{id}/address")
    assert gen.spec_path(spec, "/2.0/contact/{contact_id}/address") == "/2.0/contact/{id}/address"


def test_spec_path_parameter_matches_a_literal_segment():
    spec = paths("/2.0/{kb_document_type}/{id}")
    assert gen.spec_path(spec, "/2.0/kb_offer/{document_id}") == "/2.0/{kb_document_type}/{id}"


def test_spec_path_exact_literals_win():
    spec = paths("/2.0/{kb_document_type}/{id}", "/2.0/kb_offer/{id}")
    assert gen.spec_path(spec, "/2.0/kb_offer/{document_id}") == "/2.0/kb_offer/{id}"


def test_spec_path_ties_keep_the_first_spec_path():
    spec = paths("/2.0/{a}/x", "/2.0/{b}/x")
    assert gen.spec_path(spec, "/2.0/kb_offer/x") == "/2.0/{a}/x"


def test_spec_path_requires_the_same_segment_count():
    with pytest.raises(SpecError, match=r"/2\.0/a is not in the spec"):
        gen.spec_path(paths("/2.0/a/b", "/2.0"), "/2.0/a")


def test_spec_path_rejects_mismatched_literals():
    with pytest.raises(SpecError):
        gen.spec_path(paths("/2.0/b"), "/2.0/a")


# -- load_spec ---------------------------------------------------------------

SPEC = {"paths": {}}
PAGE = f"<script>{gen.REDOC_MARKER}{json.dumps({'spec': {'data': SPEC}})};</script>"


def test_load_spec_from_json(tmp_path):
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(SPEC), encoding="utf-8")
    assert gen.load_spec(str(path)) == SPEC


def test_load_spec_from_saved_docs_page(tmp_path):
    path = tmp_path / "docs.html"
    path.write_text(PAGE, encoding="utf-8")
    assert gen.load_spec(str(path)) == SPEC


def test_load_spec_downloads_the_docs(mocked):
    mocked.get(gen.DOCS_URL, body=PAGE)
    assert gen.load_spec(None) == SPEC


# -- endpoints and context properties ----------------------------------------


def tap_spec() -> dict[str, t.Any]:
    """Return a spec with one path per tap stream."""
    return paths(*(stream.path for stream in gen.tap_streams()))


def test_endpoints_cover_every_stream_except_static_ones():
    result = gen.endpoints(tap_spec())
    names = {stream.name for stream in gen.tap_streams()}
    assert set(result) == names - set(gen.STATIC_SCHEMAS)


def test_endpoints_pick_selectors_from_the_records_jsonpath():
    result = gen.endpoints(tap_spec())
    assert result["contacts"] == ("get", "/2.0/contact", "list")
    assert result["bills"] == ("get", "/4.0/purchase/bills", "list")
    assert result["permissions"] == ("get", "/3.0/permissions", "self")
    assert result["invoice_positions"][2] == "positions"


def test_endpoints_apply_selector_overrides():
    assert gen.endpoints(tap_spec())["payments"][2] == "self"


def test_context_properties_type_each_child_key_like_its_parents_id():
    schemas = {stream.name: {"properties": {"id": NULLABLE_INT}} for stream in gen.tap_streams()}
    schemas["contacts"]["properties"]["id"] = NULLABLE_STR
    result = gen.context_properties(schemas)
    assert result["contact_additional_addresses"] == {"contact_id": NULLABLE_STR}
    assert result["invoice_comments"] == {"document_id": NULLABLE_INT}
    assert "contacts" not in result


# -- building and writing schemas --------------------------------------------


def stream(name: str, path: str, jsonpath: str = "$[*]", key: str | None = None, children=()):
    return SimpleNamespace(
        name=name,
        path=path,
        records_jsonpath=jsonpath,
        child_context_key=key,
        child_streams=list(children),
    )


@pytest.fixture
def fake_tap(monkeypatch):
    """Replace the tap's streams and correction tables with a parent and child."""
    child = stream("child", "/2.0/parent/{parent_id}/child")
    streams = [stream("parent", "/2.0/parent", key="parent_id", children=[child]), child]
    monkeypatch.setattr(gen, "tap_streams", lambda: streams)
    monkeypatch.setattr(gen, "STATIC_SCHEMAS", {"static": {"id": INT}})
    for table in ("EXTRA_PROPERTIES", "SCHEMA_PATCHES", "SCHEMA_REMOVALS", "FORMAT_OVERRIDES"):
        monkeypatch.setattr(gen, table, {})
    listing = {"type": "array", "items": obj(id=STR, name=STR)}
    return {
        "paths": {
            "/2.0/parent": {"get": ok(listing)},
            "/2.0/parent/{id}/child": {"get": ok(listing)},
        }
    }


def test_build_schemas_adds_static_schemas_and_context_keys(fake_tap):
    schemas = gen.build_schemas(fake_tap)
    assert set(schemas) == {"parent", "child", "static"}
    assert schemas["child"]["properties"]["parent_id"] == {"type": ["string", "null"]}
    assert "parent_id" not in schemas["parent"]["properties"]
    assert schemas["static"] == {"type": "object", "properties": {"id": NULLABLE_INT}}


def test_build_schemas_applies_corrections(fake_tap, monkeypatch):
    monkeypatch.setattr(gen, "SCHEMA_REMOVALS", {"parent": ("name",)})
    assert set(gen.build_schemas(fake_tap)["parent"]["properties"]) == {"id"}


def test_apply_corrections_in_order(monkeypatch):
    extra = {"year": INT, "at": {"type": "string", "format": "date-time"}}
    monkeypatch.setattr(gen, "EXTRA_PROPERTIES", {"s": extra})
    monkeypatch.setattr(gen, "SCHEMA_PATCHES", {"s": {"when": NULLABLE_STR, "gone": INT}})
    monkeypatch.setattr(gen, "SCHEMA_REMOVALS", {"s": ("gone",)})
    monkeypatch.setattr(gen, "FORMAT_OVERRIDES", {"s": {"when": "date-time"}})
    schema = {"type": "object", "properties": {"id": NULLABLE_INT}}
    gen.apply_corrections("s", schema, Converter({}))
    assert schema["properties"] == {
        "id": NULLABLE_INT,
        "year": NULLABLE_INT,
        "at": {"type": ["string", "null"], "format": "date-time"},
        "when": {"type": ["string", "null"], "format": "date-time"},
    }


def test_apply_corrections_rejects_stale_removals(monkeypatch):
    monkeypatch.setattr(gen, "SCHEMA_REMOVALS", {"s": ("missing",)})
    with pytest.raises(KeyError):
        gen.apply_corrections("s", {"properties": {}}, Converter({}))


def test_apply_corrections_leaves_other_streams_alone():
    schema = {"type": "object", "properties": {"id": NULLABLE_INT}}
    gen.apply_corrections("not_a_stream", schema, Converter({}))
    assert schema == {"type": "object", "properties": {"id": NULLABLE_INT}}


def test_write_schemas_writes_sorted_json_and_removes_stale_files(tmp_path):
    directory = tmp_path / "schemas"
    directory.mkdir()
    (directory / "old.json").write_text("{}", encoding="utf-8")
    (directory / "notes.txt").write_text("keep", encoding="utf-8")
    gen.write_schemas({"a": {"type": "object", "properties": {}}}, directory)
    assert sorted(p.name for p in directory.iterdir()) == ["a.json", "notes.txt"]
    assert (directory / "a.json").read_text(encoding="utf-8") == (
        '{\n  "properties": {},\n  "type": "object"\n}\n'
    )


def test_write_schemas_creates_the_directory(tmp_path):
    gen.write_schemas({"a": {}}, tmp_path / "new" / "schemas")
    assert (tmp_path / "new" / "schemas" / "a.json").exists()


def test_main_regenerates_from_a_spec_file(fake_tap, tmp_path, monkeypatch, capsys):
    spec_file = tmp_path / "openapi.json"
    spec_file.write_text(json.dumps(fake_tap), encoding="utf-8")
    monkeypatch.setattr(gen, "SCHEMAS_DIR", tmp_path / "out")
    monkeypatch.setattr("sys.argv", ["generate_schemas.py", str(spec_file)])
    gen.main()
    assert sorted(p.stem for p in (tmp_path / "out").iterdir()) == ["child", "parent", "static"]
    assert capsys.readouterr().out == f"Wrote 3 schemas to {tmp_path / 'out'}\n"


def test_main_downloads_the_docs_without_an_argument(fake_tap, tmp_path, monkeypatch, mocked):
    page = f"{gen.REDOC_MARKER}{json.dumps({'spec': {'data': fake_tap}})}"
    mocked.get(gen.DOCS_URL, body=page)
    monkeypatch.setattr(gen, "SCHEMAS_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["generate_schemas.py"])
    gen.main()
    assert len(list(tmp_path.glob("*.json"))) == 3
