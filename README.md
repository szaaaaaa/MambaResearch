
<div align="center">

# MambaResearch

### 动态 DAG 规划的自主研究 Agent

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![React 19](https://img.shields.io/badge/React-19-61dafb?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

**输入研究主题 → LLM 实时规划执行 DAG → 文献检索 + 沙箱实验 + 论文撰写 + 审稿迭代 → 输出可编译 LaTeX/PDF**

[快速开始](#快速开始) · [系统架构](#核心机制) · [技能系统](#技能系统) · [API 端点](#api-端点)

</div>

---

## 这是什么

一个完整覆盖 **文献检索 → 实验设计 → 代码生成 → 沙箱执行 → 指标分析 → 论文撰写 → 审稿评分** 的自主研究 Agent。

跟 LangChain 类的固定 pipeline 区别在于：传统 pipeline 在编码时就锁死了节点顺序（search → extract → write）；本项目让 **Planner 在运行时根据当前 artifacts、最新观察、用户请求实时生成局部 DAG**，节点失败触发 replan，节点成功推进到下一段。是否做实验、何时终止、要不要审稿——全部由 LLM 看上下文决定，硬编码只兜底安全护栏。

## ✨ 核心能力

<table>
<tr>
<td width="50%">

### 🧠 LLM 全权语义决策
Planner 每轮都重新生成 2-4 节点的局部 DAG。角色选择、技能调度、实验触发判断、终止条件——全部交给 LLM 语义判断，不依赖关键词匹配或固定规则。

### 🔬 端到端实验闭环
自动设计实验 → 生成训练代码 → 沙箱执行 → 提取指标 → 优化迭代。支持早停、refine/pivot 策略切换、最佳快照回滚。`numpy_minimal` 模板让 CPU 也能在几秒内跑完合成数据对比。

### 🧬 技能自我演化
失败 → `reflect_on_failure` 反思根因 → `optimize_skill` 生成补丁 → 写入 `evolved_skills/` → 注册表热重载 → 下一轮 planner 直接用进化后的技能重试，全程无需人工介入。

</td>
<td width="50%">

### 🎭 7 角色协作 + 19 内置技能
conductor / researcher / experimenter / analyst / writer / reviewer / hitl 各自独立配置 LLM 模型，按任务动态调度。19 个内置技能覆盖检索、抽取、证据图谱、实验、分析、写作、审稿全链路。

### 📊 多维审稿循环 + 自适应触发
5 维度评分（新颖性 / 可靠性 / 清晰度 / 重要性 / 完整性），不通过自动修订重写直到达标。`needs_review` flag 机制让 reviewer 由 runtime 自动注入而不是 planner 显式排，避免触发约束 replan。

### 📄 学术级输出 + Overleaf 兼容
Jinja LaTeX 模板 + 自动生成 BibTeX 引用，三轮 pdflatex 编译消除引用占位符。一键导出 LaTeX 工程压缩包，可直接上传 Overleaf 替换会议模板。

</td>
</tr>
</table>

## 核心机制

**Planner → Executor → Skill → Tool 四层架构**

```
User Request
    │
    ▼
┌────────────────────────────────────────────────┐
│  Planner (LLM 驱动)                             │
│  • 读取 artifacts + observations + user request │
│  • 输出 RoutePlan：2-4 节点的局部 DAG           │
│  • terminate=true 时整个 run 收尾               │
└────────────────────┬────────────────────────────┘
                     │ RoutePlan
                     ▼
┌────────────────────────────────────────────────┐
│  Executor                                       │
│  • DAG 拓扑排序 + 节点状态机                    │
│  • 节点失败 → replan / skip / abort             │
│  • needs_review=true → 自动合成 reviewer 子节点 │
│  • HITL / 澄清暂停恢复                          │
└────────────────────┬────────────────────────────┘
                     │
   ┌──────┬──────┬───┴───┬──────┬──────┬──────┐
   ▼      ▼      ▼       ▼      ▼      ▼      ▼
conductor researcher experimenter analyst writer reviewer hitl
   │      │      │       │      │      │      │
   ▼      ▼      ▼       ▼      ▼      ▼      ▼
        Skills (19 内置 + 用户自定义 + LLM 进化生成)
   │      │      │       │      │      │      │
   ▼      ▼      ▼       ▼      ▼      ▼      ▼
   Tools (MCP servers: llm / search / retrieval / exec / paper_search)
```

**类型化产物驱动数据流（artifact-based dataflow）**：节点之间不直接耦合，靠产物类型契约（pydantic frozen models）连接。新节点声明它消费哪些类型、产出哪些类型，runtime 按引用 (`artifact:<Type>:<id>`) 自动解析。这种设计让节点 / 技能可任意重组，新增能力不需要改其他代码。

### 决策权分布

| 决策 | 由谁决定 | 机制 |
|------|---------|------|
| 选择角色 + 技能 | **LLM** | Planner 拿到完整 role/skill 注册表 + artifact 状态做语义判断 |
| 是否做实验 | **LLM** | RULE 11 系列规则引导，从 query 语义判断 |
| 是否需要审稿 | **LLM** | `needs_review=true` flag 标在 writer 节点上，runtime 自动触发 |
| 何时终止 | **LLM** | Planner 设 `terminate=true` |
| 拓扑顺序 / 失败重规划路径 | 确定性 | DAG 拓扑排序 + 角色限制策略（post-review 时只允许 writer/reviewer/hitl） |
| 预算 / 超时 / 权限 | 确定性 | PolicyEngine 阈值检查 |
| 审稿评分阈值 / 早停参数 | 配置 | `weighted_score >= threshold`、`patience` 等 |

**护栏 vs 智能**：硬编码只兜底安全（预算、权限、契约），所有语义判断交给 LLM。这种分工让系统既可控又灵活——出 bug 时知道找谁，加能力时不需要改决策逻辑。

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
                       (writer 设 needs_review=true)
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

`run_experiment` 在 subprocess 隔离的工作区执行 LLM 生成的训练脚本。关键设计：**区分错误来源以选择正确的恢复路径**——
- `skill_error`（技能本身 bug）→ 触发 `reflect_on_failure` → `optimize_skill` 自我进化
- `workload_error`（LLM 生成的 train.py 出问题）→ 触发 `optimize_experiment` 改写代码后重跑

这种分类让恢复机制对症下药，避免无意义的反复尝试。

### HITL 澄清

**结构化 vs 自由 HITL 双通道**：
- **结构化澄清**：`clarify_intent` 技能判断用户输入是否需要追问；不够明确就产出 `ClarificationRequest`，runtime 暂停，前端弹出选项式问答框，用户回答后产出 `ClarificationResponse`，planner 看到这个 artifact 进入下一轮
- **自由介入**：用户随时可在 HITL 节点提交 `UserGuidance`，下游节点把它作为额外 artifact 消费

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

每个技能 = 一个目录：`skill.yaml`（契约）+ `run.py`（实现 `async def run(ctx) -> SkillOutput`）+ `skill.md`（文档）。**放入目录即被自动发现**，零配置注册。

### 三层可扩展技能架构

启动时按顺序扫描，后注册的同名技能覆盖前者：

1. `src/dynamic_os/skills/builtins/` — 内置 19 个，覆盖完整研究链路
2. `{workspace}/skills/` — 用户自定义技能（git 跟踪，可团队共享）
3. `{workspace}/evolved_skills/` — `create_skill` / `optimize_skill` 写入此处（LLM 自我进化产物）

**热重载机制**：写完文件就能被发现，不需要重启。这让"运行中失败 → LLM 反思 → 生成新技能 → 立刻可用"的自进化循环成为可能。

### 实验执行模板

`src/dynamic_os/experiment/templates/` 下三套独立模板，按研究场景选择：

- **`numpy_minimal/`** — **默认模板**，仅依赖 numpy，合成数据 + SGD/Adam 对比，CPU 几秒内完成。适合最小可行实验、回归测试、教学演示
- **`generic/`** — **注册表架构模板**，三个 registry（datasets / models / metrics）支持 LLM 动态扩展。LLM 可往里加新 dataset 类、新 model 类、新 metric 类，通用 `train.py` + `evaluate.py` 通过注册表查找组件，6 个文件全部可重写
- **`default/`** — PyTorch 模板，适配真实 GPU 训练任务

LLM 拿到模板后改写其中所有可写文件（`mutable_files`），evaluate.py 输出 `METRIC name=value` 行供 runtime 解析。

## 快速开始

### 本地开发

```bash
# 依赖：Python 3.10+ / Node.js 20+ / pdflatex（可选，用于 PDF 输出）

git clone https://github.com/szaaaaaa/MambaResearch.git
cd MambaResearch

pip install -e .
cd frontend && npm ci && cd ..

cp .env.example .env
# 编辑 .env 填入 OPENAI_API_KEY 或 OPENROUTER_API_KEY 等
cp configs/agent.example.yaml configs/agent.yaml
# configs/agent.yaml 是本地配置，前端设置页会写这个文件

# 启动两个进程
python app.py                # 后端 → http://127.0.0.1:8010
cd frontend && npm run dev   # 前端 → http://127.0.0.1:3010
```

浏览器打开 `http://127.0.0.1:3010`，前端会代理到后端 8010。

### API Key 获取

| 供应商 | 获取地址 | 说明 |
|--------|---------|------|
| OpenRouter | https://openrouter.ai/keys | **推荐**，一个 key 覆盖大多数主流模型 |
| OpenAI | https://platform.openai.com/api-keys | 用于 embedding 和直接调 GPT |
| Google AI Studio | https://aistudio.google.com/apikey | Gemini 系列（可选） |
| SerpAPI | https://serpapi.com/manage-api-key | 搜索增强（可选，arXiv/SS 检索不依赖） |

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
| `GET` | `/api/knowledge-graph/{status,nodes}` | 跨 run 累积的研究知识图谱 |

### 技能管理 (`skills.py`)

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/skills` | 全部已注册技能 + 执行指标 |
| `GET` | `/api/skills/{id}` | 技能详情（含 markdown 文档） |
| `GET` | `/api/skills/metrics` | 全部指标 |
| `DELETE` | `/api/skills/{id}` | 删除（仅允许 evolved 来源的技能） |

### 配置 (`config.py`)

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET/POST` | `/api/config` | 读/写主配置 |
| `GET/POST` | `/api/credentials` | 凭证状态/保存 |
| `GET/POST` | `/api/codex/{status,login,logout,callback,verify}` | Claude Code (codex CLI) 集成入口 |

### 模型清单 (`models.py`)

`/api/{openai,gemini,openrouter,siliconflow,codex}/models` —— 各 provider 的可用模型列表。

## 项目结构

```
MambaResearch/
├── app.py                          # FastAPI 入口（端口 8010）
├── configs/agent.example.yaml      # 配置模板；复制为本地 configs/agent.yaml
├── src/
│   ├── dynamic_os/
│   │   ├── runtime.py              # 运行时入口
│   │   ├── planner/                # LLM 规划器 + RoutePlan 校验 + 修复重试
│   │   ├── executor/               # DAG 执行器 + NodeRunner + auto-review
│   │   ├── experiment/             # 实验工作区 + 3 套模板
│   │   ├── roles/                  # 7 角色定义
│   │   ├── skills/builtins/        # 19 个内置技能
│   │   ├── tools/                  # MCP 工具网关 + 自动发现 + 注册表
│   │   ├── contracts/              # 类型契约（frozen pydantic）
│   │   ├── policy/                 # 预算 + 权限 + post-review 角色限制
│   │   └── storage/                # SQLite + 知识图谱 + 技能指标 + 跨 run 用户记忆
│   └── server/routes/              # API（runs / skills / config / models）
├── frontend/src/
│   ├── components/
│   │   ├── tabs/{RunTab,HistoryTab,SkillsTab}.tsx
│   │   ├── RouteGraph.tsx          # 动态 DAG 可视化
│   │   ├── ExperimentProgress.tsx  # 实验迭代进度面板
│   │   ├── ReviewStatus.tsx        # 审稿评分面板
│   │   ├── BehaviorTimeline.tsx    # 事件时间线
│   │   ├── ClarificationModal.tsx  # 结构化澄清弹窗
│   │   ├── HitlModal.tsx           # 自由 HITL 弹窗
│   │   ├── RawTerminalPanel.tsx    # 原始终端输出
│   │   └── settings/sections/      # 11 个设置分区
│   ├── store.tsx                   # 全局状态
│   └── types.ts
├── scripts/                        # CLI + MCP server + 演示脚本
├── data/outputs/                   # 运行产出（PDF / LaTeX / BibTeX）
└── tests/                          # pytest 套件 (115 用例)
```

## 推荐配置

### 角色模型差异化（榨干性价比）

```yaml
llm:
  role_models:
    conductor:    { provider: openrouter, model: google/gemini-2.0-flash-001 }    # 协调用便宜的
    researcher:   { provider: openrouter, model: google/gemini-3-pro-preview }    # 检索抽取要准
    experimenter: { provider: openrouter, model: google/gemini-2.0-flash-001 }    # 代码生成够用
    analyst:      { provider: openrouter, model: google/gemini-3-pro-preview }    # 数据分析要稳
    writer:       { provider: openrouter, model: openai/gpt-5.5 }                 # 写作给最强
    reviewer:     { provider: openrouter, model: google/gemini-3-pro-preview }    # 批判性判断
```

### 实验配置

```yaml
agent:
  max_iterations: 15              # planner 最大规划轮数
  experiment_plan:
    max_iterations: 6             # 单个实验最大迭代轮数
    workspace:
      template: numpy_minimal     # numpy_minimal / generic / default
      hardware:
        compute: cpu              # cpu / cuda
    stopping:
      patience: 3                 # 连续无改进 N 轮后早停
      min_improvement: 0.001
  review:
    score_threshold: 6.0          # weighted_score 低于此值 = needs_revision
    max_rewrite_cycles: 2

budget_guard:
  max_tokens: 500000
  max_api_calls: 1000
  max_wall_time_sec: 3600
```

## 测试

```bash
pytest tests/                      # 后端 115 用例
cd frontend && npm run lint        # tsc --noEmit
cd frontend && npm run build       # vite production build
```

测试原则（来自 `CLAUDE.md`）：只测"坏了看不见但后果严重"的东西——契约校验、权限边界、存储读写一致性、核心执行流恢复、HITL 暂停恢复。不测第三方 API 对接细节、显示层小逻辑、LLM 输出每种纠错场景。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+ / FastAPI / uvicorn / SSE |
| 前端 | React 19 / TypeScript / Vite / Tailwind CSS |
| LLM | OpenRouter / OpenAI / Gemini / SiliconFlow / Claude Code (Codex) |
| 检索 | arXiv + Semantic Scholar via paper_search MCP / 本地 chroma 向量索引（全文缓存）/ 可选 BM25 + reranker |
| 工具通信 | MCP stdio 协议（4 个内置 server：llm / search / retrieval / exec + 第三方 paper_search_mcp） |
| 实验 | subprocess 沙箱隔离 / 3 套模板（numpy / 注册表 / PyTorch）/ `METRIC name=value` 解析 |
| 持久化 | SQLite（artifacts / events / observations）+ 知识图谱 + 技能执行指标 + 跨 run 用户记忆 |
| 输出 | Jinja LaTeX 模板 + 自动 BibTeX + 三轮 pdflatex 编译 |

## 许可证

MIT License

---

<div align="center">
<sub>Built with Claude Code · Dynamic DAG Planning · Self-Evolving Skills</sub>
</div>
