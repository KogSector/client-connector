import uuid
import structlog
from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select

from app.infra.db.postgres import get_session, Agent
from app.schemas.agent import AgentRecord, CreateAgentRequest, UpdateAgentRequest, AgentConfig, AgentUsageStats

logger = structlog.get_logger()
router = APIRouter(prefix="/api/agents", tags=["Agents"])

def _agent_to_record(agent: Agent) -> AgentRecord:
    """Convert SQLAlchemy Agent model to Pydantic AgentRecord."""
    return AgentRecord(
        id=str(agent.id),
        user_id=str(agent.user_id) if agent.user_id else None,
        name=agent.name,
        provider=agent.provider,
        agent_type=agent.agent_type,
        endpoint=agent.endpoint,
        api_key=agent.api_key,
        permissions=agent.permissions or [],
        status=agent.status or "Pending",
        config=AgentConfig(**(agent.config or {})),
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        last_used=agent.last_used,
        usage_stats=AgentUsageStats(**(agent.usage_stats or {}))
    )

@router.get("", response_model=List[AgentRecord])
async def list_agents():
    """List all connected agents."""
    logger.info("Listing all agents")
    async with get_session() as session:
        result = await session.execute(select(Agent).order_by(Agent.created_at.desc()))
        agents = result.scalars().all()
        return [_agent_to_record(a) for a in agents]

@router.post("", response_model=AgentRecord, status_code=201)
async def create_agent(payload: CreateAgentRequest):
    """Create a new agent connection."""
    logger.info("Creating agent", name=payload.name, type=payload.agent_type)
    async with get_session() as session:
        agent = Agent(
            name=payload.name,
            provider=payload.provider,
            agent_type=payload.agent_type,
            endpoint=payload.endpoint,
            api_key=payload.api_key,
            permissions=payload.permissions or [],
            status="Connected",
            config=payload.config.model_dump() if payload.config else {},
            usage_stats={}
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        return _agent_to_record(agent)

@router.get("/{agent_id}", response_model=AgentRecord)
async def get_agent(agent_id: str):
    """Get a specific agent by ID."""
    try:
        aid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID format")
        
    async with get_session() as session:
        agent = await session.get(Agent, aid)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return _agent_to_record(agent)

@router.put("/{agent_id}", response_model=AgentRecord)
async def update_agent(agent_id: str, payload: UpdateAgentRequest):
    """Update an agent's configuration or status."""
    logger.info("Updating agent", agent_id=agent_id)
    try:
        aid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID format")
        
    async with get_session() as session:
        agent = await session.get(Agent, aid)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
            
        if payload.name is not None:
            agent.name = payload.name
        if payload.status is not None:
            agent.status = payload.status
        if payload.config is not None:
            agent.config = payload.config.model_dump()
        if payload.endpoint is not None:
            agent.endpoint = payload.endpoint
        if payload.api_key is not None:
            agent.api_key = payload.api_key
            
        await session.commit()
        await session.refresh(agent)
        return _agent_to_record(agent)

@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete an agent connection."""
    logger.info("Deleting agent", agent_id=agent_id)
    try:
        aid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID format")
        
    async with get_session() as session:
        agent = await session.get(Agent, aid)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
            
        await session.delete(agent)
        await session.commit()
        return {"success": True, "message": "Agent deleted successfully"}

@router.get("/sample/windsurf")
async def get_windsurf_sample_data():
    """Get sample data for Windsurf integration testing."""
    return {
        "connected": True,
        "lastSync": "2026-05-08T14:27:00Z",
        "activeRepos": 3,
        "totalFiles": 247,
        "toolsAvailable": [
            "knowledge_search",
            "code_context",
            "semantic_search",
            "graph_traversal",
            "entity_extraction"
        ]
    }
