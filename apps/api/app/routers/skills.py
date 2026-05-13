from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from app.database.session import get_async_db
from app.database.models import Skill
from app.schemas.skill import SkillResponse, SkillCreate, SkillUpdate

router = APIRouter(prefix="/skills", tags=["skills"])

@router.get("", response_model=List[SkillResponse])
async def list_skills(
    workspace_id: Optional[int] = None,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db)
):
    query = select(Skill)
    if workspace_id:
        query = query.where((Skill.workspace_id == workspace_id) | (Skill.is_global == True))
    else:
        query = query.where(Skill.is_global == True)
        
    if category:
        query = query.where(Skill.category == category)
        
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/categories")
async def get_categories(db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Skill.category).distinct())
    return [row for row in result.scalars().all() if row]

@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: int, db: AsyncSession = Depends(get_async_db)):
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill

@router.post("/", response_model=SkillResponse)
async def create_skill(skill_data: SkillCreate, db: AsyncSession = Depends(get_async_db)):
    new_skill = Skill(**skill_data.model_dump())
    db.add(new_skill)
    await db.commit()
    await db.refresh(new_skill)
    return new_skill
