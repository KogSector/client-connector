"""Unit tests for app/grpc/channel.py — TLS/mTLS channel factory.

Tests:
1. TLS-only: secure_channel() called with CA cert only
2. mTLS: secure_channel() called with all 3 certs
3. verify_cert_files() raises RuntimeError when CA cert missing
4. verify_cert_files() raises RuntimeError when mTLS enabled but client cert missing
5. verify_cert_files() raises RuntimeError when mTLS enabled but client key missing
6. verify_cert_files() passes when all required files present (TLS-only)
7. verify_cert_files() passes when all required files present (mTLS)
8. create_grpc_channel() never returns an insecure channel
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: load the real channel module in isolation
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parents[2]  # client-connector/

_ch_spec = importlib.util.spec_from_file_location(
    "app.grpc.channel",
    _ROOT / "app/grpc/channel.py",
)
_ch_mod = importlib.util.module_from_spec(_ch_spec)
sys.modules["app.grpc.channel"] = _ch_mod
_ch_spec.loader.exec_module(_ch_mod)

verify_cert_files = _ch_mod.verify_cert_files
create_grpc_channel = _ch_mod.create_grpc_channel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_cert(tmp_path: Path, name: str, content: bytes = b"FAKE-CERT") -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


# ---------------------------------------------------------------------------
# verify_cert_files() — missing cert cases
# ---------------------------------------------------------------------------

class TestVerifyCertFiles:

    def test_missing_ca_cert_raises_runtime_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GRPC_CA_CERT_PATH", str(tmp_path / "nonexistent_ca.crt"))
        monkeypatch.setenv("GRPC_MTLS_ENABLED", "false")
        with pytest.raises(RuntimeError, match="gRPC TLS cert file not found"):
            verify_cert_files()

    def test_mtls_missing_client_cert_raises(self, tmp_path, monkeypatch):
        ca = _write_cert(tmp_path, "ca.crt")
        monkeypatch.setenv("GRPC_CA_CERT_PATH", str(ca))
        monkeypatch.setenv("GRPC_MTLS_ENABLED", "true")
        monkeypatch.setenv("GRPC_CLIENT_CERT_PATH", str(tmp_path / "missing_client.crt"))
        monkeypatch.setenv("GRPC_CLIENT_KEY_PATH", str(tmp_path / "client.key"))
        with pytest.raises(RuntimeError, match="gRPC TLS cert file not found"):
            verify_cert_files()

    def test_mtls_missing_client_key_raises(self, tmp_path, monkeypatch):
        ca = _write_cert(tmp_path, "ca.crt")
        cert = _write_cert(tmp_path, "client.crt")
        monkeypatch.setenv("GRPC_CA_CERT_PATH", str(ca))
        monkeypatch.setenv("GRPC_MTLS_ENABLED", "true")
        monkeypatch.setenv("GRPC_CLIENT_CERT_PATH", str(cert))
        monkeypatch.setenv("GRPC_CLIENT_KEY_PATH", str(tmp_path / "missing.key"))
        with pytest.raises(RuntimeError, match="gRPC TLS cert file not found"):
            verify_cert_files()

    def test_tls_only_all_present_passes(self, tmp_path, monkeypatch):
        ca = _write_cert(tmp_path, "ca.crt")
        monkeypatch.setenv("GRPC_CA_CERT_PATH", str(ca))
        monkeypatch.setenv("GRPC_MTLS_ENABLED", "false")
        verify_cert_files()  # must not raise

    def test_mtls_all_present_passes(self, tmp_path, monkeypatch):
        ca = _write_cert(tmp_path, "ca.crt")
        cert = _write_cert(tmp_path, "client.crt")
        key = _write_cert(tmp_path, "client.key")
        monkeypatch.setenv("GRPC_CA_CERT_PATH", str(ca))
        monkeypatch.setenv("GRPC_MTLS_ENABLED", "true")
        monkeypatch.setenv("GRPC_CLIENT_CERT_PATH", str(cert))
        monkeypatch.setenv("GRPC_CLIENT_KEY_PATH", str(key))
        verify_cert_files()  # must not raise

    def test_mtls_not_checked_when_disabled(self, tmp_path, monkeypatch):
        """With MTLS disabled, missing client cert must NOT raise."""
        ca = _write_cert(tmp_path, "ca.crt")
        monkeypatch.setenv("GRPC_CA_CERT_PATH", str(ca))
        monkeypatch.setenv("GRPC_MTLS_ENABLED", "false")
        monkeypatch.setenv("GRPC_CLIENT_CERT_PATH", str(tmp_path / "nonexistent.crt"))
        verify_cert_files()  # must not raise


# ---------------------------------------------------------------------------
# create_grpc_channel() — TLS and mTLS modes
# ---------------------------------------------------------------------------

class TestCreateGrpcChannel:

    def test_tls_mode_calls_secure_channel(self, tmp_path, monkeypatch):
        """TLS-only: ssl_channel_credentials called with CA cert only."""
        ca_bytes = b"CA-CERT-BYTES"
        ca = _write_cert(tmp_path, "ca.crt", ca_bytes)
        monkeypatch.setenv("GRPC_CA_CERT_PATH", str(ca))
        monkeypatch.setenv("GRPC_MTLS_ENABLED", "false")

        mock_creds = MagicMock()
        mock_channel = MagicMock()

        with (
            patch.object(_ch_mod.grpc, "ssl_channel_credentials", return_value=mock_creds) as mock_ssl,
            patch.object(_ch_mod.grpc.aio, "secure_channel", return_value=mock_channel) as mock_sc,
        ):
            ch = create_grpc_channel("mcp-server:50056")

        # ssl_channel_credentials must receive the CA cert as root_certificates
        mock_ssl.assert_called_once_with(root_certificates=ca_bytes)
        # Must NOT include client key/cert (no mTLS)
        call_kwargs = mock_ssl.call_args.kwargs
        assert "private_key" not in call_kwargs
        assert "certificate_chain" not in call_kwargs

        # secure_channel() called with the host and the credentials object
        mock_sc.assert_called_once_with("mcp-server:50056", mock_creds)
        assert ch is mock_channel

    def test_mtls_mode_calls_secure_channel_with_all_certs(self, tmp_path, monkeypatch):
        """mTLS: ssl_channel_credentials called with CA cert + client cert + client key."""
        ca_bytes = b"CA-CERT"
        cert_bytes = b"CLIENT-CERT"
        key_bytes = b"CLIENT-KEY"
        ca = _write_cert(tmp_path, "ca.crt", ca_bytes)
        cert = _write_cert(tmp_path, "client.crt", cert_bytes)
        key = _write_cert(tmp_path, "client.key", key_bytes)

        monkeypatch.setenv("GRPC_CA_CERT_PATH", str(ca))
        monkeypatch.setenv("GRPC_MTLS_ENABLED", "true")
        monkeypatch.setenv("GRPC_CLIENT_CERT_PATH", str(cert))
        monkeypatch.setenv("GRPC_CLIENT_KEY_PATH", str(key))

        mock_creds = MagicMock()
        mock_channel = MagicMock()

        with (
            patch.object(_ch_mod.grpc, "ssl_channel_credentials", return_value=mock_creds) as mock_ssl,
            patch.object(_ch_mod.grpc.aio, "secure_channel", return_value=mock_channel) as mock_sc,
        ):
            ch = create_grpc_channel("auth-middleware:50058")

        mock_ssl.assert_called_once_with(
            root_certificates=ca_bytes,
            private_key=key_bytes,
            certificate_chain=cert_bytes,
        )
        mock_sc.assert_called_once_with("auth-middleware:50058", mock_creds)
        assert ch is mock_channel

    def test_insecure_channel_never_called(self, tmp_path, monkeypatch):
        """grpc.aio.insecure_channel must never be invoked."""
        ca = _write_cert(tmp_path, "ca.crt")
        monkeypatch.setenv("GRPC_CA_CERT_PATH", str(ca))
        monkeypatch.setenv("GRPC_MTLS_ENABLED", "false")

        with (
            patch.object(_ch_mod.grpc, "ssl_channel_credentials", return_value=MagicMock()),
            patch.object(_ch_mod.grpc.aio, "secure_channel", return_value=MagicMock()),
            patch.object(_ch_mod.grpc.aio, "insecure_channel") as mock_insecure,
        ):
            create_grpc_channel("some-service:50000")

        mock_insecure.assert_not_called()

    def test_host_passed_verbatim_to_secure_channel(self, tmp_path, monkeypatch):
        """The host string must be forwarded unchanged to grpc.aio.secure_channel."""
        ca = _write_cert(tmp_path, "ca.crt")
        monkeypatch.setenv("GRPC_CA_CERT_PATH", str(ca))
        monkeypatch.setenv("GRPC_MTLS_ENABLED", "false")

        captured_host = []

        def _fake_secure(host, creds):
            captured_host.append(host)
            return MagicMock()

        with (
            patch.object(_ch_mod.grpc, "ssl_channel_credentials", return_value=MagicMock()),
            patch.object(_ch_mod.grpc.aio, "secure_channel", side_effect=_fake_secure),
        ):
            create_grpc_channel("unified-processor:50053")

        assert captured_host == ["unified-processor:50053"]
