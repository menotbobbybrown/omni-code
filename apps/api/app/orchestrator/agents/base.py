import abc
from typing import Dict, Any, List, Optional
from ..schemas.orchestrator import SubTask, TaskStatus
import asyncio
import structlog

logger = structlog.get_logger()

class BaseAgent(abc.ABC):
    def __init__(self, agent_id: str, name: str, redis_client=None):
        self.agent_id = agent_id
        self.name = name
        self.redis_client = redis_client

    async def run(self, task: SubTask, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main execution loop for the agent.
        """
        logger.info("agent_run_start", agent=self.name, task_id=task.id)
        
        try:
            # 1. Thought phase
            thought = await self.think(task, context)
            await self.publish_log(task.id, f"Thought: {thought}")
            
            # 2. Action phase
            observation = await self.act(task, context, thought)
            await self.publish_log(task.id, f"Observation: {observation}")
            
            # 3. Final Result
            result = await self.conclude(task, context, observation)
            
            logger.info("agent_run_complete", agent=self.name, task_id=task.id)
            return result
        except Exception as e:
            logger.error("agent_run_failed", agent=self.name, task_id=task.id, error=str(e))
            raise e

    @abc.abstractmethod
    async def think(self, task: SubTask, context: Dict[str, Any]) -> str:
        pass

    @abc.abstractmethod
    async def act(self, task: SubTask, context: Dict[str, Any], thought: str) -> str:
        pass

    async def conclude(self, task: SubTask, context: Dict[str, Any], observation: str) -> Dict[str, Any]:
        return {"status": "success", "observation": observation}

    async def publish_log(self, task_id: str, message: str):
        if self.redis_client:
            log_data = {
                "task_id": task_id,
                "agent": self.name,
                "message": message,
                "timestamp": asyncio.get_event_loop().time()
            }
            # Publish to Redis for SSE streaming
            # self.redis_client.publish(f"agent_logs_{task_id}", json.dumps(log_data))
            pass
        print(f"[{self.name}] {message}")

    async def heartbeat(self):
        """
        Updates the agent's last seen timestamp.
        """
        pass
