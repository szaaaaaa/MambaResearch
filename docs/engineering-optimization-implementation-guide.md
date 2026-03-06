# 工程优化落地指南

> 日期：2026-03-06
> 范围：抓取与网络依赖、LangGraph 编排可恢复性、依赖与运行环境轻量化
> 用途：作为后续工程优化修改的实施基线

## 1. 目标

把当前系统从“有基础容错和观测的研究型 agent”推进到“可恢复、可降级、可替换依赖、可持续回归”的工程态。

本指南聚焦三条主线：

1. 抓取与网络依赖健壮性
2. LangGraph 编排的可恢复性与强契约
3. 本地重依赖的解耦与轻量化

---

## 2. 当前状态总结

### 2.1 已有能力

1. provider 级失败隔离：`arXiv/OpenAlex/Semantic Scholar` 单路失败多数不会直接炸全流程  
   代码：`src/agent/plugins/search/default_search.py`
2. 部分网络错误已有 retry/backoff  
   代码：`src/ingest/web_fetcher.py`
3. PDF 下载已有 allowlist、403 host deny cache、404 跳过  
   代码：`src/agent/plugins/search/default_search.py`
4. 节点有结构化事件日志  
   代码：`src/agent/core/events.py`
5. LLM 调用已有统一入口、失败分类、retry/fallback  
   代码：`src/agent/providers/llm_provider.py`
6. PDF 提取已有 backend fallback：`marker -> pymupdf`  
   代码：`src/workflows/traditional_rag.py`

### 2.2 主要缺口

1. 没有 LangGraph checkpointer，失败后无法断点续跑  
   代码：`src/agent/graph.py`
2. 节点输出仍是“宽松 JSON 解析”，不是强 schema  
   代码：`src/agent/nodes.py`
3. 抓取层没有真正的 circuit breaker
4. 网页抓取仍依赖 `duckduckgo-search + trafilatura + BeautifulSoup`
5. embedding / reranker 仍是本地 `sentence-transformers + CrossEncoder`
6. `marker-pdf` / 多模态解析仍在主流程里同步执行

---

## 3. 总体改造策略

按优先级分三期：

### P0

1. LangGraph checkpoint / resume
2. 抓取层 circuit breaker + provider 健康管理
3. LLM / 抓取失败的显式降级语义

### P1

1. Structured Outputs + Pydantic 强校验
2. embedding / reranker backend 抽象
3. 网页抓取 backend 抽象
4. 重度文档处理异步化入口

### P2

1. 托管抓取后端接入（Jina Reader / Firecrawl）
2. 文档处理微服务化
3. 云端 embedding / reranker 默认化

---

## 4. 工作流 A：抓取层健壮性重构

### 4.1 目标

让 `fetch_sources` 满足：

1. 单个 provider 连续失败时自动熔断
2. 熔断期间不再反复打坏掉的 provider
3. provider 恢复后能自动半开探测
4. 所有失败都转成结构化状态，而不是散乱 warning
5. 网页抓取后端可替换，不绑定本地爬虫链

### 4.2 当前问题

当前做法更像 provider 级 `try/except`，但没有熔断状态机。这意味着：

1. 某 provider 连续失败时，每轮仍会继续打
2. 失败日志很多，但系统不知道“这个 provider 现在不可用”
3. 结果质量在静默下降

### 4.3 目标架构

新增 provider runtime health layer：

1. `closed`：正常调用
2. `open`：熔断，直接跳过
3. `half_open`：允许小流量探测恢复

建议新增模块：

1. `src/agent/core/provider_health.py`
2. `src/agent/core/circuit_breaker.py`

建议数据结构：

```python
@dataclass
class ProviderHealth:
    provider: str
    state: str              # closed | open | half_open
    consecutive_failures: int
    last_failure_ts: float | None
    opened_until_ts: float | None
    last_error: str
```

### 4.4 最小改造点

#### 4.4.1 在抓取入口统一包一层 provider runner

目标文件：

1. `src/agent/plugins/search/default_search.py`
2. `src/ingest/web_fetcher.py`

不要在每个 provider 分支里直接 `try/except`。改成统一的：

1. `run_provider(provider_name, call_fn, query, cfg)`
2. 内部先读 circuit breaker 状态
3. 若 `open`，直接 skip 并 emit event
4. 若调用失败，更新状态
5. 若调用成功，重置 failure count

#### 4.4.2 失败分类细化

当前 `src/agent/core/failure.py` 过于粗。

建议新增维度：

1. `rate_limit`
2. `auth_forbidden`
3. `temporary_server`
4. `not_found`
5. `parse_failed`
6. `anti_bot`
7. `network_unreachable`

再映射到动作：

1. `retry`
2. `backoff`
3. `skip`
4. `open_circuit`
5. `abort`

#### 4.4.3 provider 状态持久化

不能只放内存，否则进程重启就忘了。

建议先用 SQLite。

建议新增表：

```sql
CREATE TABLE IF NOT EXISTS provider_health (
  provider TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  consecutive_failures INTEGER NOT NULL,
  last_failure_ts REAL,
  opened_until_ts REAL,
  last_error TEXT
);
```

### 4.5 网页抓取后端抽象

当前网页抓取逻辑分散在：

1. DuckDuckGo 搜索
2. HTML fetch
3. `trafilatura`
4. `BeautifulSoup`

建议抽象接口：

```python
class WebFetchBackend(Protocol):
    def search(self, query: str, max_results: int, cfg: dict) -> list[WebResult]: ...
    def fetch(self, url: str, cfg: dict) -> FetchedPage: ...
```

实现后端：

1. `local_scraper`
2. `jina_reader`
3. `firecrawl`

调度逻辑：

1. 优先托管后端
2. 托管失败再回退本地 scraper
3. 本地 scraper 再失败就 metadata-only

### 4.6 配置设计

建议在 `configs/agent.yaml` 增加：

```yaml
providers:
  search:
    circuit_breaker:
      enabled: true
      failure_threshold: 3
      open_ttl_sec: 600
      half_open_probe_after_sec: 300

  web_fetch:
    backend: local_scraper
    fallback_backend: local_scraper
    metadata_only_on_failure: true
```

### 4.7 验收标准

1. OpenAlex 连续失败 N 次后进入 `open`
2. `open` 状态期间不再重复请求
3. 到 TTL 后只允许一次 probe
4. provider failure 不导致整条 `fetch_sources` 失败
5. `events.log` 可明确看出 provider 被熔断/恢复

---

## 5. 工作流 B：LangGraph 可恢复性与强契约

### 5.1 目标

让长流程具备：

1. 节点级 checkpoint
2. 从失败节点恢复
3. 关键节点输出强 schema
4. parse 失败时可重试或降级，而不是静默坏数据扩散

### 5.2 当前问题

当前 `src/agent/graph.py` 直接 `graph.compile()`，没有 checkpointer。  
节点 JSON 解析主要靠 `src/agent/nodes.py:_parse_json()`，不是强约束。

### 5.3 Checkpoint 设计

#### 5.3.1 第一阶段：SQLite checkpointer

建议先接 SQLite，最小成本。

目标文件：

1. `src/agent/graph.py`
2. `src/agent/core/checkpointing.py`

实现方向：

1. 由配置决定是否启用
2. run_id 作为 thread_id / session key
3. 每个节点结束后自动快照 state

建议配置：

```yaml
agent:
  checkpointing:
    enabled: true
    backend: sqlite
    sqlite_path: ${project.data_dir}/runtime/langgraph_checkpoints.sqlite
```

#### 5.3.2 第二阶段：resume CLI

新增恢复入口：

1. `scripts/resume_run.py`
2. 或主 CLI 支持 `--resume-run-id <id>`

恢复语义：

1. 从最后成功节点继续
2. 如果 state 已到 `generate_report`，不重复前面步骤
3. 如果停在 `await_experiment_results=True`，恢复时保持 pause 语义

### 5.4 强 schema 输出

#### 5.4.1 关键节点优先

先改这几个：

1. `plan_research`
2. `recommend_experiments`
3. `evaluate_progress`
4. `analyze_sources`
5. `synthesize`

#### 5.4.2 用 Pydantic 定义节点输出

建议新增：

1. `src/agent/core/output_models.py`

例如：

```python
class PlanResearchOutput(BaseModel):
    research_questions: list[str]
    search_queries: list[str]
    scope: dict
    budget: dict
```

#### 5.4.3 LLM 输出约束策略

当前 `call_llm()` 只返回字符串。

建议下一步改成支持：

1. `schema`
2. `response_format`
3. `strict_json`

接口方向：

```python
def call_llm(..., schema: type[BaseModel] | None = None, strict_json: bool = False) -> Any:
```

执行顺序：

1. provider 若支持 native structured output，直接走 schema
2. 否则要求 JSON mode
3. 仍失败则走 repair parse
4. repair 仍失败再节点级 fallback

### 5.5 节点失败恢复策略

为节点定义明确恢复策略：

1. `plan_research`：可重试 1 次
2. `fetch_sources`：部分失败可继续
3. `index_sources`：索引失败可保留旧索引并标记 partial
4. `analyze_sources`：单条 source 分析失败可 skip
5. `synthesize`：失败可重试或回退到 extractive synthesis
6. `generate_report`：失败可重试 1 次，或退化成 minimal report

### 5.6 事件与调试增强

建议补充事件类型：

1. `checkpoint_saved`
2. `checkpoint_loaded`
3. `provider_circuit_opened`
4. `provider_circuit_half_open`
5. `provider_circuit_closed`
6. `llm_schema_validation_failed`
7. `node_degraded`

### 5.7 验收标准

1. 第 3 轮 `analyze_sources` 崩溃后可从该节点恢复
2. 节点级输出不再依赖宽松 markdown-json 提取
3. schema 校验失败会留下结构化错误事件
4. 同一 run 重启后不需要从头抓取和分析

---

## 6. 工作流 C：依赖与运行环境轻量化

### 6.1 目标

让系统具备：

1. embedding backend 可切换
2. reranker backend 可切换
3. marker / 多模态链可异步执行
4. 非 GPU / 普通笔记本能以“降级模式”可用

### 6.2 当前问题

当前重依赖包括：

1. `chromadb`
2. `sentence-transformers`
3. `CrossEncoder`
4. `marker-pdf`
5. `TexSoup`
6. `pymupdf`

其中最重的运行链是：

1. embedding
2. reranker
3. marker
4. figure/VLM 处理

### 6.3 embedding backend 抽象

当前 `src/rag/embeddings.py` 直接绑定 `SentenceTransformer`。

建议改成 backend 模式：

1. `local_st`
2. `openai_embedding`
3. `gemini_embedding`
4. `disabled`

建议新增：

1. `src/rag/embedding_backends.py`

配置：

```yaml
retrieval:
  embedding_backend: local_st
  embedding_model: all-MiniLM-L6-v2
  remote_embedding_model: text-embedding-3-small
```

### 6.4 reranker backend 抽象

当前 reranker 在 `src/rag/retriever.py` 直接本地 `CrossEncoder`。

建议支持：

1. `local_crossencoder`
2. `remote_reranker`
3. `disabled`

配置：

```yaml
retrieval:
  reranker_backend: local_crossencoder
  reranker_model: BAAI/bge-reranker-v2-m3
```

### 6.5 marker / 多模态异步化

#### 6.5.1 第一阶段：任务队列式异步

不必一开始就微服务，先做本地 job queue。

思路：

1. `index_pdfs()` 发现 `marker` 或 figure pipeline 很重时，不同步死等
2. 写入一个 ingestion job
3. 主流程可先入轻量 text index
4. 多模态 enrichment 完成后增量补索引

建议新增：

1. `src/ingest/jobs.py`
2. `src/ingest/job_runner.py`

job 类型：

1. `pdf_text_extract`
2. `latex_parse`
3. `figure_extract`
4. `vlm_caption`

#### 6.5.2 第二阶段：微服务化

后续再拆：

1. `doc-parse-service`
2. `figure-caption-service`

但这不是 P0。

### 6.6 运行模式设计

建议明确三种模式：

#### `lite`

1. `pymupdf_only`
2. `embedding_backend=remote`
3. `reranker_backend=disabled`
4. `figure.enabled=false`

#### `standard`

1. `auto`
2. `embedding_backend=local_st`
3. `reranker_backend=local_crossencoder`
4. `figure.enabled=true`

#### `heavy`

1. `marker`
2. `figure.enabled=true`
3. `vlm` 启用
4. reranker 启用

这样能避免所有用户默认都跑最重路径。

---

## 7. 文件级实施清单

### 7.1 P0 必改

1. `src/agent/graph.py`
   - 接 checkpointer
   - 支持 resume
2. `src/agent/nodes.py`
   - 关键节点输出 schema 化
   - 节点级 degrade 策略
3. `src/agent/plugins/search/default_search.py`
   - provider runner + circuit breaker
4. `src/ingest/web_fetcher.py`
   - 失败分类与 backend 抽象接入
5. `src/agent/core/failure.py`
   - 扩展失败语义
6. `src/agent/core/events.py`
   - 新增 checkpoint/provider health 事件

### 7.2 P1 建议改

1. `src/agent/providers/llm_provider.py`
   - 支持 schema / strict_json
2. `src/rag/embeddings.py`
   - backend 抽象
3. `src/rag/retriever.py`
   - reranker backend 抽象
4. `src/ingest/pdf_loader.py`
   - 与 async job 体系对接
5. `src/workflows/traditional_rag.py`
   - 支持异步 enrichment 流

### 7.3 新增模块建议

1. `src/agent/core/circuit_breaker.py`
2. `src/agent/core/provider_health.py`
3. `src/agent/core/checkpointing.py`
4. `src/agent/core/output_models.py`
5. `src/rag/embedding_backends.py`
6. `src/rag/reranker_backends.py`
7. `src/ingest/jobs.py`
8. `src/ingest/job_runner.py`

---

## 8. 测试与回归计划

### 8.1 抓取层

新增测试：

1. provider 连续失败后熔断
2. 熔断期内不再请求
3. TTL 后 half-open probe
4. 单 provider 故障不影响其他 provider 返回结果

建议文件：

1. `tests/test_provider_circuit_breaker.py`
2. `tests/test_search_degrade.py`

### 8.2 LangGraph 恢复

新增测试：

1. 节点失败后 checkpoint 存在
2. 重新启动后从断点恢复
3. `await_experiment_results` 状态恢复正确

建议文件：

1. `tests/test_graph_checkpointing.py`
2. `tests/test_graph_resume.py`

### 8.3 Structured Outputs

新增测试：

1. 合法 JSON 能过 schema
2. markdown fence JSON 能修复
3. 不合法输出会触发 fallback / error event

建议文件：

1. `tests/test_llm_structured_outputs.py`

### 8.4 轻量模式

新增测试：

1. `lite` 模式下不加载本地 ST
2. `lite` 模式下不调用 marker / VLM
3. 仍能完成最小 report 生成

建议文件：

1. `tests/test_runtime_modes.py`

---

## 9. 推荐实施顺序

### 第 1 轮

1. checkpointer
2. provider circuit breaker
3. 失败事件标准化

目标：

1. 先解决“重跑成本高”和“抓取抖动大”

### 第 2 轮

1. 关键节点 schema 化
2. strict_json / response schema 支持
3. 节点级 degrade 策略

目标：

1. 解决“LLM 输出不稳导致下游坏状态传播”

### 第 3 轮

1. embedding backend 抽象
2. reranker backend 抽象
3. runtime mode 配置

目标：

1. 解决“环境过重”和“部署选择少”

### 第 4 轮

1. 异步 ingest job
2. 网页抓取托管后端
3. 文档处理服务化

目标：

1. 进一步把重操作从主流程剥离

---

## 10. 风险与注意事项

1. checkpointer 引入后，state 体积会显著增加  
   处理办法：对大字段做裁剪或只存必要快照
2. circuit breaker 如果阈值太激进，可能误熔断  
   处理办法：区分 `429/5xx` 与 `403/404`
3. schema 强约束会暴露原来被宽松解析掩盖的问题  
   这是好事，但要预留 repair/fallback
4. embedding 云端化会引入额外 API 成本  
   所以必须保留 backend 可切换
5. 异步 ingest 会让“索引完成”语义变复杂  
   要定义清楚：
   - `text_ready`
   - `multimodal_ready`
   - `fully_indexed`

---

## 11. 最终落地标准

完成这份指南后，系统应满足：

1. 任意 provider 短时故障，不会拖死整轮 fetch
2. 任意节点崩溃后，可从最近 checkpoint 恢复
3. 关键节点不再依赖宽松 JSON 提取
4. 普通笔记本可通过 `lite` 模式跑通全流程
5. 多模态 enrichment 可独立降级，不阻塞主报告产出

---

## 12. 下一步建议

建议直接按这个顺序开始改：

1. 先做 checkpointing
2. 再做抓取层 circuit breaker
3. 然后做 Structured Outputs
4. 最后处理依赖解耦和异步化

建议下一轮实施内容：

1. LangGraph checkpoint/resume
2. provider circuit breaker
3. 对应测试骨架
