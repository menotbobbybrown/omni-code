from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from ..database.session import get_db
from .engine import OrchestratorEngine
from ..schemas.orchestrator import OrchestratorRequest, OrchestratorResponse, TaskGraph
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])

@router.post("/run", response_model=OrchestratorResponse)
async def run_orchestrator(
    request_data: OrchestratorRequest,
    db: Session = Depends(get_db)
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

@router.get("/{graph_id}", response_model=TaskGraph)
async def get_graph_status(graph_id: str):
    """
    Get the status of a specific task graph.
    """
    # In a real implementation, this would fetch from DB
    # For now, it might be in engine.running_graphs
    return None

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
