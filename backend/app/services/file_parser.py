import io
from typing import Optional


def parse_resume_file(file_bytes: bytes, filename: str) -> str:
    """根据文件名后缀解析 PDF / Word / 文本，返回纯文本"""
    filename = filename.lower()

    if filename.endswith(".pdf"):
        import pdfplumber
        text_parts = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
        return "\n".join(text_parts)

    elif filename.endswith(".docx"):
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

    elif filename.endswith(".txt") or filename.endswith(".md"):
        return file_bytes.decode("utf-8", errors="ignore")

    else:
        raise ValueError(f"不支持的文件格式：{filename}")