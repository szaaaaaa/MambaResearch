# Skill Invocation

These skills are mandatory when their description matches the current turn — do not skip them.

1. **first-principles-thinking** — every user message
2. **solution-standards** — before proposing any change
3. **implementation-discipline** — before writing or fixing code
4. **session-discipline** — in multi-turn coding sessions

If you find yourself about to write code without having invoked the applicable ones, stop and invoke first.

# 身份与口吻

- 每次回答开头加一句"好的ziang"确认读过本文件
- 回复简洁，不说客套话

# 必须遵守

- 优先简单方案，不过度工程
- 不要加兜底/workaround 掩盖根因，直面问题解决它
- 排查问题尽早暴露，不试图掩盖
- 代码任务开始前，读 `.learnings/LEARNINGS.md` 和 `.learnings/ERRORS.md`（若存在），避免重复已知失误

# 常用命令

- 后端: `python app.py`
- 前端开发: `cd frontend && npm run dev`
- 前端构建: `cd frontend && npm run build`
- 测试: `pytest tests/`

# 代码修改边界

按风险等级执行对应规则。

## 🟠 高风险 — 改完必须跑测试

被 routes / MCP / tests 共享的核心模块，改动可能影响上下游。

- `src/server/projects/registry.py` — active project 单例 + 进程级 env 管理；改动会影响所有 session 创建路径与 MCP 子进程启动
- `src/server/projects/db.py` — `mamba.db` schema migrations；改 schema 必须追加而非修改既有 migration
- `src/server/workspace/classification.py` — 项目分类索引；schema 同样追加 only
- `src/server/claude_code/session_manager.py` — Claude Code SDK 会话编排；改完跑 `pytest tests/test_claude_code_session*`
- `src/server/codex/session_manager.py` — Codex app-server 会话编排；同上对应测试

规则：改完运行 `pytest tests/`；失败必须修复。

## 🟡 中风险 — 配置注册表（手编请走 schema）

枢转后全局 yaml 已物理删除，配置拆为 4 个 json 文件，schema 收紧到注册表语义；改完不必跑 pytest，但形状错会让对应 backend session 拉不起来。

- `configs/claude_code/providers.json` — Claude Code provider 注册表（`name → {base_url, api_key_env, default_model}`）；优先走 `PATCH /api/cli-providers` 或前端 CLI 视图
- `configs/mcp/env_overrides.json` — MCP 子进程 user 层 env override（`server_name → {KEY: value}`）；优先走 `PATCH /api/mcp/servers/{name}/env` 或前端 MCP 视图
- `configs/codex/auth.json` — Codex OAuth profile 绑定（``default_profile`` / ``allowed_profiles``）
- `<project>/.research-agent/config.toml` — 项目级 lazy 配置（`{codex_profile, enabled_mcp_servers}`）；优先走 `PATCH /api/project-config`

## 🟢 安全区 — 可直接修改

- `frontend/src/` 前端代码
- `scripts/`、`docs/`
- `.claude/agents/*.md`、`.skills-shared/*/SKILL.md`（pipeline / sub-agent 蒸馏文档；`.claude/skills/` 与 `.codex/skills/` 是指向 `.skills-shared/` 的 NTFS junction，不直接编辑）

# 架构约定 — 新功能加在哪

| 类型 | 位置 | 注册方式 |
|------|------|----------|
| 新 pipeline | `.skills-shared/<pipeline-name>/SKILL.md`（双向 mirror 到 `.claude/skills/` 与 `.codex/skills/`） | 跑 `pwsh scripts/skills_mirror.ps1 -Scope project` 建/补 junction |
| 新 sub-agent | `.claude/agents/<role>.md`（frontmatter + 系统提示） | `scripts/sync_subagents.py` 同步 .codex/agents/*.toml |
| 新 API | `src/server/routes/` 新文件 | `app.py` 里 `include_router()` |
| 新前端组件 | `frontend/src/components/*.tsx` | 父组件引用 |
| 新 MCP server | `src/server/integrations/<name>/mcp_server.py` 写 `default_mcp_config()` | `src/server/mcp/registry.py:_read_builtin_helpers` 注册 |

# 测试原则

**核心：只测"坏了看不见但后果严重"的东西。** 冗余测试用假数据制造"全绿"假象，反而掩盖问题。

必须测：数据模型拒绝无效输入；权限/安全边界；存储读写一致性；核心执行流跑通+失败恢复。

不要测：第三方 API 对接细节；LLM 输出纠错每种场景；显示层小逻辑；一次性验证。

编写规则：测真实行为不测 mock 配合；同一逻辑 1-2 个测试即可；新功能非强制带测；改 🟠 区必须保证现有测试通过；前端不写测试，`tsc --noEmit` + 构建通过即可。

# 代码风格

| 场景 | 语言 |
|------|------|
| 代码注释 / Docstring（numpy风格） | 中文 |
| Git commit / 日志 / 错误信息 | 英文 |
| 前端界面 / LLM 提示词 / README | 中文 |

命名：模块/函数/变量 `snake_case`；类 `PascalCase`；私有成员 `_` 前缀。

# Pipeline artifact 命名约定

`.skills-shared/` 下的 7 个 pipeline SKILL 共用一套 workspace artifact 命名约定（Claude / Codex 通过 `.claude/skills/` `.codex/skills/` junction 都能加载到同一物理文件）。所有 sub-agent 之间通过这些文件传递 artifact，不依赖任何 in-memory artifact store。

## 路径前缀

`outputs/<run_id>/`（在 active project workspace 根下）

`run_id` 由触发 pipeline 的 conductor 决定，格式约定：
- `lit_review_<YYYYMMDD>_<HHMMSS>` — structured-lit-review
- `exp_<YYYYMMDD>_<HHMMSS>` — empirical-study
- `method_cmp_<YYYYMMDD>_<HHMMSS>` — method-comparison
- `iter_<YYYYMMDD>_<HHMMSS>` — experiment-iteration
- `review_<YYYYMMDD>_<HHMMSS>_<artifact_short_name>` — artifact-review
- `brainstorm_<YYYYMMDD>_<HHMMSS>` — idea-brainstorming
- `data_explore_<YYYYMMDD>_<HHMMSS>_<dataset_short_name>` — data-exploration

## 标准文件名

| 文件 | 产出方 | 内容 |
|---|---|---|
| `plan.md` | conductor | markdown checklist，pipeline 进度的可见表示 |
| `sources.json` | paper-searcher | 候选论文清单 `[{title, authors, year, venue, abstract, url}]` |
| `evidence.json` | evidence-extractor | 每篇 paper 的相关原文片段 + 反例 |
| `analysis.md` | analyzer | findings / conflicts / open_questions 三段，每条带证据引用 |
| `report.md` | writer | 终稿叙述（默认 markdown；用户要 LaTeX 时为 `report.tex` + `references.bib`） |
| `review.md` | reviewer | 5 维评分 + standard issue 列表 + verdict |
| `critique.md` | critic | 🔴/🟠/🟡 严重度分级 issue + 详细 reasoning |
| `experiments/exp_<NNN>/` | experimenter | 单次实验子目录，含 `spec.md` + `script.py` + `result.json` + 可选 `lessons.md` |
| `sweep_plan.md` | experimenter | sweep 矩阵 + spec_overrides + compute 估计 |
| `sweep_analysis.md` | analyzer | sweep 聚合结果 + 最佳配置 + 趋势观察 |

## 跨 pipeline 复用

- 跑完 `structured-lit-review` 拿到 `sources.json` + `evidence.json` 后，可直接喂给 `method-comparison` / `idea-brainstorming` / `empirical-study` 作为 prior context（避免重复检索）
- 跑完 `empirical-study` 的 `experiments/exp_001/result.json` 可作为 `experiment-iteration` 的 baseline 输入

## 不变约束

- **永不修改物理 workspace 文件**：所有 artifact 写入 `outputs/<run_id>/` 子目录；用户原始数据 / 论文 PDF / 已有脚本绝不动
- **每 sub-agent 写自己负责的文件**：paper-searcher 只写 sources.json，analyzer 只写 analysis.md / sweep_analysis.md，等等
- **主 agent 是编排者**：spawn sub-agent 后由主 agent 检查文件存在与否决定是否进入下一步，不让 sub-agent 之间直接通信
