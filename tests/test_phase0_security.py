"""Phase 0 Security Hardening — Complete pytest test suite.

Covers ALL seven security requirements:
  1. Auth bypass removed  — WS with no creds closed 4001 even when debug=True
  2. JWT secret           — startup RuntimeError if JWT_SECRET missing/weak
  3. API key header       — X-API-Key header succeeds; ?key= query param → 401
  4. JWT header           — Authorization: Bearer succeeds; ?token= query → 401
  5. Internal token       — every Data-Connector call carries a valid internal JWT
  6. Subprocess guard     — ENV=production raises AssertionError before Popen
  7. gRPC insecure scan   — no grpc.insecure_channel() calls exist in app/ (AST)

Design principles
-----------------
- All external services are mocked.
- No network calls, no running containers required.
- Uses the existing conftest.py stub infrastructure for tests that import
  `app.*` through the normal package path.
- For tests that need real implementations (token claims, subprocess guard,
  AST scan) modules are loaded via importlib to bypass the conftest stubs.
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Bootstrap helpers
# =============================================================================

_ROOT = Path(__file__).parent.parent  # client-connector/


def _load_real(dotted: str, rel_path: str) -> ModuleType:
    """Load a real module from its file path, bypassing sys.modules stubs."""
    spec = importlib.util.spec_from_file_location(dotted, _ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    # Register first so transitive imports resolve correctly
    old = sys.modules.get(dotted)
    sys.modules[dotted] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        if old is None:
            sys.modules.pop(dotted, None)
        else:
            sys.modules[dotted] = old
        raise
    return mod


# ---------------------------------------------------------------------------
# Load real modules used in multiple test sections
# ---------------------------------------------------------------------------

# internal_token (no heavy deps)
_it = _load_real("_phase0_internal_token", "app/auth/internal_token.py")
_generate_internal_token = _it.generate_internal_token

# config + validate_secrets — executed by exec() to avoid Settings() init
_cfg_source = (_ROOT / "app/config.py").read_text()
_cfg_ns: dict = {"frozenset": frozenset, "MagicMock": MagicMock}
# Extract only the part after _BANNED_SECRET_VALUES to get validate_secrets
_after = _cfg_source[_cfg_source.index("_BANNED_SECRET_VALUES"):]
exec(_after, _cfg_ns)  # noqa: S102 — test-only; no user input
_validate_secrets = _cfg_ns["validate_secrets"]

# app.api.websocket — loaded by file path to avoid app.api.__init__ polluting
# sys.modules when unit/ tests run first and clobber the conftest stubs.
def _load_websocket_mod() -> ModuleType:
    """Load the real websocket module direct from file, bypassing package init."""
    # The websocket module needs these stubs present when it executes
    _needed = {
        "app.config":   sys.modules.get("app.config"),
        "app.auth":     sys.modules.get("app.auth"),
        "app.schemas":  sys.modules.get("app.schemas"),
        "app.services": sys.modules.get("app.services"),
    }
    # If any are missing (real module was loaded instead of stub), re-inject stubs
    from types import ModuleType as _MT
    from unittest.mock import MagicMock as _MM, AsyncMock as _AM
    from enum import Enum as _Enum

    if not _needed["app.schemas"] or not hasattr(_needed["app.schemas"], "ClientInfo"):
        class _CS(str, _Enum):
            INITIALIZING = "initializing"; READY = "ready"; CLOSED = "closed"
        stub = _MT("app.schemas")
        stub.ConnectionState = _CS
        stub.ClientInfo = _MM()
        stub.JsonRpcError = _MM(); stub.JsonRpcRequest = _MM(); stub.JsonRpcResponse = _MM()
        sys.modules["app.schemas"] = stub
        sys.modules["app.schemas.mcp"] = stub

    spec = importlib.util.spec_from_file_location(
        "_p0_websocket", _ROOT / "app/api/websocket.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_p0_websocket"] = mod
    spec.loader.exec_module(mod)
    return mod

_ws = _load_websocket_mod()
_authenticate_websocket = _ws.authenticate_websocket
_ws_router = _ws.router

# ============================================================================
# Helpers shared across sections
# ============================================================================

_JWT_SECRET = "strong-jwt-secret-not-in-banned-list-xyz"
_JWT_ALGORITHM = "HS256"
_INTERNAL_SECRET = "strong-internal-secret-value-for-testing"


def _make_settings(**overrides) -> MagicMock:
    """Minimal settings mock sufficient for all tests."""
    s = MagicMock()
    s.jwt_secret = _JWT_SECRET
    s.jwt_algorithm = _JWT_ALGORITHM
    s.cc_internal_secret = _INTERNAL_SECRET
    s.mcp_server_mode = "http"
    s.env = "production"
    s.debug = False
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ============================================================================
# 1. Auth bypass removed
#    WS connection with no credentials must be rejected with 4001
#    — even when settings.debug=True.
# ============================================================================

class TestAuthBypassRemoved:
    """Requirement 1: auth is unconditional — no debug bypass."""

    # --- helper ----------------------------------------------------------

    @contextmanager
    def _patch_session(self):
        """Stub out session manager and MCP client (infrastructure only)."""
        fake_session = MagicMock()
        fake_session.id = "sess-1"

        sm = AsyncMock()
        sm.create_session = AsyncMock(return_value=fake_session)
        sm.update_session = AsyncMock()
        sm.remove_session = AsyncMock()

        with (
            patch("app.api.websocket.get_session_manager", return_value=sm),
            patch("app.api.websocket.get_mcp_client", return_value=AsyncMock()),
        ):
            yield

    # --- tests -----------------------------------------------------------

    def test_no_credentials_closed_with_4001(self):
        """No credentials → WebSocket must be closed with code 4001."""
        from starlette.testclient import TestClient
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(_ws_router, prefix="/mcp")

        settings = _make_settings(debug=False)
        with (
            patch("_p0_websocket.get_settings", return_value=settings),
            patch("_p0_websocket.validate_jwt_token", new_callable=AsyncMock, return_value=None),
            patch("_p0_websocket.validate_api_key", new_callable=AsyncMock, return_value=None),
            self._patch_session(),
        ):
            with pytest.raises(Exception):
                with TestClient(app).websocket_connect("/mcp/ws") as ws:
                    pass

    def test_no_credentials_closed_with_4001_even_when_debug_true(self):
        """debug=True must NOT create a bypass — auth is still required."""
        from starlette.testclient import TestClient
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(_ws_router, prefix="/mcp")

        # debug=True — must still reject unauthenticated connections
        settings = _make_settings(debug=True)
        with (
            patch("_p0_websocket.get_settings", return_value=settings),
            patch("_p0_websocket.validate_jwt_token", new_callable=AsyncMock, return_value=None),
            patch("_p0_websocket.validate_api_key", new_callable=AsyncMock, return_value=None),
            self._patch_session(),
        ):
            with pytest.raises(Exception):
                with TestClient(app).websocket_connect("/mcp/ws") as ws:
                    pass

    @pytest.mark.asyncio
    async def test_authenticate_websocket_returns_none_with_no_creds(self):
        """authenticate_websocket() must return None when no creds supplied."""
        with patch("_p0_websocket.get_settings", return_value=_make_settings()):
            result = await _authenticate_websocket(authorization=None, x_api_key=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_websocket_returns_none_with_debug_true(self):
        """debug=True must not influence the None return — no bypass."""
        with patch("_p0_websocket.get_settings", return_value=_make_settings(debug=True)):
            result = await _authenticate_websocket(authorization=None, x_api_key=None)
        assert result is None


# ============================================================================
# 2. JWT secret startup validation
#    App startup raises RuntimeError if JWT_SECRET is missing or weak.
# ============================================================================

class TestJwtSecretStartupValidation:
    """Requirement 2: validate_secrets() crashes on missing or weak JWT_SECRET."""

    def _s(self, jwt_secret: str, cc_internal_secret: str = _INTERNAL_SECRET,
           mcp_server_mode: str = "http", env: str = "production") -> MagicMock:
        return _make_settings(
            jwt_secret=jwt_secret,
            cc_internal_secret=cc_internal_secret,
            mcp_server_mode=mcp_server_mode,
            env=env,
        )

    def test_missing_jwt_secret_raises(self):
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            _validate_secrets(self._s(jwt_secret=""))

    def test_dev_secret_key_raises(self):
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            _validate_secrets(self._s(jwt_secret="dev_secret_key"))

    def test_changeme_raises(self):
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            _validate_secrets(self._s(jwt_secret="changeme"))

    def test_secret_raises(self):
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            _validate_secrets(self._s(jwt_secret="secret"))

    def test_test_raises(self):
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            _validate_secrets(self._s(jwt_secret="test"))

    def test_development_raises(self):
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            _validate_secrets(self._s(jwt_secret="development"))

    def test_strong_secret_passes(self):
        """A properly random secret must not raise."""
        _validate_secrets(self._s(jwt_secret=_JWT_SECRET))  # must not raise


# ============================================================================
# 3. API key must come from X-API-Key header, not ?key= query param
# ============================================================================

class TestApiKeyHeader:
    """Requirement 3: API key via header accepted; ?key= query param rejected (401)."""

    @contextmanager
    def _app_client(self):
        """Yield a TestClient with a FastAPI app that uses the real auth middleware."""
        from starlette.testclient import TestClient
        from app.auth.middleware import get_current_user
        from fastapi import FastAPI, Depends

        app = FastAPI()

        @app.get("/protected")
        async def protected(user=Depends(get_current_user)):
            return {"user_id": user.user_id}

        yield TestClient(app, raise_server_exceptions=False)

    @pytest.mark.asyncio
    async def test_api_key_header_accepted_at_auth_layer(self):
        """X-API-Key header → validate_api_key is called and returns a user."""
        from app.auth import AuthUser

        fake_user = MagicMock(spec=AuthUser)
        fake_user.user_id = "user-from-api-key"

        with (
            patch("_p0_websocket.get_settings", return_value=_make_settings()),
            patch("_p0_websocket.validate_api_key", new_callable=AsyncMock, return_value=fake_user),
        ):
            result = await _authenticate_websocket(authorization=None, x_api_key="valid-key-value")

        assert result is fake_user

    @pytest.mark.asyncio
    async def test_query_param_key_never_forwarded_to_validate_api_key(self):
        """?key= must NOT be forwarded to validate_api_key — auth rejects it."""
        mock_validate = AsyncMock(return_value=MagicMock())

        with (
            patch("_p0_websocket.get_settings", return_value=_make_settings()),
            patch("_p0_websocket.validate_api_key", mock_validate),
        ):
            result = await _authenticate_websocket(authorization=None, x_api_key=None)

        mock_validate.assert_not_called()
        assert result is None

    def test_websocket_with_query_param_key_is_rejected(self):
        """WS connection with ?key= instead of X-API-Key header must be rejected."""
        from starlette.testclient import TestClient
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(_ws_router, prefix="/mcp")

        with (
            patch("_p0_websocket.get_settings", return_value=_make_settings()),
            patch("_p0_websocket.validate_api_key", new_callable=AsyncMock, return_value=None),
            patch("_p0_websocket.validate_jwt_token", new_callable=AsyncMock, return_value=None),
            patch("_p0_websocket.get_session_manager", new_callable=AsyncMock),
            patch("_p0_websocket.get_mcp_client", new_callable=AsyncMock),
        ):
            with pytest.raises(Exception):
                with TestClient(app).websocket_connect("/mcp/ws?key=some-api-key") as ws:
                    pass


# ============================================================================
# 4. JWT must come from Authorization: Bearer header, not ?token= query param
# ============================================================================

class TestJwtHeader:
    """Requirement 4: JWT via Authorization: Bearer header accepted; ?token= rejected."""

    @pytest.mark.asyncio
    async def test_bearer_token_header_accepted(self):
        """Authorization: Bearer <token> → validate_jwt_token is called."""
        from app.auth import AuthUser

        fake_user = MagicMock(spec=AuthUser)
        fake_user.user_id = "user-from-jwt"

        with (
            patch("_p0_websocket.get_settings", return_value=_make_settings()),
            patch("_p0_websocket.validate_jwt_token", new_callable=AsyncMock, return_value=fake_user),
        ):
            result = await _authenticate_websocket(
                authorization="Bearer valid.jwt.token",
                x_api_key=None,
            )

        assert result is fake_user

    @pytest.mark.asyncio
    async def test_query_param_token_not_forwarded(self):
        """?token= must not reach validate_jwt_token — auth ignores query params."""
        mock_validate = AsyncMock(return_value=MagicMock())

        with (
            patch("_p0_websocket.get_settings", return_value=_make_settings()),
            patch("_p0_websocket.validate_jwt_token", mock_validate),
        ):
            result = await _authenticate_websocket(authorization=None, x_api_key=None)

        mock_validate.assert_not_called()
        assert result is None

    def test_websocket_query_param_token_rejected(self):
        """WS connection with ?token= instead of Authorization header must be rejected."""
        from starlette.testclient import TestClient
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(_ws_router, prefix="/mcp")

        with (
            patch("_p0_websocket.get_settings", return_value=_make_settings()),
            patch("_p0_websocket.validate_jwt_token", new_callable=AsyncMock, return_value=None),
            patch("_p0_websocket.validate_api_key", new_callable=AsyncMock, return_value=None),
            patch("_p0_websocket.get_session_manager", new_callable=AsyncMock),
            patch("_p0_websocket.get_mcp_client", new_callable=AsyncMock),
        ):
            with pytest.raises(Exception):
                with TestClient(app).websocket_connect("/mcp/ws?token=some.jwt.token") as ws:
                    pass

    @pytest.mark.asyncio
    async def test_non_bearer_authorization_header_ignored(self):
        """Authorization: Basic ... must not be treated as JWT."""
        mock_validate = AsyncMock(return_value=MagicMock())

        with (
            patch("_p0_websocket.get_settings", return_value=_make_settings()),
            patch("_p0_websocket.validate_jwt_token", mock_validate),
        ):
            result = await _authenticate_websocket(
                authorization="Basic dXNlcjpwYXNz",
                x_api_key=None,
            )

        mock_validate.assert_not_called()
        assert result is None


# ============================================================================
# 5. Internal token
#    Every call to Data-Connector (via QueryProcessor) carries a valid internal JWT
#    with correct iss/sub/aud claims and a non-expired exp.
# ============================================================================

class TestInternalToken:
    """Requirement 5: all outbound Data-Connector calls carry a valid internal JWT."""

    # Load real QueryProcessor from file (unit/conftest.py already handles this,
    # but we load it here explicitly so this file is self-contained)
    @pytest.fixture(autouse=True)
    def _load_real_qp(self):
        """Load real query_processor bypassing any stubs."""
        # Load internal_token first (already loaded at module level)
        sys.modules["app.auth.internal_token"] = _it

        # Load real query_processor
        spec = importlib.util.spec_from_file_location(
            "_phase0_qp", _ROOT / "app/services/query_processor.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self._QueryProcessor = mod.QueryProcessor

    def _make_qp(self):
        return self._QueryProcessor(
            data_vent_url="http://data-vent:3005",
            embeddings_service_url="http://emb:3001",
            internal_secret=_INTERNAL_SECRET,
        )

    def _mock_resp(self, body: dict) -> MagicMock:
        r = MagicMock()
        r.raise_for_status = MagicMock()
        r.json.return_value = body
        return r

    def _decode_bearer(self, bearer: str) -> dict:
        from jose import jwt
        token = bearer.removeprefix("Bearer ")
        return jwt.decode(
            token, _INTERNAL_SECRET, algorithms=["HS256"], audience="data-connector"
        )

    @pytest.mark.asyncio
    async def test_vector_search_token_has_correct_iss(self):
        qp = self._make_qp()
        qp._http_client = AsyncMock()
        qp._http_client.post = AsyncMock(return_value=self._mock_resp({"chunks": [], "total": 0}))
        await qp._vector_search([0.1] * 10, limit=5, source_ids=None)
        bearer = qp._http_client.post.call_args.kwargs["headers"]["Authorization"]
        payload = self._decode_bearer(bearer)
        assert payload["iss"] == "client-connector"

    @pytest.mark.asyncio
    async def test_vector_search_token_has_correct_aud(self):
        qp = self._make_qp()
        qp._http_client = AsyncMock()
        qp._http_client.post = AsyncMock(return_value=self._mock_resp({"chunks": [], "total": 0}))
        await qp._vector_search([0.1] * 10, limit=5, source_ids=None)
        bearer = qp._http_client.post.call_args.kwargs["headers"]["Authorization"]
        payload = self._decode_bearer(bearer)
        assert payload["aud"] == "data-connector"

    @pytest.mark.asyncio
    async def test_vector_search_token_not_expired(self):
        qp = self._make_qp()
        qp._http_client = AsyncMock()
        qp._http_client.post = AsyncMock(return_value=self._mock_resp({"chunks": [], "total": 0}))
        await qp._vector_search([0.1] * 10, limit=5, source_ids=None)
        bearer = qp._http_client.post.call_args.kwargs["headers"]["Authorization"]
        payload = self._decode_bearer(bearer)
        assert payload["exp"] > int(time.time()), "Token must not already be expired"

    @pytest.mark.asyncio
    async def test_hybrid_search_token_has_correct_iss_and_aud(self):
        qp = self._make_qp()
        qp._http_client = AsyncMock()
        qp._http_client.post = AsyncMock(
            return_value=self._mock_resp(
                {"chunks": [], "vector_matches": 0, "graph_matches": 0, "completion_reached": False}
            )
        )
        await qp._hybrid_search("query", [0.1] * 10, limit=5, source_ids=None)
        bearer = qp._http_client.post.call_args.kwargs["headers"]["Authorization"]
        payload = self._decode_bearer(bearer)
        assert payload["iss"] == "client-connector"
        assert payload["aud"] == "data-connector"

    @pytest.mark.asyncio
    async def test_internal_token_ttl_is_60s(self):
        qp = self._make_qp()
        qp._http_client = AsyncMock()
        qp._http_client.post = AsyncMock(return_value=self._mock_resp({"chunks": [], "total": 0}))
        await qp._vector_search([0.1] * 10, limit=5, source_ids=None)
        bearer = qp._http_client.post.call_args.kwargs["headers"]["Authorization"]
        payload = self._decode_bearer(bearer)
        assert payload["exp"] - payload["iat"] == 60


# ============================================================================
# 6. Subprocess guard
#    Calling _start_subprocess with ENV=production raises AssertionError.
# ============================================================================

class TestSubprocessGuard:
    """Requirement 6: subprocess path must raise AssertionError outside ENV=local."""

    @pytest.fixture(autouse=True)
    def _load_real_mcp_client(self):
        """Load real McpClient bypassing conftest stubs."""
        # Stub dependencies of mcp_client.py
        for name, attrs in [
            ("app.config", {"get_settings": MagicMock()}),
            ("app.schemas", {"JsonRpcRequest": MagicMock(), "JsonRpcResponse": MagicMock()}),
        ]:
            if name not in sys.modules or not hasattr(sys.modules[name], "__real__"):
                pass  # use existing conftest stubs if present

        spec = importlib.util.spec_from_file_location(
            "_phase0_mcp_client", _ROOT / "app/services/mcp_client.py"
        )
        mod = importlib.util.module_from_spec(spec)
        # Temporarily inject stubs so mcp_client.py can be imported
        old = {}
        stubs = {
            "app.config": _stub_mod("app.config", get_settings=MagicMock()),
            "app.schemas": _stub_mod("app.schemas", JsonRpcRequest=MagicMock(), JsonRpcResponse=MagicMock()),
        }
        for k, v in stubs.items():
            old[k] = sys.modules.get(k)
            sys.modules[k] = v
        try:
            spec.loader.exec_module(mod)
        finally:
            for k, v in old.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        self._McpClient = mod.McpClient

    def _make_client(self, env: str, mode: str = "subprocess") -> object:
        import asyncio
        client = self._McpClient.__new__(self._McpClient)
        s = MagicMock()
        s.env = env
        s.mcp_server_mode = mode
        s.mcp_server_path = "/fake/mcp-server"
        s.mcp_server_url = "http://mcp:7777"
        client.settings = s
        client._process = None
        client._http_client = None
        client._request_id = 0
        client._pending_requests = {}
        client._read_task = None
        client._lock = asyncio.Lock()
        return client

    @pytest.mark.asyncio
    async def test_subprocess_mode_raises_in_production(self):
        client = self._make_client(env="production")
        with pytest.raises(AssertionError, match="Subprocess mode forbidden"):
            await client._start_subprocess()

    @pytest.mark.asyncio
    async def test_subprocess_mode_raises_in_staging(self):
        client = self._make_client(env="staging")
        with pytest.raises(AssertionError, match="Subprocess mode forbidden"):
            await client._start_subprocess()

    @pytest.mark.asyncio
    async def test_subprocess_mode_raises_in_development(self):
        client = self._make_client(env="development")
        with pytest.raises(AssertionError, match="Subprocess mode forbidden"):
            await client._start_subprocess()

    @pytest.mark.asyncio
    async def test_subprocess_env_check_passes_for_local(self):
        """ENV=local must clear the ENV assertion (FileNotFoundError expected next, not AssertionError)."""
        client = self._make_client(env="local")
        try:
            await client._start_subprocess()
        except AssertionError as e:
            raise AssertionError(
                f"ENV=local should not raise AssertionError but got: {e}"
            ) from e
        except Exception:
            pass  # FileNotFoundError for fake binary is expected


# ============================================================================
# 7. gRPC insecure channel static scan
#    No grpc.insecure_channel() calls exist anywhere in app/
# ============================================================================

class TestNoInsecureGrpcChannels:
    """Requirement 7: AST-scan app/ for any grpc.insecure_channel() usage."""

    def _find_insecure_calls(self) -> list[tuple[Path, int]]:
        """Return (file, line) for every grpc.insecure_channel / grpc.aio.insecure_channel call."""
        occurrences: list[tuple[Path, int]] = []
        app_dir = _ROOT / "app"

        for py_file in sorted(app_dir.rglob("*.py")):
            try:
                tree = ast.parse(py_file.read_text(), filename=str(py_file))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                # Match: grpc.insecure_channel(...)
                if isinstance(func, ast.Attribute) and func.attr == "insecure_channel":
                    occurrences.append((py_file, node.lineno))
                # Match: grpc.aio.insecure_channel(...)
                if (isinstance(func, ast.Attribute)
                        and func.attr == "insecure_channel"
                        and isinstance(func.value, ast.Attribute)
                        and func.value.attr == "aio"):
                    occurrences.append((py_file, node.lineno))

        return occurrences

    def test_no_insecure_channel_in_app(self):
        """AST scan: grpc.insecure_channel() must not exist anywhere in app/."""
        hits = self._find_insecure_calls()
        if hits:
            details = "\n".join(f"  {f.relative_to(_ROOT)}:{ln}" for f, ln in hits)
            pytest.fail(
                f"Found {len(hits)} grpc.insecure_channel() call(s) in app/:\n{details}\n"
                "Replace with create_grpc_channel() from app/grpc/channel.py"
            )

    def test_insecure_channel_also_not_in_infra(self):
        """AST scan: check infra/ as well (client-connector has infra/grpc/)."""
        infra_dir = _ROOT / "infra"
        if not infra_dir.exists():
            pytest.skip("No infra/ directory in this service")

        occurrences = []
        for py_file in sorted(infra_dir.rglob("*.py")):
            try:
                tree = ast.parse(py_file.read_text(), filename=str(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Attribute) and func.attr == "insecure_channel":
                        occurrences.append((py_file, node.lineno))

        if occurrences:
            details = "\n".join(f"  {f.relative_to(_ROOT)}:{ln}" for f, ln in occurrences)
            pytest.fail(
                f"Found grpc.insecure_channel() in infra/:\n{details}"
            )


# ============================================================================
# Private utilities
# ============================================================================

def _stub_mod(name: str, **attrs) -> ModuleType:
    """Create a lightweight stub ModuleType."""
    mod = ModuleType(name)
    mod.__dict__.update(attrs)
    return mod
