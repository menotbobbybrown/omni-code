import asyncio
from typing import Dict, List, Any, Optional
from .decomposer import TaskDecomposer
from .model_router import ModelRouter
from .mcp_manager import MCPManager
from .agents.backend_agent import BackendAgent
from .agents.frontend_agent import FrontendAgent
from ..schemas.orchestrator import TaskGraph, SubTask, TaskStatus
from ..database.models import TaskGraphModel, SubTaskModel, TaskCheckpointModel, AgentSessionModel
import structlog
import json
from datetime import datetime

logger = structlog.get_logger()

class OrchestratorEngine:
    def __init__(self, db_session=None, redis_client=None):
        self.model_router = ModelRouter()
        self.decomposer = TaskDecomposer(self.model_router)
        self.mcp_manager = MCPManager()
        self.db = db_session
        self.redis_client = redis_client

    async def execute_workflow(self, prompt: str, workspace_id: int):
        """
        Main entry point to start a workflow.
        """
        # 1. Decomposition
        context = {"workspace_id": workspace_id}
        graph = await self.decomposer.decompose(prompt, context)
        
        # Save graph to DB
        self.save_graph_to_db(graph, workspace_id)
        
        logger.info("workflow_started", graph_id=graph.id, subtasks_count=len(graph.subtasks))
        
        # 2. Execution Loop
        asyncio.create_task(self.run_graph(graph))
        
        return graph

    def save_graph_to_db(self, graph: TaskGraph, workspace_id: int):
        if not self.db:
            return
            
        db_graph = TaskGraphModel(
            id=graph.id,
            goal=graph.goal,
            status=graph.status,
            workspace_id=workspace_id
        )
        self.db.add(db_graph)
        
        for st in graph.subtasks:
            db_subtask = SubTaskModel(
                id=st.id,
                graph_id=graph.id,
                title=st.title,
                description=st.description,
                agent_type=st.agent_type,
                status=st.status,
                dependencies=st.dependencies,
                input_data=st.input_data,
                retry_count=st.retry_count,
                max_retries=st.max_retries
            )
            self.db.add(db_subtask)
        
        self.db.commit()

    async def run_graph(self, graph: TaskGraph):
        """
        Executes the subtasks in the graph according to their dependencies.
        """
        self.update_graph_status(graph.id, TaskStatus.RUNNING)
        graph.status = TaskStatus.RUNNING
        
        while not all(t.status == TaskStatus.COMPLETED for t in graph.subtasks):
            # Find tasks that are ready to run
            ready_tasks = [
                t for t in graph.subtasks 
                if t.status == TaskStatus.PENDING and 
                all(self.get_task_status_local(graph, dep_id) == TaskStatus.COMPLETED for dep_id in t.dependencies)
            ]
            
            if not ready_tasks:
                if any(t.status == TaskStatus.RUNNING for t in graph.subtasks):
                    await asyncio.sleep(1)
                    continue
                if any(t.status == TaskStatus.FAILED for t in graph.subtasks):
                    self.update_graph_status(graph.id, TaskStatus.FAILED)
                    graph.status = TaskStatus.FAILED
                    break
                break

            # Start ready tasks in parallel
            await asyncio.gather(*[self.run_subtask(graph, task) for task in ready_tasks])

        if all(t.status == TaskStatus.COMPLETED for t in graph.subtasks):
            self.update_graph_status(graph.id, TaskStatus.COMPLETED)
            graph.status = TaskStatus.COMPLETED

    async def run_subtask(self, graph: TaskGraph, task: SubTask):
        self.update_subtask_status(task.id, TaskStatus.RUNNING)
        task.status = TaskStatus.RUNNING
        
        agent = self.get_agent(task.agent_type, task.id)
        
        try:
            await self.create_checkpoint(graph.id)
            
            result = await agent.run(task, {"graph_goal": graph.goal})
            
            # Log feedback for the model used (assuming we know which one)
            self.model_router.log_feedback(
                model_id="gpt-4o",  # Should be dynamic
                success=True,
                latency=1.0,  # Should be measured
                tokens_used=100  # Should be tracked
            )
            
            task.output_data = result
            task.status = TaskStatus.COMPLETED
            self.update_subtask_status(task.id, TaskStatus.COMPLETED, output_data=result)
        except Exception as e:
            task.retry_count += 1
            if task.retry_count < task.max_retries:
                task.status = TaskStatus.PENDING
                self.update_subtask_status(task.id, TaskStatus.PENDING, retry_count=task.retry_count)
            else:
                task.status = TaskStatus.FAILED
                self.update_subtask_status(task.id, TaskStatus.FAILED)
                await self.trigger_recovery(graph, task, e)
        
        await self.create_checkpoint(graph.id)

    def update_graph_status(self, graph_id: str, status: TaskStatus):
        if self.db:
            db_graph = self.db.query(TaskGraphModel).filter(TaskGraphModel.id == graph_id).first()
            if db_graph:
                db_graph.status = status
                self.db.commit()

    def update_subtask_status(self, task_id: str, status: TaskStatus, output_data=None, retry_count=None):
        if self.db:
            db_task = self.db.query(SubTaskModel).filter(SubTaskModel.id == task_id).first()
            if db_task:
                db_task.status = status
                if output_data:
                    db_task.output_data = output_data
                if retry_count is not None:
                    db_task.retry_count = retry_count
                self.db.commit()

    def get_task_status_local(self, graph: TaskGraph, task_id: str) -> TaskStatus:
        for t in graph.subtasks:
            if t.id == task_id:
                return t.status
        return TaskStatus.FAILED

    async def create_checkpoint(self, graph_id: str):
        if not self.db:
            return
            
        # Get current state
        db_graph = self.db.query(TaskGraphModel).filter(TaskGraphModel.id == graph_id).first()
        if not db_graph:
            return
            
        subtasks = self.db.query(SubTaskModel).filter(SubTaskModel.graph_id == graph_id).all()
        state = {
            "graph_status": db_graph.status,
            "subtasks": [{st.id: st.status} for st in subtasks]
        }
        
        # Count existing checkpoints
        checkpoint_count = self.db.query(TaskCheckpointModel).filter(TaskCheckpointModel.graph_id == graph_id).count()
        
        checkpoint = TaskCheckpointModel(
            graph_id=graph_id,
            checkpoint_number=checkpoint_count + 1,
            state_snapshot=state
        )
        self.db.add(checkpoint)
        self.db.commit()

    async def trigger_recovery(self, graph: TaskGraph, task: SubTask, error: Exception):
        """
        Level 3 Recovery: Escalation to a Master Agent.
        """
        logger.info("triggering_recovery", task_id=task.id)
        # Placeholder for Master Agent logic
        pass

    def get_agent(self, agent_type: str, task_id: str):
        if agent_type == "frontend":
            return FrontendAgent(task_id, self.mcp_manager, self.redis_client)
        else:
            return BackendAgent(task_id, self.mcp_manager, self.redis_client)
