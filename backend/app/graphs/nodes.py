from typing import Literal
from .state import AgentState
from app.intelligence.tools import read_file, write_file, search_codebase, run_terminal
from app.core.model_provider import ModelProvider
from langchain_core.messages import ToolMessage
import logging
import json

logger = logging.getLogger(__name__)

tools = [read_file, write_file, search_codebase, run_terminal]
tools_by_name = {t.name: t for t in tools}

def call_model(state: AgentState):
    messages = state["messages"]
    provider, model_name = ModelProvider.route_model("coding")
    llm = ModelProvider.get_model(provider, model_name)
    llm_with_tools = llm.bind_tools(tools)
    
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

def execute_tools(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    
    tool_messages = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        
        logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
        
        # Inject thread_id/workspace_id if needed
        if tool_name in ["write_file", "run_terminal"]:
            tool_args["thread_id"] = state.get("thread_id")
        if tool_name == "search_codebase":
            tool_args["workspace_id"] = state.get("workspace_id")
            
        tool = tools_by_name[tool_name]
        result = tool.invoke(tool_args)
        
        tool_messages.append(ToolMessage(
            tool_call_id=tool_call["id"],
            content=str(result)
        ))
        
    return {"messages": tool_messages}

def should_continue(state: AgentState) -> Literal["tools", "__end__"]:
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return "__end__"
