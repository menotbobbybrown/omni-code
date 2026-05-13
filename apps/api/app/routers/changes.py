from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from app.database.session import get_async_db
from app.database.models import PendingChange

# Align with SDK which uses /api/pending-changes
router = APIRouter(prefix="/pending-changes", tags=["changes"])

@router.get("/{thread_id}")
async def get_changes(thread_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(PendingChange).where(PendingChange.thread_id == thread_id))
    return result.scalars().all()

@router.post("/{change_id}/accept")
async def accept_change(change_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(PendingChange).where(PendingChange.id == change_id))
    change = result.scalar_one_or_none()
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    
    change.status = "accepted"
    await db.commit()
    return {"status": "accepted"}

@router.post("/{change_id}/reject")
async def reject_change(change_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(PendingChange).where(PendingChange.id == change_id))
    change = result.scalar_one_or_none()
    if not change:
        raise HTTPException(status_code=404, detail="Change not found")
    
    change.status = "rejected"
    await db.commit()
    return {"status": "rejected"}
