# workflow.py
from langgraph.graph import StateGraph, START, END
from app.graph.state import InterviewState
from app.graph.nodes import (
    parse_resume_node,
    generate_questions_node,
    ask_question_node,
    evaluate_node,
    should_continue_node,
    generate_report_node
)


def build_workflow():
    """完整工作流（用于 /start）"""
    workflow = StateGraph(InterviewState)

    # 添加节点
    workflow.add_node("parse_resume", parse_resume_node)
    workflow.add_node("generate_questions", generate_questions_node)
    workflow.add_node("ask_question", ask_question_node)
    workflow.add_node("evaluate", evaluate_node)
    workflow.add_node("generate_report", generate_report_node)

    # 设置入口
    workflow.add_edge(START, "parse_resume")

    # 边
    workflow.add_edge("parse_resume", "generate_questions")
    workflow.add_edge("generate_questions", "ask_question")
    workflow.add_edge("ask_question", "evaluate")

    # 条件分支（加上 "ask" 映射）
    workflow.add_conditional_edges(
        "evaluate",
        should_continue_node,
        {
            "ask": "ask_question",
            "follow_up": "ask_question",
            "next_question": "ask_question",
            "finish": "generate_report"
        }
    )

    workflow.add_edge("generate_report", END)

    return workflow.compile()


def build_answer_workflow():
    """只处理答题的工作流（用于 /answer），从 evaluate 开始"""
    workflow = StateGraph(InterviewState)

    workflow.add_node("ask_question", ask_question_node)
    workflow.add_node("evaluate", evaluate_node)
    workflow.add_node("generate_report", generate_report_node)

    workflow.add_edge(START, "evaluate")

    # 条件分支（必须包含 "ask"）
    workflow.add_conditional_edges(
        "evaluate",
        should_continue_node,
        {
            "ask": "ask_question",
            "follow_up": "ask_question",
            "next_question": "ask_question",
            "finish": "generate_report"
        }
    )

    workflow.add_edge("generate_report", END)

    return workflow.compile()