"""README and meltano.yml describe the same settings and streams as the tap."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tap_bexio.client import BexioStream
from tap_bexio.tap import SETTINGS as TAP_SETTINGS
from tap_bexio.tap import TapBexio

ROOT = Path(__file__).parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
SCHEMA = TAP_SETTINGS.to_dict()
SETTINGS = SCHEMA["properties"]


def _kind(prop: dict) -> str:
    if "enum" in prop:
        return "options"
    if prop.get("format") == "date-time":
        return "date_iso8601"
    types = prop["type"] if isinstance(prop["type"], list) else [prop["type"]]
    return next(ty for ty in types if ty != "null")


def _table(heading_cell: str) -> list[list[str]]:
    """Return the rows of the README table whose header starts with ``heading_cell``."""
    lines = README.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"| {heading_cell}"))
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip().strip("`") for cell in line.strip("|").split("|")])
    return rows


def _meltano_settings(plugin: dict) -> dict[str, dict]:
    return {setting["name"]: setting for setting in plugin["settings"]}


def _expected_setting(name: str) -> dict:
    prop = SETTINGS[name]
    expected = {"kind": _kind(prop)}
    if "default" in prop:
        expected["value"] = prop["default"]
    if prop.get("secret"):
        expected["sensitive"] = True
    if "enum" in prop:
        expected["options"] = prop["enum"]
    return expected


def _actual_setting(setting: dict, keys: dict) -> dict:
    actual = {key: setting[key] for key in keys if key in setting and key != "options"}
    if "options" in setting:
        actual["options"] = [option["value"] for option in setting["options"]]
    return actual


def test_meltano_yml_settings_match_the_tap():
    meltano = yaml.safe_load((ROOT / "meltano.yml").read_text(encoding="utf-8"))
    settings = _meltano_settings(meltano["plugins"]["extractors"][0])
    assert list(settings) == list(SETTINGS)
    for name, setting in settings.items():
        expected = _expected_setting(name)
        assert _actual_setting(setting, expected) == expected, name
        assert setting["description"].rstrip(".") == SETTINGS[name]["description"].rstrip(".")


def test_readme_meltano_snippet_lists_every_setting():
    snippet = re.search(r"```yaml\n(plugins:.*?)```", README, re.DOTALL)
    assert snippet
    settings = _meltano_settings(yaml.safe_load(snippet[1])["plugins"]["extractors"][0])
    assert list(settings) == list(SETTINGS)
    for name, setting in settings.items():
        assert setting["kind"] == _kind(SETTINGS[name]), name


def test_readme_settings_table_matches_the_tap():
    rows = {row[0]: row for row in _table("Setting")}
    assert list(rows) == list(SETTINGS)
    for name, (_, required, default, _) in rows.items():
        assert (required == "yes") == (name in SCHEMA.get("required", [])), name
        assert default == str(SETTINGS[name].get("default", "")), name


@pytest.fixture(scope="module")
def streams() -> list[BexioStream]:
    tap = TapBexio(config={"auth_token": "dummy"})
    return [s for s in tap.streams.values() if isinstance(s, BexioStream)]


def test_readme_stream_table_matches_the_tap(streams):
    expected = sorted(
        [
            s.name,
            s.path,
            "incremental" if s.replication_key else "full",
            s.parent_stream_type.name if s.parent_stream_type else "",
        ]
        for s in streams
    )
    assert _table("Stream") == expected
