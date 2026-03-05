import time
import uuid
from contextvars import ContextVar
from typing import Optional

import uuid6

from app.interfaces import RequestContext

# ContextVar for per-async-task context storage
_ctx_var: ContextVar[RequestContext] = ContextVar("request_context")


def get_context() -> RequestContext:
    """Retrieve the RequestContext for the current asyncio task.
    
    Raises
    ------
    RuntimeError
        If no context has been set for the current task.
    """
    try:
        return _ctx_var.get()
    except LookupError:
        raise RuntimeError("No RequestContext set for the current asyncio task")


def set_context(ctx: RequestContext) -> None:
    """Set the RequestContext for the current asyncio task."""
    _ctx_var.set(ctx)


def new_request_id() -> str:
    """Generate a new UUIDv7 string.
    
    UUIDv7 is time-ordered, making it suitable for database indexing and 
    distributed tracing.
    """
    return str(uuid6.uuid7())


def new_context(
    agent_id: str = "",
    tenant_id: Optional[str] = None,
    scopes: Optional[list[str]] = None,
    deadline_ms: int = 30000,
) -> RequestContext:
    """Create a fresh RequestContext.
    
    Parameters
    ----------
    agent_id : str
        The agent identifier, defaults to empty string.
    tenant_id : str | None
        The tenant identifier, if applicable.
    scopes : list[str] | None
        Permission scopes, defaults to an empty list.
    deadline_ms : int
        The absolute deadline in Unix epoch milliseconds. 
        If the value provided is small (e.g. 30000), it's treated as a relative 
        timeout from now and added to the current time.
        
    Returns
    -------
    RequestContext
        The newly created context with a fresh UUIDv7 request_id and UUIDv4 trace_id.
    """
    if scopes is None:
        scopes = []
        
    # If deadline_ms seems to be a relative timeout (e.g., 30000 ms), 
    # convert it to an absolute deadline timestamp.
    if deadline_ms < 1000000000000:
        absolute_deadline = int(time.time() * 1000) + deadline_ms
    else:
        absolute_deadline = deadline_ms

    ctx = RequestContext(
        request_id=new_request_id(),
        trace_id=str(uuid.uuid4()),
        agent_id=agent_id,
        tenant_id=tenant_id,
        scopes=scopes,
        deadline_ms=absolute_deadline,
        stage_timings={},
    )
    return ctx


async def inject_context() -> RequestContext:
    """FastAPI dependency to inject and set a new standard RequestContext.
    
    Returns
    -------
    RequestContext
        The newly injected request context.
    """
    ctx = new_context()
    set_context(ctx)
    return ctx
