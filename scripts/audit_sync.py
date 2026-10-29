"""Audit a tap-bexio sync against the stream schemas.

Reports, per stream with data: schema violations, fields the API returned that the schema
lacks (the SDK drops them), and schema fields absent from every record. Prints field names
and types only, never values.

Usage:
    set -a; source .env; set +a
    uv run tap-bexio --config ENV > sync.out 2> sync.err
    uv run scripts/audit_sync.py sync.out sync.err
"""

from __future__ import annotations

import collections
import json
import re
import sys
import typing as t
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

if t.TYPE_CHECKING:
    from jsonschema.protocols import Validator

DROPPED = re.compile(
    r"\| (\S+) +\| Properties \((.*)\) were present .* not found in catalog schema"
)


def main() -> None:
    """Print the audit for a sync's stdout and stderr files."""
    out_path, err_path = (Path(arg) for arg in sys.argv[1:3])
    validators: dict[str, Validator] = {}
    properties: dict[str, set[str]] = {}
    present: dict[str, set[str]] = collections.defaultdict(set)
    counts: collections.Counter[str] = collections.Counter()
    violations: dict[tuple[str, str], set[str]] = collections.defaultdict(set)

    for line in out_path.read_text(encoding="utf-8").splitlines():
        message = json.loads(line)
        stream = message.get("stream")
        if message["type"] == "SCHEMA":
            validators[stream] = Draft202012Validator(
                message["schema"], format_checker=FormatChecker()
            )
            properties[stream] = set(message["schema"]["properties"])
        elif message["type"] == "RECORD":
            record = message["record"]
            counts[stream] += 1
            present[stream] |= set(record)
            for error in validators[stream].iter_errors(record):
                path = re.sub(r"\.\d+(?=\.|$)", "[]", ".".join(map(str, error.path)))
                found = type(error.instance).__name__
                violations[stream, path].add(
                    f"{found}, expected {error.validator}={error.validator_value}"
                )

    out = sys.stdout
    out.write(f"streams with data: {len(counts)}\n\n== schema violations\n")
    for (stream, path), problems in sorted(violations.items()):
        out.write(f"  {stream}.{path}: {sorted(problems)}\n")
    out.write("\n== returned by the API but not in the schema (dropped)\n")
    for line in err_path.read_text(encoding="utf-8").splitlines():
        if match := DROPPED.search(line):
            out.write(f"  {match[1].removeprefix('tap-bexio.')}: {match[2]}\n")
    out.write("\n== in the schema but absent from every record\n")
    for stream in sorted(counts):
        absent = sorted(properties[stream] - present[stream])
        if absent:
            out.write(f"  {stream} ({counts[stream]} records): {absent}\n")


if __name__ == "__main__":
    main()
