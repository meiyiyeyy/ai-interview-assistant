import streamlit as st
import requests
import pandas as pd

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="AI面试助手", page_icon="🎯", layout="wide")
st.title("🎯 AI 面试助手")
st.caption("模拟面试 · 简历评估 · 真题解析")

# ========== 全局状态 ==========
for key, default in [
    ("session_id", None), ("messages", []),
    ("is_finished", False), ("report", None),
    ("radar_data", {}), ("qa_pairs", []),
    ("resume_text", ""),
    ("review_result", None), ("explain_result", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ========== 三个 Tab ==========
tab_interview, tab_resume, tab_question, tab_history = st.tabs(
    ["🎤 模拟面试", "📄 简历评估", "📚 真题解析", "📜 历史记录"]
)

# ============================================================
# Tab 1：模拟面试（设置 + 对话左右分栏）
# ============================================================
with tab_interview:
    col_setting, col_chat = st.columns([1, 2])

    # ---------- 左侧：面试设置 ----------
    with col_setting:
        st.subheader("⚙️ 面试设置")
        position = st.text_input("应聘职位", placeholder="例：后端开发工程师")
        tech_stack = st.text_input("技术栈（逗号分隔）", placeholder="例：Python, FastAPI")

        mode_label = st.selectbox("面试模式", ["技术面", "行为面", "系统设计面", "HR面"], index=0)
        mode_map = {"技术面": "technical", "行为面": "behavioral",
                    "系统设计面": "system_design", "HR面": "hr"}
        interview_mode = mode_map[mode_label]

        difficulty_label = st.selectbox("初始难度", ["简单", "中等", "困难"], index=1)
        difficulty_map = {"简单": "easy", "中等": "medium", "困难": "hard"}
        difficulty = difficulty_map[difficulty_label]

        st.markdown("**📋 岗位 JD（可选）**")
        jd_text = st.text_area("粘贴完整 JD", height=100, label_visibility="collapsed")

        st.markdown("**📄 简历上传（可选）**")
        resume_file = st.file_uploader("上传 PDF / Word / TXT",
                                       type=["pdf", "docx", "txt", "md"],
                                       label_visibility="collapsed")
        style_label = st.selectbox(
            "面试官风格",
            ["温和型", "严厉型", "追问型", "沉默型"],
            index=0
        )
        style_map = {
            "温和型": "gentle",
            "严厉型": "strict",
            "追问型": "probing",
            "沉默型": "silent",
        }
        interviewer_style = style_map[style_label]
        if resume_file is not None:
            if st.button("解析简历", key="parse_resume_btn"):
                with st.spinner("解析中..."):
                    try:
                        files = {"file": (resume_file.name, resume_file.getvalue())}
                        r = requests.post(f"{API_BASE}/upload_resume", files=files)
                        if r.status_code == 200:
                            st.session_state.resume_text = r.json()["text"]
                            st.success(f"✅ 解析成功，共 {r.json()['length']} 字")
                        else:
                            st.error(f"解析失败：{r.text}")
                    except Exception as e:
                        st.error(f"上传失败：{e}")

        if st.session_state.resume_text:
            st.caption(f"已解析简历 {len(st.session_state.resume_text)} 字")

        tech_list = [t.strip() for t in tech_stack.split(",")] if tech_stack else []

        if st.button("🚀 开始面试", type="primary", use_container_width=True):
            if not position or not tech_list:
                st.error("请完整填写职位和技术栈")
            else:
                with st.spinner("生成面试题中..."):
                    try:
                        payload = {
                            "position": position,
                            "tech_stack": tech_list,
                            "interview_mode": interview_mode,
                            "difficulty": difficulty,
                            "interviewer_style": interviewer_style,
                        }
                        if jd_text.strip():
                            payload["jd_text"] = jd_text
                        if st.session_state.resume_text:
                            payload["resume_text"] = st.session_state.resume_text

                        response = requests.post(f"{API_BASE}/start", json=payload)
                        if response.status_code == 200:
                            data = response.json()
                            st.session_state.session_id = data["session_id"]
                            st.session_state.messages = [{
                                "role": "assistant",
                                "content": f"💡 面试开始（{mode_label}｜难度：{difficulty_label}）\n\n**第 1 题：**\n\n{data['question']}"
                            }]
                            st.session_state.is_finished = False
                            st.session_state.report = None
                            st.session_state.radar_data = {}
                            st.session_state.qa_pairs = []
                            st.rerun()
                        else:
                            st.error(f"启动失败：{response.text}")
                    except Exception as e:
                        st.error(f"连接后端失败：{e}")

    # ---------- 右侧：对话区 ----------
    with col_chat:
        st.subheader("💬 面试对话")

        # 消息区
        msg_box = st.container(height=450, autoscroll=False)
        with msg_box:
            if not st.session_state.messages:
                st.info("👈 在左侧填写信息，点击「开始面试」")
            for msg in st.session_state.messages:
                st.chat_message(msg["role"]).write(msg["content"])

        # 输入框
        if not st.session_state.is_finished and st.session_state.session_id:
            if prompt := st.chat_input("请输入你的回答..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.spinner("评估中..."):
                    try:
                        response = requests.post(
                            f"{API_BASE}/answer",
                            json={"session_id": st.session_state.session_id, "answer": prompt},
                        )
                        if response.status_code == 200:
                            data = response.json()
                            if data.get("type") == "finished":
                                st.session_state.is_finished = True
                                rr = requests.get(f"{API_BASE}/report/{st.session_state.session_id}")
                                if rr.status_code == 200:
                                    rd = rr.json()
                                    st.session_state.report = rd["report"]
                                    st.session_state.radar_data = rd.get("radar_data", {})
                                    st.session_state.qa_pairs = rd.get("qa_pairs", [])
                                    st.session_state.messages.append({
                                        "role": "assistant",
                                        "content": "✅ 面试结束！下方查看报告。"
                                    })
                                st.rerun()
                            else:
                                prefix = "🔄 追问：" if data["is_follow_up"] else f"📝 下一题（难度：{data.get('difficulty', 'medium')}）："
                                st.session_state.messages.append({
                                    "role": "assistant",
                                    "content": f"{prefix}\n\n{data['question']}"
                                })
                                st.rerun()
                        else:
                            st.error(f"提交失败：{response.text}")
                    except Exception as e:
                        st.error(f"连接后端失败：{e}")

    # ---------- 提前结束按钮 ----------
    if (not st.session_state.is_finished
            and st.session_state.session_id
            and st.session_state.messages):
        answered = len([m for m in st.session_state.messages if m["role"] == "user"])
        if answered > 0:
            if st.button("🛑 提前结束并生成报告", use_container_width=True):
                with st.spinner("生成报告中..."):
                    try:
                        r = requests.post(
                            f"{API_BASE}/finish_early/{st.session_state.session_id}"
                        )
                        if r.status_code == 200:
                            data = r.json()
                            st.session_state.is_finished = True
                            st.session_state.report = data["report"]
                            st.session_state.radar_data = data.get("radar_data", {})
                            rr = requests.get(f"{API_BASE}/report/{st.session_state.session_id}")
                            if rr.status_code == 200:
                                st.session_state.qa_pairs = rr.json().get("qa_pairs", [])
                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": f"⏹ 已提前结束面试，基于已答的 {data['answered_count']} 题生成报告。"
                            })
                            st.rerun()
                        else:
                            st.error(f"生成失败：{r.text}")
                    except Exception as e:
                        st.error(f"连接后端失败：{e}")

    # ---------- 报告区（占满整行） ----------
    if st.session_state.is_finished and st.session_state.report:
        st.divider()
        # 判断是否提前结束
        try:
            rr = requests.get(f"{API_BASE}/report/{st.session_state.session_id}")
            if rr.status_code == 200 and rr.json().get("finished_early"):
                st.warning("⏹ 本报告基于提前结束的面试生成，仅供参考")
        except Exception:
            pass
        with st.expander("📊 查看完整面试报告", expanded=True):
            st.markdown(st.session_state.report)

            radar = st.session_state.radar_data
            if radar:
                import plotly.graph_objects as go
                categories = list(radar.keys())
                values = list(radar.values())
                fig = go.Figure(data=go.Scatterpolar(
                    r=values + [values[0]],
                    theta=categories + [categories[0]],
                    fill='toself',
                    name='能力评分'
                ))
                fig.update_layout(
                    polar=dict(radialaxis=dict(visible=True, range=[0, 10])),
                    showlegend=False, height=400
                )
                st.plotly_chart(fig, use_container_width=True)

    if st.session_state.qa_pairs:
        st.subheader("📝 逐题参考答案对比")
        for i, qa in enumerate(st.session_state.qa_pairs):
            with st.expander(f"第 {i+1} 题：{qa['question'][:40]}..."):
                st.markdown(f"**题目：** {qa['question']}")
                st.markdown(f"**你的回答：**\n\n{qa['answer']}")
                st.markdown(f"**参考答案：**\n\n{qa['reference_answer']}")
                ev = qa.get("evaluation", {})
                if ev:
                    st.markdown(f"**综合得分：** {ev.get('overall_score', '-')}")
                    st.markdown(f"**评价：** {ev.get('summary', '-')}")

    if st.session_state.session_id:
        if st.button("🔄 重新开始", use_container_width=True):
            for k in ["session_id", "messages", "is_finished", "report", "radar_data", "qa_pairs"]:
                if k == "session_id":
                    st.session_state[k] = None
                elif k in ("messages", "qa_pairs"):
                    st.session_state[k] = []
                elif k == "is_finished":
                    st.session_state[k] = False
                elif k == "report":
                    st.session_state[k] = None
                elif k == "radar_data":
                    st.session_state[k] = {}
            st.rerun()

# ============================================================
# Tab 2：简历评估
# ============================================================
with tab_resume:
    st.subheader("📄 简历智能评估")
    st.caption("上传或粘贴简历，AI 从多个维度给出评分和修改建议")

    col1, col2 = st.columns([1, 2])

    with col1:
        target_position = st.text_input("目标岗位（可选）", key="review_pos")
        upload = st.file_uploader("上传简历", type=["pdf", "docx", "txt", "md"],
                                  key="review_upload")

        # 上传后自动解析（不用再点按钮）
        if upload is not None:
            # 用文件名 + 文件大小做唯一 key，避免重复解析
            file_key = f"{upload.name}_{upload.size}"
            if st.session_state.get("last_parsed_file") != file_key:
                with st.spinner("解析中..."):
                    try:
                        files = {"file": (upload.name, upload.getvalue())}
                        r = requests.post(f"{API_BASE}/upload_resume", files=files)
                        if r.status_code == 200:
                            st.session_state["review_text"] = r.json()["text"]
                            st.session_state["last_parsed_file"] = file_key
                            st.success(f"✅ 解析成功，共 {r.json()['length']} 字")
                        else:
                            st.error(f"解析失败：{r.text}")
                    except Exception as e:
                        st.error(f"上传失败：{e}")

        if st.button("🔍 开始评估", type="primary", use_container_width=True):
            # 优先用文本框里的内容
            text = st.session_state.get("review_text", "")
            if not text.strip():
                st.warning("请先上传简历或粘贴内容")
            else:
                with st.spinner("评估中..."):
                    try:
                        r = requests.post(
                            f"{API_BASE}/review_resume",
                            json={"resume_text": text, "target_position": target_position}
                        )
                        if r.status_code == 200:
                            st.session_state.review_result = r.json()
                        else:
                            st.error(f"评估失败：{r.text}")
                    except Exception as e:
                        st.error(f"错误：{e}")

    with col2:
        # 直接用 key 绑定，让上传解析后自动填入
        st.text_area(
            "简历原文（可直接粘贴）",
            height=400,
            key="review_text",       # 关键：直接绑定到 session_state
            placeholder="上传文件后自动填入，或直接粘贴简历内容"
        )
    if st.session_state.review_result:
        res = st.session_state.review_result
        st.divider()
        st.subheader(f"📊 综合评分：{res.get('overall_score', '-')}/10")

        dims = res.get("dimension_scores", {})
        if dims:
            df = pd.DataFrame([
                {"维度": k, "得分": v.get("score", 0), "点评": v.get("comment", "")}
                for k, v in dims.items()
            ])
            st.dataframe(df, use_container_width=True, hide_index=True)

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("### ✅ 优点")
            for s in res.get("strengths", []):
                st.markdown(f"- {s}")
        with col_b:
            st.markdown("### ⚠️ 不足")
            for w in res.get("weaknesses", []):
                st.markdown(f"- {w}")

        st.markdown("### 💡 修改建议")
        for i, sug in enumerate(res.get("suggestions", []), 1):
            with st.expander(f"建议 {i}：{sug.get('section', '')} - {sug.get('issue', '')}"):
                st.markdown(f"**问题：** {sug.get('issue', '')}")
                st.markdown(f"**修改方向：** {sug.get('fix', '')}")
                if sug.get("example"):
                    st.markdown(f"**示例改写：**")
                    st.code(sug["example"], language="markdown")

        st.info(f"**总体评价：** {res.get('summary', '')}")

# ============================================================
# Tab 3：真题解析
# ============================================================
# ============================================================
# Tab 3：真题解析
# ============================================================
with tab_question:
    st.subheader("📚 面试真题解析")
    st.caption("粘贴单道或多道真题，AI 给出考察点、参考答案和延伸问题")

    col1, col2 = st.columns([1, 2])

    with col1:
        q_position = st.text_input("岗位（可选）", key="q_pos")
        q_tech = st.text_input("技术栈（逗号分隔，可选）", key="q_tech")

        # 图片上传
        st.markdown("**📷 上传题目截图（可选）**")
        img_file = st.file_uploader(
            "上传图片",
            type=["png", "jpg", "jpeg"],
            key="question_image",
            label_visibility="collapsed"
        )

        if img_file is not None:
            st.image(img_file, caption="已上传", use_container_width=True)
            if st.button("识别图片文字", key="extract_img_btn"):
                with st.spinner("识别中..."):
                    try:
                        files = {"file": (img_file.name, img_file.getvalue())}
                        r = requests.post(f"{API_BASE}/extract_text_from_image", files=files)
                        if r.status_code == 200:
                            extracted = r.json()["text"]
                            if extracted:
                                st.session_state["question_text_area"] = extracted
                                st.success("✅ 识别成功，已填入文本框")
                                st.rerun()
                            else:
                                st.warning("图片中未识别到文字")
                        else:
                            st.error(f"识别失败：{r.text}")
                    except Exception as e:
                        st.error(f"识别失败：{e}")

        st.divider()

        # 两个解析按钮
        col_single, col_batch = st.columns(2)
        with col_single:
            single_clicked = st.button("🔍 单题解析", type="primary", use_container_width=True)
        with col_batch:
            batch_clicked = st.button("📚 批量解析", use_container_width=True)

        # 单题解析
        if single_clicked:
            text = st.session_state.get("question_text_area", "")
            if not text.strip():
                st.warning("请先粘贴题目")
            else:
                with st.spinner("解析中..."):
                    try:
                        r = requests.post(
                            f"{API_BASE}/explain_question",
                            json={
                                "question_text": text,
                                "position": q_position,
                                "tech_stack": [t.strip() for t in q_tech.split(",") if t.strip()]
                            },
                            timeout=180
                        )
                        if r.status_code == 200:
                            st.session_state.explain_result = r.json()
                            st.session_state["batch_results"] = None   # 清空批量结果
                        else:
                            st.error(f"解析失败：{r.text}")
                    except Exception as e:
                        st.error(f"错误：{e}")

        # 批量解析
        if batch_clicked:
            text = st.session_state.get("question_text_area", "")
            if not text.strip():
                st.warning("请先粘贴题目")
            else:
                with st.spinner("批量解析中，每道题约 5 秒，请耐心等待..."):
                    try:
                        r = requests.post(
                            f"{API_BASE}/explain_questions_batch",
                            json={
                                "question_text": text,
                                "position": q_position,
                                "tech_stack": [t.strip() for t in q_tech.split(",") if t.strip()]
                            },
                            timeout=900   # 15 分钟
                        )
                        if r.status_code == 200:
                            data = r.json()
                            st.session_state["batch_results"] = data["results"]
                            st.session_state.explain_result = None   # 清空单题结果
                            st.success(f"✅ 批量解析完成：成功 {data['success']}/{data['total']} 道")
                        else:
                            st.error(f"批量解析失败：{r.text}")
                    except Exception as e:
                        st.error(f"错误：{e}")

    with col2:
        st.text_area(
            "粘贴题目（可多道，一行一题或用序号区分）",
            height=300,
            key="question_text_area",
            placeholder="例：\n1. Spring Boot 自动装配原理\n2. Redis 缓存一致性\n3. MySQL 索引优化"
        )

    # ========== 单题结果展示 ==========
    if st.session_state.get("explain_result"):
        res = st.session_state.explain_result
        st.divider()
        st.markdown(f"**题目类型：** `{res.get('question_type', '-')}`")

        st.markdown("### 🎯 核心考察点")
        for p in res.get("core_points", []):
            st.markdown(f"- {p}")

        st.markdown("### ✅ 参考答案")
        st.markdown(res.get("reference_answer", ""))

        st.markdown("### 📝 答题框架")
        for step in res.get("answer_framework", []):
            st.markdown(f"- {step}")

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("### 🔄 可能的追问")
            for f in res.get("follow_up_questions", []):
                st.markdown(f"- {f}")
        with col_b:
            st.markdown("### ⚠️ 常见误区")
            for m in res.get("common_mistakes", []):
                st.markdown(f"- {m}")

        # 导出
        explain_id = res.get("explain_id")
        if explain_id:
            st.divider()
            st.subheader("📥 导出")
            col_md, col_docx = st.columns(2)
            with col_md:
                md_url = f"{API_BASE}/question_explains/{explain_id}/export?format=md"
                st.markdown(
                    f'<a href="{md_url}" target="_blank">'
                    f'<button style="width:100%;padding:8px;background:#f0f2f6;border:1px solid #ccc;border-radius:6px;cursor:pointer;">'
                    f'📄 下载 Markdown</button></a>',
                    unsafe_allow_html=True
                )
            with col_docx:
                docx_url = f"{API_BASE}/question_explains/{explain_id}/export?format=docx"
                st.markdown(
                    f'<a href="{docx_url}" target="_blank">'
                    f'<button style="width:100%;padding:8px;background:#4CAF50;color:white;border:none;border-radius:6px;cursor:pointer;">'
                    f'📝 下载 Word</button></a>',
                    unsafe_allow_html=True
                )

    # ========== 批量结果展示 ==========
    if st.session_state.get("batch_results"):
        results = st.session_state.batch_results
        st.divider()
        st.subheader(f"📚 批量解析结果（共 {len(results)} 道题）")

        # 顶部批量导出
        st.caption("💡 每题可单独导出，也可下滑查看全部")

        for i, res in enumerate(results, 1):
            if "error" in res:
                st.error(f"第 {i} 题解析失败：{res['error']}")
                continue

            q_text = res.get("question_text", f"第 {i} 题")
            with st.expander(f"第 {i} 题：{q_text[:60]}..."):
                st.markdown(f"**题目：** {q_text}")
                st.markdown(f"**题目类型：** `{res.get('question_type', '-')}`")

                st.markdown("### 🎯 核心考察点")
                for p in res.get("core_points", []):
                    st.markdown(f"- {p}")

                st.markdown("### ✅ 参考答案")
                st.markdown(res.get("reference_answer", ""))

                st.markdown("### 📝 答题框架")
                for step in res.get("answer_framework", []):
                    st.markdown(f"- {step}")

                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown("### 🔄 可能的追问")
                    for f in res.get("follow_up_questions", []):
                        st.markdown(f"- {f}")
                with col_b:
                    st.markdown("### ⚠️ 常见误区")
                    for m in res.get("common_mistakes", []):
                        st.markdown(f"- {m}")

                # 单题导出
                if res.get("explain_id"):
                    eid = res["explain_id"]
                    col_md, col_docx = st.columns(2)
                    with col_md:
                        st.markdown(
                            f'<a href="{API_BASE}/question_explains/{eid}/export?format=md" '
                            f'target="_blank">📄 下载 Markdown</a>',
                            unsafe_allow_html=True
                        )
                    with col_docx:
                        st.markdown(
                            f'<a href="{API_BASE}/question_explains/{eid}/export?format=docx" '
                            f'target="_blank">📝 下载 Word</a>',
                            unsafe_allow_html=True
                        )

# ============================================================
# Tab 4：历史记录
# ============================================================
with tab_history:
    st.subheader("📜 历史记录")

    # 顶部 token 统计
    try:
        ts = requests.get(f"{API_BASE}/token_stats").json()
        col1, col2, col3 = st.columns(3)
        col1.metric("累计 LLM 调用", ts.get("calls", 0))
        col2.metric("Prompt Tokens", ts.get("prompt", 0))
        col3.metric("Completion Tokens", ts.get("completion", 0))
    except Exception:
        pass

    st.divider()

    # 三个子 Tab
    hist_tab1, hist_tab2, hist_tab3 = st.tabs(
        ["🎤 模拟面试", "📄 简历评估", "📚 真题解析"]
    )

    # ========== 子 Tab 1：模拟面试记录 ==========
    with hist_tab1:
        if st.button("🔄 刷新", key="refresh_sessions"):
            st.rerun()
        try:
            r = requests.get(f"{API_BASE}/sessions?limit=50")
            if r.status_code == 200:
                sessions = r.json().get("sessions", [])
                if not sessions:
                    st.info("暂无面试记录")
                for s in sessions:
                    if s["is_finished"]:
                        if s.get("finished_early"):
                            status = "⏹ 提前结束"
                        else:
                            status = "✅ 已完成"
                    else:
                        status = "⏸ 进行中"
                    label = f"{status} | {s['position']} | {s['mode']} | {s['updated_at']}"
                    with st.expander(label):
                        col_a, col_b = st.columns([1, 2])
                        with col_a:
                            st.caption(f"Session ID: `{s['session_id']}`")
                        with col_b:
                            if s["is_finished"]:
                                if st.button("查看详情", key=f"view_{s['session_id']}"):
                                    detail = requests.get(f"{API_BASE}/report/{s['session_id']}")
                                    if detail.status_code == 200:
                                        rd = detail.json()
                                        st.markdown(rd.get("report", "无报告"))
                                        qa = rd.get("qa_pairs", [])
                                        if qa:
                                            st.markdown("### 📝 逐题详情")
                                            for i, item in enumerate(qa, 1):
                                                with st.expander(f"第 {i} 题：{item['question'][:40]}..."):
                                                    st.markdown(f"**题目：** {item['question']}")
                                                    st.markdown(f"**你的回答：**\n\n{item['answer']}")
                                                    st.markdown(f"**参考答案：**\n\n{item['reference_answer']}")
                            else:
                                st.caption("未完成，无报告")
                            if st.button("删除", key=f"del_{s['session_id']}"):
                                requests.delete(f"{API_BASE}/sessions/{s['session_id']}")
                                st.rerun()
        except Exception as e:
            st.error(f"连接后端失败：{e}")

    # ========== 子 Tab 2：简历评估记录 ==========
    with hist_tab2:
        if st.button("🔄 刷新", key="refresh_reviews"):
            st.rerun()
        try:
            r = requests.get(f"{API_BASE}/resume_reviews?limit=50")
            if r.status_code == 200:
                reviews = r.json().get("reviews", [])
                if not reviews:
                    st.info("暂无简历评估记录")
                for rev in reviews:
                    label = f"📄 {rev['target_position'] or '未指定岗位'} | 评分 {rev['overall_score']} | {rev['created_at']}"
                    with st.expander(label):
                        st.caption(f"记录 ID: `{rev['id']}`")
                        if st.button("查看详情", key=f"view_rev_{rev['id']}"):
                            detail = requests.get(f"{API_BASE}/resume_reviews/{rev['id']}")
                            if detail.status_code == 200:
                                data = detail.json()
                                res = data["result"]
                                st.markdown(f"### 综合评分：{res.get('overall_score', '-')}/10")
                                st.markdown(f"**总体评价：** {res.get('summary', '')}")
                                dims = res.get("dimension_scores", {})
                                if dims:
                                    import pandas as pd
                                    df = pd.DataFrame([
                                        {"维度": k, "得分": v.get("score", 0), "点评": v.get("comment", "")}
                                        for k, v in dims.items()
                                    ])
                                    st.dataframe(df, use_container_width=True, hide_index=True)
                                st.markdown("### ✅ 优点")
                                for s in res.get("strengths", []):
                                    st.markdown(f"- {s}")
                                st.markdown("### ⚠️ 不足")
                                for w in res.get("weaknesses", []):
                                    st.markdown(f"- {w}")
                                st.markdown("### 💡 修改建议")
                                for sug in res.get("suggestions", []):
                                    with st.expander(f"{sug.get('section', '')} - {sug.get('issue', '')}"):
                                        st.markdown(f"**问题：** {sug.get('issue', '')}")
                                        st.markdown(f"**修改方向：** {sug.get('fix', '')}")
                                        if sug.get("example"):
                                            st.code(sug["example"], language="markdown")
                        if st.button("删除", key=f"del_rev_{rev['id']}"):
                            requests.delete(f"{API_BASE}/resume_reviews/{rev['id']}")
                            st.rerun()
        except Exception as e:
            st.error(f"连接后端失败：{e}")

    # ========== 子 Tab 3：真题解析记录 ==========
    with hist_tab3:
        if st.button("🔄 刷新", key="refresh_explains"):
            st.rerun()
        try:
            r = requests.get(f"{API_BASE}/question_explains?limit=50")
            if r.status_code == 200:
                explains = r.json().get("explains", [])
                if not explains:
                    st.info("暂无真题解析记录")
                for exp in explains:
                    label = f"📚 {exp['question_text'][:50]}... | {exp['created_at']}"
                    with st.expander(label):
                        st.caption(f"记录 ID: `{exp['id']}`")
                        if st.button("查看详情", key=f"view_exp_{exp['id']}"):
                            detail = requests.get(f"{API_BASE}/question_explains/{exp['id']}")
                            if detail.status_code == 200:
                                data = detail.json()
                                res = data["result"]
                                st.markdown(f"**题目：** {data['question_text']}")
                                st.markdown(f"**题目类型：** `{res.get('question_type', '-')}`")
                                st.markdown("### 🎯 核心考察点")
                                for p in res.get("core_points", []):
                                    st.markdown(f"- {p}")
                                st.markdown("### ✅ 参考答案")
                                st.markdown(res.get("reference_answer", ""))
                                st.markdown("### 📝 答题框架")
                                for step in res.get("answer_framework", []):
                                    st.markdown(f"- {step}")
                                st.markdown("### 🔄 可能的追问")
                                for f in res.get("follow_up_questions", []):
                                    st.markdown(f"- {f}")
                                st.markdown("### ⚠️ 常见误区")
                                for m in res.get("common_mistakes", []):
                                    st.markdown(f"- {m}")
                        if st.button("删除", key=f"del_exp_{exp['id']}"):
                            requests.delete(f"{API_BASE}/question_explains/{exp['id']}")
                            st.rerun()
        except Exception as e:
            st.error(f"连接后端失败：{e}")