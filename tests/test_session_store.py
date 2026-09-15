import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.storage.session_store import SessionStore


def test_save_and_get():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = SessionStore(db_path=db_path)
    try:
        state = {"position": "后端", "answers": {"0": "test"}}
        store.save_state("s1", state)

        result = store.get_state("s1")
        assert result["position"] == "后端"
        assert result["answers"]["0"] == "test"

        store.delete_state("s1")
        assert store.get_state("s1") is None
    finally:
        store.close()          # 先关连接
        os.unlink(db_path)     # 再删文件


def test_list_sessions():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = SessionStore(db_path=db_path)
    try:
        store.save_state("s1", {"position": "A", "mode": "technical", "is_finished": True})
        store.save_state("s2", {"position": "B", "mode": "hr", "is_finished": False})

        sessions = store.list_sessions()
        assert len(sessions) == 2
    finally:
        store.close()
        os.unlink(db_path)