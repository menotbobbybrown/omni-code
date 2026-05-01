from langgraph.graph import StateGraph, START, END
from .state import AgentState
from .nodes import call_model, execute_tools, should_continue

def create_workflow():
    """Create and compile the LangGraph workflow."""
    graph = StateGraph(AgentState)
    
    graph.add_node("agent", call_model)
    graph.add_node("tools", execute_tools)
    
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
    )
    graph.add_edge("tools", "agent")
    
    return graph.compile()

workflow = create_workflow()
