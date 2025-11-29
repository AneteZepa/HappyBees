"""
HappyBees API - Log Endpoints

Handles device log storage and retrieval.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime

from backend.app.database import get_session
from backend.app.models import DeviceLog, Node

router = APIRouter(prefix="/logs", tags=["logs"])


class LogCreate(BaseModel):
    """Schema for creating log entries."""
    node_id: str
    message: str


@router.post("/")
async def create_log(data: LogCreate, session: AsyncSession = Depends(get_session)):
    """Store a log message from an edge device."""
    # Auto-register node if not exists
    node = await session.get(Node, data.node_id)
    if not node:
        new_node = Node(
            node_id=data.node_id,
            name=f"Auto-Reg: {data.node_id}",
            last_seen_at=datetime.utcnow()
        )
        session.add(new_node)
        await session.flush()
    else:
        node.last_seen_at = datetime.utcnow()

    log = DeviceLog(node_id=data.node_id, message=data.message)
    session.add(log)
    await session.commit()
    return {"status": "ok"}


@router.get("/")
async def get_logs(
    node_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_session)
):
    """Get log history for a node."""
    stmt = (
        select(DeviceLog)
        .where(DeviceLog.node_id == node_id)
        .order_by(DeviceLog.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(reversed(result.scalars().all()))
