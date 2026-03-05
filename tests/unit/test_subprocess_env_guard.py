"""Tests for subprocess mode ENV guard in McpClient._start_subprocess().

Requirements verified:
1. subprocess mode raises AssertionError when ENV != "local"
2. subprocess mode proceeds past ENV check when ENV == "local"
3. validate_secrets() raises RuntimeError for subprocess + non-local ENV
4. shell=True is never used (structural assertion on Popen kwargs)
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: load the real mcp_client and config modules in isolation
# without triggering app/__init__.py → app.main → Settings() chain.
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parents[2]  # client-connector/


def _load(dotted: str, rel_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(dotted, _ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = mod
    return spec, mod


# Load internal_token first (no deps)
_it_spec, _it_mod = _load("app.auth.internal_token", "app/auth/internal_token.py")
_it_spec.loader.exec_module(_it_mod)

# Stub app.config (avoid Settings() without env vars)
_stub_settings = MagicMock()
_stub_settings.env = "production"          # default: non-local
_stub_settings.mcp_server_mode = "subprocess"
_stub_settings.mcp_server_path = "/usr/local/bin/mcp-server"

_config_stub = ModuleType("app.config")
_config_stub.get_settings = MagicMock(return_value=_stub_settings)
_config_stub.Settings = MagicMock()
sys.modules["app.config"] = _config_stub

# Stub app.schemas
_schemas_stub = ModuleType("app.schemas")
_schemas_stub.JsonRpcRequest = MagicMock()
_schemas_stub.JsonRpcResponse = MagicMock()
sys.modules["app.schemas"] = _schemas_stub

# Now load the real mcp_client module
_mc_spec, _mc_mod = _load("app.services.mcp_client", "app/services/mcp_client.py")
_mc_spec.loader.exec_module(_mc_mod)

McpClient = _mc_mod.McpClient


# Also load the real config module for validate_secrets tests
_cfg_spec, _cfg_mod = _load("_real_config", "app/config.py")
# We need to intercept the Settings() call to avoid missing env vars
# so we test validate_secrets() directly with a MagicMock settings object.


# ---------------------------------------------------------------------------
# Helper: build a McpClient with specific settings already injected
# ---------------------------------------------------------------------------

def _make_client(env: str, mode: str = "subprocess", path: str = "/bin/mcp") -> McpClient:
    client = McpClient.__new__(McpClient)
    s = MagicMock()
    s.env = env
    s.mcp_server_mode = mode
    s.mcp_server_path = path
    s.mcp_server_url = "http://localhost:7777"
    client.settings = s
    client._process = None
    client._http_client = None
    client._request_id = 0
    client._pending_requests = {}
    client._read_task = None
    import asyncio
    client._lock = asyncio.Lock()
    return client


# ---------------------------------------------------------------------------
# 1. AssertionError when ENV != "local" and mode == "subprocess"
# ---------------------------------------------------------------------------

class TestSubprocessEnvGuard:

    @pytest.mark.asyncio
    async def test_raises_assertion_error_in_production(self):
        """subprocess mode must raise AssertionError when ENV=production."""
        client = _make_client(env="production")
        with pytest.raises(AssertionError, match="Subprocess mode forbidden in ENV='production'"):
            await client._start_subprocess()

    @pytest.mark.asyncio
    async def test_raises_assertion_error_in_staging(self):
        """subprocess mode must raise AssertionError when ENV=staging."""
        client = _make_client(env="staging")
        with pytest.raises(AssertionError, match="Subprocess mode forbidden in ENV='staging'"):
            await client._start_subprocess()

    @pytest.mark.asyncio
    async def test_raises_assertion_error_in_development(self):
        """subprocess mode must raise AssertionError when ENV=development."""
        client = _make_client(env="development")
        with pytest.raises(AssertionError, match="Subprocess mode forbidden in ENV='development'"):
            await client._start_subprocess()

    @pytest.mark.asyncio
    async def test_env_check_passes_when_local(self):
        """When ENV=local the ENV assertion must pass (no AssertionError on that check).

        The Popen call will then fail with FileNotFoundError (no real binary) —
        that's acceptable here; we only care the ENV gate was cleared.
        """
        client = _make_client(env="local", path="/nonexistent/mcp-binary")
        with pytest.raises(Exception) as exc_info:
            await client._start_subprocess()
        # Must NOT be an AssertionError about ENV
        if isinstance(exc_info.value, AssertionError):
            assert "Subprocess mode forbidden" not in str(exc_info.value), (
                "ENV=local should not trigger the subprocess-forbidden assertion"
            )

    @pytest.mark.asyncio
    async def test_empty_path_raises_assertion_error(self):
        """mcp_server_path=None/empty must raise AssertionError even in local ENV."""
        client = _make_client(env="local", path="")
        client.settings.mcp_server_path = None
        with pytest.raises(AssertionError, match="MCP_SERVER_PATH must be set"):
            await client._start_subprocess()


# ---------------------------------------------------------------------------
# 2. shell=True is never used — structural assertion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_popen_never_uses_shell_true():
    """subprocess.Popen must never be called with shell=True."""
    client = _make_client(env="local", path="/fake/mcp-server")

    popen_kwargs_captured: dict = {}

    def fake_popen(args, **kwargs):
        popen_kwargs_captured.update(kwargs)
        popen_kwargs_captured["_args"] = args
        raise FileNotFoundError("fake binary")  # abort after capture

    with patch.object(subprocess, "Popen", side_effect=fake_popen):
        with pytest.raises(FileNotFoundError):
            await client._start_subprocess()

    assert popen_kwargs_captured.get("shell", False) is False, (
        f"shell=True detected in Popen call! kwargs={popen_kwargs_captured}"
    )
    assert isinstance(popen_kwargs_captured.get("_args"), list), (
        "Popen must receive a list of arguments, not a shell string"
    )


# ---------------------------------------------------------------------------
# 3. validate_secrets() blocks subprocess + non-local ENV at startup
# ---------------------------------------------------------------------------

def _make_validate_settings(
    jwt_secret: str = "strong-jwt-secret-value-xyz-123",
    cc_internal_secret: str = "strong-cc-secret-value-xyz-456",
    mcp_server_mode: str = "subprocess",
    env: str = "production",
) -> MagicMock:
    s = MagicMock()
    s.jwt_secret = jwt_secret
    s.cc_internal_secret = cc_internal_secret
    s.mcp_server_mode = mcp_server_mode
    s.env = env
    return s


# Load validate_secrets directly from source
_vs_spec = importlib.util.spec_from_file_location(
    "_cfg_for_vs",
    _ROOT / "app/config.py",
)
# We can't exec the full module (Settings() would fail), so load validate_secrets
# from source by extracting just that function using exec in a controlled namespace.
_vs_source = (_ROOT / "app/config.py").read_text()

# Extract validate_secrets by compiling its body independently
_vs_ns: dict = {
    "frozenset": frozenset,
    "Settings": MagicMock,  # not called, just needed for annotation
}
# Execute only the constant and the function (everything after get_settings())
_after_fn = _vs_source[_vs_source.index("_BANNED_SECRET_VALUES"):]
exec(_after_fn, _vs_ns)  # noqa: S102  — test-only, no user input
_validate_secrets = _vs_ns["validate_secrets"]


class TestValidateSecretsSubprocessGuard:

    def test_subprocess_in_production_raises_runtime_error(self):
        """validate_secrets must raise RuntimeError for subprocess + ENV=production."""
        s = _make_validate_settings(mcp_server_mode="subprocess", env="production")
        with pytest.raises(RuntimeError, match="subprocess mode is forbidden"):
            _validate_secrets(s)

    def test_subprocess_in_staging_raises_runtime_error(self):
        s = _make_validate_settings(mcp_server_mode="subprocess", env="staging")
        with pytest.raises(RuntimeError, match="subprocess mode is forbidden"):
            _validate_secrets(s)

    def test_subprocess_in_local_passes(self):
        """subprocess + ENV=local must NOT raise."""
        s = _make_validate_settings(mcp_server_mode="subprocess", env="local")
        _validate_secrets(s)  # should not raise

    def test_http_mode_in_production_passes(self):
        """http mode in production is always fine."""
        s = _make_validate_settings(mcp_server_mode="http", env="production")
        _validate_secrets(s)  # should not raise
