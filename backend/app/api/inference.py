"""
HappyBees API - Inference Endpoints

Handles ML inference result storage and retrieval.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from backend.app.database import get_session
from backend.app.models import InferenceResult
from backend.app.schemas import InferenceCreate

router = APIRouter(prefix="/inference", tags=["inference"])


@router.post("/")
async def create_inference(data: InferenceCreate, session: AsyncSession = Depends(get_session)):
    """Store an inference result from an edge device."""
    entry = InferenceResult(
        time=data.timestamp or datetime.utcnow(),
        node_id=data.node_id,
        model_type=data.model_type,
        classification=data.classification,
        confidence=data.confidence,
        anomaly_score=data.anomaly_score,
        raw_outputs=data.raw_outputs
    )
    session.add(entry)
    await session.commit()
    return {"status": "ok"}


@router.get("/latest")
async def get_latest_inference(node_id: str, session: AsyncSession = Depends(get_session)):
    """Get the most recent inference result for a node."""
    stmt = (
        select(InferenceResult)
        .where(InferenceResult.node_id == node_id)
        .order_by(InferenceResult.time.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


@router.get("/")
async def get_inference_history(
    node_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_session)
):
    """Get inference history for a node."""
    stmt = (
        select(InferenceResult)
        .where(InferenceResult.node_id == node_id)
        .order_by(InferenceResult.time.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(reversed(result.scalars().all()))
