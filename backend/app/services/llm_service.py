import os
import json
import re
import base64
from datetime import datetime
from typing import List
from openai import OpenAI
from dotenv import load_dotenv
import openai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

load_dotenv()

client = OpenAI(
    api_key=os.getenv("SOPHNET_API_KEY"),
    base_url="https://www.sophnet.com/api/open-apis"
)


# ============================================================
# LLM 调用统一封装（重试 + 超时 + token 统计）
# ============================================================
TOKEN_STATS = {"prompt": 0, "completion": 0, "calls": 0}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((
        openai.APIConnectionError,
        openai.APITimeoutError,
        openai.RateLimitError,
    )),
    reraise=True
)
def _call_llm(messages, model="qwen3.7-max", temperature=0.5, **kwargs):
    """
    统一的 LLM 调用入口，带重试、超时、token 统计。
    所有业务函数都应通过它调用，不再直接 client.chat.completions.create
    """
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        timeout=60,
        **kwargs
    )

    # 统计 token
    if hasattr(response, "usage") and response.usage:
        TOKEN_STATS["prompt"] += response.usage.prompt_tokens or 0
        TOKEN_STATS["completion"] += response.usage.completion_tokens or 0
        TOKEN_STATS["calls"] += 1
        print(
            f"💰 [LLM] model={model} "
            f"prompt={response.usage.prompt_tokens} "
            f"completion={response.usage.completion_tokens} "
            f"| 累计: {TOKEN_STATS}"
        )

    return response


# ============================================================
# 时间上下文工具
# ============================================================
def _get_current_date() -> str:
    """返回当前日期字符串，如 2026年09月12日"""
    return datetime.now().strftime("%Y年%m月%d日")


def _time_context() -> str:
    """
    返回带时间的系统上下文说明。
    所有涉及时间判断的 prompt 都应把它放在最开头。
    """
    today = _get_current_date()
    return (
        f"【当前真实日期】{today}。\n"
        f"【时间判断规则】\n"
        f"1. 所有早于或等于 {today} 的时间都属于过去，不要标记为「未来时间」。\n"
        f"2. 只有严格晚于 {today} 的时间才算未来时间，才需要指出逻辑错误。\n"
        f"3. 判断项目经历、工作年限、技术时效性时，一律以当前真实日期为基准。"
    )


# ============================================================
# 面试模式 & 难度定义
# ============================================================
INTERVIEW_MODES = {
    "technical": {
        "name": "技术面",
        "system_prompt": "你是一位资深技术面试官，重点考察候选人的技术深度、原理理解和实战经验。",
        "dimensions": ["技术准确性", "深度", "广度", "表达清晰度", "举例能力"],
    },
    "behavioral": {
        "name": "行为面",
        "system_prompt": "你是一位行为面试官，使用 STAR 法则考察候选人的项目经历、团队协作和问题解决能力。",
        "dimensions": ["Situation清晰度", "Task明确度", "Action有效性", "Result量化度"],
    },
    "system_design": {
        "name": "系统设计面",
        "system_prompt": "你是一位系统架构师，考察候选人的架构设计能力、权衡取舍和技术选型。",
        "dimensions": ["需求理解", "架构合理性", "扩展性", "容错设计", "技术选型"],
    },
    "hr": {
        "name": "HR面",
        "system_prompt": "你是一位 HR，考察候选人的职业规划、沟通表达、价值观和文化匹配度。",
        "dimensions": ["表达清晰度", "职业规划", "沟通能力", "稳定性", "价值观匹配"],
    },
}

# ============================================================
# 面试官人设配置
# ============================================================
INTERVIEWER_STYLES = {
    "strict": {
        "name": "严厉型",
        "persona": "你是一位严厉的资深面试官，语气直接，对回答的质量要求很高，会毫不留情地指出不足。",
        "max_follow_up": 3,
        "tone": "语气直接、专业，不做过多铺垫，点评一针见血。",
    },
    "gentle": {
        "name": "温和型",
        "persona": "你是一位温和友善的面试官，会鼓励候选人，即使回答不完美也会给出积极引导。",
        "max_follow_up": 1,
        "tone": "语气温和、鼓励，点评时先肯定优点，再委婉指出不足。",
    },
    "probing": {
        "name": "追问型",
        "persona": "你是一位喜欢深挖的面试官，任何回答都会继续追问，直到候选人的知识边界被完全暴露。",
        "max_follow_up": 4,
        "tone": "语气中性但步步紧逼，善于通过连续追问暴露候选人的知识盲区。",
    },
    "silent": {
        "name": "沉默型",
        "persona": "你是一位话少、严肃的面试官，只问关键问题，不做过多的追问和反馈，模拟真实高压面试场景。",
        "max_follow_up": 0,
        "tone": "语气简洁、冷静，点评简短，不展开。",
    },
}


def get_style_config(style: str) -> dict:
    """获取面试官人设配置"""
    return INTERVIEWER_STYLES.get(style, INTERVIEWER_STYLES["gentle"])

DIFFICULTY_HINTS = {
    "easy": "出偏基础、概念性的问题，适合初中级候选人。",
    "medium": "出中等难度的问题，兼顾原理和实战，适合中高级候选人。",
    "hard": "出高难度、深度原理或复杂场景题，适合资深候选人。",
}


# ============================================================
# JSON 解析工具（多层容错）
# ============================================================
def _extract_json(text: str, fallback=None):
    """从 LLM 返回里提取 JSON，兼容 markdown 包裹、控制字符，失败时返回兜底值"""
    if not text:
        print("⚠️ _extract_json: LLM 返回为空")
        return fallback if fallback is not None else {}

    text = text.strip()

    # 去掉 ```json ... ``` 包裹
    if "```" in text:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1).strip()

    # 找到第一个 [ 或 { 到最后一个 ] 或 }
    starts = [i for i in [text.find("["), text.find("{")] if i != -1]
    end_candidates = [text.rfind("]"), text.rfind("}")]
    start = min(starts) if starts else -1
    end = max(end_candidates)
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]

    # 清理字符串内部的非法控制字符（换行/制表/回车）
    text = _escape_control_chars(text)

    # 第一次尝试：直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"⚠️ JSON 解析失败：{e}")
        print(f"⚠️ 原文前 500 字：{text[:500]}")

    # 第二次尝试：修复中文引号
    try:
        text_fixed = text.replace("“", "「").replace("”", "」")
        return json.loads(text_fixed)
    except json.JSONDecodeError:
        pass

    # 第三次尝试：正则兜底
    try:
        return _fallback_parse(text)
    except Exception:
        pass

    print("❌ 无法解析 JSON，返回兜底值")
    return fallback if fallback is not None else {}


def _escape_control_chars(text: str) -> str:
    """将 JSON 字符串内部的真实控制字符转义"""
    result = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == "\\":
            result.append(ch)
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string:
            if ch == "\n":
                result.append("\\n")
            elif ch == "\r":
                result.append("\\r")
            elif ch == "\t":
                result.append("\\t")
            else:
                result.append(ch)
        else:
            result.append(ch)
    return "".join(result)


def _fallback_parse(text: str) -> dict:
    """粗暴兜底：从文本里抓 score / summary"""
    result = {}
    scores = re.findall(r'"score"\s*:\s*(\d+(?:\.\d+)?)', text)
    if scores:
        nums = [float(s) for s in scores]
        result["overall_score"] = sum(nums) / len(nums)
    m = re.search(r'"summary"\s*:\s*"([^"]+)"', text)
    if m:
        result["summary"] = m.group(1)
    result.setdefault("overall_score", 6.0)
    result.setdefault("summary", "评估解析失败，使用默认分数")
    return result


# ============================================================
# 1. 技能提取
# ============================================================
def extract_skills(position: str, tech_stack: List[str]) -> List[str]:
    prompt = f"""
    职位：{position}
    技术栈：{', '.join(tech_stack)}

    请从以上信息中提取5-8个核心技能关键词，只返回JSON数组格式，例如：["Python", "Django", "REST API"]。
    不要加任何解释、不要用 markdown 代码块，直接输出 JSON 数组。
    """
    response = _call_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    content = response.choices[0].message.content
    print("=== extract_skills 返回 ===")
    print(repr(content))
    return _extract_json(content, fallback=[])


# ============================================================
# 2. 题目生成
# ============================================================
def generate_questions(
    skills: List[str],
    num: int = 5,
    mode: str = "technical",
    difficulty: str = "medium",
    jd_info: dict = None,
    resume_info: dict = None,
    style: str = "gentle",
    rag_context: List[str] = None,# 新增
) -> List[dict]:
    mode_cfg = INTERVIEW_MODES.get(mode, INTERVIEW_MODES["technical"])
    style_cfg = get_style_config(style)
    difficulty_hint = DIFFICULTY_HINTS.get(difficulty, DIFFICULTY_HINTS["medium"])

    extra = ""
    if jd_info:
        extra += f"\n岗位必备技能：{', '.join(jd_info.get('must_have', []))}"
        extra += f"\n岗位加分项：{', '.join(jd_info.get('nice_to_have', []))}"
        extra += f"\n软技能要求：{', '.join(jd_info.get('soft_skills', []))}"
    if resume_info and resume_info.get("projects"):
        projects_desc = "; ".join([
            f"{p.get('name', '')}({p.get('role', '')})"
            for p in resume_info["projects"][:3]
        ])
        extra += f"\n候选人项目经历：{projects_desc}"

    prompt = f"""
    角色：{mode_cfg['system_prompt']}
    {style_cfg['persona']}

    技能列表：{', '.join(skills)}
    难度要求：{difficulty_hint}{extra}

    请生成{num}道{mode_cfg['name']}题目，覆盖不同维度。
    返回JSON数组格式，每道题包含：
    {{
      "id": 1,
      "question": "题目内容",
      "dimension": "考察维度（从 {mode_cfg['dimensions']} 中选）",
      "difficulty": "{difficulty}",
      "expected_knowledge": ["知识点1", "知识点2"]
    }}

    严格要求：
    1. 只输出 JSON，不要 markdown 代码块、不要解释
    2. 字符串内部不要出现换行符，需要换行时用空格代替
    3. 所有字符串内部的双引号必须转义
    4. 题目之间不要重复
    """
    response = _call_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return _extract_json(response.choices[0].message.content, fallback=[])

# ============================================================
# 3. 追问判断
# ============================================================
def should_follow_up(answer: str, question: dict, style: str = "gentle") -> bool:
    style_cfg = get_style_config(style)
    max_follow = style_cfg["max_follow_up"]

    # 沉默型不追问
    if max_follow == 0:
        return False

    prompt = f"""
    {style_cfg['persona']}
    {style_cfg['tone']}

    问题：{question['question']}
    期望知识点：{', '.join(question.get('expected_knowledge', []))}
    回答：{answer}

    判断该回答是否完整覆盖了所有期望知识点，如果缺失关键点，返回"需要追问"否则返回"无需追问"。
    只返回这两个短语之一。
    """
    response = _call_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    return "需要追问" in response.choices[0].message.content

# ============================================================
# 4. 生成追问
# ============================================================
def generate_follow_up(question: str, answer: str, expected_knowledge: List[str], style: str = "gentle") -> str:
    style_cfg = get_style_config(style)

    prompt = f"""
    {style_cfg['persona']}
    {style_cfg['tone']}

    原始问题：{question}
    期望知识点：{', '.join(expected_knowledge)}
    用户回答：{answer}

    用户回答没有完整覆盖期望知识点。请基于用户的回答，生成一个针对性的追问题目，
    引导用户补充缺失的关键点。追问要具体、口语化，不要重复原题。

    只输出追问的题目本身，不要加任何解释或前后缀。
    """
    response = _call_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content.strip()

# ============================================================
# 5. 回答评估（注入时间上下文）
# ============================================================
def evaluate_answer(
    question: str,
    answer: str,
    expected_knowledge: List[str],
    mode: str = "technical",
    style: str = "gentle"   # 新增
) -> dict:
    mode_cfg = INTERVIEW_MODES.get(mode, INTERVIEW_MODES["technical"])
    style_cfg = get_style_config(style)
    dimensions = mode_cfg["dimensions"]
    dim_prompt = "\n".join([f"- {d}" for d in dimensions])

    prompt = f"""
    {_time_context()}

    {style_cfg['persona']}
    {style_cfg['tone']}

    问题：{question}
    期望知识点：{', '.join(expected_knowledge)}
    候选人回答：{answer}

    请从以下维度逐项评分（1-10分）：
    {dim_prompt}

    返回JSON格式（key 用中文维度名）：
    {{
      "维度名": {{"score": 8, "suggestion": "改进建议"}},
      "overall_score": 7.5,
      "summary": "总体评价"
    }}

    严格要求：
    1. 只输出 JSON，不要加任何解释、markdown 代码块
    2. 字符串内部不要出现换行符
    3. 所有字符串值内部的双引号必须转义为 \\"
    """
    response = _call_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    result = _extract_json(
        response.choices[0].message.content,
        fallback={"overall_score": 6.0, "summary": "评估解析失败，按中等分处理"}
    )
    result["mode"] = mode
    result["style"] = style
    return result

# ============================================================
# 6. 参考答案生成
# ============================================================
def generate_reference_answer(question: str, expected_knowledge: List[str]) -> str:
    prompt = f"""
    问题：{question}
    期望知识点：{', '.join(expected_knowledge)}

    请生成一份「优秀回答示范」，要求：
    1. 结构清晰，分点作答
    2. 覆盖所有期望知识点
    3. 有具体例子或代码片段
    4. 控制在 300 字以内

    只输出回答本身，不要加前后缀。
    """
    response = _call_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    return response.choices[0].message.content.strip()


# ============================================================
# 7. 最终报告（注入时间上下文）
# ============================================================
def generate_report(evaluations: List[dict], position: str, mode: str = "technical") -> dict:
    prompt = f"""
    {_time_context()}

    职位：{position}
    面试模式：{mode}
    各题评估结果：{evaluations}

    请生成一份面试诊断报告，包含：
    1. 总体评价（优点/不足）
    2. 各维度得分汇总
    3. 针对性学习建议（3-5个具体复习方向）

    同时，请汇总所有维度的平均分，返回JSON格式：
    {{
      "report_markdown": "...",
      "radar_data": {{"技术准确性": 8.0, "深度": 7.5}},
      "overall_score": 7.5
    }}

    严格要求：
    1. 只输出 JSON，不要 markdown 代码块
    2. 字符串内部不要出现换行符，需要换行用 \\n 转义
    3. 引号统一用中文「」
    """
    response = _call_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    return _extract_json(
        response.choices[0].message.content,
        fallback={"report_markdown": "报告生成失败", "radar_data": {}, "overall_score": 0}
    )


# ============================================================
# 8. JD 解析
# ============================================================
def parse_jd(jd_text: str) -> dict:
    prompt = f"""
    以下是岗位 JD 原文：
    {jd_text}

    请提取以下信息，返回 JSON：
    {{
      "must_have": ["必备技能1", "必备技能2"],
      "nice_to_have": ["加分项1", "加分项2"],
      "soft_skills": ["软技能1", "软技能2"]
    }}
    只输出 JSON，不要加任何解释。
    """
    response = _call_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return _extract_json(
        response.choices[0].message.content,
        fallback={"must_have": [], "nice_to_have": [], "soft_skills": []}
    )


# ============================================================
# 9. 简历解析
# ============================================================
def parse_resume(resume_text: str) -> dict:
    prompt = f"""
    以下是候选人简历原文：
    {resume_text}

    请提取以下信息，返回 JSON：
    {{
      "skills": ["技能1", "技能2"],
      "projects": [
        {{"name": "项目名", "role": "角色", "tech": ["技术1"], "highlights": ["亮点1"]}}
      ],
      "highlights": ["整体亮点1"]
    }}
    只输出 JSON，不要加任何解释。
    """
    response = _call_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return _extract_json(
        response.choices[0].message.content,
        fallback={"skills": [], "projects": [], "highlights": []}
    )


# ============================================================
# 10. 简历评估（注入时间上下文）
# ============================================================
def review_resume(resume_text: str, target_position: str = "") -> dict:
    """评估简历，返回分维度打分 + 修改建议"""
    prompt = f"""
    {_time_context()}

    你是一位资深 HR 和技术面试官，请评估以下简历。

    目标岗位：{target_position or '未指定'}
    简历原文：
    {resume_text}

    【时间判断特别提醒】
    请严格按照上面给出的「当前真实日期」判断简历中的时间。
    2024 年、2025 年、2026 年的项目经历，只要不晚于当前真实日期，都属于过去，不能标记为「未来时间」。
    只有当时间严格晚于当前真实日期时，才属于逻辑错误。

    请从以下维度评估（每项 1-10 分）：
    - 结构与排版
    - 项目经历质量
    - 技术栈匹配度
    - 量化成果
    - 表达清晰度

    返回 JSON 格式：
    {{
      "overall_score": 7.5,
      "dimension_scores": {{
        "结构与排版": {{"score": 8, "comment": "..."}},
        "项目经历质量": {{"score": 7, "comment": "..."}}
      }},
      "strengths": ["优点1", "优点2"],
      "weaknesses": ["不足1", "不足2"],
      "suggestions": [
        {{"section": "项目经历", "issue": "描述过于笼统", "fix": "建议改成...", "example": "示例改写"}}
      ],
      "summary": "总体评价"
    }}

    严格要求：
    1. 只输出 JSON，不要 markdown 代码块
    2. 字符串内部不要出现换行符，需要换行用空格代替
    3. 引号统一用中文「」
    """
    response = _call_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    return _extract_json(
        response.choices[0].message.content,
        fallback={"overall_score": 0, "summary": "评估失败"}
    )


# ============================================================
# 11. 真题解析（注入时间上下文）
# ============================================================
def explain_interview_question(
    question_text: str,
    position: str = "",
    tech_stack: List[str] = None,
) -> dict:
    tech_str = ", ".join(tech_stack) if tech_stack else "未指定"

    prompt = f"""
    {_time_context()}

    你是资深技术面试官。下面是一道面试真题或面经问题：

    题目：{question_text}
    岗位：{position or '未指定'}
    技术栈：{tech_str}

    请给出详细解析，返回 JSON：
    {{
      "question_type": "概念/项目/设计/算法/行为",
      "core_points": ["考察点1", "考察点2"],
      "reference_answer": "完整参考答案（300字以内，分点作答）",
      "answer_framework": ["第一步：...", "第二步：..."],
      "follow_up_questions": ["延伸追问1", "延伸追问2"],
      "common_mistakes": ["常见误区1", "常见误区2"]
    }}

    严格要求：
    1. 只输出 JSON，不要 markdown 代码块
    2. 字符串内部不要出现换行符，需要换行用空格代替
    3. 引号统一用中文「」
    """
    response = _call_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    return _extract_json(
        response.choices[0].message.content,
        fallback={"reference_answer": "解析失败"}
    )


# ============================================================
# 12. 图片文字识别（Qwen3-VL 视觉模型）
# ============================================================
def extract_text_from_image(image_bytes: bytes) -> str:
    """
    使用 Qwen3-VL 从图片中提取文字内容。
    用于识别用户上传的面试题截图、面经图片。
    """
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_uri = f"data:image/jpeg;base64,{b64}"

    prompt = f"""
    {_time_context()}

    请仔细识别这张图片中的所有文字内容，原样输出。
    如果是面试题截图，请完整提取题目文本。
    如果是面经分享，请提取问题和回答要点。

    要求：
    1. 只输出图片中的文字内容，不要加任何解释或前后缀
    2. 保持原文的层次结构，代码片段用代码块包裹
    3. 如果图片中没有任何文字，返回空字符串
    """

    response = _call_llm(
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_uri}},
                {"type": "text", "text": prompt}
            ]
        }],
        model="qwen3-vl-plus",
        temperature=0.1
    )
    return response.choices[0].message.content.strip()

def split_questions(text: str) -> List[str]:
    """把用户粘贴的多道题切分成独立的题目列表"""
    prompt = f"""
    以下是一段面试题文本，可能包含多道题目。
    请把它们切分成独立的题目列表。

    原文：
    {text}

    返回 JSON 数组格式：
    ["题目1", "题目2", "题目3", ...]

    要求：
    1. 只输出 JSON，不要 markdown 代码块
    2. 每道题保留完整表述，不要省略
    3. 如果只有一道题，也返回只包含一个元素的数组
    4. 去掉题号（如"1."、"2."），只保留题目内容
    """
    response = _call_llm(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )
    return _extract_json(response.choices[0].message.content, fallback=[text])
