"""
HappyBees API - Command Endpoints

Handles command queue for edge devices.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.app.database import get_session
from backend.app.models import Command
from backend.app.schemas import CommandCreate, CommandResponse

router = APIRouter(prefix="/commands", tags=["commands"])


@router.post("/", response_model=CommandResponse)
async def queue_command(data: CommandCreate, session: AsyncSession = Depends(get_session)):
    """Queue a command for an edge device."""
    cmd = Command(
        node_id=data.node_id,
        command_type=data.command_type,
        params=data.params
    )
    session.add(cmd)
    await session.commit()
    return {"command_id": cmd.command_id, "status": "pending"}


@router.get("/pending")
async def get_pending_commands(node_id: str, session: AsyncSession = Depends(get_session)):
    """Get pending commands for a specific device."""
    stmt = (
        select(Command)
        .where(Command.node_id == node_id, Command.status == "pending")
    )
    result = await session.execute(stmt)
    commands = result.scalars().all()
    
    # Mark commands as sent
    for cmd in commands:
        cmd.status = "sent"
    await session.commit()
    
    return commands
