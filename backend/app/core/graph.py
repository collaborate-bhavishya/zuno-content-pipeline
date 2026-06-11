"""Assembles the LangGraph. Build fresh per request so config edits apply."""
from langgraph.graph import StateGraph, END
from app.core.state import LessonState
from app.nodes.graph_nodes import (
    planner_node, blueprint_evaluator_node, route_blueprint,
    fabricator_node, matrix_evaluator_node, route_matrix,
    asset_planner_node, eval_node,
    image_factory_node, vision_critic_node, route_image, route_after_factory,
)


def build_graph():
    wf = StateGraph(LessonState)

    wf.add_node("planner", planner_node)
    wf.add_node("blueprint_evaluator", blueprint_evaluator_node)
    wf.add_node("fabricator", fabricator_node)
    wf.add_node("matrix_evaluator", matrix_evaluator_node)
    wf.add_node("asset_planner", asset_planner_node)
    wf.add_node("eval", eval_node)
    wf.add_node("image_factory", image_factory_node)
    wf.add_node("vision_critic", vision_critic_node)

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
    wf.add_edge("eval", "image_factory")
    # Conditional: if the factory short-circuited (quota/cutoff/empty), exit to
    # END instead of running the critic on a null image (which would loop).
    wf.add_conditional_edges("image_factory", route_after_factory, {
        "critic": "vision_critic",
        "all_done": END,
    })
    wf.add_conditional_edges("vision_critic", route_image, {
        "retry": "image_factory",
        "next": "image_factory",
        "all_done": END,
    })
    return wf.compile()
