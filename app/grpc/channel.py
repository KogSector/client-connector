"""Secure gRPC channel factory for client-connector.

All gRPC connections from this service must use TLS. mTLS (mutual TLS)
is supported when ``GRPC_MTLS_ENABLED=true``.

Environment variables
---------------------
GRPC_CA_CERT_PATH      Path to the CA certificate file.
                       Default: /certs/ca.crt
GRPC_MTLS_ENABLED      Enable mutual TLS (client cert auth).
                       Default: false
GRPC_CLIENT_CERT_PATH  Path to the client certificate (mTLS only).
                       Default: /certs/client.crt
GRPC_CLIENT_KEY_PATH   Path to the client private key (mTLS only).
                       Default: /certs/client.key
"""
from __future__ import annotations

import os
from pathlib import Path

import grpc
import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_CA_CERT_PATH = "/certs/ca.crt"
_DEFAULT_CLIENT_CERT_PATH = "/certs/client.crt"
_DEFAULT_CLIENT_KEY_PATH = "/certs/client.key"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _mtls_enabled() -> bool:
    return _env("GRPC_MTLS_ENABLED", "false").strip().lower() == "true"


# ---------------------------------------------------------------------------
# Startup cert validation
# ---------------------------------------------------------------------------


def verify_cert_files() -> None:
    """Verify all required TLS certificate files exist and are readable.

    Raises
    ------
    RuntimeError
        If any required file is missing or cannot be read.

    Call this inside the FastAPI lifespan *before* creating any gRPC channels.
    """
    ca_path = Path(_env("GRPC_CA_CERT_PATH", _DEFAULT_CA_CERT_PATH))
    _assert_readable(ca_path, "GRPC_CA_CERT_PATH (CA certificate)")

    if _mtls_enabled():
        cert_path = Path(_env("GRPC_CLIENT_CERT_PATH", _DEFAULT_CLIENT_CERT_PATH))
        key_path = Path(_env("GRPC_CLIENT_KEY_PATH", _DEFAULT_CLIENT_KEY_PATH))
        _assert_readable(cert_path, "GRPC_CLIENT_CERT_PATH (client certificate)")
        _assert_readable(key_path, "GRPC_CLIENT_KEY_PATH (client private key)")

    logger.info(
        "grpc_cert_files_verified",
        ca=str(ca_path),
        mtls=_mtls_enabled(),
    )


def _assert_readable(path: Path, label: str) -> None:
    if not path.exists():
        raise RuntimeError(
            f"FATAL: gRPC TLS cert file not found: {path} ({label}). "
            "Ensure the certificate is mounted before starting the service."
        )
    try:
        path.read_bytes()
    except OSError as exc:
        raise RuntimeError(
            f"FATAL: gRPC TLS cert file is not readable: {path} ({label}). "
            f"OS error: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Channel factory
# ---------------------------------------------------------------------------


def create_grpc_channel(host: str) -> grpc.aio.Channel:
    """Return a TLS-secured (or mTLS-secured) async gRPC channel.

    Parameters
    ----------
    host:
        The ``host:port`` string for the gRPC server, e.g.
        ``"mcp-server:50056"`` or ``"auth-middleware:50058"``.

    Returns
    -------
    grpc.aio.Channel
        A secure channel — never an insecure one.
    """
    ca_cert = Path(_env("GRPC_CA_CERT_PATH", _DEFAULT_CA_CERT_PATH)).read_bytes()

    if _mtls_enabled():
        client_cert = Path(_env("GRPC_CLIENT_CERT_PATH", _DEFAULT_CLIENT_CERT_PATH)).read_bytes()
        client_key = Path(_env("GRPC_CLIENT_KEY_PATH", _DEFAULT_CLIENT_KEY_PATH)).read_bytes()

        credentials = grpc.ssl_channel_credentials(
            root_certificates=ca_cert,
            private_key=client_key,
            certificate_chain=client_cert,
        )
        logger.info("grpc_channel_created", host=host, mode="mtls")
    else:
        credentials = grpc.ssl_channel_credentials(root_certificates=ca_cert)
        logger.info("grpc_channel_created", host=host, mode="tls")

    return grpc.aio.secure_channel(host, credentials)
