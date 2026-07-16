"""Assembles the LangGraph. Build fresh per request so config edits apply."""
from langgraph.graph import StateGraph, END
from app.core.state import LessonState
from app.nodes.graph_nodes import (
    planner_node, blueprint_evaluator_node, route_blueprint,
    fabricator_node, matrix_evaluator_node, route_matrix,
    asset_planner_node, audio_planner_node, eval_node,
)

# The pipeline plans images but does not render them: asset_planner lists
# every image the matrix needs and registers new ones as pending (status=0)
# in Supabase (see app/core/db.py:upsert_pending) for a separate generation
# process. The old in-graph image factory / vision critic were removed in
# the simplification pass — see git history if they're ever needed again.


def build_graph():
    wf = StateGraph(LessonState)

    wf.add_node("planner", planner_node)
    wf.add_node("blueprint_evaluator", blueprint_evaluator_node)
    wf.add_node("fabricator", fabricator_node)
    wf.add_node("matrix_evaluator", matrix_evaluator_node)
    wf.add_node("asset_planner", asset_planner_node)
    wf.add_node("audio_planner", audio_planner_node)
    wf.add_node("eval", eval_node)

    wf.set_entry_point("planner")
    wf.add_edge("planner", "blueprint_evaluator")
    wf.add_conditional_edges("blueprint_evaluator", route_blueprint, {
        "regenerate": "planner",
        "hard_fail": END,
        "proceed_to_questions": "fabricator",
    })

    wf.add_edge("fabricator", "matrix_evaluator")
    wf.add_conditional_edges("matrix_evaluator", route_matrix, {
        "regenerate": "fabricator",
        "hard_fail": END,
        "trigger_assets": "asset_planner",
    })

    wf.add_edge("asset_planner", "audio_planner")
    wf.add_edge("audio_planner", "eval")
    wf.add_edge("eval", END)
    return wf.compile()
