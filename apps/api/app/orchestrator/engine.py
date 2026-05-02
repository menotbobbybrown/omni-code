import asyncio
from typing import Dict, List, Any, Optional
from .decomposer import TaskDecomposer
from .model_router import ModelRouter
from .mcp_manager import MCPManager
from .agents.backend_agent import BackendAgent
from .agents.frontend_agent import FrontendAgent
from ..schemas.orchestrator import TaskGraph, SubTask, TaskStatus
from ..database.models import TaskGraphModel, SubTaskModel, TaskCheckpointModel, AgentSessionModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
import structlog
import json
from datetime import datetime, timedelta

logger = structlog.get_logger()

class OrchestratorEngine:
    def __init__(self, db_session: AsyncSession = None, redis_client=None):
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
        await self.save_graph_to_db(graph, workspace_id)
        
        logger.info("workflow_started", graph_id=graph.id, subtasks_count=len(graph.subtasks))
        
        # 2. Execution Loop
        asyncio.create_task(self.run_graph(graph))
        
        return graph

    async def save_graph_to_db(self, graph: TaskGraph, workspace_id: int):
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
                model_id=st.model_id,
                status=st.status,
                dependencies=st.dependencies,
                input_data=st.input_data,
                retry_count=st.retry_count,
                max_retries=st.max_retries
            )
            self.db.add(db_subtask)
        
        await self.db.commit()

    async def run_graph(self, graph: TaskGraph):
        """
        Executes the subtasks in the graph according to their dependencies.
        """
        await self.update_graph_status(graph.id, TaskStatus.RUNNING)
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
                    await self.update_graph_status(graph.id, TaskStatus.FAILED)
                    graph.status = TaskStatus.FAILED
                    break
                break

            # Start ready tasks in parallel
            await asyncio.gather(*[self.run_subtask(graph, task) for task in ready_tasks])

        if all(t.status == TaskStatus.COMPLETED for t in graph.subtasks):
            await self.update_graph_status(graph.id, TaskStatus.COMPLETED)
            graph.status = TaskStatus.COMPLETED

    async def run_subtask(self, graph: TaskGraph, task: SubTask):
        await self.update_subtask_status(task.id, TaskStatus.RUNNING)
        task.status = TaskStatus.RUNNING
        
        agent = self.get_agent(task.agent_type, task.id)
        
        try:
            await self.create_checkpoint(graph.id)
            
            result = await agent.run(task, {"graph_goal": graph.goal})
            
            # Log feedback for the model used
            self.model_router.log_feedback(
                model_id=task.model_id or "gpt-4o",
                success=True,
                latency=1.0,
                tokens_used=100
            )
            
            task.output_data = result
            task.status = TaskStatus.COMPLETED
            # Simulate cost tracking
            cost_data = {"amount": 0.05, "currency": "USD"}
            await self.update_subtask_status(
                task.id, 
                TaskStatus.COMPLETED, 
                output_data=result, 
                cost=cost_data, 
                tokens_used=1200,
                completed_at=datetime.utcnow()
            )
        except Exception as e:
            task.retry_count += 1
            if task.retry_count < task.max_retries:
                task.status = TaskStatus.PENDING
                await self.update_subtask_status(task.id, TaskStatus.PENDING, retry_count=task.retry_count)
            else:
                task.status = TaskStatus.FAILED
                await self.update_subtask_status(task.id, TaskStatus.FAILED)
                await self.trigger_recovery(graph, task, e)
        
        await self.create_checkpoint(graph.id)

    async def update_graph_status(self, graph_id: str, status: TaskStatus):
        if self.db:
            await self.db.execute(
                update(TaskGraphModel).where(TaskGraphModel.id == graph_id).values(status=status, updated_at=datetime.utcnow())
            )
            await self.db.commit()

    async def update_subtask_status(self, task_id: str, status: TaskStatus, output_data=None, retry_count=None, cost=None, tokens_used=None, completed_at=None):
        if self.db:
            values = {"status": status}
            if output_data:
                values["output_data"] = output_data
            if retry_count is not None:
                values["retry_count"] = retry_count
            if cost:
                values["cost"] = cost
            if tokens_used is not None:
                values["tokens_used"] = tokens_used
            if completed_at:
                values["completed_at"] = completed_at
            
            await self.db.execute(
                update(SubTaskModel).where(SubTaskModel.id == task_id).values(**values)
            )
            await self.db.commit()

    def get_task_status_local(self, graph: TaskGraph, task_id: str) -> TaskStatus:
        for t in graph.subtasks:
            if t.id == task_id:
                return t.status
        return TaskStatus.FAILED

    async def create_checkpoint(self, graph_id: str):
        if not self.db:
            return
            
        # Get current state
        result = await self.db.execute(select(TaskGraphModel).where(TaskGraphModel.id == graph_id))
        db_graph = result.scalar_one_or_none()
        if not db_graph:
            return
            
        result = await self.db.execute(select(SubTaskModel).where(SubTaskModel.graph_id == graph_id))
        subtasks = result.scalars().all()
        state = {
            "graph_status": db_graph.status,
            "subtasks": [{st.id: st.status} for st in subtasks]
        }
        
        # Count existing checkpoints
        result = await self.db.execute(select(TaskCheckpointModel).where(TaskCheckpointModel.graph_id == graph_id))
        checkpoint_count = len(result.scalars().all())
        
        checkpoint = TaskCheckpointModel(
            graph_id=graph_id,
            checkpoint_number=checkpoint_count + 1,
            state_snapshot=state
        )
        self.db.add(checkpoint)
        await self.db.commit()

    async def trigger_recovery(self, graph: TaskGraph, task: SubTask, error: Exception):
        """
        Level 3 Recovery: Escalation to a Master Agent.
        """
        logger.info("triggering_recovery", task_id=task.id)
        # Placeholder for Master Agent logic
        pass

    async def recover_running_graphs(self):
        """
        Finds graphs that were running but stopped due to server restart and resumes them.
        """
        if not self.db:
            return
            
        result = await self.db.execute(select(TaskGraphModel).where(TaskGraphModel.status == TaskStatus.RUNNING))
        running_graphs = result.scalars().all()
        
        for db_graph in running_graphs:
            logger.info("recovering_graph", graph_id=db_graph.id)
            # Fetch subtasks
            result = await self.db.execute(select(SubTaskModel).where(SubTaskModel.graph_id == db_graph.id))
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
                    retry_count=st.retry_count,
                    max_retries=st.max_retries
                ) for st in db_subtasks
            ]
            
            graph = TaskGraph(
                id=db_graph.id,
                goal=db_graph.goal,
                subtasks=subtasks,
                status=db_graph.status
            )
            
            # Resume execution
            asyncio.create_task(self.run_graph(graph))

    async def cleanup_completed_tasks(self, ttl_days: int = 7):
        """
        Automatic TTL and cleanup for completed task data.
        """
        if not self.db:
            return
            
        cutoff = datetime.utcnow() - timedelta(days=ttl_days)
        
        # Find completed/failed graphs older than cutoff
        stmt = select(TaskGraphModel.id).where(
            TaskGraphModel.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED]),
            TaskGraphModel.updated_at < cutoff
        )
        result = await self.db.execute(stmt)
        old_graph_ids = result.scalars().all()
        
        if old_graph_ids:
            logger.info("cleaning_up_old_graphs", count=len(old_graph_ids))
            # Cascade delete handles subtasks and checkpoints
            await self.db.execute(
                delete(TaskGraphModel).where(TaskGraphModel.id.in_(old_graph_ids))
            )
            await self.db.commit()

    def get_agent(self, agent_type: str, task_id: str):
        if agent_type == "frontend":
            return FrontendAgent(task_id, self.mcp_manager, self.redis_client)
        else:
            return BackendAgent(task_id, self.mcp_manager, self.redis_client)
