# 🎯 AI 面试工作台

> 基于 LangGraph + Qwen 的多功能 AI 面试模拟与诊断平台

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.63-red)](https://streamlit.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 📖 项目介绍

一个面向技术求职者的 AI 面试工作台，覆盖 **模拟面试、简历评估、真题解析、历史记录** 四大模块。

项目使用 **LangGraph** 编排多 Agent 协作流程，集成 **RAG 检索增强生成**（基于 SophNet Embedding + Chroma）实现知识库驱动的出题与评估，并支持 **Qwen3-VL 视觉模型** 识别面试题截图。

---

## ✨ 核心功能

| 模块 | 功能 |
|------|------|
| 🎤 **模拟面试** | 技术面/行为面/系统设计/HR面，支持难度自适应、动态追问、四种面试官人设 |
| 📄 **简历评估** | 多维度打分 + 逐条修改建议（含示例改写），解决 LLM 时间感知缺失问题 |
| 📚 **真题解析** | 单题/批量解析，输出考察点、参考答案、答题框架、延伸追问与常见误区 |
| 📷 **图片识别** | 基于 Qwen3-VL 的面试题截图 OCR，自动提取文字 |
| 📜 **历史记录** | 三类记录持久化，支持查看详情与删除 |
| 🔍 **RAG 增强** | 实时索引历史 Q&A，出题时检索相关题目作为上下文参考 |
| 📥 **导出** | 真题解析支持 Markdown / Word 导出 |
| 🛠 **基础设施** | SQLite 持久化、LLM 调用重试+超时、Token 统计、12 个单元测试 |

---

## 🚀 快速开始

### 环境要求

- Python 3.12+
- Git

### 安装

```bash
# 1. 克隆项目
git clone https://github.com/your-username/mianshiRAG.git
cd mianshiRAG

# 2. 创建虚拟环境
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# 3. 安装依赖
pip install -r backend/requirements.txt