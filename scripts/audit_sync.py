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
import dataclasses
import json
import re
import sys
import typing as t
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

if t.TYPE_CHECKING:
    from jsonschema.exceptions import ValidationError
    from jsonschema.protocols import Validator

DROPPED = re.compile(
    r"\| (\S+) +\| Properties \((.*)\) were present .* not found in catalog schema"
)


@dataclasses.dataclass
class Audit:
    """What a sync's messages show about each stream."""

    validators: dict[str, Validator] = dataclasses.field(default_factory=dict)
    properties: dict[str, set[str]] = dataclasses.field(default_factory=dict)
    present: dict[str, set[str]] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(set)
    )
    counts: collections.Counter[str] = dataclasses.field(default_factory=collections.Counter)
    violations: dict[tuple[str, str], set[str]] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(set)
    )

    def read(self, line: str) -> None:
        """Take in one Singer message: SCHEMA and RECORD count, everything else is ignored."""
        message = json.loads(line)
        stream = message.get("stream")
        if message["type"] == "SCHEMA":
            self.validators[stream] = Draft202012Validator(
                message["schema"], format_checker=FormatChecker()
            )
            self.properties[stream] = set(message["schema"]["properties"])
        elif message["type"] == "RECORD":
            self.record(stream, message["record"])

    def record(self, stream: str, record: dict[str, t.Any]) -> None:
        """Count a record, note its fields and collect its schema violations."""
        self.counts[stream] += 1
        self.present[stream] |= set(record)
        for error in self.validators[stream].iter_errors(record):
            found = type(error.instance).__name__
            self.violations[stream, violation_path(error)].add(
                f"{found}, expected {error.validator}={error.validator_value}"
            )


def violation_path(error: ValidationError) -> str:
    """Return the field path of an error, with array indexes collapsed to ``[]``."""
    return re.sub(r"\.\d+(?=\.|$)", "[]", ".".join(map(str, error.path)))


def write_report(audit: Audit, err_lines: list[str], out: t.TextIO) -> None:
    """Write the three report sections."""
    out.write(f"streams with data: {len(audit.counts)}\n\n== schema violations\n")
    out.writelines(
        f"  {stream}.{path}: {sorted(problems)}\n"
        for (stream, path), problems in sorted(audit.violations.items())
    )
    out.write("\n== returned by the API but not in the schema (dropped)\n")
    for line in err_lines:
        if match := DROPPED.search(line):
            out.write(f"  {match[1].removeprefix('tap-bexio.')}: {match[2]}\n")
    out.write("\n== in the schema but absent from every record\n")
    for stream in sorted(audit.counts):
        absent = sorted(audit.properties[stream] - audit.present[stream])
        if absent:
            out.write(f"  {stream} ({audit.counts[stream]} records): {absent}\n")


def main() -> None:
    """Print the audit for a sync's stdout and stderr files."""
    out_path, err_path = (Path(arg) for arg in sys.argv[1:3])
    audit = Audit()
    for line in out_path.read_text(encoding="utf-8").splitlines():
        audit.read(line)
    write_report(audit, err_path.read_text(encoding="utf-8").splitlines(), sys.stdout)


if __name__ == "__main__":
    main()
