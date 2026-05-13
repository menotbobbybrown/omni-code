from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from app.database.session import get_async_db
from app.database.models import BackgroundTask, BlockerNotification
from app.schemas.task import TaskResponse, TaskCreate, BlockerResolve

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get("", response_model=List[TaskResponse])
async def list_tasks(
    workspace_id: Optional[int] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db)
):
    query = select(BackgroundTask)
    if workspace_id:
        query = query.where(BackgroundTask.workspace_id == workspace_id)
    if status:
        query = query.where(BackgroundTask.status == status)
    
    query = query.order_by(BackgroundTask.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(BackgroundTask).where(BackgroundTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.post("/{task_id}/resolve")
async def resolve_blocker(
    task_id: int, 
    resolve_data: BlockerResolve, 
    db: AsyncSession = Depends(get_async_db)
):
    # Find active blocker for this task
    result = await db.execute(
        select(BlockerNotification)
        .where(BlockerNotification.task_id == task_id)
        .where(BlockerNotification.resolved == False)
    )
    blocker = result.scalar_one_or_none()
    
    if not blocker:
        raise HTTPException(status_code=404, detail="No active blocker found for this task")
        
    blocker.resolved = True
    blocker.resolution = resolve_data.resolution
    
    # Also update task status if it was blocked
    task_result = await db.execute(select(BackgroundTask).where(BackgroundTask.id == task_id))
    task = task_result.scalar_one_or_none()
    if task and task.status == "blocked":
        task.status = "pending"
        
    await db.commit()
    return {"status": "success", "message": "Blocker resolved"}
