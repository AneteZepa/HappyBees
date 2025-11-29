from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

# User: postgres, Pass: beewatch_dev, DB: beewatch, Port: 5432
DATABASE_URL = "postgresql+psycopg://postgres:beewatch_dev@localhost:5432/beewatch"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    """Initializes tables and TimescaleDB hypertables."""
    async with engine.begin() as conn:
        # Enable TimescaleDB extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb;"))
        
        # Create standard tables
        await conn.run_sync(Base.metadata.create_all)
        
        # Convert to hypertables (suppress error if they already exist)
        try:
            await conn.execute(text("SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE);"))
            await conn.execute(text("SELECT create_hypertable('inference_results', 'time', if_not_exists => TRUE);"))
        except Exception as e:
            print(f"Hypertable notice (safe to ignore): {e}")
