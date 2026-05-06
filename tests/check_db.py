import asyncio
import structlog
from app.infra.db.postgres import init_postgresql, get_session, close_postgresql
from sqlalchemy import text

async def check():
    print("Initializing database...")
    await init_postgresql()
    async with get_session() as session:
        try:
            res = await session.execute(text('SELECT count(*) FROM agents'))
            count = res.scalar()
            print(f"Total agents in database: {count}")
        except Exception as e:
            print(f"Error: {e}")
    await close_postgresql()

if __name__ == "__main__":
    asyncio.run(check())
