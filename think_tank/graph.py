"""think_tank/graph.py — LangGraph construction with four specialised agent nodes."""

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from think_tank.agents import researcher_node, skeptic_node, synthesizer_node, visionary_node
from think_tank.arbiter import arbiter_node, route_after_arbiter
from think_tank.state import ThinkTankState


def build_think_tank_graph() -> CompiledStateGraph:
    """
    Build the Think Tank graph.

    Topology (sequential within each round):
        START → researcher → skeptic → visionary → synthesizer → arbiter
                  ↑                                              ↓
                  └──────────── (loop while diverged) ───────────┘
                                                               → END (converged)

    Each agent node receives the full ThinkTankState and returns a partial
    update dict that appends its artefact to the appropriate list.
    """
    graph = StateGraph(ThinkTankState)  # ty:ignore[invalid-argument-type]

    # --- Agent nodes (sequential within a round) ---
    graph.add_node("researcher", researcher_node)
    graph.add_node("skeptic", skeptic_node)
    graph.add_node("visionary", visionary_node)
    graph.add_node("synthesizer", synthesizer_node)

    # --- Arbiter node ---
    graph.add_node("arbiter", arbiter_node)

    # --- Edges ---
    graph.add_edge(START, "researcher")
    graph.add_edge("researcher", "skeptic")
    graph.add_edge("skeptic", "visionary")
    graph.add_edge("visionary", "synthesizer")
    graph.add_edge("synthesizer", "arbiter")

    graph.add_conditional_edges(
        "arbiter",
        route_after_arbiter,
        {
            "researcher": "researcher",  # loop back to start of agent chain
            "__end__": END,
        },
    )

    return graph.compile()  # ty:ignore[invalid-return-type]
