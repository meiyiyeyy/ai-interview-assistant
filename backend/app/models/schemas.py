from pydantic import BaseModel
from typing import List, Optional, Dict


class StartRequest(BaseModel):
    position: str
    tech_stack: List[str]
    interview_mode: str = "technical"
    difficulty: str = "medium"
    interviewer_style: str = "gentle"  # 新增
    jd_text: Optional[str] = None
    resume_text: Optional[str] = None
    session_id: Optional[str] = None


class AnswerRequest(BaseModel):
    session_id: str
    answer: str


class QuestionResponse(BaseModel):
    session_id: str
    question: str
    question_id: int
    is_follow_up: bool
    is_last: bool
    difficulty: str = "medium"
    mode: str = "technical"


class ReportResponse(BaseModel):
    session_id: str
    report: str
    evaluations: List[dict]
    radar_data: Optional[Dict[str, float]] = None
    qa_pairs: Optional[List[dict]] = None
    finished_early: bool = False      # 新增：是否提前结束


class ResumeReviewRequest(BaseModel):
    resume_text: str
    target_position: Optional[str] = ""


class InterviewQuestionRequest(BaseModel):
    question_text: str
    position: Optional[str] = ""
    tech_stack: Optional[List[str]] = []