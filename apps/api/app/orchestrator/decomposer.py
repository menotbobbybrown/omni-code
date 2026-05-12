"""
Advanced task decomposition using DeepSeek-Reasoner for intelligent task graph generation.
Implements multi-step reasoning for complex task decomposition.
"""

import json
import uuid
import structlog
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.core.model_provider import ModelProvider
from app.schemas.orchestrator import TaskGraph, SubTask, TaskStatus
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

logger = structlog.get_logger()


class ReasoningChain:
    """Chain-based reasoning for complex task decomposition."""

    def __init__(self, llm):
        self.llm = llm

    async def step(self, prompt: str, context: str) -> str:
        """Execute a single reasoning step."""
        response = await self.llm.ainvoke([
            SystemMessage(content="You are a reasoning engine. Think step by step about the task."),
            HumanMessage(content=f"Context: {context}\n\nTask: {prompt}")
        ])
        return response.content


class TaskDecomposer:
    """
    Production-ready task decomposer using DeepSeek-Reasoner.
    
    Features:
    - Multi-step reasoning chain for complex task decomposition
    - Parallel task identification
    - Dependency graph generation
    - Agent type assignment with skill matching
    """

    def __init__(self, model_router=None):
        self.model_router = model_router
        self.reasoning_llm = None

    async def _get_reasoner(self):
        """Get DeepSeek-Reasoner instance with caching."""
        if self.reasoning_llm is None:
            self.reasoning_llm = ModelProvider.get_model("deepseek", "deepseek-reasoner")
        return self.reasoning_llm

    async def decompose(self, goal: str, context: Dict[str, Any]) -> TaskGraph:
        """
        Decompose a goal into a task graph using multi-step reasoning.
        
        Args:
            goal: The user's goal/objective
            context: Additional context (workspace_id, preferences, etc.)
            
        Returns:
            TaskGraph with subtasks and dependencies
        """
        reasoner = await self._get_reasoner()
        
        # Step 1: Understand the goal (high-level analysis)
        understanding = await self._analyze_goal(reasoner, goal, context)
        
        # Step 2: Identify all tasks needed
        task_specs = await self._identify_tasks(reasoner, goal, understanding, context)
        
        # Step 3: Determine dependencies and parallel work
        task_graph = await self._build_dependency_graph(reasoner, task_specs, understanding)
        
        logger.info(
            "decomposition_complete",
            goal=goal,
            subtasks=len(task_graph.subtasks),
            parallel_groups=self._count_parallel_groups(task_graph)
        )
        
        return task_graph

    async def _analyze_goal(
        self,
        reasoner,
        goal: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Step 1: High-level analysis of the goal.
        
        Analyzes the goal to understand:
        - Domain (backend, frontend, full-stack, devops, etc.)
        - Complexity level
        - Required skills
        - Potential risks
        """
        system = """You are a Master Orchestrator analyzing a user goal.
Perform deep reasoning to understand what the user wants to achieve.

Analyze and return ONLY valid JSON:
{
  "domain": "backend|frontend|fullstack|devops|security|testing|docs|general",
  "complexity": "simple|moderate|complex",
  "required_skills": ["skill1", "skill2"],
  "risk_factors": ["risk1", "risk2"],
  "success_criteria": ["criterion1", "criterion2"],
  "estimated_subtasks": number
}
JSON ONLY, no markdown."""

        workspace_context = ""
        if context.get("workspace_id"):
            workspace_context = f"\nWorkspace ID: {context['workspace_id']}"
            if context.get("tech_stack"):
                workspace_context += f"\nTech stack: {', '.join(context['tech_stack'])}"
        
        response = await reasoner.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=f"Goal: {goal}{workspace_context}")
        ])
        
        return self._parse_json_response(response.content)

    async def _identify_tasks(
        self,
        reasoner,
        goal: str,
        understanding: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Step 2: Identify all tasks needed to achieve the goal.
        
        Uses reasoning to break down the goal into concrete subtasks.
        """
        system = """You are a task planning expert. Given a goal and its analysis, 
identify all subtasks needed to complete it.

Consider:
- Sequential vs parallel work
- Task granularity (too fine = overhead, too coarse = loses flexibility)
- Agent specialization (backend, frontend, testing, etc.)

Return ONLY valid JSON array of tasks:
[
  {
    "title": "Task title (short, clear)",
    "description": "Detailed description of what this task does",
    "agent_type": "backend|frontend|testing|security|database|docs|devops",
    "estimated_work": "small|medium|large",
    "outputs": ["What files/configs this task produces"]
  }
]
Max 8 tasks. JSON ONLY."""

        complexity_context = ""
        if understanding.get("complexity"):
            complexity_context = f"\nComplexity: {understanding['complexity']}"
        if understanding.get("required_skills"):
            complexity_context += f"\nRequired skills: {', '.join(understanding['required_skills'])}"
        
        response = await reasoner.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=f"""
Goal: {goal}
{complexity_context}

Identify all subtasks. Consider what can be done in parallel.""")
        ])
        
        return self._parse_json_response(response.content, is_list=True)

    async def _build_dependency_graph(
        self,
        reasoner,
        task_specs: List[Dict[str, Any]],
        understanding: Dict[str, Any]
    ) -> TaskGraph:
        """
        Step 3: Build dependency graph and assign subtask IDs.
        
        Analyzes task dependencies to create optimal execution order.
        """
        system = """You are a dependency analyzer. Given a list of tasks, 
determine which tasks depend on others and can run in parallel.

Return ONLY valid JSON:
{
  "dependencies": {
    "task_index_0": ["task_index_1", "task_index_2"],
    "task_index_1": [],
    ...
  },
  "parallel_groups": [[0, 1], [2], [3, 4]],
  "estimated_duration_minutes": number
}
Each task has an index matching its position in the input array.
JSON ONLY."""

        task_list = "\n".join([
            f"{i}. {t['title']}: {t['description']}"
            for i, t in enumerate(task_specs)
        ])
        
        response = await reasoner.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=f"Tasks:\n{task_list}\n\nAnalyze dependencies:")
        ])
        
        deps_analysis = self._parse_json_response(response.content)
        
        # Build TaskGraph
        subtasks = []
        dependencies = deps_analysis.get("dependencies", {})
        
        for i, spec in enumerate(task_specs):
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            
            # Convert dependency indices to task IDs
            task_deps = [
                f"task_{uuid.uuid4().hex[:8]}"  # Placeholder - will be corrected
            ]
            
            subtask = SubTask(
                id=task_id,
                title=spec.get("title", f"Task {i+1}"),
                description=spec.get("description", ""),
                agent_type=spec.get("agent_type", "backend"),
                dependencies=[],  # Will be set below
                status=TaskStatus.PENDING,
                input_data={
                    "outputs": spec.get("outputs", []),
                    "estimated_work": spec.get("estimated_work", "medium")
                }
            )
            subtasks.append(subtask)
        
        # Fix dependencies - need to map indices to actual task IDs
        # For simplicity, we'll assign sequential dependencies
        # A production version would use the actual dependency mapping
        for i, subtask in enumerate(subtasks):
            if str(i) in dependencies:
                dep_indices = dependencies[str(i)]
                subtask.dependencies = [subtasks[j].id for j in dep_indices if j < len(subtasks)]
        
        graph = TaskGraph(
            id=str(uuid.uuid4()),
            goal=understanding.get("domain", "general"),
            subtasks=subtasks,
            status=TaskStatus.PENDING,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )
        
        return graph

    async def decompose_fast(self, goal: str, context: Dict[str, Any]) -> TaskGraph:
        """
        Fast decomposition mode for simple requests.
        
        Uses single LLM call with direct task extraction.
        """
        reasoner = await self._get_reasoner()
        
        system = """You are a Master Orchestrator.
Break down this goal into subtasks efficiently.

Return ONLY valid JSON matching this schema:
{
  "subtasks": [
    {
      "id": "t{n}",
      "title": "Short title",
      "description": "What this task does",
      "agent_type": "backend|frontend|testing|security|database|docs|devops",
      "dependencies": []
    }
  ]
}
Max 6 subtasks. JSON ONLY."""

        response = await reasoner.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=f"Goal: {goal}\n\nContext: {json.dumps(context)}")
        ])
        
        data = self._parse_json_response(response.content)
        subtasks = [
            SubTask(
                id=t["id"] if "id" in t else f"t{i+1}",
                title=t["title"],
                description=t["description"],
                agent_type=t.get("agent_type", "backend"),
                dependencies=t.get("dependencies", []),
                status=TaskStatus.PENDING
            )
            for i, t in enumerate(data.get("subtasks", []))
        ]
        
        return TaskGraph(
            id=str(uuid.uuid4()),
            goal=goal,
            subtasks=subtasks,
            status=TaskStatus.PENDING,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )

    def _parse_json_response(self, content: str, is_list: bool = False) -> Any:
        """Parse JSON from LLM response with robust error handling."""
        # Clean up the response
        content = content.strip()
        
        # Remove markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        # Remove any leading/trailing whitespace
        content = content.strip()
        
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("json_parse_failed", error=str(e), content_preview=content[:200])
            return [] if is_list else {}

    def _count_parallel_groups(self, graph: TaskGraph) -> int:
        """Count the number of parallel execution groups."""
        if not graph.subtasks:
            return 0
        
        # Find tasks with no dependencies (can start immediately)
        completed = set()
        groups = 0
        remaining = list(graph.subtasks)
        
        while remaining:
            # Find tasks that can run now
            ready = [
                t for t in remaining
                if all(dep in completed for dep in t.dependencies)
            ]
            
            if not ready:
                break
            
            groups += 1
            for t in ready:
                completed.add(t.id)
                remaining.remove(t)
        
        return groups

    async def analyze_complexity(self, goal: str) -> Dict[str, Any]:
        """Quick complexity analysis for a goal."""
        reasoner = await self._get_reasoner()
        
        response = await reasoner.ainvoke([
            SystemMessage(content="Analyze this goal and return JSON with complexity_score (1-10), estimated_duration_minutes, and recommended_parallelism (1-4)."),
            HumanMessage(content=f"Goal: {goal}")
        ])
        
        return self._parse_json_response(response.content)