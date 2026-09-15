"""
RAG 检索服务
- 使用 SophNet Embedding API 把文本向量化
- 使用 Chroma 持久化向量库
- 提供 retrieve_context() 供出题时检索参考
- 提供 add_to_index() 供实时索引新 Q&A
"""
import os
import json
import uuid
import hashlib
import requests
from typing import List, Dict
from dotenv import load_dotenv
import chromadb

load_dotenv()

# ============================================================
# 配置
# ============================================================
SOPHNET_API_KEY = os.getenv("SOPHNET_API_KEY")
EMBEDDING_URL = "https://www.sophnet.com/api/open-apis/projects/6gDPrTiaVAVXnguKVA7lgK/easyllms/embeddings"
EASYLLM_ID = "6L3UXanqJKEtlZU7O0AhHg"
EMBEDDING_DIMENSIONS = 1024

CHROMA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "chroma_db")
COLLECTION_NAME = "interview_kb"


# ============================================================
# Embedding
# ============================================================
def embed_texts(texts: List[str]) -> List[List[float]]:
    """调用 SophNet Embedding API，批量向量化"""
    headers = {
        "Authorization": f"Bearer {SOPHNET_API_KEY}",
        "Content-Type": "application/json"
    }
    batch_size = 8
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        payload = {
            "easyllm_id": EASYLLM_ID,
            "input_texts": batch,
            "dimensions": EMBEDDING_DIMENSIONS
        }
        resp = requests.post(EMBEDDING_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        embeddings = data.get("result") or data.get("embeddings")
        if embeddings is None and "data" in data:
            embeddings = [
                item["embedding"] if isinstance(item, dict) else item
                for item in data["data"]
            ]
        if embeddings is None:
            raise ValueError(f"未知 Embedding 响应格式：{json.dumps(data)[:300]}")

        all_embeddings.extend(embeddings)

    return all_embeddings


# ============================================================
# 文本去重（用 md5 做 id）
# ============================================================
def _text_hash(text: str) -> str:
    """根据文本内容生成稳定的 id，用于去重"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# ============================================================
# 检索
# ============================================================
def retrieve_context(query: str, top_k: int = 3) -> List[str]:
    """
    检索相关历史题目，返回文本列表。
    知识库不可用时返回空列表，调用方应能优雅降级。
    """
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = chroma_client.get_collection(COLLECTION_NAME)
    except Exception as e:
        print(f"⚠️ RAG 知识库不可用：{e}")
        return []

    try:
        query_embedding = embed_texts([query])[0]
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"]
        )

        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]

        filtered = []
        for doc, dist in zip(docs, distances):
            similarity = 1 - dist
            if similarity >= 0.5:
                filtered.append(doc)

        print(f"📚 RAG 检索到 {len(filtered)} 条相关上下文（原始 {len(docs)} 条）")
        return filtered

    except Exception as e:
        print(f"⚠️ RAG 检索失败：{e}")
        return []


# ============================================================
# 实时索引（方案 C 核心）
# ============================================================
def add_to_index(text: str, metadata: Dict = None) -> bool:
    """
    把一条新的 Q&A 实时加入向量库。
    用文本 hash 作为 id，自动去重（同一内容不会重复入库）。
    返回 True 表示成功，False 表示失败（不影响主流程）。
    """
    try:
        # 1. 生成 id（去重）
        doc_id = _text_hash(text)

        # 2. 打开 collection
        chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

        # 3. 检查是否已存在（避免重复 embedding）
        existing = collection.get(ids=[doc_id])
        if existing and existing.get("ids"):
            print(f"ℹ️ 该内容已存在，跳过索引：{doc_id[:8]}")
            return True

        # 4. Embedding
        embedding = embed_texts([text])[0]

        # 5. 写入
        collection.add(
            ids=[doc_id],
            documents=[text],
            embeddings=[embedding],
            metadatas=[metadata or {}]
        )
        print(f"✅ 实时索引成功：{doc_id[:8]}")
        return True

    except Exception as e:
        print(f"⚠️ 实时索引失败（不影响主流程）：{e}")
        return False


# ============================================================
# 格式化 Q&A 为待索引文本
# ============================================================
def format_qa_text(position: str, tech_stack: List[str],
                   question: str, answer: str, reference: str) -> str:
    """把一条 Q&A 格式化成统一的文本，用于向量化"""
    return (
        f"【岗位】{position}\n"
        f"【技术栈】{', '.join(tech_stack)}\n\n"
        f"【问题】{question}\n\n"
        f"【候选人回答】{answer}\n\n"
        f"【参考答案】{reference}"
    )