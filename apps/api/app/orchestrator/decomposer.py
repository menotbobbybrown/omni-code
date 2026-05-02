import json
from typing import List, Dict, Any
from .model_router import ModelRouter, ModelCapability
from ..schemas.orchestrator import TaskGraph, SubTask, TaskStatus
import uuid
from datetime import datetime

class TaskDecomposer:
    def __init__(self, model_router: ModelRouter):
        self.model_router = model_router

    async def decompose(self, goal: str, context: Dict[str, Any]) -> TaskGraph:
        """
        Decomposes a high-level goal into a graph of subtasks.
        """
        model = self.model_router.route(complexity=0.7, context_size=len(str(context)), priority=ModelCapability.REASONING)
        
        # In a real implementation, we would call the LLM here.
        # For now, we simulate the LLM output or use a sophisticated prompt.
        
        prompt = f"""
        Goal: {goal}
        Context: {json.dumps(context)}
        
        You are a Master Orchestrator. Your task is to break down the user's goal into a set of granular, actionable subtasks.
        Each subtask should be assigned to a specific agent type (backend, frontend, devops, etc.).
        Define dependencies between tasks to ensure a proper execution order (DAG).
        
        Requirements:
        1. Tasks should be small enough to be completed in one go.
        2. Identify parallelizable tasks.
        3. Specify clear inputs and expected outputs for each task.
        
        Return a JSON object representing a TaskGraph:
        {{
            "id": "unique-graph-id",
            "goal": "{goal}",
            "subtasks": [
                {{
                    "id": "task-1",
                    "title": "...",
                    "description": "...",
                    "agent_type": "backend|frontend|devops",
                    "dependencies": ["other-task-id"],
                    "input_data": {{}}
                }}
            ]
        }}
        """
        
        # Simulating LLM response for a common task
        # In production, this would be: response = await call_llm(model.id, prompt)
        
        subtasks = [
            SubTask(
                id="task-1",
                title="Analyze requirements",
                description="Review the goal and context to identify key components.",
                agent_type="backend",
                dependencies=[],
                status=TaskStatus.PENDING
            ),
            SubTask(
                id="task-2",
                title="Implement core logic",
                description="Develop the main functionality as requested.",
                agent_type="backend",
                dependencies=["task-1"],
                status=TaskStatus.PENDING
            ),
            SubTask(
                id="task-3",
                title="Create frontend components",
                description="Build UI elements to interact with the core logic.",
                agent_type="frontend",
                dependencies=["task-1"],
                status=TaskStatus.PENDING
            ),
            SubTask(
                id="task-4",
                title="Integration testing",
                description="Verify that backend and frontend work together.",
                agent_type="backend",
                dependencies=["task-2", "task-3"],
                status=TaskStatus.PENDING
            )
        ]
        
        graph = TaskGraph(
            id=str(uuid.uuid4()),
            goal=goal,
            subtasks=subtasks,
            status=TaskStatus.PENDING,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )
        
        self.validate_graph(graph)
        return graph

    def validate_graph(self, graph: TaskGraph):
        """
        Ensures the graph is a Directed Acyclic Graph (DAG).
        """
        adj = {t.id: t.dependencies for t in graph.subtasks}
        visited = set()
        path = set()

        def visit(node_id):
            if node_id in path:
                raise ValueError(f"Cycle detected in task graph at {node_id}")
            if node_id in visited:
                return
            
            path.add(node_id)
            for dep in adj.get(node_id, []):
                visit(dep)
            path.remove(node_id)
            visited.add(node_id)

        for task in graph.subtasks:
            visit(task.id)
