import httpx
import asyncio
import uuid

BASE_URL = "http://localhost:8095/api/v1/agents"

async def test_api():
    async with httpx.AsyncClient() as client:
        # 1. List agents
        print("--- Listing Agents ---")
        r = await client.get(BASE_URL)
        print(f"Status: {r.status_code}")
        print(r.json())

        # 2. Create an agent
        print("\n--- Creating Agent ---")
        agent_data = {
            "name": f"Test Agent {uuid.uuid4().hex[:4]}",
            "provider": "cursor",
            "config": {"theme": "dark"}
        }
        r = await client.post(BASE_URL, json=agent_data)
        print(f"Status: {r.status_code}")
        agent = r.json()
        print(agent)
        agent_id = agent["id"]

        # 3. Get agent
        print(f"\n--- Getting Agent {agent_id} ---")
        r = await client.get(f"{BASE_URL}/{agent_id}")
        print(f"Status: {r.status_code}")
        print(r.json())

        # 4. Delete agent
        print(f"\n--- Deleting Agent {agent_id} ---")
        r = await client.delete(f"{BASE_URL}/{agent_id}")
        print(f"Status: {r.status_code}")
        print(r.json())

if __name__ == "__main__":
    asyncio.run(test_api())
