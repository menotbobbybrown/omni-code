import json
from typing import List, Dict, Any, Optional, Set
from .model_router import ModelRouter, ModelCapability, ModelInfo
from ..schemas.orchestrator import TaskGraph, SubTask, TaskStatus
import uuid
from datetime import datetime
import structlog

logger = structlog.get_logger()


class ComplexityEstimator:
    """Estimates task complexity for model routing."""

    COMPLEXITY_INDICATORS = {
        "high": [
            "implement", "build", "create", "design", "architecture",
            "database", "authentication", "security", "performance",
            "optimization", "refactor", "migration"
        ],
        "medium": [
            "fix", "update", "modify", "add", "enhance", "improve",
            "test", "document", "configure", "setup"
        ],
        "low": [
            "read", "list", "show", "get", "check", "validate"
        ]
    }

    @classmethod
    def estimate(cls, description: str) -> float:
        """
        Estimate complexity of a task based on description.
        
        Returns value between 0.0 and 1.0.
        """
        desc_lower = description.lower()
        
        complexity = 0.3  # Base complexity
        
        # Check for high complexity indicators
        for indicator in cls.COMPLEXITY_INDICATORS["high"]:
            if indicator in desc_lower:
                complexity += 0.2
                
        # Check for medium complexity indicators
        for indicator in cls.COMPLEXITY_INDICATORS["medium"]:
            if indicator in desc_lower:
                complexity += 0.1
                
        # Check for low complexity indicators (reduces complexity)
        for indicator in cls.COMPLEXITY_INDICATORS["low"]:
            if indicator in desc_lower:
                complexity -= 0.05
        
        # Check for specific technologies that add complexity
        complex_tech = [
            "kubernetes", "docker", "microservice", "distributed",
            "machine learning", "ai", "blockchain", "real-time"
        ]
        for tech in complex_tech:
            if tech in desc_lower:
                complexity += 0.1
        
        return max(0.1, min(1.0, complexity))


class TaskDecomposer:
    """
    Decomposes high-level goals into task graphs using LLM planning.
    
    Features:
    - Complexity-based model routing
    - DAG validation
    - Parallel task identification
    - Agent type assignment
    """

    def __init__(self, model_router: ModelRouter):
        self.model_router = model_router

    async def decompose(
        self,
        goal: str,
        context: Dict[str, Any]
    ) -> TaskGraph:
        """
        Decomposes a high-level goal into a graph of subtasks.
        
        Args:
            goal: The user's goal/objective
            context: Additional context (workspace_id, preferences, etc.)
            
        Returns:
            A TaskGraph with decomposed subtasks
        """
        complexity = ComplexityEstimator.estimate(goal)
        
        model = self.model_router.route(
            complexity=complexity,
            context_size=len(str(context)),
            priority=ModelCapability.REASONING
        )
        
        logger.info(
            "decomposition_started",
            goal=goal[:100],
            complexity=complexity,
            model=model.id
        )

        # Generate task decomposition
        # In production, this would call the LLM
        subtasks = await self._generate_tasks(goal, context, complexity)
        
        # Assign models to each task
        for st in subtasks:
            model_info = self._route_task_model(st, context)
            st.model_id = model_info.id
        
        # Validate the resulting graph
        graph = TaskGraph(
            id=str(uuid.uuid4()),
            goal=goal,
            subtasks=subtasks,
            status=TaskStatus.PENDING,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )
        
        self.validate_graph(graph)
        
        logger.info(
            "decomposition_completed",
            graph_id=graph.id,
            subtasks_count=len(subtasks)
        )
        
        return graph

    async def _generate_tasks(
        self,
        goal: str,
        context: Dict[str, Any],
        complexity: float
    ) -> List[SubTask]:
        """
        Generate task list based on goal analysis.
        
        Uses pattern matching and heuristic decomposition.
        """
        subtasks = []
        goal_lower = goal.lower()
        
        # Detect primary domain
        primary_domain = self._detect_domain(goal_lower)
        
        # Phase 1: Analysis/Planning task
        analysis_task = SubTask(
            id=f"task-{uuid.uuid4().hex[:8]}",
            title="Analyze requirements",
            description=f"Review the goal: '{goal}'. Identify key components, dependencies, and technical requirements. Determine the best approach.",
            agent_type="backend",
            dependencies=[],
            status=TaskStatus.PENDING,
            input_data={"goal": goal, "domain": primary_domain}
        )
        subtasks.append(analysis_task)
        
        # Phase 2: Implementation tasks based on domain
        impl_tasks = self._generate_implementation_tasks(goal, primary_domain)
        for task in impl_tasks:
            task.dependencies = [analysis_task.id]
        subtasks.extend(impl_tasks)
        
        # Phase 3: Validation and testing
        test_task = SubTask(
            id=f"task-{uuid.uuid4().hex[:8]}",
            title="Integration testing",
            description="Verify that all components work together correctly. Run the test suite and fix any failures.",
            agent_type="backend",
            dependencies=[t.id for t in impl_tasks if t.agent_type == "backend"],
            status=TaskStatus.PENDING
        )
        subtasks.append(test_task)
        
        # Phase 4: Frontend work if UI is mentioned
        if self._requires_ui(goal_lower):
            ui_task = SubTask(
                id=f"task-{uuid.uuid4().hex[:8]}",
                title="Create UI components",
                description=f"Build user interface components for: '{goal}'",
                agent_type="frontend",
                dependencies=[analysis_task.id],
                status=TaskStatus.PENDING
            )
            subtasks.append(ui_task)
            
            # Update test dependencies
            test_task.dependencies.append(ui_task.id)
        
        # Phase 5: Security review if sensitive
        if self._is_security_sensitive(goal_lower):
            security_task = SubTask(
                id=f"task-{uuid.uuid4().hex[:8]}",
                title="Security audit",
                description="Review implementation for security vulnerabilities. Check for SQL injection, XSS, authentication issues.",
                agent_type="security",
                dependencies=[impl_tasks[0].id] if impl_tasks else [analysis_task.id],
                status=TaskStatus.PENDING
            )
            subtasks.append(security_task)
        
        # Phase 6: DevOps setup if deployment mentioned
        if self._requires_deployment(goal_lower):
            devops_task = SubTask(
                id=f"task-{uuid.uuid4().hex[:8]}",
                title="Setup deployment",
                description="Configure CI/CD, Docker, and deployment scripts.",
                agent_type="devops",
                dependencies=[test_task.id],
                status=TaskStatus.PENDING
            )
            subtasks.append(devops_task)
        
        return subtasks

    def _detect_domain(self, goal: str) -> str:
        """Detect the primary domain of the goal."""
        domains = {
            "backend": ["api", "server", "database", "backend", "service", "logic"],
            "frontend": ["ui", "interface", "component", "frontend", "web", "page"],
            "devops": ["deploy", "docker", "kubernetes", "ci/cd", "pipeline", "infrastructure"],
            "security": ["auth", "security", "encrypt", "protect", "validate"]
        }
        
        detected = []
        for domain, keywords in domains.items():
            if any(kw in goal for kw in keywords):
                detected.append(domain)
        
        return detected[0] if detected else "backend"

    def _generate_implementation_tasks(
        self,
        goal: str,
        primary_domain: str
    ) -> List[SubTask]:
        """Generate implementation subtasks based on goal."""
        tasks = []
        
        if primary_domain in ["backend", "api"]:
            # Backend implementation
            tasks.append(SubTask(
                id=f"task-{uuid.uuid4().hex[:8]}",
                title="Implement core backend logic",
                description=f"Develop the main backend functionality for: {goal}",
                agent_type="backend",
                dependencies=[],
                status=TaskStatus.PENDING
            ))
            
            tasks.append(SubTask(
                id=f"task-{uuid.uuid4().hex[:8]}",
                title="Create API endpoints",
                description="Design and implement REST API endpoints with proper validation.",
                agent_type="backend",
                dependencies=[],
                status=TaskStatus.PENDING
            ))
            
        elif primary_domain == "frontend":
            # Frontend implementation
            tasks.append(SubTask(
                id=f"task-{uuid.uuid4().hex[:8]}",
                title="Build UI components",
                description=f"Create UI components for: {goal}",
                agent_type="frontend",
                dependencies=[],
                status=TaskStatus.PENDING
            ))
            
        elif primary_domain == "devops":
            # DevOps tasks
            tasks.append(SubTask(
                id=f"task-{uuid.uuid4().hex[:8]}",
                title="Configure infrastructure",
                description=f"Setup infrastructure for: {goal}",
                agent_type="devops",
                dependencies=[],
                status=TaskStatus.PENDING
            ))
        
        return tasks

    def _requires_ui(self, goal: str) -> bool:
        """Check if goal requires UI work."""
        ui_keywords = ["ui", "interface", "user", "dashboard", "page", "web", "frontend"]
        return any(kw in goal for kw in ui_keywords)

    def _is_security_sensitive(self, goal: str) -> bool:
        """Check if goal requires security review."""
        security_keywords = [
            "auth", "login", "password", "token", "payment", "sensitive",
            "private", "user data", "credential", "permission"
        ]
        return any(kw in goal for kw in security_keywords)

    def _requires_deployment(self, goal: str) -> bool:
        """Check if goal mentions deployment."""
        deploy_keywords = ["deploy", "docker", "kubernetes", "ci/cd", "production"]
        return any(kw in goal for kw in deploy_keywords)

    def _route_task_model(
        self,
        task: SubTask,
        context: Dict[str, Any]
    ) -> ModelInfo:
        """Route individual task to appropriate model."""
        complexity = ComplexityEstimator.estimate(task.description)
        
        # Determine priority based on task type
        if task.agent_type == "frontend":
            priority = ModelCapability.SPEED
        elif task.agent_type == "security":
            priority = ModelCapability.REASONING
        else:
            priority = ModelCapability.REASONING
        
        prefer_local = context.get("prefer_local", False)
        
        return self.model_router.route(
            complexity=complexity,
            context_size=1000,
            priority=priority,
            prefer_local=prefer_local
        )

    def validate_graph(self, graph: TaskGraph) -> None:
        """
        Ensures the graph is a Directed Acyclic Graph (DAG).
        
        Raises:
            ValueError: If a cycle is detected in the graph
        """
        # Build adjacency map
        adj: Dict[str, List[str]] = {t.id: t.dependencies for t in graph.subtasks}
        
        # Track visited nodes for cycle detection
        visited: Set[str] = set()
        path: Set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in path:
                raise ValueError(f"Cycle detected in task graph at node: {node_id}")
            if node_id in visited:
                return
            
            path.add(node_id)
            
            for dep in adj.get(node_id, []):
                visit(dep)
            
            path.remove(node_id)
            visited.add(node_id)

        # Visit all nodes
        for task in graph.subtasks:
            if task.id not in visited:
                visit(task.id)

    async def replan(
        self,
        original_graph: TaskGraph,
        failure_context: Dict[str, Any]
    ) -> TaskGraph:
        """
        Replan a failed graph with new context.
        
        Args:
            original_graph: The failed graph
            failure_context: Information about why it failed
            
        Returns:
            A new TaskGraph with revised tasks
        """
        failed_task_id = failure_context.get("failed_task")
        
        # Find the failed task
        failed_task = None
        for task in original_graph.subtasks:
            if task.id == failed_task_id:
                failed_task = task
                break
        
        if not failed_task:
            return original_graph
        
        # Create replacement tasks with different approach
        new_subtasks = []
        
        # Analysis task
        analysis = SubTask(
            id=f"task-{uuid.uuid4().hex[:8]}",
            title="Analyze failure and replan",
            description=(
                f"Analyze why the previous attempt at '{failed_task.title}' failed. "
                f"Error: {failure_context.get('error', 'Unknown')}. "
                "Propose an alternative approach."
            ),
            agent_type="backend",
            dependencies=[],
            status=TaskStatus.PENDING
        )
        new_subtasks.append(analysis)
        
        # Retry with simpler approach
        retry = SubTask(
            id=f"task-{uuid.uuid4().hex[:8]}",
            title=f"Retry: {failed_task.title}",
            description=(
                f"Implement {failed_task.title} using a simplified approach. "
                "Break down into smaller, verifiable steps."
            ),
            agent_type=failed_task.agent_type,
            dependencies=[analysis.id],
            status=TaskStatus.PENDING
        )
        new_subtasks.append(retry)
        
        # Add completed tasks from original graph
        for task in original_graph.subtasks:
            if task.status == TaskStatus.COMPLETED:
                new_task = SubTask(
                    id=task.id,
                    title=task.title,
                    description=task.description,
                    agent_type=task.agent_type,
                    dependencies=[retry.id],  # New dependency
                    status=TaskStatus.COMPLETED,
                    output_data=task.output_data
                )
                new_subtasks.append(new_task)
        
        return TaskGraph(
            id=str(uuid.uuid4()),
            goal=original_graph.goal,
            subtasks=new_subtasks,
            status=TaskStatus.PENDING,
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )