# Plan: Workbench 多模型支持 + Subagent 分档

**Created**: 2026-04-23
**Status**: in-progress
**Scope**: Workbench 按 session 切换 LLM provider（L2）+ 废弃 v1.0 `role_models`、引入 Claude Code 原生 subagent 分档（L3/L4），达成"省 token"目标，对齐 v2.0 "Claude Code 做大脑 + 老架构退化为基础设施层" 定位。

## Tasks

### [DONE] 1. 后端 provider 层（L2-a）

- **What**: `configs/agent.yaml` 加 `claude_code.providers` registry（name → base_url / api_key_env / default_model）；session 创建/补丁 API 接收 `provider` 字段；`_build_client` 把 provider env 注入 `ClaudeAgentOptions.env`；新增 `GET /api/claude-code/providers` 端点列可用 provider。
- **Files**:
  - `configs/agent.yaml`
  - `src/server/claude_code/session_manager.py`
  - `src/server/routes/claude_code.py`
- **Acceptance**:
  - `POST /api/claude-code/sessions` 接受 `{provider: "<name>"}` 字段，非空时按 registry 查表注入 env；未传时用 Anthropic 默认行为（零变更）
  - SDK 子进程 env 里 `ANTHROPIC_BASE_URL` 指向 registry 的 base_url（用 logging 或测试 fixture 验证）
  - `GET /api/claude-code/sessions/{id}` 返回当前 session 的 provider 名，**不回传 api_key**
  - `GET /api/claude-code/providers` 返回注册的 provider 列表（去 secret 字段）
  - 现有 HITL / MCP 桥 / slash / 持久化相关 pytest 全部通过




### [TODO] 1c. Providers 列表端点
- **What**: 新增 `GET /api/claude-code/providers` 端点，返回 registry 中注册的 provider 列表，去除 secret 字段（不含 api_key 明文）。
- **Acceptance**:
  - `GET /api/claude-code/providers` 返回注册的 provider 列表（去 secret 字段）
  - 响应中仅包含 name / base_url / default_model 等非敏感字段
### [WIP] 1b. Session API 接收 provider 并注入 env
- **What**: session 创建/补丁 API 接收 `provider` 字段；`_build_client` 把 provider 对应的 env（含 `ANTHROPIC_BASE_URL` 与 api_key_env 解析值）注入 `ClaudeAgentOptions.env`；`GET /api/claude-code/sessions/{id}` 返回 provider 名但不回传 api_key。
- **Acceptance**:
  - `POST /api/claude-code/sessions` 接受 `{provider: "<name>"}` 字段，非空时按 registry 查表注入 env；未传时用 Anthropic 默认行为（零变更）
  - SDK 子进程 env 里 `ANTHROPIC_BASE_URL` 指向 registry 的 base_url（用 logging 或测试 fixture 验证）
  - `GET /api/claude-code/sessions/{id}` 返回当前 session 的 provider 名，不回传 api_key
  - 现有 HITL / MCP 桥 / slash / 持久化相关 pytest 全部通过
### [DONE] 1a. Provider registry 配置与加载
- **What**: `configs/agent.yaml` 新增 `claude_code.providers` registry（name → base_url / api_key_env / default_model），后端加载并暴露只读访问接口（不含 secret）。
- **Acceptance**:
  - `configs/agent.yaml` 包含 `claude_code.providers` 段，结构为 name → {base_url, api_key_env, default_model}
  - 后端能加载 registry 并在内存中按 name 索引
  - registry 加载失败（字段缺失/类型错误）应在启动时显式报错，不静默忽略
### [TODO] 2. 前端 provider UI（L2-b）

- **What**: 新建会话 Modal 加 provider 下拉（默认 `anthropic`）；会话列表 / 设置面板展示当前 provider；现有 ModelPicker 按 provider 过滤可选 model。
- **Files**:
  - `frontend/src/components/`（新会话 Modal、Session sidebar、ModelPicker 相关组件）
  - `frontend/src/api/`（provider/session API 客户端）
- **Acceptance**:
  - 新建会话 Modal 从 `GET /api/claude-code/providers` 拉列表渲染下拉
  - 选非默认 provider 后，创建请求 body 带 `provider` 字段
  - 会话列表每条显示当前 provider 标签（简短 pill / chip）
  - `tsc --noEmit` 和 `cd frontend && npm run build` 通过

### [TODO] 3. Subagent 定义（L3 主体）

- **What**: 按任务语义（参考 AI-Scientist-v2 分档经验）在 `.claude/agents/` 下创建 5 个 subagent 定义文件；验证 SDK 能正常加载。
- **Files**（新增）:
  - `.claude/agents/paper-searcher.md`
  - `.claude/agents/evidence-extractor.md`
  - `.claude/agents/analyzer.md`
  - `.claude/agents/writer.md`
  - `.claude/agents/critic.md`
- **Acceptance**:
  - 5 个文件各有完整 YAML 前言：`name / description / model / tools / mcpServers`
  - 模型分配（使用别名不写死具体 ID）：
    - `paper-searcher` + `evidence-extractor` → `haiku`
    - `analyzer` + `writer` → `sonnet`
    - `critic` → `opus`
  - **关键探索**：任务一开始先实测 `setting_sources=["user"]` 是否阻止加载项目 `.claude/agents/` 目录——
    - 如加载成功：直接用 Markdown 路径
    - 如被阻止：改走 SDK `ClaudeAgentOptions.agents` 程序化注入（回落路径 B）
  - Workbench 新建会话后，`/agents` slash 命令能列出全部 5 个 subagent
  - 主 agent 在真实对话里至少成功委派一次 `paper-searcher` 完成简单搜索任务（手测，保留 transcript）

### [TODO] 4. 废弃 role_models（L4）

- **What**: 清理 v1.0 "角色-模型静态映射" 遗产。`mcp.llm.chat` 网关忽略 `role_id` 参数（保留签名向后兼容）；`configs/agent.yaml` 的 `llm.role_models` 段删除。
- **Files**:
  - `configs/agent.yaml`（删 `llm.role_models` 段）
  - `src/dynamic_os/tools/gateway/llm.py`（role_id 参数保留但标记 deprecated 并忽略）
  - 可选：各 skill yaml 里 `mcp.llm.chat` 调用清理 role_id（不改也不影响）
- **Acceptance**:
  - `configs/agent.yaml` 无 `llm.role_models` 段
  - `mcp.llm.chat` 传任意 role_id 不报错、不影响路由（LLM 调用走默认 `llm.provider/model`）
  - 跑一次完整流程 `plan_research → search_papers → draft_report`，日志里所有 LLM 调用走同一 provider（日志字段 `llm.provider/model` 一致）
  - `pytest tests/` 全绿

### [TODO] 5. 非 Claude provider 兼容性验证

- **What**: 本地启 claude-code-router 指向 DeepSeek（或 GPT-4o-mini），跑完整会话验证 MCP 桥和 subagent 在非 Claude 模型下的兼容性。
- **Files**:
  - `docs/releases/v2.x-multi-model.md`（发现记录）
  - 可选：`tests/integration/test_non_anthropic_provider.py`
- **Acceptance**:
  - 本地启 claude-code-router，registry 里配 DeepSeek provider，Workbench 创建对应 session
  - 主 agent 成功调用至少 **3 个** MCP skill（`plan_research / search_papers / clarify_intent`），返回的 `structuredContent` 合法可解析
  - 成功委派一次 `paper-searcher` subagent（依赖 Task 3 走通）
  - 记录发现的问题（tool_use schema 跑偏、JSON 格式错、指令遵守度等）到文档，标明"可接受" / "需修复"
  - 如果 DeepSeek 不能通过，回落验证 GPT-4o-mini（至少一个非 Anthropic provider 跑通是硬性 acceptance）

### [TODO] 6. 使用手册 + 决策 log 落地

- **What**: 写清"怎么用多 provider" + "为什么废弃 role_models" + "v1.0 role vs v2.0 subagent"。
- **Files**:
  - `docs/releases/v2.x-multi-model.md`
  - 本 plan 的 Decisions log（已预写）
  - `README.md`（多模型段落）
- **Acceptance**:
  - 文档包含：Anthropic / DeepSeek / OpenRouter 三组 provider 配置样例
  - 启 claude-code-router 的命令清单（安装 / 启 / healthcheck）
  - 新建多模型会话的 UI 操作流程截图或文字描述
  - "v1.0 role vs v2.0 subagent" 对比表（形似神异）写进 release notes
  - README 对应段落更新为 v2.0 多模型支持

## Out of scope

- claude-code-router 的安装、日常维护、fallback 策略（用户自管，Workbench 不感知）
- 动态语义路由（RouteLLM / OpenRouter Auto 风格）——本 plan 明确走静态分档
- Workbench 内嵌代理进程 / 代理生命周期管理——未来单独 plan
- subagent 跨 session 复用 / 模板市场 / 社区共享
- 主 agent 动态调 `effort` 级别（`low/medium/high/max`）——subagent 先写死默认档，后续再议
- skill 内部 LLM 差异化（已决策：不做，参见 Decisions log）

## Decision points

Anticipated execution-time forks with pre-defined strategies.

- **DP1**: If `setting_sources=["user"]` blocks loading project `.claude/agents/` → fall back to programmatic injection via `ClaudeAgentOptions.agents` passed at session build time.
- **DP2**: If DeepSeek provider unreachable in Task 5 → fall back to GPT-4o-mini. If both unreachable → STOP with reason `no non-Anthropic provider available for compatibility verification`.
- **DP3**: If `/agents` slash command does not list the 5 defined subagents in Task 3 after fallback path DP1 → STOP with reason `subagent loading mechanism failure`.
- **DP4**: If subagent evaluator in `/pipeline` returns invalid JSON for any task in this plan → STOP per `/pipeline` SKILL.md Phase 2.2 rule (FP triggered).
- **DP5**: If Task 4 (drop `role_models`) causes any existing skill to fail at import because it passed `role_id` as a required kwarg → STOP. Fix the caller to use the network's default provider routing instead of adding a compat shim.

## External preconditions

Physical prerequisites the user must satisfy before `/pipeline` starts processing this plan.

- **EP1**: Environment variable `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70` set — verify: `echo $CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` returns `70` — on-failure: STOP.
- **EP2**: For Task 5 only — claude-code-router running locally — verify: `curl -fsS http://localhost:3456/health` returns 200 within 5s — on-failure: STOP (cannot proceed to Task 5 without a reverse-proxy endpoint).
- **EP3**: Git working tree clean on `development` branch before kickoff — verify: `git status --porcelain` empty — on-failure: STOP (pipeline produces one commit per task; dirty state pollutes commits).
- **EP4**: `ANTHROPIC_API_KEY` present (either original or router-scoped) — verify: `[[ -n "$ANTHROPIC_API_KEY" ]]` — on-failure: STOP.

## Failure policy

STOP conditions halting execution and surfacing the failure. **Not fallbacks** — no silent retry, no silent skip.

- **FP1**: If `pytest tests/` fails after 2 fix attempts within any task → STOP with stage `test`, reason `pytest tests/ failed for task <id>`; attach failing test name + last 20 lines of traceback.
- **FP2**: If `/review` flags issues 3 times in a row for the same task → STOP with stage `review`, reason `review loop exceeded for task <id>`; attach last review findings.
- **FP3**: If `git commit` produces a merge conflict → STOP with stage `commit`, reason `commit conflict on task <id>`; attach conflicting file list.
- **FP4**: If subagent evaluator for SSP returns non-JSON or missing keys → STOP with stage `evaluate`, reason `subagent evaluation returned invalid JSON for task <id>`.
- **FP5**: If `frontend/` build (`tsc --noEmit` then `npm run build`) fails on any frontend task → STOP with stage `test`, reason `frontend build failed for task <id>`; attach tsc/build error.
- **FP6**: If Phase 0 `check-sections` against this plan file fails → STOP at pre-flight (means DP/EP/FP/SSP missing or malformed).

## Subtask split policy

When a task should be auto-split at execution time, and how the split is labeled.

- **Trigger**: task touches > 5 files across > 2 modules, **OR** has > 5 top-level acceptance criteria, **OR** its `What` describes > 2 independent concerns that can be implemented and reviewed in isolation.
- **Split rule**: split by module boundary when possible (backend / frontend / config); within a single module, split by independent concern (e.g., "registry schema" vs. "env injection" vs. "API endpoint").
- **Labeling**: append lowercase letters `a`, `b`, `c`, ... to the parent task id in declaration order (`1` → `1a`, `1b`, `1c`). The parent task transitions to `[DONE]` once split (container role); each sub-task is processed as a fresh leaf.

**Per-task split prediction** (informational — evaluator decides at runtime):
- Task 1 (backend provider): likely split (3 files, 3 concerns).
- Task 2 (frontend UI): likely split (multiple components, 2+ concerns).
- Task 3 (subagent definitions): may split (5 MD files — one concern per file).
- Task 4 (drop `role_models`): single-unit likely.
- Task 5 (non-Claude verification): single-unit (manual driven).
- Task 6 (docs): single-unit likely.

## Decisions log

- **2026-04-23**：代理层外挂（用户自启 claude-code-router），Workbench 不内嵌代理进程。理由：关注点分离、避免 Node 生态耦合、代理换了不影响 Workbench。
- **2026-04-23**：采用**按任务语义定义 subagent**（`paper-searcher / analyzer / critic` 等），不做 `cheap/default/premium` 档位抽象。理由：Claude Code 原生没有 tier 概念，`model` 字段直接用别名（`haiku/sonnet/opus`），参考 AI-Scientist-v2 分档经验（实验→Sonnet、写作→Opus 等）更贴合科研流程。
- **2026-04-23**：**废弃 `llm.role_models`**。Skill 是黑盒，内部 LLM 调用不做差异化；省 token 的决策权交给（a）用户的 session provider 选择、（b）subagent 分档。理由：v1.0 的角色-模型映射是静态硬编码，违背 v2.0 "LLM 决策权"精神；skill 内部差异化会导致"DeepSeek session 里偷偷调 Claude"的账单 surprise。
- **2026-04-23**：**v2.0 subagent 形似 v1.0 role 但本质不同**——LLM 意图驱动路由（非规则）、独立 context 线程（非共享）、Claude Code 原生载体（非自建运行时）、stateless 按需调用（非永久身份）。这是对"v2.0 砍老架构"的真正兑现，不是回到 v1.0。
- **2026-04-23**：v2.0 继续在 `development` 分支累积，不开新分支。整个 v2.0 里程碑稳定后一次性 merge 到 main + 打 tag。

## Reference

- [SakanaAI/AI-Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2) — 科研 agent 分档先例（实验/写作/citation/plot 各用不同模型）
- [Claude Code Sub-agents](https://code.claude.com/docs/en/sub-agents) — 官方 subagent 机制
- [Choosing a Model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model.md) — Anthropic 官方模型档位建议
- `docs/plans/2026-04-21-claude-code-workbench.md` — 前置 plan（Workbench 12 task）
