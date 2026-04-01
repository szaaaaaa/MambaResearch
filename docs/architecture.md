# ResearchAgent 项目架构文档

> 面向新工程师的完整项目导读，帮助你快速理解系统全貌。

---

## 一、项目是什么

ResearchAgent 是一个**自主学术研究代理系统**。用户输入一个研究主题，系统会自动完成：

1. 分解研究问题
2. 检索论文
3. 提取笔记、构建证据图谱
4. 设计并运行实验
5. 生成带引用的 LaTeX 研究报告
6. 自动审稿

核心理念：**LLM 驱动的 DAG 动态规划 + 多角色协作 + 可扩展技能系统**。

---

## 二、你应该按什么顺序看代码

### 第一步：理解数据模型（30 分钟）

这些是全系统的基石，所有模块都依赖它们：

| 顺序 | 文件 | 看什么 |
|------|------|--------|
| 1 | `src/dynamic_os/contracts/route_plan.py` | RoutePlan / PlanNode / PlanEdge — 理解执行图长什么样 |
| 2 | `src/dynamic_os/contracts/artifact.py` | ArtifactRecord — 理解系统中流转的"数据"是什么 |
| 3 | `src/dynamic_os/contracts/skill_io.py` | SkillContext / SkillOutput — 技能的输入输出接口 |
| 4 | `src/dynamic_os/contracts/observation.py` | Observation — 节点执行后的反馈 |
| 5 | `src/dynamic_os/contracts/policy.py` | BudgetPolicy / PermissionPolicy — 安全约束 |

### 第二步：理解主流程（1 小时）

沿着执行路径走一遍：

| 顺序 | 文件 | 看什么 |
|------|------|--------|
| 6 | `src/dynamic_os/runtime.py` | `DynamicResearchRuntime.run()` — 入口，串联所有组件 |
| 7 | `src/dynamic_os/planner/planner.py` | `Planner.plan()` — 如何生成执行计划 |
| 8 | `src/dynamic_os/executor/executor.py` | `Executor.run()` + `execute_plan()` — 如何执行 DAG |
| 9 | `src/dynamic_os/executor/node_runner.py` | `NodeRunner.run_node()` — 单个节点怎么跑 |

### 第三步：理解支撑系统（按需）

| 文件 | 看什么 |
|------|--------|
| `src/dynamic_os/planner/routing.py` | 角色路由策略 — 怎么决定用哪些角色 |
| `src/dynamic_os/planner/prompts.py` | 给 LLM 的规划提示词 |
| `src/dynamic_os/policy/engine.py` | 预算和权限的运行时检查 |
| `src/dynamic_os/tools/backends.py` | LLM 调用的适配器（OpenAI/Gemini/OpenRouter 等） |
| `src/dynamic_os/tools/discovery.py` | MCP 服务器发现和启动 |
| `src/dynamic_os/skills/registry.py` | 技能的自动发现和加载 |
| `src/dynamic_os/roles/registry.py` | 角色的加载和校验 |
| `src/dynamic_os/storage/` | 存储层（内存 / SQLite / 知识图谱） |

### 第四步：看一个具体技能的实现

挑 `src/dynamic_os/skills/builtins/search_papers/` 看三个文件：
- `skill.yaml` — 元数据声明
- `skill.md` — 文档
- `run.py` — `async def run(ctx: SkillContext) -> SkillOutput`

理解完一个，其他 17 个技能结构完全一样。

---

## 三、系统架构总览

```
┌─────────────────────────────────────────────────────────┐
│                      Frontend (React)                    │
│   RunTab / HistoryTab / RouteGraph / BehaviorTimeline   │
│                    ↕ SSE + REST API                      │
├─────────────────────────────────────────────────────────┤
│                    FastAPI Server                         │
│   app.py → routes/runs.py / config.py / models.py       │
├─────────────────────────────────────────────────────────┤
│              DynamicResearchRuntime                       │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐        │
│  │ Planner  │→│ Executor  │→│  NodeRunner     │        │
│  │(LLM生成  │  │(DAG拓扑  │  │(单节点执行     │        │
│  │RoutePlan)│  │排序执行)  │  │ 调用Skill)     │        │
│  └──────────┘  └──────────┘  └───────┬────────┘        │
│       ↕              ↕               ↕                   │
│  ┌─────────┐  ┌───────────┐  ┌──────────────┐          │
│  │RoleReg  │  │PolicyEngine│  │ ToolGateway  │          │
│  │SkillReg │  │(预算+权限) │  │(LLM/搜索/执行)│          │
│  └─────────┘  └───────────┘  └──────┬───────┘          │
│                                      ↕                   │
│                              ┌──────────────┐            │
│                              │  MCP Servers  │            │
│                              │(llm/search/   │            │
│                              │ retrieval/exec)│            │
│                              └──────────────┘            │
├─────────────────────────────────────────────────────────┤
│                      Storage                             │
│   InMemory / SQLite / KnowledgeGraph / UserMemory       │
└─────────────────────────────────────────────────────────┘
```

---

## 四、核心执行流程

```
用户输入研究主题
    │
    ▼
runtime.run()
    │
    ├─ 1. 加载配置 (configs/agent.yaml + .env)
    ├─ 2. 初始化存储 (内存模式 或 SQLite+知识图谱)
    ├─ 3. 加载角色注册表 (roles.yaml)
    ├─ 4. 发现并加载技能 (builtins/ + skills/ + evolved_skills/)
    ├─ 5. 启动 MCP 工具服务 (5 个 stdio 进程)
    ├─ 6. 创建 PolicyEngine / ToolGateway / Planner / NodeRunner
    ├─ 7. 创建 Executor
    │
    └─ Executor.run() 主循环:
         │
         while not terminated:
         │
         ├─ Planner.plan()
         │   ├─ _route_roles() → LLM 决定启用哪些角色
         │   └─ _generate_plan() → LLM 生成 RoutePlan (DAG)
         │
         ├─ execute_plan()
         │   └─ 拓扑排序 → 并行执行就绪节点:
         │       │
         │       NodeRunner.run_node()
         │       ├─ 解析输入 artifact 引用
         │       ├─ 选择技能
         │       ├─ PolicyEngine 检查权限
         │       ├─ 调用 skill.run(SkillContext)
         │       │   └─ 技能通过 ToolGateway 使用工具
         │       ├─ 保存输出 artifact
         │       └─ 生成 Observation
         │
         ├─ 检查: 是否产生了最终 artifact? → 终止
         └─ 检查: 是否需要重新规划? → 继续循环

    完成后:
    ├─ 编译 LaTeX 报告
    ├─ 构建参考文献
    ├─ 保存运行状态
    └─ 返回 DynamicRunResult
```

---

## 五、七个角色

| RoleId | 职责 | 典型技能 | 输出 Artifact |
|--------|------|---------|--------------|
| `conductor` | 总指挥，分解研究问题 | plan_research, create_skill | TopicBrief, SearchPlan |
| `researcher` | 检索论文 | search_papers, fetch_fulltext | SourceSet |
| `experimenter` | 设计和运行实验 | design_experiment, run_experiment, optimize_experiment | ExperimentPlan, ExperimentResults |
| `analyst` | 分析和综合 | extract_notes, build_evidence_map, analyze_trends, compare_methods | PaperNotes, EvidenceMap, TrendAnalysis |
| `writer` | 撰写报告 | draft_report, generate_figures | ResearchReport (**终态**) |
| `reviewer` | 审稿 | review_artifact | ReviewVerdict (**终态**) |
| `hitl` | 人类介入节点 | 无 | UserGuidance |

角色定义在 `src/dynamic_os/roles/roles.yaml`，每个角色有 system_prompt、允许的技能列表、输入/输出 artifact 类型。

---

## 六、18 个内置技能

每个技能是 `src/dynamic_os/skills/builtins/` 下的一个目录，包含三个文件：

| 技能 | 所属角色 | 功能 |
|------|---------|------|
| `plan_research` | conductor | 将用户请求分解为 TopicBrief + SearchPlan |
| `create_skill` | conductor | 动态创建新技能 |
| `search_papers` | researcher | 从 arXiv/Semantic Scholar 等检索论文 |
| `fetch_fulltext` | researcher | 下载并解析 PDF 全文 |
| `extract_notes` | analyst | 从论文中提取结构化笔记 |
| `build_evidence_map` | analyst | 构建证据图谱（主张↔来源） |
| `compare_methods` | analyst | 对比不同方法 |
| `analyze_trends` | analyst | 趋势分析 |
| `analyze_metrics` | analyst | 实验指标分析 |
| `design_experiment` | experimenter | 设计实验方案 |
| `run_experiment` | experimenter | 在沙箱中运行实验代码 |
| `optimize_experiment` | experimenter | 超参调优 |
| `optimize_skill` | conductor | 基于反馈优化已有技能 |
| `draft_report` | writer | 生成 LaTeX 研究报告 |
| `generate_figures` | writer | 生成可视化图表 |
| `review_artifact` | reviewer | 审查报告质量 |
| `reflect_on_failure` | analyst | 分析失败原因并提出改进 |

---

## 七、数据流：Artifact 传递链

```
用户请求
  │
  ▼
[conductor] plan_research
  ├─ TopicBrief
  └─ SearchPlan
       │
       ▼
[researcher] search_papers → SourceSet
       │
       ▼
[analyst] extract_notes → PaperNotes
       ├─ build_evidence_map → EvidenceMap
       └─ analyze_trends → TrendAnalysis
       │
       ▼
[experimenter] (如需要)
       ├─ design_experiment → ExperimentPlan
       ├─ run_experiment → ExperimentResults
       └─ optimize_experiment → ExperimentIteration
       │
       ▼
[writer] draft_report → ResearchReport ← 终态触发结束
       │
       ▼
[reviewer] review_artifact → ReviewVerdict ← 终态触发结束
```

每个 Artifact 通过 `artifact:Type:id` 格式引用，在节点间传递。

---

## 八、目录结构速查

```
ResearchAgent/
├── app.py                          # FastAPI 入口，启动后端服务
├── configs/
│   └── agent.yaml                  # 主配置（LLM/搜索/预算/MCP 服务器）
├── frontend/src/
│   ├── App.tsx                     # React 根组件
│   ├── store.tsx                   # 全局状态管理 (Context API)
│   ├── types.ts                    # TypeScript 类型定义
│   ├── components/
│   │   ├── Sidebar.tsx             # 侧边栏（对话列表）
│   │   ├── tabs/RunTab.tsx         # 研究执行主界面
│   │   ├── tabs/HistoryTab.tsx     # 历史记录
│   │   ├── RouteGraph.tsx          # DAG 可视化
│   │   ├── BehaviorTimeline.tsx    # 执行时间线
│   │   ├── HitlModal.tsx           # 人类介入弹窗
│   │   └── settings/              # 设置面板（10 个分区）
│   └── ...
├── src/
│   ├── server/
│   │   ├── routes/runs.py          # /api/runs — 运行管理 + SSE 流
│   │   ├── routes/config.py        # /config — 配置管理
│   │   ├── routes/models.py        # /models — 模型列表
│   │   └── settings.py             # 服务端常量
│   ├── dynamic_os/
│   │   ├── contracts/              # ★ 数据模型（Pydantic, frozen）
│   │   │   ├── route_plan.py       #   RoutePlan / PlanNode / PlanEdge / RoleId
│   │   │   ├── artifact.py         #   ArtifactRecord
│   │   │   ├── skill_io.py         #   SkillContext / SkillOutput
│   │   │   ├── observation.py      #   Observation / NodeStatus
│   │   │   ├── events.py           #   所有事件类型
│   │   │   ├── policy.py           #   BudgetPolicy / PermissionPolicy
│   │   │   ├── role_spec.py        #   RoleSpec
│   │   │   └── skill_spec.py       #   SkillSpec / SkillInputContract
│   │   ├── runtime.py              # ★ 主运行时（入口 + 生命周期管理）
│   │   ├── artifact_refs.py        # ★ Artifact 引用系统
│   │   ├── planner/
│   │   │   ├── planner.py          # ★ DAG 规划器（LLM 生成执行图）
│   │   │   ├── routing.py          # ★ 角色路由策略
│   │   │   ├── prompts.py          #   规划提示词
│   │   │   └── meta_skills.py      #   元技能（审稿/重规划/终止判断）
│   │   ├── executor/
│   │   │   ├── executor.py         # ★ DAG 执行循环
│   │   │   └── node_runner.py      # ★ 单节点执行器
│   │   ├── policy/
│   │   │   └── engine.py           #   PolicyEngine（预算+权限）
│   │   ├── tools/
│   │   │   ├── backends.py         #   LLM 客户端适配器
│   │   │   ├── discovery.py        #   MCP 服务器发现
│   │   │   ├── registry.py         #   工具注册表
│   │   │   └── gateway/            #   工具网关（统一接口）
│   │   │       ├── __init__.py     #     ToolGateway 主类
│   │   │       ├── mcp.py          #     MCP 协议客户端
│   │   │       ├── llm.py          #     LLM 调用
│   │   │       ├── search.py       #     搜索
│   │   │       ├── retrieval.py    #     检索
│   │   │       ├── exec.py         #     代码执行
│   │   │       └── filesystem.py   #     文件系统
│   │   ├── roles/
│   │   │   ├── registry.py         #   角色注册表
│   │   │   └── roles.yaml          #   7 个角色的定义
│   │   ├── skills/
│   │   │   ├── registry.py         #   技能注册表
│   │   │   ├── loader.py           #   技能动态加载
│   │   │   ├── discovery.py        #   技能包发现
│   │   │   └── builtins/           #   18 个内置技能
│   │   │       ├── search_papers/  #     每个技能一个目录
│   │   │       │   ├── skill.yaml  #       元数据
│   │   │       │   ├── skill.md    #       文档
│   │   │       │   └── run.py      #       实现
│   │   │       └── ...
│   │   ├── storage/
│   │   │   ├── memory.py           #   内存存储（Artifact/Observation/Plan）
│   │   │   ├── sqlite_store.py     #   SQLite 持久存储
│   │   │   ├── knowledge_graph.py  #   知识图谱（SQLite 实现）
│   │   │   ├── user_memory.py      #   跨运行用户记忆
│   │   │   └── skill_metrics.py    #   技能性能追踪
│   │   └── experiment/
│   │       ├── workspace.py        #   实验工作空间管理
│   │       └── templates/          #   实验代码模板
│   ├── ingest/                     # PDF/论文摄入管线
│   │   ├── pdf_loader.py           #   PDF 解析
│   │   ├── pdf_indexing.py         #   PDF 索引编排
│   │   ├── chunking.py             #   文本分块
│   │   ├── faiss_indexer.py        #   FAISS 向量索引
│   │   ├── fetchers.py             #   论文源抓取（arXiv 等）
│   │   ├── figure_extractor.py     #   PDF 图片提取
│   │   └── ...
│   ├── retrieval/                  # 向量检索 + 混合搜索
│   │   ├── chroma_retriever.py     #   ChromaDB 检索
│   │   ├── faiss_retriever.py      #   FAISS 检索
│   │   ├── bm25_index.py           #   BM25 稀疏检索
│   │   ├── embeddings.py           #   Embedding 生成
│   │   └── reranker_backends.py    #   重排序模型
│   └── common/                     # 通用工具
│       ├── config_utils.py         #   YAML 加载、模板变量
│       ├── openai_codex.py         #   OpenAI Codex 认证
│       └── ...
├── scripts/
│   ├── dynamic_os_mcp_server.py    # MCP 服务器进程（JSON-RPC via stdio）
│   ├── run_agent.py                # CLI 运行入口
│   └── build_index.py              # 向量索引构建工具
├── tests/                          # 测试
├── skills/                         # 用户自定义技能（运行时填充）
├── evolved_skills/                 # 自动进化的技能（运行时填充）
├── data/                           # 持久数据（论文/索引/元数据）
└── outputs/                        # 生成的报告和产物
```

---

## 九、关键设计模式

### 1. 不可变数据合约
所有 Pydantic 模型用 `frozen=True`，数据一旦创建不可修改，保证系统状态可追溯。

### 2. 事件驱动
每个动作都发射事件（`events.py` 中定义），通过 EventSink 回调推送到前端 SSE 流和日志。

### 3. 策略优先安全
PolicyEngine 在每次工具调用、节点执行前检查预算和权限，超限即抛 `PolicyViolationError`。

### 4. 动态技能发现
技能不硬编码，运行时从 `builtins/`、`skills/`、`evolved_skills/` 三个目录自动发现加载。

### 5. LLM 驱动规划
Planner 不是固定流程，而是用 LLM 根据当前状态动态生成 DAG，支持失败重规划。

### 6. 角色隔离
每个角色有独立的技能白名单和 artifact 类型约束，不会越权。

### 7. Protocol 抽象存储
存储层用 Python Protocol 定义接口，可在内存模式和 SQLite 模式间无缝切换。

### 8. MCP 标准工具协议
工具通过 Model Context Protocol 服务器暴露，统一接口，易于扩展。

---

## 十、配置系统

主配置文件：`configs/agent.yaml`（约 314 行），核心部分：

| 配置段 | 内容 |
|--------|------|
| `providers` | LLM 后端、搜索引擎、检索器配置 |
| `mcp_servers` | 5 个 MCP 服务器定义（llm/search/retrieval/exec/paper_search） |
| `llm` | 默认模型 + 每个角色的专属模型 |
| `retrieval` | Embedding 模型、混合搜索、重排序配置 |
| `academic_sources` | arXiv/Semantic Scholar 等论文源开关 |
| `agent` | 最大迭代数、论文数、查询改写策略、话题过滤 |
| `output` | 输出目录、索引后端、PDF 提取方式 |

环境变量在 `.env` 中配置（API Key 等），通过 `${ENV_VAR}` 在 YAML 中引用。

---

## 十一、如何启动

```bash
# 后端
python app.py              # FastAPI on :8000

# 前端（开发模式）
cd frontend && npm run dev  # Vite on :5173

# CLI 直接运行
python scripts/run_agent.py --topic "你的研究主题"

# Docker
docker-compose up
```

---

## 十二、技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+, FastAPI, Uvicorn, Pydantic v2 |
| 前端 | React 19, TypeScript, Vite, Tailwind CSS |
| LLM | OpenAI / Gemini / OpenRouter / SiliconFlow（通过 MCP） |
| 向量数据库 | ChromaDB / FAISS |
| 元数据存储 | SQLite |
| 知识图谱 | SQLite 实现的 RDF 风格图 |
| 工具协议 | MCP (Model Context Protocol, JSON-RPC via stdio) |
| 论文源 | arXiv API, Semantic Scholar API |
| PDF | PyMuPDF, Marker |
| 报告 | LaTeX + pdflatex |
