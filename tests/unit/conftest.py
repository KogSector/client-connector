"""Minimal conftest for unit tests that import real production modules.

The top-level `tests/conftest.py` stubs out `app.auth` and
`app.services.query_processor` to prevent the full app from booting.

Tests in THIS directory need the REAL implementations of those modules
(specifically `app.auth.internal_token` and `app.services.query_processor`).
We undo the stubs by loading the real modules directly before any test code
imports them.
"""
from __future__ import annotations

import importlib
import sys


def _restore(dotted_name: str) -> None:
    """Remove the stub and force a real import of the module."""
    # Pop both the name and any cached parent stubs that block it
    sys.modules.pop(dotted_name, None)
    module = importlib.import_module(dotted_name)
    sys.modules[dotted_name] = module
    return module


# Restore the real internal_token module so tests can import it directly.
# We do NOT restore app.auth (the package) because that would chain-load
# app.main → Settings() → missing env vars → crash.
# Instead we inject internal_token under its full dotted name only.
import types as _types

_internal_token_path = "app/auth/internal_token.py"
_spec = importlib.util.spec_from_file_location(
    "app.auth.internal_token",
    __file__.replace("tests/unit/conftest.py", _internal_token_path),
)
_real_internal_token = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_real_internal_token)
sys.modules["app.auth.internal_token"] = _real_internal_token

# Restore the real query_processor module.
# It imports app.auth.internal_token (now stubbed above) and httpx — both safe.
_qp_path = "app/services/query_processor.py"
_spec2 = importlib.util.spec_from_file_location(
    "app.services.query_processor",
    __file__.replace("tests/unit/conftest.py", _qp_path),
)
_real_qp = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(_real_qp)
sys.modules["app.services.query_processor"] = _real_qp
