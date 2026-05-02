from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
from ..database.session import get_async_db
from .engine import OrchestratorEngine
from ..schemas.orchestrator import OrchestratorRequest, OrchestratorResponse, TaskGraph
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])

@router.post("/run", response_model=OrchestratorResponse)
async def run_orchestrator(
    request_data: OrchestratorRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Start a new orchestration workflow.
    """
    logger.info("orchestrator_run_request", workspace_id=request_data.workspace_id)
    
    engine = OrchestratorEngine(db_session=db)
    graph = await engine.execute_workflow(request_data.prompt, request_data.workspace_id)
    
    return OrchestratorResponse(
        graph_id=graph.id,
        status=graph.status
    )

@router.post("/preview", response_model=TaskGraph)
async def preview_orchestrator(
    request_data: OrchestratorRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Preview the decomposition of a prompt.
    """
    logger.info("orchestrator_preview_request", workspace_id=request_data.workspace_id)
    
    engine = OrchestratorEngine(db_session=db)
    context = {"workspace_id": request_data.workspace_id}
    graph = await engine.decomposer.decompose(request_data.prompt, context)
    
    # Add dummy timestamps for the schema
    graph_dict = graph.dict()
    graph_dict["created_at"] = datetime.utcnow().isoformat()
    graph_dict["updated_at"] = datetime.utcnow().isoformat()
    
    return graph_dict

from ..database.models import TaskGraphModel, SubTaskModel
from sqlalchemy import select

@router.get("/{graph_id}", response_model=TaskGraph)
async def get_graph_status(
    graph_id: str,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get the status of a specific task graph.
    """
    result = await db.execute(select(TaskGraphModel).where(TaskGraphModel.id == graph_id))
    db_graph = result.scalar_one_or_none()
    
    if not db_graph:
        raise HTTPException(status_code=404, detail="Graph not found")
        
    result = await db.execute(select(SubTaskModel).where(SubTaskModel.graph_id == graph_id))
    db_subtasks = result.scalars().all()
    
    subtasks = [
        SubTask(
            id=st.id,
            title=st.title,
            description=st.description,
            agent_type=st.agent_type,
            status=st.status,
            dependencies=st.dependencies,
            input_data=st.input_data,
            output_data=st.output_data,
            cost=st.cost,
            tokens_used=st.tokens_used,
            retry_count=st.retry_count,
            max_retries=st.max_retries,
            completed_at=st.completed_at.isoformat() if st.completed_at else None
        ) for st in db_subtasks
    ]
    
    return TaskGraph(
        id=db_graph.id,
        goal=db_graph.goal,
        subtasks=subtasks,
        status=db_graph.status,
        created_at=db_graph.created_at.isoformat(),
        updated_at=db_graph.updated_at.isoformat()
    )

from fastapi.responses import StreamingResponse
import asyncio
import json

@router.get("/{graph_id}/stream")
async def stream_graph_logs(graph_id: str, request: Request):
    """
    Stream orchestration logs via SSE.
    """
    async def event_generator():
        # In production, this would subscribe to Redis
        # For now, we simulate some progress updates
        yield f"data: {json.dumps({'message': f'Connected to stream for {graph_id}'})}\n\n"
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(5)
            yield f"data: {json.dumps({'message': 'Heartbeat', 'graph_id': graph_id})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/{graph_id}/inject")
async def inject_task(graph_id: str, task_data: Dict[str, Any]):
    """
    Inject a new task or modify an existing one in a running graph.
    """
    return {"status": "success"}
