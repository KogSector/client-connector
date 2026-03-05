"""SQLAlchemy 2.0 async declarative models for the Client Connector service.

All tables use UUID primary keys and timezone-aware datetimes. The
:class:`TimestampMixin` provides ``created_at`` / ``updated_at`` bookkeeping for
any model that needs it.

Tables
------
* :class:`Session`          — live / recent agent WebSocket sessions
* :class:`AuditEvent`       — immutable append-only audit trail
* :class:`IdempotencyKey`   — idempotent request deduplication records
* :class:`EncryptionKey`    — envelope-encryption key registry

Note: ``from __future__ import annotations`` is intentionally absent. SQLAlchemy
2.0 ``Mapped`` introspects annotations eagerly at class-definition time; the
future import makes all annotations lazy strings, which breaks that mechanism.
Python 3.11+ supports ``X | Y`` union syntax natively without the import.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    JSON,
    LargeBinary,
    String,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    """Return the current UTC datetime with tzinfo set."""
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Root declarative base for all Client Connector models."""


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` columns to any model.

    Attributes
    ----------
    created_at:
        UTC timestamp set once at row creation and never changed.
    updated_at:
        UTC timestamp refreshed on every ``UPDATE``.  Application code is
        responsible for setting this; SQLAlchemy does not do it automatically
        in async sessions without an ``onupdate`` event listener.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Session(TimestampMixin, Base):
    """Persisted record of a live or recently-closed agent WebSocket session.

    A row is created when an agent successfully authenticates and upgrades to
    a WebSocket connection.  The ``last_active`` timestamp is updated on every
    received message to support idle-timeout enforcement.

    Attributes
    ----------
    id:
        UUID-v4 primary key assigned by the application at session creation.
    agent_id:
        Stable identifier for the AI agent owning this session.  Indexed to
        enable fast per-agent session lookup.
    tenant_id:
        Optional tenant scope, ``NULL`` for single-tenant deployments.
    created_at:
        UTC timestamp at which the session was established.  Inherited from
        :class:`TimestampMixin`.
    last_active:
        UTC timestamp updated on each incoming frame.  Used for idle-timeout
        enforcement and session expiry.
    metadata_:
        Free-form JSON bag for implementation-specific session state (e.g.,
        negotiated capabilities, MCP server version).  Mapped to
        ``metadata`` in the database column.
    """

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata",   # DB column name stays "metadata"
        JSON,
        default=dict,
        nullable=False,
    )


class AuditEvent(Base):
    """Immutable, append-only audit record emitted for every significant action.

    Rows must **never** be updated or deleted.  The ``hmac`` column provides a
    tamper-evident signature over the remaining fields.

    Attributes
    ----------
    id:
        UUID-v4 primary key.
    request_id:
        Correlates the event to the originating ``RequestContext``.  Indexed
        for fast request-level audit retrieval.
    agent_id:
        Identifier of the agent that performed the action.  Indexed for
        per-agent audit queries.
    tenant_id:
        Tenant scope, ``NULL`` for single-tenant deployments.
    action:
        Dot-delimited action label, e.g. ``"tool.call"`` or
        ``"session.open"``.
    resource:
        Identifier of the resource acted upon (tool name, resource URI, etc.).
    outcome:
        ``"success"``, ``"denied"``, or ``"error"``.
    latency_ms:
        End-to-end handling time in milliseconds.
    stage_timings:
        Per-stage duration map (seconds) copied from ``RequestContext``.
    input_hash:
        Hex-encoded SHA-256 of the sanitised input payload.
    output_hash:
        Hex-encoded SHA-256 of the response payload.
    policy_decision:
        JSON snapshot of the ``PolicyDecision`` that governed this action,
        or ``NULL`` for pre-policy events.
    error_code:
        Machine-readable error code on failure, ``NULL`` on success.
    timestamp:
        UTC wall-clock time at event creation.
    hmac:
        HMAC-SHA-256 signature over the serialised event for tamper-evidence.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource: Mapped[str] = mapped_column(String(256), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    stage_timings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    hmac: Mapped[str] = mapped_column(String(64), nullable=False)


class IdempotencyKey(Base):
    """Deduplication record for idempotent request processing.

    A row is inserted at the boundary of a new request with
    ``status="PENDING"`` and updated to ``"COMPLETE"`` or ``"FAILED"`` once
    processing finishes.  The encrypted response payload is stored so that
    repeat requests within the TTL window receive the cached result without
    re-executing the handler.

    Attributes
    ----------
    key:
        Application-level idempotency key supplied by the caller, used as the
        primary key.  Max 256 characters.
    agent_id:
        Agent that submitted the original request.  Indexed for ownership
        queries.
    status:
        Lifecycle state: ``"MISS"`` (not yet processed), ``"PENDING"``
        (in-flight), ``"COMPLETE"`` (finished successfully), or ``"FAILED"``
        (terminal error).
    response_encrypted:
        AES-GCM encrypted serialisation of the original response, stored so
        that replay requests get an identical answer.  ``NULL`` until the
        request completes.
    created_at:
        UTC timestamp at which this key was first seen.
    expires_at:
        UTC timestamp after which this record may be purged.  Indexed to
        support efficient TTL sweeps.
    """

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )


class EncryptionKey(Base):
    """Registry of envelope-encryption keys used by the service.

    Each row represents one Data Encryption Key (DEK) or Key Encryption Key
    (KEK).  The ``active`` flag marks the current key used for new encryptions;
    older rows are retained for decryption of existing ciphertexts until they
    are formally retired.

    Attributes
    ----------
    key_id:
        Short, human-readable identifier for the key (e.g. ``"dek-v1"``).
        Primary key.
    algorithm:
        Encryption algorithm this key is used with, e.g. ``"AES-256-GCM"``
        or ``"RSA-4096-OAEP"``.
    created_at:
        UTC timestamp at which this key was registered.
    rotated_at:
        UTC timestamp at which this key was superseded by a new key, or
        ``NULL`` if it has not yet been rotated.
    active:
        ``True`` if this key should be used for new encryption operations.
        Only one key per algorithm should have ``active=True`` at any time.
    """

    __tablename__ = "encryption_keys"

    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
