"""Assembles the LangGraph. Build fresh per request so config edits apply."""
from langgraph.graph import StateGraph, END
from app.core.state import LessonState
from app.nodes.graph_nodes import (
    planner_node, blueprint_evaluator_node, route_blueprint,
    fabricator_node, matrix_evaluator_node, route_matrix,
    asset_planner_node, eval_node,
)

# Image generation/vision-critique are intentionally NOT wired in for now —
# asset_planner already lists every needed image and registers it as
# `pending` (status=0) in Supabase (see app/core/db.py:upsert_pending), which
# is all we need at this stage. The generation/critic nodes still exist in
# app/nodes/graph_nodes.py (image_factory_node, vision_critic_node) if this
# gets re-enabled later — just re-add them as nodes here.


def build_graph():
    wf = StateGraph(LessonState)

    wf.add_node("planner", planner_node)
    wf.add_node("blueprint_evaluator", blueprint_evaluator_node)
    wf.add_node("fabricator", fabricator_node)
    wf.add_node("matrix_evaluator", matrix_evaluator_node)
    wf.add_node("asset_planner", asset_planner_node)
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

    wf.add_edge("asset_planner", "eval")
    wf.add_edge("eval", END)
    return wf.compile()
