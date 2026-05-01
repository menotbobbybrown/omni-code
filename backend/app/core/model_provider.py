from typing import Optional
from langchain_openai import ChatOpenAI
from app.core.config import get_settings

settings = get_settings()

class ModelProvider:
    @staticmethod
    def get_model(provider: str, model_name: str, temperature: float = 0):
        base_urls = {
            "DeepSeek": "https://api.deepseek.com/v1",
            "Moonshot": "https://api.moonshot.cn/v1",
            "MiniMax": "https://api.minimax.chat/v1",
            "Ollama": "http://localhost:11434/v1",
            "OpenAI": None # Default
        }
        
        base_url = base_urls.get(provider)
        
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            openai_api_key=settings.openai_api_key,
            base_url=base_url
        )

    @staticmethod
    def route_model(task_type: str) -> tuple[str, str]:
        """Auto-routing logic based on task type."""
        if task_type == "coding":
            return "DeepSeek", "deepseek-coder"
        elif task_type == "analysis":
            return "OpenAI", "gpt-4-turbo"
        else:
            return "OpenAI", "gpt-3.5-turbo"
