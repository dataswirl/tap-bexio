"""Tests standard tap features using the built-in SDK tests library."""

from __future__ import annotations

import os

import pytest
from singer_sdk.testing import SuiteConfig, get_tap_test_class
from singer_sdk.testing.suites import SingerTestSuite, tap_stream_tests
from singer_sdk.testing.tap_tests import StreamReturnsRecordTest

from tap_bexio.tap import TapBexio

SAMPLE_CONFIG = {
    "auth_token": os.environ.get("TAP_BEXIO_AUTH_TOKEN", ""),
}


class StreamReturnsRecordIfAnyTest(StreamReturnsRecordTest):
    """Pass when the stream returned records; skip only when it really returned none.

    The SDK version skips every ignored stream without counting its records.
    """

    def test(self) -> None:
        """Run test."""
        if not self.stream_records and self.ignore_no_records:
            pytest.skip(f"No records returned in stream '{self.stream.name}'")
        assert self.stream_records, f"No records returned in stream '{self.stream.name}'."


stream_tests = SingerTestSuite(
    kind=tap_stream_tests.kind,
    tests=[
        StreamReturnsRecordIfAnyTest if test is StreamReturnsRecordTest else test
        for test in tap_stream_tests.tests
    ],
)

if SAMPLE_CONFIG["auth_token"]:
    TestTapBexio = get_tap_test_class(
        tap_class=TapBexio,
        config=SAMPLE_CONFIG,
        include_stream_tests=False,
        custom_suites=[stream_tests],
        # Many endpoints have no data in a test company; validate the ones that do.
        suite_config=SuiteConfig(ignore_no_records=True),
    )
else:
    pytest.skip("TAP_BEXIO_AUTH_TOKEN not set", allow_module_level=True)
