from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_session
from app.models import InferenceResult
from app.schemas import InferenceCreate
from datetime import datetime

router = APIRouter(prefix="/inference", tags=["inference"])

@router.post("/")
async def create_inference(data: InferenceCreate, session: AsyncSession = Depends(get_session)):
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
    stmt = select(InferenceResult).where(InferenceResult.node_id == node_id).order_by(InferenceResult.time.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
