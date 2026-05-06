import asyncio
import uuid
from app.infra.db.postgres import init_postgresql, get_session, Agent, close_postgresql

async def seed_agents():
    print("Initializing database...")
    await init_postgresql()
    
    async with get_session() as session:
        # Check if agents already exist
        from sqlalchemy import select
        result = await session.execute(select(Agent))
        if result.scalars().first():
            print("Agents already exist, skipping seed.")
            return

        print("Seeding demo agents...")
        agents = [
            Agent(
                id=uuid.uuid4(),
                name="Cursor",
                provider="Anysphere",
                agent_type="ide",
                status="Connected",
                config={"model": "claude-3-5-sonnet", "temperature": 0.5},
                permissions=["read", "write", "mcp"],
                usage_stats={"total_requests": 142, "total_tokens": 85000}
            ),
            Agent(
                id=uuid.uuid4(),
                name="ChatGPT",
                provider="OpenAI",
                agent_type="webapp",
                status="Connected",
                config={"model": "gpt-4o", "temperature": 0.7},
                permissions=["read", "mcp"],
                usage_stats={"total_requests": 56, "total_tokens": 12000}
            ),
            Agent(
                id=uuid.uuid4(),
                name="GitHub Copilot",
                provider="GitHub",
                agent_type="extension",
                status="Connected",
                config={"model": "gpt-4", "temperature": 0.2},
                permissions=["read", "write"],
                usage_stats={"total_requests": 890, "total_tokens": 240000}
            )
        ]
        
        session.add_all(agents)
        await session.commit()
        print("Demo agents seeded successfully!")

    await close_postgresql()

if __name__ == "__main__":
    asyncio.run(seed_agents())
