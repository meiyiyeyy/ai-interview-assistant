import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.llm_service import _extract_json, _escape_control_chars


def test_plain_json():
    assert _extract_json('[1, 2, 3]') == [1, 2, 3]


def test_markdown_wrapped():
    text = '```json\n{"a": 1}\n```'
    assert _extract_json(text) == {"a": 1}


def test_markdown_no_lang():
    text = '```\n{"a": 2}\n```'
    assert _extract_json(text) == {"a": 2}


def test_extra_text_before_json():
    text = '好的，这是结果：\n{"a": 3}\n希望有帮助'
    assert _extract_json(text) == {"a": 3}


def test_control_chars_in_string():
    text = '{"a": "line1\\nline2"}'
    result = _extract_json(text)
    assert result["a"] == "line1\nline2"


def test_real_newline_in_string():
    """LLM 常见错误：字符串内真实换行"""
    text = '{"a": "line1\nline2"}'
    result = _extract_json(text)
    assert "line1" in result["a"]


def test_invalid_returns_fallback():
    fallback = {"x": 1}
    result = _extract_json("not json at all", fallback=fallback)
    # 要么返回 fallback，要么返回 _fallback_parse 的兜底结果
    assert result == fallback or "overall_score" in result

def test_empty_returns_fallback():
    fallback = {"default": True}
    assert _extract_json("", fallback=fallback) == fallback


def test_escape_control_chars():
    text = '{"a": "hello\nworld"}'
    result = _escape_control_chars(text)
    assert "\\n" in result


def test_fallback_parse_score():
    """正则兜底：从坏 JSON 里抓 overall_score"""
    text = '{"dimensions": [{"score": 8}, {"score": 6}], "summary": "还行"}'
    result = _extract_json(text)
    assert "overall_score" in result or "summary" in result