import asyncio

import pytest

from app.context import get_context, inject_context, new_context, set_context


@pytest.mark.asyncio
async def test_concurrent_contexts():
    """Verify that concurrent asyncio tasks receive independent ContextVar storage."""
    # Define a helper coroutine that sets a context and yields control
    async def task_workflow(agent_id: str, delay: float):
        # Create and set a unique context for this task
        ctx = new_context(agent_id=agent_id)
        set_context(ctx)
        
        # Yield control to the event loop so the other task can run
        await asyncio.sleep(delay)
        
        # Retrieve the context and verify it hasn't been overwritten
        retrieved_ctx = get_context()
        
        assert retrieved_ctx.agent_id == agent_id
        assert retrieved_ctx.request_id == ctx.request_id
        return retrieved_ctx

    # Run two tasks concurrently with different agent_ids
    result1, result2 = await asyncio.gather(
        task_workflow("agent-1", 0.02),
        task_workflow("agent-2", 0.01)
    )

    # Verify both got their respective contexts without cross-contamination
    assert result1.agent_id == "agent-1"
    assert result2.agent_id == "agent-2"
    assert result1.request_id != result2.request_id


@pytest.mark.asyncio
async def test_inject_context():
    """Verify the FastAPI dependency creates and sets a valid context."""
    ctx = await inject_context()
    
    assert ctx is not None
    assert ctx.request_id is not None
    assert ctx.trace_id is not None
    assert ctx.stage_timings == {}
    
    # Verify it was actually set in the ContextVar
    retrieved = get_context()
    assert retrieved is ctx


def test_get_context_no_context():
    """Verify get_context raises RuntimeError when no context is set."""
    # Clear the context for this test
    from app.context import _ctx_var
    token = _ctx_var.set(None)  # Type ignore but forces error or just reset
    _ctx_var.reset(token)
    
    with pytest.raises(RuntimeError, match="No RequestContext set"):
        get_context()
