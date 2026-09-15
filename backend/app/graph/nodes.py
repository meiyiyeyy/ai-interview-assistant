from app.graph.state import InterviewState
from app.services import llm_service


def parse_resume_node(state: InterviewState) -> dict:
    """解析简历提取技能"""
    skills = llm_service.extract_skills(state["position"], state["tech_stack"])
    return {"skills": skills}


def generate_questions_node(state: InterviewState) -> dict:
    """生成题目"""
    questions = llm_service.generate_questions(state["skills"], num=5)
    for q in questions:
        q["asked"] = False
        q["follow_up_count"] = 0
    return {
        "questions": questions,
        "current_q_idx": 0,
        "follow_up_round": 0,
        "is_finished": False
    }


def ask_question_node(state: InterviewState) -> dict:
    """出题节点（标记当前题目为已问，追问时生成新问题）"""
    idx = state["current_q_idx"]
    questions = [dict(q) for q in state["questions"]]

    if idx >= len(questions):
        return {}

    current_q = questions[idx]

    # 如果是追问（follow_up_round > 0），生成针对性的追问题目
    if state["follow_up_round"] > 0 and state["answers"]:
        last_answer = state["answers"].get(idx, "")
        follow_up_question = llm_service.generate_follow_up(
            current_q["question"],
            last_answer,
            current_q.get("expected_knowledge", [])
        )
        current_q["question"] = follow_up_question
        current_q["asked"] = True
        questions[idx] = current_q
        return {"questions": questions}

    # 普通出新题
    current_q["asked"] = True
    questions[idx] = current_q
    return {"questions": questions}


def evaluate_node(state: InterviewState) -> dict:
    """评估当前回答 + 推进流程"""
    updates = {}
    current_idx = state["current_q_idx"]
    questions = state["questions"]

    if current_idx >= len(questions):
        return updates

    current_q = questions[current_idx]

    # 当前题是否已有回答
    if current_idx in state["answers"]:
        answer = state["answers"][current_idx]

        # 只评估一次（避免重复评估）
        already_evaluated = any(
            ev.get("question_id") == current_idx
            for ev in state["evaluations"]
        )
        if not already_evaluated:
            eval_result = llm_service.evaluate_answer(
                current_q["question"],
                answer,
                current_q.get("expected_knowledge", [])
            )
            eval_result["question_id"] = current_idx
            updates["evaluations"] = [eval_result]

            # 判断是否追问
            if state["follow_up_round"] < 2:
                if llm_service.should_follow_up(answer, current_q):
                    updates["follow_up_round"] = state["follow_up_round"] + 1
                    # 追问：重置当前题的 asked，让 ask_question 重新出题
                    new_questions = [dict(q) for q in questions]
                    new_questions[current_idx]["asked"] = False
                    updates["questions"] = new_questions
                    # 删除本题的旧回答，等待新回答
                    new_answers = dict(state["answers"])
                    new_answers.pop(current_idx, None)
                    updates["answers"] = new_answers
                    return updates

            # 不追问，进入下一题
            updates["current_q_idx"] = current_idx + 1
            updates["follow_up_round"] = 0

    return updates


def should_continue_node(state: InterviewState) -> str:
    """决定下一步：追问、下一题、还是结束"""
    idx = state["current_q_idx"]
    questions = state["questions"]

    if idx >= len(questions):
        return "finish"

    current_q = questions[idx]

    # 当前题还没问过 → 出题
    if not current_q["asked"]:
        return "ask"

    # 已问过 → 判断是否追问
    if state["follow_up_round"] < 2:
        answer = state["answers"].get(idx, "")
        if answer and llm_service.should_follow_up(answer, current_q):
            return "follow_up"

    # 进入下一题
    if idx + 1 >= len(questions):
        return "finish"
    return "next_question"


def generate_report_node(state: InterviewState) -> dict:
    """生成最终报告"""
    report = llm_service.generate_report(state["evaluations"], state["position"])
    return {"final_report": report, "is_finished": True}