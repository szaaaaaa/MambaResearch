
<div align="center">

# MambaResearch

### 动态 DAG 规划的研究 Agent

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![React 19](https://img.shields.io/badge/React-19-61dafb?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

**输入研究主题 → LLM 规划执行 DAG → 文献检索 + 实验代码生成 + 论文撰写 → 输出 LaTeX/PDF**

[快速开始](#快速开始) · [系统架构](#系统架构) · [技能系统](#技能系统) · [API 端点](#api-端点) · [已知局限](#已知局限)

</div>

---

## 这是什么

一个端到端的研究 Agent 项目，特点是**让 LLM 在运行时实时规划执行 DAG**，而不是写死的流水线。

跟典型的 LangChain pipeline 区别在哪：传统 pipeline 在编码时就确定了节点顺序（比如 search → extract → write）；本项目里 planner 每一轮都根据当前已有的 artifacts、最新观察、用户请求重新生成一个 2-4 节点的局部 DAG，节点失败会触发 replan，节点成功会推进到下一段。是否做实验、何时终止、要不要审稿——都是 LLM 看上下文决定。

> 这是一个研究/学习性质的项目，不是 production-ready 工具。下面的"已知局限"那一节如实列了哪些东西不稳。

## 核心机制

**Planner → Executor → Skill → Tool 四层**

```
User Request
    │
    ▼
┌────────────────────────────────────────────────┐
│  Planner (LLM)                                  │
│  • 看 artifacts + observations + user request   │
│  • 输出 RoutePlan (2-4 节点的局部 DAG)          │
│  • 设 terminate=true 时整个 run 收尾            │
└────────────────────┬────────────────────────────┘
                     │ RoutePlan
                     ▼
┌────────────────────────────────────────────────┐
│  Executor                                       │
│  • 拓扑排序 + 节点状态管理                      │
│  • 节点失败 → replan / skip / abort              │
│  • needs_review=true 自动合成 reviewer 子节点   │
└────────────────────┬────────────────────────────┘
                     │
   ┌──────┬──────┬───┴───┬──────┬──────┬──────┐
   ▼      ▼      ▼       ▼      ▼      ▼      ▼
conductor researcher experimenter analyst writer reviewer hitl
   │      │      │       │      │      │      │
   ▼      ▼      ▼       ▼      ▼      ▼      ▼
        Skills (19 builtin + user/evolved)
   │      │      │       │      │      │      │
   ▼      ▼      ▼       ▼      ▼      ▼      ▼
   Tools (MCP servers: llm / search / retrieval / exec / paper_search)
```

**Artifact-based dataflow**：节点之间不直接耦合，靠产物类型契约（pydantic frozen models）连接。新节点声明它消费哪些 artifact 类型、产出哪些类型，runtime 负责按引用 (`artifact:<Type>:<id>`) 解析。

### 决策权分布

| 决策 | 由谁决定 | 机制 |
|------|---------|------|
| 选择角色 + 技能 | **LLM** | Planner system prompt 里给完整 role/skill 注册表 + artifact 状态，让它语义判断 |
| 是否做实验 | **LLM** | RULE 11：检测 query 里"实验/benchmark/对比性能"等信号 |
| 是否需要审稿 | **LLM** | 通过 `needs_review=true` flag 标在 writer 节点上，runtime 自动触发 |
| 何时终止 | **LLM** | Planner 设 `terminate=true` |
| 拓扑顺序 / 失败重规划路径 | 确定性 | DAG 拓扑排序 + 角色限制策略（post-review 时只允许 writer/reviewer/hitl） |
| 预算 / 超时 / 权限 | 确定性 | PolicyEngine 阈值检查 |
| 审稿评分阈值 / 早停参数 | 配置 | `weighted_score >= threshold`、`patience` 等 |

**护栏 vs 智能**：硬编码只兜底安全（预算、权限、契约），所有语义判断交给 LLM。

### 实验闭环

```
design_experiment ──→ run_experiment
        ▲                    │
        │                    ▼
        │           ExperimentResults
        │                    │
        │                    ▼
        │           optimize_experiment
        │                    │
        │           should_continue=true
        └────────────────────┘
                    │
            should_continue=false / 早停
                    ▼
   analyze_metrics 或 aggregate_results
                    │
                    ▼
         generate_figures → draft_report
                                │
                       (writer 可设 needs_review=true)
                                │
                                ▼
                  ReviewVerdict (auto-trigger)
                                │
                       verdict=needs_revision
                                │
                                ▼
                       下一轮 planner 排
                       writer (修订版, needs_review=true)
                       直到 accept 或 max_rewrite_cycles
```

`run_experiment` 在沙箱里跑 LLM 生成的训练脚本（subprocess + workspace 隔离）。失败时区分 `skill_error`（技能本身 bug → 触发 reflect_on_failure → optimize_skill 自进化）vs `workload_error`（LLM 生成的 train.py 出问题 → 触发 optimize_experiment 改写代码后重跑）。

### HITL 澄清

`clarify_intent` 技能（conductor 角色）会判断用户输入是否需要追问。如果不够明确，产出 `ClarificationRequest` artifact，runtime 暂停，前端弹出结构化问答框，用户回答后产出 `ClarificationResponse`，planner 看到这个 artifact 进入下一轮。

非阻塞 HITL（用户可以中途加指导）走另一条路径：HITL 节点产出 `UserGuidance`。

## 技能系统

### 19 个内置技能

| 角色 | 技能 | 主要输入 | 主要输出 |
|------|------|---------|---------|
| **conductor** | `clarify_intent` | (可选) ClarificationResponse | ClarifiedIntent / ClarificationRequest |
| | `plan_research` | — | TopicBrief, SearchPlan |
| **researcher** | `search_papers` | SearchPlan | SourceSet |
| | `fetch_fulltext` | SourceSet | SourceSet (附 retrieved_document) |
| | `extract_notes` | SourceSet | PaperNotes |
| | `build_evidence_map` | PaperNotes, SourceSet | EvidenceMap, GapMap |
| | `analyze_trends` | PaperNotes, SourceSet | TrendAnalysis |
| **experimenter** | `design_experiment` | (可选) EvidenceMap | ExperimentPlan |
| | `run_experiment` | ExperimentPlan | ExperimentResults |
| | `create_skill` | (可选) ReflectionReport | SkillCreation |
| | `optimize_skill` | ReflectionReport | SkillPatch |
| **analyst** | `analyze_metrics` | ExperimentResults | ExperimentAnalysis, PerformanceMetrics |
| | `aggregate_results` | ExperimentResults | ExperimentAnalysis, PerformanceMetrics |
| | `optimize_experiment` | ExperimentResults | ExperimentIteration |
| | `compare_methods` | PaperNotes, EvidenceMap | MethodComparison |
| | `generate_figures` | ExperimentResults / EvidenceMap | FigureSet |
| | `reflect_on_failure` | — | ReflectionReport |
| **writer** | `draft_report` | EvidenceMap, ExperimentAnalysis 等（全部可选） | ResearchReport |
| **reviewer** | `review_artifact` | ResearchReport（auto-trigger 时自动注入） | ReviewVerdict |

每个技能 = 一个目录：`skill.yaml`（契约）+ `run.py`（实现 `async def run(ctx) -> SkillOutput`）+ `skill.md`（文档）。

### 三个技能根目录

启动时按顺序扫描，后注册的同名技能覆盖前者：

1. `src/dynamic_os/skills/builtins/` — 内置 19 个
2. `{workspace}/skills/` — 用户自定义（git 跟踪）
3. `{workspace}/evolved_skills/` — `create_skill` / `optimize_skill` 写到这里（自进化产物）

写完文件就能被发现，不需要重启（`SkillRegistry.refresh()`）。

### 实验模板

`src/dynamic_os/experiment/templates/` 下三个模板：

- **`numpy_minimal/`** — 仅 numpy 的合成线性回归 + SGD/Adam 对比，CPU 几秒内跑完，**默认值**，最适合演示
- **`generic/`** — 注册表架构（datasets/models/metrics 三个 registry），LLM 可往里加新组件后用通用 train.py + evaluate.py 跑
- **`default/`** — 历史遗留的 PyTorch 模板

LLM 拿到模板后改写其中所有可写文件（`mutable_files`），evaluate.py 输出 `METRIC name=value` 行供解析。

## 快速开始

### 本地开发（推荐）

```bash
# 依赖：Python 3.10+ / Node.js 20+ / pdflatex（可选，用于 PDF 输出）

git clone https://github.com/szaaaaaa/MambaResearch.git
cd MambaResearch

pip install -e .
cd frontend && npm ci && cd ..

cp .env.example .env
# 编辑 .env 填入 OPENAI_API_KEY 或 OPENROUTER_API_KEY 等

# 启动两个进程
python app.py                # 后端 → http://127.0.0.1:8010
cd frontend && npm run dev   # 前端 → http://127.0.0.1:3010
```

前端会代理到后端 8010，浏览器打开 `http://127.0.0.1:3010` 即可。

### Docker

`docker-compose.yml` 当前的端口映射 (`8000:8000`) 与代码 (`port=8010`) 不一致，使用前需要改一下其中一个。建议优先用本地开发模式。

### API Key

| 供应商 | 获取地址 | 必需性 |
|--------|---------|------|
| OpenRouter | https://openrouter.ai/keys | 推荐，一个 key 覆盖大多数模型 |
| OpenAI | https://platform.openai.com/api-keys | 用于 embedding 和直接调 GPT |
| Google AI Studio | https://aistudio.google.com/apikey | Gemini 系列（可选） |
| SerpAPI | https://serpapi.com/manage-api-key | 搜索增强（可选，arXiv/SS 不需要） |

至少配一个能调通的 LLM provider 即可启动。

## API 端点

实际在 `src/server/routes/` 下，分四个 router：

### 研究运行 (`runs.py`)

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/run` | 启动研究任务，SSE 流式返回事件 |
| `POST` | `/api/run/stop` | 停止运行中的任务 |
| `GET` | `/api/runs` | 历史运行列表 |
| `GET` | `/api/runs/{id}/state` | 运行状态、route_plan、artifacts |
| `GET` | `/api/runs/{id}/events` | 该 run 全部事件流 |
| `GET` | `/api/runs/{id}/artifacts` | 产物列表 |
| `GET` | `/api/runs/{id}/artifacts/{aid}` | 单个产物详情 |
| `GET` | `/api/runs/{id}/workspace/tree` | 实验工作区文件树（LLM 写入的 train.py 等） |
| `GET` | `/api/runs/{id}/workspace/file` | 读取工作区单个文件（白名单 + 大小限制） |
| `POST` | `/api/runs/{id}/hitl` | 提交人类介入响应 |
| `GET` | `/api/runs/{id}/report.{pdf,tex}` | PDF / LaTeX 输出 |
| `GET` | `/api/runs/{id}/references.bib` | BibTeX |
| `GET` | `/api/runs/{id}/latex.zip` | LaTeX 工程压缩包（可上传 Overleaf） |
| `GET` | `/api/knowledge-graph/{status,nodes}` | 跨 run 累积的知识图谱 |

### 技能管理 (`skills.py`)

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/skills` | 全部已注册技能 + 执行指标 |
| `GET` | `/api/skills/{id}` | 技能详情（含 markdown 文档） |
| `GET` | `/api/skills/metrics` | 全部指标 |
| `DELETE` | `/api/skills/{id}` | 删除（仅允许 evolved 来源的） |

### 配置 (`config.py`)

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET/POST` | `/api/config` | 读/写主配置 |
| `GET/POST` | `/api/credentials` | 凭证状态/保存 |
| `GET/POST` | `/api/codex/{status,login,logout,callback,verify}` | Claude Code (codex CLI) 集成入口 |

### 模型清单 (`models.py`)

`/api/{openai,gemini,openrouter,siliconflow,codex}/models` —— 各 provider 的可用模型列表。

## 已知局限

诚实点列：

- **LLM nondeterminism**：同一个 query 跑两次，planner 可能给出不同 DAG。比如有时排 `analyze_metrics`，有时排 `compare_methods`；有时主动加 reviewer 有时不加。这不是 bug，是 LLM 的特性。`needs_review` flag 把审稿决策从 planner DAG 转成 runtime auto-trigger，部分缓解了相关失败模式。
- **Planner output 校验**：LLM 生成的 RoutePlan JSON 可能违反 schema（ID 不合法、role 不存在、artifact ref 错误等）。当前策略是 LLM 重试一次（用修复 prompt），仍失败则整个 run 失败——之前的"确定性 fallback DAG"已经移除（commit 5665721）。
- **实验沙箱**：`run_experiment` 用 subprocess 隔离，不是容器隔离。生产环境用要再加一层。
- **检索栈**：主路径是 paper_search MCP（arXiv + Semantic Scholar）。本地 chroma 索引存在但只用于已抓全文的二次检索，不是主要召回路径。BM25 + reranker 配置项存在但默认未开。
- **多语言**：retrieval/默认 LLM 调用都偏英文。中文 query 在 `clarify_intent` / `plan_research` 阶段处理，但论文输出主要是英文。
- **Docker**：`docker-compose.yml` 端口与 `app.py` 不匹配，需要手改。
- **GPU 加速**：实验模板默认 CPU，配置里有 GPU passthrough 注释但未实测。
- **测试覆盖**：115 个 pytest 用例覆盖 contracts / executor / planner / 部分 skills。前端不做单元测试，靠 `tsc + npm run build` 通过。

## 项目结构

```
MambaResearch/
├── app.py                          # FastAPI 入口，监听 8010
├── configs/agent.yaml              # 主配置
├── src/
│   ├── dynamic_os/
│   │   ├── runtime.py              # 运行时入口
│   │   ├── planner/                # LLM 规划器 + RoutePlan 校验
│   │   ├── executor/               # DAG 执行器 + NodeRunner + auto-review
│   │   ├── experiment/             # 实验工作区 + 3 个模板
│   │   ├── roles/                  # 7 角色定义
│   │   ├── skills/builtins/        # 19 内置技能
│   │   ├── tools/                  # MCP 工具网关 + 注册表
│   │   ├── contracts/              # 类型契约（frozen pydantic）
│   │   ├── policy/                 # 预算 + 权限 + post-review 限制
│   │   └── storage/                # SQLite + 知识图谱 + 技能指标 + 跨 run 用户记忆
│   └── server/routes/              # API 路由
├── frontend/src/
│   ├── components/
│   │   ├── tabs/{RunTab,HistoryTab,SkillsTab}.tsx
│   │   ├── RouteGraph.tsx          # DAG 可视化
│   │   ├── ExperimentProgress.tsx
│   │   ├── ReviewStatus.tsx
│   │   ├── BehaviorTimeline.tsx
│   │   ├── ClarificationModal.tsx  # HITL 澄清弹窗
│   │   ├── HitlModal.tsx           # 自由 HITL 弹窗
│   │   ├── RawTerminalPanel.tsx
│   │   └── settings/sections/      # 11 个设置分区
│   ├── store.tsx                   # 全局状态
│   └── types.ts
├── scripts/                        # CLI + MCP server + 演示脚本
├── data/outputs/                   # 运行产出
└── tests/                          # pytest 套件 (115 用例)
```

## 配置示例

`configs/agent.yaml` 关键字段：

```yaml
llm:
  role_models:
    conductor:    { provider: openrouter, model: google/gemini-2.0-flash-001 }
    researcher:   { provider: openrouter, model: google/gemini-2.0-flash-001 }
    experimenter: { provider: openrouter, model: google/gemini-2.0-flash-001 }
    analyst:      { provider: openrouter, model: google/gemini-2.0-flash-001 }
    writer:       { provider: openrouter, model: google/gemini-2.0-flash-001 }
    reviewer:     { provider: openrouter, model: google/gemini-2.0-flash-001 }

agent:
  max_iterations: 15              # planner 最大规划轮数
  experiment_plan:
    max_iterations: 6
    workspace:
      template: numpy_minimal     # numpy_minimal / generic / default
      hardware:
        compute: cpu              # cpu / cuda
    stopping:
      patience: 3
      min_improvement: 0.001
  review:
    score_threshold: 6.0          # weighted_score 低于此值 = needs_revision
    max_rewrite_cycles: 2

budget_guard:
  max_tokens: 500000
  max_api_calls: 1000
  max_wall_time_sec: 3600
```

按需把不同角色挂不同模型（reasoning-heavy 用更强的，convert-light 用便宜的）。

## 测试

```bash
pytest tests/                     # 后端 115 用例
cd frontend && npm run lint        # tsc --noEmit
cd frontend && npm run build       # vite production build
```

测试原则（来自 `CLAUDE.md`）：只测"坏了看不见但后果严重"的东西——契约、权限、存储读写、核心执行流恢复、HITL 暂停恢复。不测第三方 API 对接细节、显示层小逻辑、LLM 输出每种纠错场景。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+ / FastAPI / uvicorn / SSE |
| 前端 | React 19 / TypeScript / Vite / Tailwind CSS |
| LLM | OpenRouter / OpenAI / Gemini / SiliconFlow / Codex (Claude Code) |
| 检索 | arXiv + Semantic Scholar via paper_search MCP / 本地 chroma 索引（缓存全文用） |
| 工具通信 | MCP stdio（4 个内置 server：llm / search / retrieval / exec + 第三方 paper_search_mcp） |
| 实验 | subprocess 隔离 / 3 个模板 / `METRIC name=value` 解析 |
| 持久化 | SQLite（artifacts / events / observations）+ 知识图谱 + 技能执行指标 + 跨 run 用户记忆 |
| 输出 | LaTeX (jinja 模板) + BibTeX + pdflatex（可选）|

## 许可证

MIT License

---

<div align="center">
<sub>Built with Claude Code · 这个 README 写的是当前代码实际实现的功能，没有 roadmap / vaporware</sub>
</div>
