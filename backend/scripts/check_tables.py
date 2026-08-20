import asyncio
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from database.database import Base, engine
import database.models
from sqlalchemy import text

async def main():
    print(f"Connecting to database: {engine.url}")
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table';"))
        print("SQLAlchemy tables:")
        print(res.fetchall())
        
        # Print path of database file
        import os
        print(f"Current working directory: {os.getcwd()}")
        print(f"Checking if ai_stock.db exists in cwd: {os.path.exists('ai_stock.db')}")
        if os.path.exists('ai_stock.db'):
            print(f"Size of ai_stock.db: {os.path.getsize('ai_stock.db')} bytes")

if __name__ == "__main__":
    asyncio.run(main())
