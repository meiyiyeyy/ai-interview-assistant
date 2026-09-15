import sqlite3
import json
import os
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "sessions.db")


class SessionStore:
    def __init__(self, db_path: str = DB_PATH):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        # 面试会话表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                state TEXT,
                updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
            )
        """)
        # 简历评估记录表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS resume_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_position TEXT,
                resume_text TEXT,
                result TEXT,
                created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
            )
        """)
        # 真题解析记录表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS question_explains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT,
                position TEXT,
                tech_stack TEXT,
                result TEXT,
                created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
            )
        """)
        self.conn.commit()

    # ========== 面试会话 ==========
    def save_state(self, session_id: str, state: dict):
        self.conn.execute(
            "REPLACE INTO sessions (session_id, state, updated_at) "
            "VALUES (?, ?, datetime('now', 'localtime'))",
            (session_id, json.dumps(state, ensure_ascii=False, default=str))
        )
        self.conn.commit()

    def get_state(self, session_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT state FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def delete_state(self, session_id: str):
        self.conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self.conn.commit()

    def list_sessions(self, limit: int = 50):
        rows = self.conn.execute(
            "SELECT session_id, state, updated_at FROM sessions "
            "ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for sid, state_str, updated_at in rows:
            try:
                state = json.loads(state_str)
                result.append({
                    "session_id": sid,
                    "position": state.get("position", ""),
                    "mode": state.get("mode", "technical"),
                    "updated_at": updated_at,
                    "is_finished": state.get("is_finished", False),
                    "finished_early": state.get("finished_early", False),  # 新增
                })
            except Exception:
                continue
        return result

    # ========== 简历评估记录 ==========
    def save_resume_review(self, target_position: str, resume_text: str, result: dict):
        cur = self.conn.execute(
            "INSERT INTO resume_reviews (target_position, resume_text, result) "
            "VALUES (?, ?, ?)",
            (target_position, resume_text, json.dumps(result, ensure_ascii=False, default=str))
        )
        self.conn.commit()
        return cur.lastrowid

    def list_resume_reviews(self, limit: int = 50):
        rows = self.conn.execute(
            "SELECT id, target_position, result, created_at FROM resume_reviews "
            "ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for rid, pos, result_str, created_at in rows:
            try:
                res = json.loads(result_str)
                result.append({
                    "id": rid,
                    "target_position": pos,
                    "overall_score": res.get("overall_score", 0),
                    "summary": res.get("summary", ""),
                    "created_at": created_at,
                })
            except Exception:
                continue
        return result

    def get_resume_review(self, review_id: int) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT target_position, resume_text, result FROM resume_reviews WHERE id = ?",
            (review_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "target_position": row[0],
            "resume_text": row[1],
            "result": json.loads(row[2]),
        }

    def delete_resume_review(self, review_id: int):
        self.conn.execute("DELETE FROM resume_reviews WHERE id = ?", (review_id,))
        self.conn.commit()

    # ========== 真题解析记录 ==========
    def save_question_explain(self, question_text: str, position: str,
                              tech_stack: list, result: dict):
        cur = self.conn.execute(
            "INSERT INTO question_explains (question_text, position, tech_stack, result) "
            "VALUES (?, ?, ?, ?)",
            (question_text, position, json.dumps(tech_stack, ensure_ascii=False),
             json.dumps(result, ensure_ascii=False, default=str))
        )
        self.conn.commit()
        return cur.lastrowid

    def list_question_explains(self, limit: int = 50):
        rows = self.conn.execute(
            "SELECT id, question_text, position, result, created_at FROM question_explains "
            "ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for qid, q_text, pos, result_str, created_at in rows:
            try:
                res = json.loads(result_str)
                result.append({
                    "id": qid,
                    "question_text": q_text[:80],
                    "position": pos,
                    "question_type": res.get("question_type", ""),
                    "created_at": created_at,
                })
            except Exception:
                continue
        return result

    def get_question_explain(self, explain_id: int) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT question_text, position, tech_stack, result FROM question_explains WHERE id = ?",
            (explain_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "question_text": row[0],
            "position": row[1],
            "tech_stack": json.loads(row[2]) if row[2] else [],
            "result": json.loads(row[3]),
        }

    def delete_question_explain(self, explain_id: int):
        self.conn.execute("DELETE FROM question_explains WHERE id = ?", (explain_id,))
        self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


# 单例
session_store = SessionStore()