from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from app.database.session import get_async_db
from app.database.models import Thread, Message, ActionHistory, AgentLog
from app.schemas.thread import ThreadResponse, MessageResponse, ActionHistoryResponse

router = APIRouter(prefix="/threads", tags=["threads"])

@router.get("/{thread_id}", response_model=ThreadResponse)
async def get_thread(thread_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Thread).where(Thread.id == thread_id))
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread

# SDK uses /api/threads/{id}/history
@router.get("/{thread_id}/history")
async def get_thread_history(thread_id: int, db: AsyncSession = Depends(get_async_db)):
    # Combine messages and actions for history
    messages_result = await db.execute(
        select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at.asc())
    )
    actions_result = await db.execute(
        select(ActionHistory).where(ActionHistory.thread_id == thread_id).order_by(ActionHistory.created_at.asc())
    )
    
    history = []
    for m in messages_result.scalars().all():
        history.append({"type": "message", "data": m})
    for a in actions_result.scalars().all():
        history.append({"type": "action", "data": a})
        
    return history

@router.get("/{thread_id}/messages", response_model=List[MessageResponse])
async def get_thread_messages(thread_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(Message)
        .where(Message.thread_id == thread_id)
        .order_by(Message.created_at.asc())
    )
    return result.scalars().all()

@router.get("/{thread_id}/actions", response_model=List[ActionHistoryResponse])
async def get_thread_actions(thread_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(ActionHistory)
        .where(ActionHistory.thread_id == thread_id)
        .order_by(ActionHistory.created_at.asc())
    )
    return result.scalars().all()

@router.get("/{thread_id}/logs")
async def get_thread_logs(thread_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(
        select(AgentLog)
        .where(AgentLog.thread_id == thread_id)
        .order_by(AgentLog.created_at.asc())
    )
    return [log.content for log in result.scalars().all()]
