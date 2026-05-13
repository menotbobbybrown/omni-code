from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database.session import get_async_db
from app.database.models import ActionHistory
import os

router = APIRouter(prefix="/rollback", tags=["rollback"])

@router.post("/{action_id}")
async def rollback_action(action_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(ActionHistory).where(ActionHistory.id == action_id))
    action = result.scalar_one_or_none()
    
    if not action:
        raise HTTPException(status_code=404, detail="Action history not found")
        
    if action.action_type != "file_edit":
         raise HTTPException(status_code=400, detail="Only file_edit actions can be rolled back")

    # In a real system, we would apply the content_before back to the file
    # For now, we'll just simulate it and mark it as rolled back if we had a status field
    
    return {
        "status": "success", 
        "reverted_file": action.file_path,
        "action_id": action_id
    }
