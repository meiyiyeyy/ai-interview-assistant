from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from app.models.schemas import (
    StartRequest, AnswerRequest, QuestionResponse, ReportResponse,
    ResumeReviewRequest, InterviewQuestionRequest,
)
from app.storage.session_store import session_store
from app.services import llm_service, rag_service
from app.services.file_parser import parse_resume_file
import uuid
import io
from fastapi.responses import StreamingResponse

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _adjust_difficulty(current: str, avg_score: float) -> str:
    if avg_score >= 8 and current != "hard":
        return "hard" if current == "medium" else "medium"
    if avg_score <= 5 and current != "easy":
        return "easy" if current == "medium" else "medium"
    return current


# ============================================================
# 面试流程
# ============================================================
@app.post("/start")
async def start_interview(req: StartRequest):
    session_id = req.session_id or str(uuid.uuid4())
    mode = req.interview_mode or "technical"
    difficulty = req.difficulty or "medium"
    style = req.interviewer_style or "gentle"

    # JD 解析
    jd_info = None
    if req.jd_text and req.jd_text.strip():
        jd_info = llm_service.parse_jd(req.jd_text)

    # 简历解析
    resume_info = None
    if req.resume_text and req.resume_text.strip():
        resume_info = llm_service.parse_resume(req.resume_text)

    # 技能提取
    skills = llm_service.extract_skills(req.position, req.tech_stack)

    # 【新增】RAG 检索
    query = f"{req.position} {' '.join(req.tech_stack)} {' '.join(skills)}"
    rag_context = rag_service.retrieve_context(query, top_k=3)

    # 生成题目（融合 RAG）
    questions = llm_service.generate_questions(
        skills, num=5, mode=mode, difficulty=difficulty,
        jd_info=jd_info, resume_info=resume_info,
        style=style,
        rag_context=rag_context,   # 新增
    )
    for q in questions:
        q["asked"] = False

    state = {
        "position": req.position,
        "tech_stack": req.tech_stack,
        "skills": skills,
        "mode": mode,
        "difficulty": difficulty,
        "style": style,
        "jd_info": jd_info,
        "resume_info": resume_info,
        "questions": questions,
        "current_q_idx": 0,
        "answers": {},
        "follow_up_round": 0,
        "is_finished": False,
        "finished_early": False,
        "evaluations": [],
        "final_report": "",
        "radar_data": {},
        "qa_pairs": [],
    }
    questions[0]["asked"] = True
    session_store.save_state(session_id, state)

    return QuestionResponse(
        session_id=session_id,
        question=questions[0]["question"],
        question_id=0,
        is_follow_up=False,
        is_last=(len(questions) == 1),
        difficulty=difficulty,
        mode=mode,
    )


@app.post("/answer")
async def submit_answer(req: AnswerRequest):
    state = session_store.get_state(req.session_id)
    if not state:
        raise HTTPException(404, "会话不存在或已过期")

    questions = state["questions"]
    current_idx = state["current_q_idx"]
    mode = state.get("mode", "technical")
    style = state.get("style", "gentle")   # 新增

    if current_idx >= len(questions):
        return {"type": "finished", "session_id": req.session_id}

    state["answers"][str(current_idx)] = req.answer
    current_q = questions[current_idx]

    # 评估时传入 style
    eval_result = llm_service.evaluate_answer(
        current_q["question"], req.answer,
        current_q.get("expected_knowledge", []),
        mode=mode,
        style=style   # 新增
    )
    eval_result["question_id"] = current_idx
    state["evaluations"].append(eval_result)

    overall = eval_result.get("overall_score", 6)
    state["difficulty"] = _adjust_difficulty(state["difficulty"], overall)

    # 追问判断时传入 style
    style_cfg = llm_service.get_style_config(style)
    max_follow = style_cfg["max_follow_up"]

    need_follow_up = (
        state["follow_up_round"] < max_follow
        and llm_service.should_follow_up(req.answer, current_q, style=style)
    )

    if need_follow_up:
        state["follow_up_round"] += 1
        follow_up_q = llm_service.generate_follow_up(
            current_q["question"], req.answer,
            current_q.get("expected_knowledge", []),
            style=style   # 新增
        )
        questions[current_idx]["question"] = follow_up_q
        questions[current_idx]["asked"] = True
        state["answers"].pop(str(current_idx), None)
        next_question_text = follow_up_q
        is_follow_up = True
    else:
        try:
            ref_answer = llm_service.generate_reference_answer(
                current_q["question"],
                current_q.get("expected_knowledge", [])
            )
        except Exception as e:
            print(f"⚠️ 参考答案生成失败：{e}")
            ref_answer = "（参考答案生成失败）"

        state["qa_pairs"].append({
            "question_id": current_idx,
            "question": current_q["question"],
            "answer": req.answer,
            "reference_answer": ref_answer,
            "evaluation": eval_result,
        })
        # ========== 实时索引到 RAG 知识库 ==========
        try:
            qa_text = rag_service.format_qa_text(
                position=state["position"],
                tech_stack=state["tech_stack"],
                question=current_q["question"],
                answer=req.answer,
                reference=ref_answer,
            )
            rag_service.add_to_index(
                text=qa_text,
                metadata={
                    "position": state["position"],
                    "question": current_q["question"][:100],
                    "source": "live"
                }
            )
        except Exception as e:
            print(f"⚠️ RAG 实时索引失败（不影响主流程）：{e}")

        state["follow_up_round"] = 0
        questions[current_idx]["asked"] = True
        state["current_q_idx"] = current_idx + 1

        if state["current_q_idx"] >= len(questions):
            state["is_finished"] = True
            session_store.save_state(req.session_id, state)
            return {"type": "finished", "session_id": req.session_id}

        # 动态出题时也传入 style
        if state["difficulty"] != current_q.get("difficulty", "medium"):
            new_qs = llm_service.generate_questions(
                state["skills"], num=1, mode=mode,
                difficulty=state["difficulty"],
                jd_info=state.get("jd_info"),
                resume_info=state.get("resume_info"),
                style=style   # 新增
            )
            if new_qs:
                next_q = new_qs[0]
                next_q["asked"] = True
                questions[state["current_q_idx"]] = next_q

        questions[state["current_q_idx"]]["asked"] = True
        next_question_text = questions[state["current_q_idx"]]["question"]
        is_follow_up = False

    session_store.save_state(req.session_id, state)

    return QuestionResponse(
        session_id=req.session_id,
        question=next_question_text,
        question_id=state["current_q_idx"],
        is_follow_up=is_follow_up,
        is_last=(state["current_q_idx"] == len(questions) - 1),
        difficulty=state["difficulty"],
        mode=mode,
    )

@app.post("/finish_early/{session_id}")
async def finish_early(session_id: str):
    """提前结束面试，用已答的题生成报告"""
    state = session_store.get_state(session_id)
    if not state:
        raise HTTPException(404, "会话不存在或已过期")

    if not state.get("evaluations"):
        raise HTTPException(400, "尚未回答任何问题，无法生成报告")

    if not state.get("final_report"):
        result = llm_service.generate_report(
            state["evaluations"], state["position"], state.get("mode", "technical")
        )
        state["final_report"] = result.get("report_markdown", str(result))
        state["radar_data"] = result.get("radar_data", {})

    state["is_finished"] = True
    state["finished_early"] = True
    session_store.save_state(session_id, state)

    return {
        "status": "ok",
        "session_id": session_id,
        "report": state["final_report"],
        "radar_data": state["radar_data"],
        "answered_count": len(state.get("evaluations", [])),
    }


@app.get("/report/{session_id}")
async def get_report(session_id: str):
    state = session_store.get_state(session_id)
    if not state:
        raise HTTPException(404, "会话不存在或已过期")

    if not state.get("final_report"):
        result = llm_service.generate_report(
            state["evaluations"], state["position"], state.get("mode", "technical")
        )
        state["final_report"] = result.get("report_markdown", str(result))
        state["radar_data"] = result.get("radar_data", {})
        session_store.save_state(session_id, state)

    return ReportResponse(
        session_id=session_id,
        report=state["final_report"],
        evaluations=state.get("evaluations", []),
        radar_data=state.get("radar_data", {}),
        qa_pairs=state.get("qa_pairs", []),
        finished_early=state.get("finished_early", False),
    )


# ============================================================
# 简历上传 / 评估
# ============================================================
@app.post("/upload_resume")
async def upload_resume(file: UploadFile = File(...)):
    try:
        content = await file.read()
        text = parse_resume_file(content, file.filename)
        return {"filename": file.filename, "text": text, "length": len(text)}
    except Exception as e:
        raise HTTPException(400, f"简历解析失败：{e}")


@app.post("/review_resume")
async def review_resume_api(req: ResumeReviewRequest):
    try:
        result = llm_service.review_resume(req.resume_text, req.target_position)
        review_id = session_store.save_resume_review(
            req.target_position, req.resume_text, result
        )
        result["review_id"] = review_id
        return result
    except Exception as e:
        raise HTTPException(500, f"简历评估失败：{e}")


# ============================================================
# 真题解析 / 图片识别
# ============================================================
@app.post("/explain_question")
async def explain_question_api(req: InterviewQuestionRequest):
    try:
        tech = req.tech_stack or []
        result = llm_service.explain_interview_question(
            req.question_text, req.position, tech
        )
        explain_id = session_store.save_question_explain(
            req.question_text, req.position, tech, result
        )
        result["explain_id"] = explain_id
        return result
    except Exception as e:
        raise HTTPException(500, f"真题解析失败：{e}")

@app.post("/explain_questions_batch")
async def explain_questions_batch(req: InterviewQuestionRequest):
    """批量解析多道真题"""
    # 1. 切分题目
    try:
        questions = llm_service.split_questions(req.question_text)
    except Exception as e:
        raise HTTPException(500, f"题目切分失败：{e}")

    if not questions:
        raise HTTPException(400, "未识别到任何题目")

    # 限制单次最多 20 道
    if len(questions) > 20:
        questions = questions[:20]

    print(f"📚 批量解析：共 {len(questions)} 道题")

    # 2. 逐题解析
    results = []
    tech = req.tech_stack or []

    for i, q in enumerate(questions, 1):
        print(f"  [{i}/{len(questions)}] 解析中：{q[:50]}...")
        try:
            res = llm_service.explain_interview_question(
                q, req.position, tech
            )
            # 保存到数据库
            explain_id = session_store.save_question_explain(
                q, req.position, tech, res
            )
            res["explain_id"] = explain_id
            res["question_text"] = q
            results.append(res)
        except Exception as e:
            print(f"    ❌ 第 {i} 题失败：{e}")
            results.append({
                "question_text": q,
                "error": str(e)
            })

    return {
        "total": len(results),
        "success": len([r for r in results if "error" not in r]),
        "results": results
    }

@app.post("/extract_text_from_image")
async def extract_text_from_image_api(file: UploadFile = File(...)):
    try:
        content = await file.read()
        text = llm_service.extract_text_from_image(content)
        return {"text": text, "length": len(text)}
    except Exception as e:
        raise HTTPException(500, f"图片识别失败：{e}")


# ============================================================
# 历史记录
# ============================================================
@app.get("/sessions")
async def list_sessions(limit: int = 50):
    return {"sessions": session_store.list_sessions(limit)}


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    session_store.delete_state(session_id)
    return {"status": "ok"}


@app.get("/resume_reviews")
async def list_resume_reviews(limit: int = 50):
    return {"reviews": session_store.list_resume_reviews(limit)}


@app.get("/resume_reviews/{review_id}")
async def get_resume_review(review_id: int):
    data = session_store.get_resume_review(review_id)
    if not data:
        raise HTTPException(404, "记录不存在")
    return data


@app.delete("/resume_reviews/{review_id}")
async def delete_resume_review(review_id: int):
    session_store.delete_resume_review(review_id)
    return {"status": "ok"}


@app.get("/question_explains")
async def list_question_explains(limit: int = 50):
    return {"explains": session_store.list_question_explains(limit)}


@app.get("/question_explains/{explain_id}")
async def get_question_explain(explain_id: int):
    data = session_store.get_question_explain(explain_id)
    if not data:
        raise HTTPException(404, "记录不存在")
    return data


@app.delete("/question_explains/{explain_id}")
async def delete_question_explain(explain_id: int):
    session_store.delete_question_explain(explain_id)
    return {"status": "ok"}


# ============================================================
# Token 统计
# ============================================================
@app.get("/token_stats")
async def token_stats():
    from app.services.llm_service import TOKEN_STATS
    return TOKEN_STATS

@app.get("/question_explains/{explain_id}/export")
async def export_explain(explain_id: int, format: str = "docx"):
    """导出真题解析（format: md / docx）"""
    data = session_store.get_question_explain(explain_id)
    if not data:
        raise HTTPException(404, "记录不存在")

    from app.services.export_service import export_to_docx, export_to_markdown
    from fastapi.responses import Response
    from urllib.parse import quote

    if format == "docx":
        filename, content = export_to_docx(data)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        filename, content = export_to_markdown(data)
        media_type = "text/markdown; charset=utf-8"

    encoded = quote(filename)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )

