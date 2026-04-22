from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class AgentConfig(BaseModel):
    """Configuration options for an agent."""
    model: Optional[str] = "gpt-4"
    temperature: Optional[float] = 0.7
    system_prompt: Optional[str] = None
    extra: Optional[Dict[str, Any]] = Field(default_factory=dict)

class AgentUsageStats(BaseModel):
    """Usage statistics for an agent."""
    total_requests: int = 0
    total_tokens: int = 0
    last_active: Optional[datetime] = None

class AgentRecord(BaseModel):
    """Complete record of a connected agent."""
    id: str
    user_id: Optional[str] = None
    name: str
    provider: Optional[str] = None
    agent_type: str
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    permissions: List[str] = []
    status: str
    config: AgentConfig
    created_at: datetime
    updated_at: datetime
    last_used: Optional[datetime] = None
    usage_stats: AgentUsageStats

class CreateAgentRequest(BaseModel):
    """Request payload for creating a new agent connection."""
    name: str
    provider: Optional[str] = None
    agent_type: str
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    permissions: Optional[List[str]] = ["read"]
    config: Optional[AgentConfig] = None

class UpdateAgentRequest(BaseModel):
    """Request payload for updating an existing agent."""
    name: Optional[str] = None
    status: Optional[str] = None
    config: Optional[AgentConfig] = None
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
