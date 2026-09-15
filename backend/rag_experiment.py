"""
RAG 实验脚本（独立运行，不影响主流程）

用法：
    cd backend
    python rag_experiment.py build    # 构建知识库
    python rag_experiment.py query "Spring Boot 自动装配"   # 检索测试
"""
import os
import sys
import json
import sqlite3
from typing import List, Dict

import requests
from dotenv import load_dotenv
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

# ============================================================
# 配置
# ============================================================
SOPHNET_API_KEY = os.getenv("SOPHNET_API_KEY")

# SophNet 自定义 Embedding 接口
EMBEDDING_URL = "https://www.sophnet.com/api/open-apis/projects/6gDPrTiaVAVXnguKVA7lgK/easyllms/embeddings"
EASYLLM_ID = "6L3UXanqJKEtlZU7O0AhHg"
EMBEDDING_DIMENSIONS = 1024

DB_PATH = os.path.join(os.path.dirname(__file__), "sessions.db")
CHROMA_DIR = os.path.join(os.path.dirname(__file__), "..", "chroma_db")


# ============================================================
# 1. 从 SQLite 读历史数据
# ============================================================
def load_history_docs() -> List[Dict]:
    """从 sessions.db 读取历史 Q&A，转成文档列表"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT state FROM sessions").fetchall()
    conn.close()

    docs = []
    for (state_str,) in rows:
        try:
            state = json.loads(state_str)
        except Exception:
            continue

        position = state.get("position", "")
        tech_stack = state.get("tech_stack", [])
        qa_pairs = state.get("qa_pairs", [])

        for qa in qa_pairs:
            question = qa.get("question", "")
            answer = qa.get("answer", "")
            ref = qa.get("reference_answer", "")

            if not question:
                continue

            text = f"【岗位】{position}\n【技术栈】{', '.join(tech_stack)}\n\n"
            text += f"【问题】{question}\n\n"
            text += f"【候选人回答】{answer}\n\n"
            text += f"【参考答案】{ref}"

            docs.append({
                "text": text,
                "metadata": {
                    "position": position,
                    "question": question[:100],
                    "source": "history"
                }
            })

    return docs


# ============================================================
# 2. 调用 SophNet EasyLLM Embedding 接口
# ============================================================
def embed_texts(texts: List[str]) -> List[List[float]]:
    """批量 embed，返回向量列表"""
    headers = {
        "Authorization": f"Bearer {SOPHNET_API_KEY}",
        "Content-Type": "application/json"
    }

    batch_size = 8   # SophNet 单次限制未知，先用小批量
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        payload = {
            "easyllm_id": EASYLLM_ID,
            "input_texts": batch,
            "dimensions": EMBEDDING_DIMENSIONS
        }

        try:
            resp = requests.post(EMBEDDING_URL, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError as e:
            print(f"❌ HTTP 错误：{e}")
            print(f"   响应：{resp.text[:500]}")
            raise
        except Exception as e:
            print(f"❌ 调用失败：{e}")
            raise

        # 响应格式解析：可能是 {"result": [[...], [...]]} 或 {"data": [...]}
        embeddings = None
        if isinstance(data, dict):
            if "result" in data and isinstance(data["result"], list):
                embeddings = data["result"]
            elif "data" in data and isinstance(data["data"], list):
                # 兼容 OpenAI 格式
                embeddings = [
                    item["embedding"] if isinstance(item, dict) else item
                    for item in data["data"]
                ]
            elif "embeddings" in data:
                embeddings = data["embeddings"]

        if embeddings is None:
            print(f"❌ 无法解析响应：{json.dumps(data, ensure_ascii=False)[:500]}")
            raise ValueError("未知的 Embedding 响应格式")

        all_embeddings.extend(embeddings)
        print(f"  已 embedding {i + len(batch)}/{len(texts)}")

    return all_embeddings


# ============================================================
# 3. 构建知识库
# ============================================================
def build_knowledge_base():
    """从 sessions.db 读数据，切分，embedding，存入 Chroma"""
    print("📚 加载历史数据...")
    docs = load_history_docs()
    print(f"  共 {len(docs)} 条 Q&A")

    if not docs:
        print("⚠️ 没有历史数据，先去跑几次面试")
        return

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", "。", "！", "？", " ", ""]
    )

    chunks = []
    metadatas = []
    for doc in docs:
        pieces = splitter.split_text(doc["text"])
        for piece in pieces:
            chunks.append(piece)
            metadatas.append(doc["metadata"])

    print(f"  切分后 {len(chunks)} 个文本块")

    print("🔢 调用 SophNet Embedding API...")
    embeddings = embed_texts(chunks)

    print("💾 存入 Chroma...")
    chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)

    try:
        chroma_client.delete_collection("interview_kb")
    except Exception:
        pass

    collection = chroma_client.create_collection(
        name="interview_kb",
        metadata={"hnsw:space": "cosine"}
    )

    ids = [f"doc_{i}" for i in range(len(chunks))]
    collection.add(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas
    )

    print(f"✅ 知识库构建完成，共 {len(chunks)} 个向量")
    print(f"   存储位置：{CHROMA_DIR}")


# ============================================================
# 4. 检索测试
# ============================================================
def query_knowledge_base(query: str, top_k: int = 3):
    """检索最相关的 top_k 个文档"""
    chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    try:
        collection = chroma_client.get_collection("interview_kb")
    except Exception:
        print("❌ 知识库不存在，先运行 build")
        return

    query_embedding = embed_texts([query])[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )

    print(f"\n🔍 查询：{query}\n")
    print("=" * 60)
    for i, (doc, meta, dist) in enumerate(zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ), 1):
        print(f"\n【结果 {i}】相似度：{1 - dist:.4f}")
        print(f"岗位：{meta.get('position', '')}")
        print(f"内容：\n{doc[:500]}...")
        print("-" * 60)


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：")
        print("  python rag_experiment.py build")
        print("  python rag_experiment.py query '你的查询'")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "build":
        build_knowledge_base()
    elif cmd == "query":
        if len(sys.argv) < 3:
            print("请提供查询内容")
            sys.exit(1)
        query_knowledge_base(sys.argv[2])
    else:
        print(f"未知命令：{cmd}")