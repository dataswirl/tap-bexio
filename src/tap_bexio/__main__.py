"""Run tap-bexio as a module: ``python -m tap_bexio``."""

from __future__ import annotations

from tap_bexio.tap import TapBexio

TapBexio.cli()
