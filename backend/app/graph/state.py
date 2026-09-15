from typing import List, Dict, Optional, TypedDict, Any

class InterviewState(TypedDict):
    # 输入
    position: str
    tech_stack: List[str]
    # 简历解析结果
    skills: List[str]
    # 题目列表
    questions: List[Dict[str, Any]]
    # 当前进度
    current_q_idx: int
    # 回答记录：{题号: 回答内容}
    answers: Dict[int, str]
    # 追问轮次
    follow_up_round: int
    # 是否结束
    is_finished: bool
    # 评估结果
    evaluations: List[dict]
    # 最终报告
    final_report: str