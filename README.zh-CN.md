# ResearchAgent（中文版）

ResearchAgent 是一个本地优先的科研助手系统，提供两种运行模式：

- 传统 RAG 流水线（抓取 -> 解析 -> 分块 -> 建索引 -> 检索 -> 生成回答）
- 基于 LangGraph 的自主研究代理（规划 -> 抓取 -> 索引 -> 分析 -> 综合 -> 迭代 -> 报告）

本文档重点说明如何安装、配置、运行和评测。

## 1. 当前已实现功能

### 1.1 传统 RAG

- 从 arXiv 抓取论文元数据（可选下载 PDF）
- 元数据写入 SQLite
- 使用 PyMuPDF 解析 PDF
- 文本分块（支持 overlap）
- 建立 Chroma 向量索引（包含 `doc_id`、`chunk_id`、offset 元信息）
- 向量检索
- 可选本地 reranker（CrossEncoder）
- 调用 OpenAI 生成带引用回答
- 输出 JSON / Markdown 报告

### 1.2 自主研究代理（Agent）

- 主题拆解：生成研究问题 + arXiv 搜索词
- 迭代抓取与索引
- 基于 RAG 的单篇论文分析
- 跨论文综合与知识空白识别
- 根据 `should_continue` 控制继续迭代或结束
- 输出最终 Markdown 报告 + JSON 状态

### 1.3 评测能力

- 检索命中率
- 引用出现率 + 引用编号合法率
- 引用语义对齐（claim 与被引证据的语义相似）
- 可选一致性评测（多次生成）
- `s2` 专项误差分析（query / top_k / candidate_k / reranker_model）

## 2. 仓库结构

```text
ResearchAgent/
  configs/
    rag.yaml
    agent.yaml
    eval_samples.example.jsonl
  scripts/
    fetch_arxiv.py
    build_index.py
    demo_query.py
    run_mvp.py
    evaluate_rag.py
    run_agent.py
  src/
    ingest/
    rag/
    workflows/
    agent/
    common/
  data/      # 运行期数据（一般建议 gitignore）
  outputs/   # 输出文件（一般建议 gitignore）
```

## 3. 环境要求

- Python 3.10+（仓库建议 3.13）
- OpenAI API Key（环境变量 `OPENAI_API_KEY`）
- 网络（首次运行常见需要）：
  - arXiv API
  - OpenAI API
  - Hugging Face（首次下载 embedding/reranker 模型；若已缓存可离线）

## 4. 安装

### 4.1 使用 Conda（推荐）

```powershell
conda create -n ResearchAgent python=3.13 -y
conda activate ResearchAgent
pip install -U pip
pip install -e .
```

### 4.2 配置 API Key

PowerShell：

```powershell
$env:OPENAI_API_KEY="your_api_key"
```

Bash：

```bash
export OPENAI_API_KEY="your_api_key"
```

## 5. 配置说明

主要修改两份配置：

- `configs/rag.yaml`：传统 RAG
- `configs/agent.yaml`：代理模式

### 5.1 `configs/rag.yaml` 关键项

- `paths.papers_dir`：PDF 目录
- `metadata_store.sqlite_path`：SQLite 路径
- `index.persist_dir`：Chroma 索引目录
- `fetch.max_results`：默认抓取数量
- `fetch.download_pdf`：是否下载 PDF
- `fetch.polite_delay_sec`：下载间隔
- `retrieval.top_k`：最终返回 chunk 数
- `retrieval.candidate_k`：rerank 前候选数
- `retrieval.reranker_model`：reranker 模型名（空字符串表示关闭）
- `openai.model`、`openai.temperature`

### 5.2 `configs/agent.yaml` 关键项

- `llm.model`、`llm.temperature`
- `agent.max_iterations`
- `agent.papers_per_query`
- `agent.max_queries_per_iteration`
- `agent.top_k_for_analysis`
- `agent.language`（`en` 或 `zh`）

两套配置都支持 `${...}` 变量展开（见 `src/common/config_utils.py`）。

## 6. 传统 RAG 用法

### 6.1 抓取论文

```powershell
python -m scripts.fetch_arxiv --query "retrieval augmented generation" --max_results 5
```

只抓元数据，不下载 PDF：

```powershell
python -m scripts.fetch_arxiv --query "retrieval augmented generation" --max_results 5 --no-download
```

### 6.2 建索引

```powershell
python -m scripts.build_index --papers_dir data/papers --chunk_size 1200 --overlap 200
```

单文件模式：

```powershell
python -m scripts.build_index --pdf_path data/papers/arxiv_2306.08657v1.pdf --doc_id arxiv:2306.08657v1
```

### 6.3 问答演示

```powershell
python -m scripts.demo_query --query "List the paper's main contributions. Cite evidence." --top_k 8 --model gpt-4.1-mini
```

启用 reranker：

```powershell
python -m scripts.demo_query --query "List the paper's main contributions. Cite evidence." --top_k 8 --candidate_k 30 --reranker_model "BAAI/bge-reranker-base"
```

### 6.4 一键闭环（MVP）

```powershell
python -m scripts.run_mvp --fetch_query "retrieval augmented generation" --question "List contributions. Cite evidence." --max_results 3 --download --index_from fetched --top_k 8 --candidate_k 30 --reranker_model "BAAI/bge-reranker-base"
```

## 7. 代理模式用法（推荐）

基础运行：

```powershell
python -m scripts.run_agent --topic "retrieval augmented generation"
```

带参数覆盖：

```powershell
python -m scripts.run_agent --topic "LLM alignment techniques" --max_iter 5 --papers_per_query 8 --model gpt-4.1-mini --language en -v
```

中文报告：

```powershell
python -m scripts.run_agent --topic "多模态大模型" --language zh
```

## 8. 评测用法

示例数据：`configs/eval_samples.example.jsonl`

### 8.1 仅检索评测

```powershell
python -m scripts.evaluate_rag --dataset configs/eval_samples.example.jsonl --skip_generation --top_k 8 --candidate_k 30 --reranker_model "BAAI/bge-reranker-base"
```

### 8.2 完整评测（含生成）

```powershell
python -m scripts.evaluate_rag --dataset configs/eval_samples.example.jsonl --top_k 8 --candidate_k 30 --reranker_model "BAAI/bge-reranker-base" --model gpt-4.1-mini --temperature 0.2 --consistency_runs 1
```

### 8.3 输出指标

- `retrieval_hit_rate`
- `citation_presence_rate`
- `citation_valid_ratio_mean`
- `citation_semantic_ratio_mean`
- `answer_consistency_mean`（当 `consistency_runs > 1`）
- `s2_error_analysis`（数据集中含 `id=s2` 时）

## 9. 输出文件

统一写入 `outputs/`：

- `demo_query_*.json` / `demo_query_*.md`
- `run_mvp_*.json` / `run_mvp_*.md`
- `eval_rag_*.json` / `eval_rag_*.md`
- `research_report_*.md` / `research_state_*.json`

## 10. 常见问题排查

- `Missing OPENAI_API_KEY`
  - 先设置环境变量再运行

- `openai.APIConnectionError` / 超时
  - 检查代理变量：`HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`
  - 检查网络/防火墙是否允许访问 OpenAI

- `ModuleNotFoundError`
  - 重新执行：`pip install -e .`

- `Collection not found`
  - 先建索引（`build_index.py`），或使用 `run_mvp.py` / `run_agent.py`

- `No PDF found under ...`
  - 确认 `fetch.download_pdf=true`，并检查 `papers_dir` 路径

- Hugging Face 模型下载失败
  - 首次联网缓存模型；缓存后可离线运行

## 11. 发布到 GitHub 建议

建议 `.gitignore` 至少包含：

- `data/`
- `outputs/`
- `__pycache__/`
- `*.pyc`
- `.env*`
- `*.sqlite`、`*.db`、`*.bin`

不要提交任何密钥、token 或私有凭据。

