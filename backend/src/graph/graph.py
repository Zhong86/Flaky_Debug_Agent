from langgraph.graph import END, StateGraph

from graph.nodes import (
    check_flaky,
    code_fix,
    debug_agent,
    documents,
    output,
    retest_flaky,
)
from graph.state import GraphState


def _route_flaky(state: GraphState) -> str:
    return "debug_agent" if state["is_flaky"] else END


builder = StateGraph(GraphState)

builder.add_node("check_flaky", check_flaky)
builder.add_node("debug_agent", debug_agent)
builder.add_node("code_fix", code_fix)
builder.add_node("retest_flaky", retest_flaky)
builder.add_node("documents", documents)
builder.add_node("output", output)

builder.set_entry_point("check_flaky")

builder.add_conditional_edges("check_flaky", _route_flaky)

builder.add_edge("debug_agent", "code_fix")
builder.add_edge("code_fix", "retest_flaky")
builder.add_edge("retest_flaky", "documents")
builder.add_edge("documents", "output")
builder.add_edge("output", END)

graph = builder.compile()
