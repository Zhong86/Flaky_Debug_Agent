from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph.nodes import check_flaky, clone_repo, debug_agent, documents, output
from graph.state import GraphState


def _route_flaky(state: GraphState) -> str:
    return "clone_repo" if state["is_flaky"] else END


def _route_cloned(state: GraphState) -> str:
    # Without a checkout there's nothing for Bob to investigate or report on.
    return "debug_agent" if state["repo_path"] else "output"


builder = StateGraph(GraphState)

builder.add_node("check_flaky", check_flaky)
builder.add_node("clone_repo", clone_repo)
builder.add_node("debug_agent", debug_agent)
builder.add_node("documents", documents)
builder.add_node("output", output)

builder.set_entry_point("check_flaky")

builder.add_conditional_edges("check_flaky", _route_flaky)

builder.add_conditional_edges("clone_repo", _route_cloned)
builder.add_edge("debug_agent", "documents")
builder.add_edge("documents", "output")
builder.add_edge("output", END)


def compile_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Compile the graph, optionally wired to a checkpointer for persisted run history."""
    return builder.compile(checkpointer=checkpointer)


# Uncompiled default (no persistence) — kept for `python -m graph` and tests.
graph = compile_graph()
