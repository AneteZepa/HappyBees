from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.app.database import get_session
from backend.app.models import Telemetry, Node
from backend.app.schemas import TelemetryCreate
from datetime import datetime

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

@router.post("/")
async def create_telemetry(data: TelemetryCreate, session: AsyncSession = Depends(get_session)):
    node = await session.get(Node, data.node_id)
    if not node:
        node = Node(node_id=data.node_id, name=f"Node {data.node_id}", last_seen_at=datetime.utcnow())
        session.add(node)
    else:
        node.last_seen_at = datetime.utcnow()

    entry = Telemetry(
        time=data.timestamp or datetime.utcnow(),
        node_id=data.node_id,
        temperature_c=data.temperature_c,
        humidity_pct=data.humidity_pct,
        battery_mv=data.battery_mv,
        rssi_dbm=data.rssi_dbm,
        error_flags=data.error_flags
    )
    session.add(entry)
    await session.commit()
    return {"status": "ok"}

# --- THIS WAS MISSING ---
@router.get("/")
async def get_telemetry_history(
    node_id: str, 
    limit: int = 100, 
    session: AsyncSession = Depends(get_session)
):
    stmt = (
        select(Telemetry)
        .where(Telemetry.node_id == node_id)
        .order_by(Telemetry.time.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    # Return reversed (oldest first) so the graph draws left-to-right correctly
    return list(reversed(result.scalars().all()))
# ------------------------

@router.get("/latest")
async def get_latest_telemetry(node_id: str, session: AsyncSession = Depends(get_session)):
    stmt = select(Telemetry).where(Telemetry.node_id == node_id).order_by(Telemetry.time.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
