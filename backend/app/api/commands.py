from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_session
from app.models import Command
from app.schemas import CommandCreate, CommandResponse

router = APIRouter(prefix="/commands", tags=["commands"])

@router.post("/", response_model=CommandResponse)
async def queue_command(data: CommandCreate, session: AsyncSession = Depends(get_session)):
    cmd = Command(node_id=data.node_id, command_type=data.command_type, params=data.params)
    session.add(cmd)
    await session.commit()
    return {"command_id": cmd.command_id, "status": "pending"}

@router.get("/pending")
async def get_pending_commands(node_id: str, session: AsyncSession = Depends(get_session)):
    stmt = select(Command).where(Command.node_id == node_id, Command.status == "pending")
    result = await session.execute(stmt)
    return result.scalars().all()
