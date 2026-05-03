
<div align="center">


# 🧬 MambaResearch

### 一个建在 Claude Code / Codex CLI 上的研究向 IDE 壳

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![React 19](https://img.shields.io/badge/React-19-61dafb?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

**所有 LLM 出口都走订阅版的 Claude Code / Codex CLI；MambaResearch 自身零 LLM 路由、零 agent runtime、零自建 skill 注册表。**

[快速开始](#-快速开始) · [架构](#-三层架构) · [Sub-agent + Pipeline](#-sub-agent--pipeline-skill) · [配置](#-配置)

---

</div>

## 这是什么

MambaResearch v3 是 Claude Code / Codex 之上的一层 IDE 壳：

- 提供 6 个研究向可视化域（工作台、技能、Agent 角色、4 bucket 文件管理、MCP 功能、情境性 tab）
- **多对话并行**：每条 conversation 绑死一个 backend（Claude 或 Codex），永不切换；不同 backend 的对话在 sidebar 上并列共存
- 跨对话引用通过 `mamba_history` MCP tool 按需取（backend 主动调，懒拉不预 push）
- LLM 智能完全交给已订阅的 Claude Code / Codex CLI
- 自定义研究流程通过 **8 个 sub-agent**（`.claude/agents/*.md`）+ **7 个 pipeline SKILL.md**（`.claude/skills/`）沉淀
- 自定义工具通过 **MCP servers** 接入（`workspace` / `mamba_history` / `zotero` / `colab` / `experiment` / `paper_search`）

> 上一代版本拥有自建 `dynamic_os` 多 agent runtime（21 builtin skill + 7 role + planner + executor + policy + tool gateway），v3.0 完全删除——细节见 [v3.0 release note](docs/releases/v3.0-mamba-as-claude-code-shell.md)。

## 🏗 三层架构

```
┌──────────────────────────────────────────────────────────────┐
│ MambaResearch UI（薄壳，本仓库写的）                         │
│   - 6 个可视化域                                             │
│   - 项目注册表 + 会话编排薄表                                │
│   - 文件分类索引 (.mambaresearch/classification.db)          │
└──────────────────────┬───────────────────────────────────────┘
                       │ 调
                       ▼
┌──────────────────────────────────────────────────────────────┐
│ Claude Code CLI / Codex CLI（订阅引擎，唯一 LLM 出口）       │
│   - Session 存储（CLI JSONL）                                │
│   - Sub-agent 自动发现（.claude/agents/ ↔ .codex/agents/）   │
│   - Pipeline SKILL.md 自动发现（.claude/skills/）            │
│   - MCP 集成 / Slash 命令 / 权限提示 / Bash·Read·Write·Edit  │
└──────────────────────┬───────────────────────────────────────┘
                       │ 调
                       ▼
┌──────────────────────────────────────────────────────────────┐
│ MCP Servers（统一扩展机制）                                  │
│   - workspace.* / zotero.* / colab.* / experiment.*          │
│   - paper_search.*（6 source）                               │
│   - 用户自配的任何标准 MCP server                            │
└──────────────────────────────────────────────────────────────┘
```

## 🎭 8 个 Sub-agent + 7 个 Pipeline SKILL

### Sub-agent（`.claude/agents/*.md`，由 `scripts/sync_subagents.py` 同步到 `.codex/agents/*.toml`）

| Sub-agent | 职责 | 模型档位 |
|---|---|---|
| paper-searcher | arXiv / Semantic Scholar / Google Scholar 多源检索 + 去重 | haiku |
| evidence-extractor | 给定论文集 → 抽取定量结果 / 论据段落 / 图表注记 | haiku |
| analyzer | 比对、归纳、找冲突；可跑实验脚本验证假设 | sonnet |
| writer | 把 analyzer 的结构化发现 + 证据组合成连贯技术文档 | sonnet |
| critic | 关键节点重度评审：找漏洞 / 挑逻辑跳跃 / 判断结论可信度 | opus |
| **conductor** | 接 user request → 拆任务 → 决定调用顺序 + 分配 sub-agent | sonnet |
| **experimenter** | 设计实验 + 调 `experiment.*` MCP 跑本地脚本 + 报告 metric | sonnet |
| **reviewer** | 审 artifact（report / sources / experiment 结果），返 verdict | sonnet |

### Pipeline SKILL.md（`.claude/skills/`，主 agent 看到关键词时自动触发）

| Pipeline | 何时用 | sub-agent 链 |
|---|---|---|
| structured-lit-review | "做综述" | paper-searcher → evidence-extractor → analyzer → writer → critic |
| empirical-study | "做实验" / "复现某方法" | conductor → experimenter (× N iter) → analyzer → writer |
| method-comparison | "对比 A 与 B 方法" | paper-searcher → evidence-extractor → analyzer → writer |
| experiment-iteration | "调优 / 跑 sweep" | experimenter sweep → analyzer → reviewer |
| artifact-review | "审 report / 审 sources" | reviewer → critic |
| idea-brainstorming | "我有个 idea，帮我探讨" | conductor → analyzer → critic |
| data-exploration | "看看这份数据" | conductor → analyzer → writer |

所有 sub-agent 通过 `outputs/<run_id>/` 下的标准文件互通：`plan.md` / `sources.json` / `evidence.json` / `analysis.md` / `report.md` / `review.md` / `critique.md` / `experiments/exp_<NNN>/result.json`。完整命名约定写在 `CLAUDE.md` + `AGENTS.md`。

## 🚀 快速开始

### 前置条件

- Python 3.10+ / Node.js 20+
- 装好至少一个：`claude` CLI（Claude Pro/Max 订阅）或 `codex` CLI（ChatGPT Plus/Pro 订阅）
- 各自完成 OAuth 登录

### 本地开发

```bash
git clone https://github.com/szaaaaaa/MambaResearch.git
cd MambaResearch

pip install -e .
cd frontend && npm ci && cd ..

# 启动
python app.py              # 后端 → http://127.0.0.1:8000
cd frontend && npm run dev  # 前端 → http://localhost:3000
```

启动后流程：Home（项目选择）→ 选 / 建 project → 进入 IDE。

### Codex sub-agent 同步

修改 `.claude/agents/*.md` 后跑：

```bash
python scripts/sync_subagents.py
```

会把 8 个 .md 同步成 `.codex/agents/*.toml`，让 Codex CLI 也能 spawn 同一组 sub-agent。

## 📦 6 个可视化域

| 域 | 做什么 |
|---|---|
| 工作台（Workbench） | Claude / Codex 会话主界面，含 slash 命令、HITL、CLI 切换 |
| 技能 | 列出 `.claude/skills/` 下所有 pipeline SKILL.md |
| Agent 角色 | 占位（后续可扩展为 sub-agent 配置面板） |
| 4 bucket（实验/文献/数据集/灵感） | 项目文件按 LLM 增量分类的 4 个虚拟视图 |
| MCP 功能 | 5 子视图：servers / tools / 调用历史 / sandbox 试调 / 配置编辑 |
| 情境性 tab | VSCode 风格 ephemeral：开 PDF 开文献 tab，跑实验开执行 tab，关掉消失 |

## 🔌 内置 MCP Servers

由 `src/server/integrations/*/mcp_server.py` 通过项目级 `.mcp.json` 暴露给 Claude PTY 子进程 / Codex app-server：

- **workspace.\*** — 文件分类索引读写
- **zotero.\*** — Zotero Web API 客户端
- **colab.\*** — Drive Desktop 元数据 → Colab URL
- **experiment.\*** — 本地 Python 子进程 + metric 流（`outputs/<run_id>/experiments/<exp_id>/result.json`）
- **paper_search.\*** — 6 source（arXiv / Semantic Scholar / OpenAlex / Crossref / DOAJ / IEEE 部分）

## 🧰 项目结构

```
MambaResearch/
├── app.py                          # FastAPI 入口
├── configs/
│   ├── claude_code/providers.json  # Claude Code provider 注册表
│   ├── mcp/env_overrides.json      # MCP 子进程 user 层 env override
│   └── codex/auth.json             # Codex OAuth profile 绑定
├── .claude/
│   ├── agents/                     # 8 个 sub-agent 真相源（.md）
│   └── skills/                     # 7 + 1 个 SKILL.md（pipeline + classify-workspace）
├── .codex/
│   └── agents/                     # 8 个 .toml（由 sync_subagents.py 生成）
├── src/
│   ├── server/
│   │   ├── projects/               # 项目注册表 + active project env
│   │   ├── workspace/              # 分类索引 + workspace MCP
│   │   ├── terminal/               # Claude PTY 桥（pywinpty）+ ANSI strip + turn tee
│   │   ├── claude_code/            # provider 注册表 + 历史 session 存储（GET-only）
│   │   ├── codex/                  # Codex app-server 会话编排（仍走 SDK，下个 plan PTY pivot）
│   │   ├── integrations/           # zotero / colab / experiment MCP servers
│   │   ├── mcp/                    # MCP server registry
│   │   ├── bridge/                 # cross-CLI continues 桥（v3.2 hybrid MT 已撤回）
│   │   └── routes/                 # FastAPI 路由
│   └── common/                     # 共享 utils
├── frontend/src/                   # React 19 + Tailwind + Zustand
└── scripts/
    └── sync_subagents.py           # .md → .toml 同步
```

## ⚙ 配置

枢转后全局 yaml 物理删除，配置按职责拆为 4 个 json 注册表：

| 文件 | 职责 | 编辑入口 |
|---|---|---|
| `configs/claude_code/providers.json` | Claude Code provider（`name → {base_url, api_key_env, default_model}`） | 前端 CLI 视图 / `PATCH /api/cli-providers` |
| `configs/mcp/env_overrides.json` | MCP 子进程 user 层 env override | 前端 MCP 视图 / `PATCH /api/mcp/servers/{name}/env` |
| `configs/codex/auth.json` | Codex OAuth profile 绑定 | 自动维护，需要时手编 |
| `<project>/.mambaresearch/config.json` | 项目级 lazy 配置（`{codex_profile, enabled_mcp_servers}`） | 前端项目视图 / `PATCH /api/project-config` |

MCP server 命令行（`command` / `args`）由 `src/server/integrations/<name>/mcp_server.py` 的 `default_mcp_config()` 硬编码 + `src/server/mcp/registry.py:_read_builtin_helpers()` 注册；UI 只能改 env override，不可改命令行。

API key 等凭证仍在 `.env`，通过设置面板"凭证"段落写入。

## 🔁 自动化开发流程（/pipeline）

用户级 Claude Code skill `/pipeline` 把规划阶段决策集中、执行阶段无人介入地跑完一个多任务 plan。配合升级过的 `/plan` template（新增 Decision points / External preconditions / Failure policy / Subtask split policy 四段），一次规划定案后，`/dev → /review → /fix` 自动循环跑每个 task，失败立即 STOP 暴露根因（不兜底）。

详见 [docs/pipeline-usage.md](docs/pipeline-usage.md)。

## 📚 版本演进

- [v3.0 — MambaResearch as Claude Code / Codex shell](docs/releases/v3.0-mamba-as-claude-code-shell.md)
- [v2.x — multi-subscription（双订阅工作流）](docs/releases/v2.x-multi-subscription.md)
- [v2.x — multi-model（多 provider Workbench）](docs/releases/v2.x-multi-model.md)
- 历史里程碑：v0.1 LangGraph → v0.5 3-agent → v0.9 6-agent → v1.0 dynamic-os（已删除）

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.10+ / FastAPI / uvicorn / SSE |
| 前端 | React 19 / TypeScript / Vite / Tailwind CSS |
| LLM 出口 | Claude Code CLI（Pro/Max 订阅）或 Codex CLI（ChatGPT 订阅） |
| 跨 CLI 桥 | continues v4.0.12 |
| MCP servers | workspace / zotero / colab / experiment / paper_search |
| 持久化 | `~/.mambaresearch/mamba.db` + `<project>/.mambaresearch/*.db` |
| 项目记忆 | `<project>/.mambaresearch/memory/*.md` + `@import` 双侧暴露给 CLAUDE.md / AGENTS.md |

## 许可证

MIT License

---

<div align="center">
<sub>Built as a thin shell on top of Claude Code / Codex CLI</sub>
</div>
