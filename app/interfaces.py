"""Interfaces for the Client Connector (MCP Protocol Gateway) microservice.

This module defines the canonical boundary contracts for the service. **No
implementation code lives here** — only structural typing via
:class:`typing.Protocol` and lightweight value objects via
:func:`dataclasses.dataclass`.

Design notes
------------
* All :class:`~typing.Protocol` classes are decorated with
  :func:`~typing.runtime_checkable` so that ``isinstance(obj, IFoo)`` works at
  runtime for duck-type guards and dependency-injection validation.
* Dataclasses use ``slots=True`` for memory efficiency and ``frozen=True``
  where objects are conceptually immutable value types.
* Every async method in a Protocol is declared with ``async def`` so that type
  checkers (mypy, pyright) can verify ``await`` usage correctly.
* Python 3.11+ union syntax (``X | Y``) is used throughout in preference to
  ``Optional[X]``.

Module layout
-------------
1. Input / transport types  (``JsonRpcRequest``)
2. Value objects / DTOs      (``RequestContext``, ``AgentIdentity``, …)
3. Protocol interfaces       (``IToolGateway``, ``IIdentityProvider``, …)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Input / Transport types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JsonRpcRequest:
    """A parsed JSON-RPC 2.0 request received from an MCP client.

    The Client Connector validates and normalises incoming WebSocket frames
    into this type before passing them to :class:`IToolGateway`.

    Attributes
    ----------
    jsonrpc:
        Must always be ``"2.0"``.
    id:
        Caller-supplied request identifier (integer, string, or ``None`` for
        notifications).  Used to correlate responses.
    method:
        The JSON-RPC method name, e.g. ``"tools/call"`` or
        ``"resources/read"``.
    params:
        Optional mapping of method parameters.  ``None`` when the method
        takes no parameters.
    """

    jsonrpc: str
    id: int | str | None
    method: str
    params: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Value objects / Data Transfer Objects
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RequestContext:
    """Carries per-request metadata through the entire request lifecycle.

    Created at the edge (WebSocket accept or HTTP handler) and propagated to
    every downstream layer without mutation by those layers.

    Attributes
    ----------
    request_id:
        A UUID-v4 string that uniquely identifies this individual request.
    trace_id:
        Distributed-tracing correlation ID (e.g., W3C Trace Context
        ``traceparent`` value).  May equal ``request_id`` for simple cases.
    agent_id:
        Stable identifier for the AI agent sending the request, e.g.
        ``"cursor-agent-abc123"``.
    tenant_id:
        Optional tenant / organisation identifier for multi-tenant
        deployments.  ``None`` for single-tenant or anonymous contexts.
    scopes:
        List of OAuth-style permission scopes granted to the agent, e.g.
        ``["mcp:tools:read", "mcp:resources:write"]``.
    deadline_ms:
        Absolute Unix epoch millisecond at which this request must be
        abandoned.  Handlers must honour this to avoid cascading latency.
    stage_timings:
        Mutable mapping populated by each processing stage recording
        wall-clock durations in seconds.  Example keys: ``"auth"``,
        ``"policy"``, ``"tool_call"``, ``"serialise"``.
    """

    request_id: str
    trace_id: str
    agent_id: str
    tenant_id: str | None
    scopes: list[str]
    deadline_ms: int
    stage_timings: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """Verified identity of an authenticated agent.

    Produced by :class:`IIdentityProvider` after successful credential
    validation and propagated through the request lifecycle.

    Attributes
    ----------
    agent_id:
        Stable, globally unique identifier for the agent.
    tenant_id:
        Tenant that owns this identity.  ``None`` for single-tenant
        deployments.
    scopes:
        Permission scopes granted to this identity as determined by the
        identity provider.
    agent_type:
        Broad classification of the agent, e.g. ``"cursor"``,
        ``"claude-desktop"``, ``"custom"``.
    credential_type:
        The authentication mechanism used, e.g. ``"jwt"``, ``"api_key"``,
        ``"mtls"``.
    """

    agent_id: str
    tenant_id: str | None
    scopes: list[str]
    agent_type: str
    credential_type: str


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Result of an :class:`IPolicyEvaluator` evaluation.

    Attributes
    ----------
    allowed:
        ``True`` if the action is permitted, ``False`` if denied.
    reason:
        Human-readable explanation of the decision.  Logged for audit trails
        and surfaced in error responses so callers understand rejections.
    matched_rule:
        Identifier of the policy rule that produced this decision, e.g.
        ``"rule:tenant-isolation"`` or ``"rule:scope-check"``.  Empty string
        when no specific rule matched (e.g., default-deny).
    """

    allowed: bool
    reason: str
    matched_rule: str


@dataclass(slots=True)
class AuditEvent:
    """A structured, tamper-evident record emitted to :class:`IAuditLogger`.

    Not frozen because ``outcome``, ``latency_ms``, ``output_hash``, and
    ``hmac`` are typically populated *after* the action completes.

    Attributes
    ----------
    id:
        UUID-v4 string uniquely identifying this audit entry.
    request_id:
        Correlates the event to the originating :class:`RequestContext`.
    agent_id:
        Identifier of the agent that performed the action.
    tenant_id:
        Tenant that owns the agent, or ``None`` for single-tenant contexts.
    action:
        Dot-delimited action name, e.g. ``"tool.call"`` or
        ``"session.open"``.
    resource:
        Identifier of the resource acted upon, e.g. a tool name or resource
        URI.
    outcome:
        ``"success"``, ``"denied"``, or ``"error"``.  Populated after the
        action completes.
    latency_ms:
        How long the action took in milliseconds.  ``None`` until complete.
    stage_timings:
        Per-stage durations (in seconds) copied from the active
        :class:`RequestContext`.
    input_hash:
        Hex-encoded SHA-256 hash of the sanitised input payload, used to
        detect tampering without storing raw data.
    output_hash:
        Hex-encoded SHA-256 hash of the response payload.  ``None`` until
        the response is produced.
    policy_decision:
        The :class:`PolicyDecision` that governed this action, or ``None``
        for pre-policy events.
    error_code:
        Machine-readable error identifier, e.g. ``"ERR_TOOL_TIMEOUT"``.
        ``None`` on success.
    timestamp:
        Wall-clock UTC timestamp at which this event was created.
    hmac:
        HMAC-SHA-256 signature of the serialised event fields for
        tamper-evidence.  Populated by the logger implementation.
    """

    id: str
    request_id: str
    agent_id: str
    tenant_id: str | None
    action: str
    resource: str
    outcome: str | None = None
    latency_ms: float | None = None
    stage_timings: dict[str, float] = field(default_factory=dict)
    input_hash: str | None = None
    output_hash: str | None = None
    policy_decision: PolicyDecision | None = None
    error_code: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    hmac: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    """The normalised result of a tool execution routed by :class:`IToolGateway`.

    Attributes
    ----------
    request_id:
        Correlates the result back to the originating :class:`JsonRpcRequest`
        / :class:`RequestContext`.
    status:
        Execution status: ``"success"``, ``"error"``, or
        ``"partial"`` (for incremental / streamed results).
    payload:
        Raw response bytes from the upstream tool, serialised in the
        format expected by the MCP client (typically UTF-8 JSON).
    meta:
        Arbitrary metadata attached by the gateway or tool implementation,
        e.g. ``{"tool_version": "1.2", "cache_hit": true}``.
    error_code:
        Machine-readable error identifier when *status* is ``"error"``,
        e.g. ``"ERR_TOOL_TIMEOUT"``.  ``None`` on success.
    """

    request_id: str
    status: str
    payload: bytes
    meta: dict[str, Any]
    error_code: str | None


# ---------------------------------------------------------------------------
# Protocol Interfaces
# ---------------------------------------------------------------------------


@runtime_checkable
class IToolGateway(Protocol):
    """Routes MCP tool-call requests to the appropriate upstream handler.

    The tool gateway owns lookup, invocation, and result normalisation.
    Implementations may fan out to multiple backend services, apply caching,
    or perform request coalescing.

    All conforming implementations must be usable as async context managers
    if they hold resources; the protocol itself does not mandate that, but
    individual contracts may extend it.
    """

    async def execute(
        self,
        request: JsonRpcRequest,
        ctx: RequestContext,
    ) -> ToolResult:
        """Execute the tool invocation described by *request*.

        Parameters
        ----------
        request:
            The fully parsed and validated JSON-RPC 2.0 request.  The
            ``"method"`` field indicates which tool to invoke and the
            ``"params"`` field carries the raw arguments.
        ctx:
            The active request context, used for tenant filtering, deadline
            enforcement, and observability stage timings.

        Returns
        -------
        ToolResult
            A normalised result wrapping the upstream tool's response.

        Raises
        ------
        TimeoutError
            If ``ctx.deadline_ms`` is exceeded before the upstream responds.
        ValueError
            If *request* does not describe a valid tool invocation.
        """
        ...


@runtime_checkable
class IIdentityProvider(Protocol):
    """Authenticates raw credentials and produces :class:`AgentIdentity` objects.

    Implementations cover JWT bearer tokens, API keys, mTLS certificates, or
    any other scheme supported by the platform.  A provider must be stateless
    enough to be called on every incoming connection.
    """

    async def verify(
        self,
        token: str,
    ) -> AgentIdentity | None:
        """Validate *token* and return the corresponding :class:`AgentIdentity`.

        This is the single entry-point for all credential types.
        Implementations inspect the token format to determine whether it is a
        JWT, an opaque API key, or another scheme.

        Parameters
        ----------
        token:
            The raw credential value extracted from the connection headers
            (e.g., the JWT string from ``Authorization: Bearer …`` or the
            value from ``X-API-Key``).

        Returns
        -------
        AgentIdentity | None
            The verified identity on success, or ``None`` if the token is
            invalid, expired, or revoked.  Returning ``None`` rather than
            raising makes it straightforward to compose multiple providers.
        """
        ...


@runtime_checkable
class IPolicyEvaluator(Protocol):
    """Evaluates whether an agent action is permitted under the current policy.

    Implementations may call an external OPA / Cedar policy engine, evaluate
    local rule tables, or combine multiple strategies.  The evaluator must
    never raise on a well-formed request — it always returns a
    :class:`PolicyDecision`.
    """

    async def evaluate(
        self,
        identity: AgentIdentity,
        tool_name: str,
    ) -> PolicyDecision:
        """Evaluate whether *identity* may invoke *tool_name*.

        Parameters
        ----------
        identity:
            The verified identity of the requesting agent.
        tool_name:
            The canonical name of the tool the agent wants to call, e.g.
            ``"search_codebase"`` or ``"create_embedding"``.

        Returns
        -------
        PolicyDecision
            The evaluation result.  Callers **must** check
            :attr:`PolicyDecision.allowed` before proceeding with the
            tool invocation.
        """
        ...


@runtime_checkable
class ISessionStore(Protocol):
    """Persists and retrieves agent session state.

    A session is the server-side record of a live or recently disconnected
    WebSocket connection.  The store may be backed by Redis, PostgreSQL, or
    an in-process dictionary for testing.

    Method naming follows a ``<verb>_session`` convention so callers can
    discover all session-related operations at a glance.
    """

    async def create_session(
        self,
        session_id: str,
        identity: AgentIdentity,
        ctx: RequestContext,
    ) -> dict[str, Any]:
        """Create a new session record and return it.

        Parameters
        ----------
        session_id:
            A pre-generated UUID-v4 string for the new session.
        identity:
            The authenticated identity that owns this session.
        ctx:
            The request context active at connection time.

        Returns
        -------
        dict[str, Any]
            The full session record as stored, including created-at and
            TTL metadata fields.

        Raises
        ------
        RuntimeError
            If the store has reached its configured session-count limit.
        """
        ...

    async def get_session(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve a session by *session_id*.

        Parameters
        ----------
        session_id:
            The UUID-v4 identifier assigned at :meth:`create_session` time.

        Returns
        -------
        dict[str, Any] | None
            The session record, or ``None`` if it does not exist or has
            expired.
        """
        ...

    async def close_session(
        self,
        session_id: str,
    ) -> None:
        """Mark a session as closed and remove it from active tracking.

        Implementations should persist a ``closed_at`` tombstone for audit
        purposes rather than performing a hard delete where compliance
        requirements demand it.  Idempotent — must not raise if
        *session_id* is already absent or closed.

        Parameters
        ----------
        session_id:
            The session to close.
        """
        ...

    async def list_sessions(
        self,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all currently active sessions, optionally scoped by tenant.

        Parameters
        ----------
        tenant_id:
            When provided, only sessions owned by this tenant are returned.
            When ``None``, sessions for all tenants are returned (requires
            elevated privilege in production implementations).

        Returns
        -------
        list[dict[str, Any]]
            Active session records, ordered by creation time descending.
        """
        ...


@runtime_checkable
class IAuditLogger(Protocol):
    """Appends immutable :class:`AuditEvent` records to the audit trail.

    The audit log must be tamper-evident and retained according to the
    platform's compliance requirements.  Implementations may write to a
    PostgreSQL append-only table, a managed SIEM, or a Kafka topic.

    The single :meth:`log` method must never propagate exceptions — any
    write failure must be handled internally (e.g., fallback to stderr) to
    avoid blocking the critical request path.
    """

    async def log(
        self,
        event: AuditEvent,
    ) -> None:
        """Append *event* to the audit trail.

        Implementations must treat this as a fire-and-forget operation from
        the caller's perspective.  This contract explicitly guarantees that no
        exception will propagate to the caller — internal errors must be
        swallowed and routed to a secondary store or structured log line.

        Parameters
        ----------
        event:
            The fully populated :class:`AuditEvent` to record.  The
            implementation is responsible for computing and setting
            :attr:`AuditEvent.hmac` if not already present.
        """
        ...


@runtime_checkable
class ISchemaRegistry(Protocol):
    """Manages JSON Schema definitions for tool inputs and resource types.

    The schema registry is the single source of truth for what a valid tool
    argument payload looks like.  It enables edge validation before any
    upstream call is made, reducing unnecessary round-trips on malformed
    requests.
    """

    async def get_schema(
        self,
        tool_name: str,
        api_version: str,
    ) -> dict[str, Any]:
        """Return the JSON Schema for *tool_name* at *api_version*.

        Parameters
        ----------
        tool_name:
            The canonical tool name, e.g. ``"search_codebase"``.
        api_version:
            The API version string for which the schema is requested, e.g.
            ``"2024-11-05"`` (MCP spec version) or a semver such as
            ``"1.2.0"``.  Implementations must resolve the appropriate
            schema variant for the given version.

        Returns
        -------
        dict[str, Any]
            A JSON Schema object (Draft-07 or later) describing the tool's
            ``inputSchema``.

        Raises
        ------
        KeyError
            If no schema is registered for the combination of *tool_name*
            and *api_version*.
        """
        ...
