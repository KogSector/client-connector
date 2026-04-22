import asyncio
import os
from sqlalchemy import text
from app.infra.db.postgres import get_session

async def check_agents():
    print("Checking agents table in client-connector DB...")
    async with get_session() as session:
        try:
            result = await session.execute(text("SELECT id, name, provider, status FROM agents"))
            agents = result.fetchall()
            print(f"Found {len(agents)} agents:")
            for agent in agents:
                print(f" - {agent.name} ({agent.provider}): {agent.status} [ID: {agent.id}]")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_agents())
