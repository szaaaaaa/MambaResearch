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




### [DONE] 1c. Providers 列表端点
- **What**: 新增 `GET /api/claude-code/providers` 端点，返回 registry 中注册的 provider 列表，去除 secret 字段（不含 api_key 明文）。
- **Acceptance**:
  - `GET /api/claude-code/providers` 返回注册的 provider 列表（去 secret 字段）
  - 响应中仅包含 name / base_url / default_model 等非敏感字段
### [DONE] 1b. Session API 接收 provider 并注入 env
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
### [DONE] 2. 前端 provider UI（L2-b）

- **What**: 新建会话 Modal 加 provider 下拉（默认 `anthropic`）；会话列表 / 设置面板展示当前 provider；现有 ModelPicker 按 provider 过滤可选 model。
- **Files**:
  - `frontend/src/components/`（新会话 Modal、Session sidebar、ModelPicker 相关组件）
  - `frontend/src/api/`（provider/session API 客户端）
- **Acceptance**:
  - 新建会话 Modal 从 `GET /api/claude-code/providers` 拉列表渲染下拉
  - 选非默认 provider 后，创建请求 body 带 `provider` 字段
  - 会话列表每条显示当前 provider 标签（简短 pill / chip）
  - `tsc --noEmit` 和 `cd frontend && npm run build` 通过

### [DONE] 3. Subagent 定义（L3 主体）

> **AC 改写记录 (2026-04-24)**：原 AC 含"Workbench `/agents` 列 5 个 subagent"与"真实对话手测委派 paper-searcher"两条手测项。F 方案下转由单测硬性覆盖注入机制，手测降级为 supplementary（见 Decisions log 2026-04-24 第 4 条）。

- **What**: 按任务语义（参考 AI-Scientist-v2 分档经验）在 `.claude/agents/` 下创建 5 个 subagent 定义文件；通过单测硬性验证 SDK 程序化注入机制（DP1 fallback 路径）。
- **Files**（新增）:
  - `.claude/agents/paper-searcher.md`
  - `.claude/agents/evidence-extractor.md`
  - `.claude/agents/analyzer.md`
  - `.claude/agents/writer.md`
  - `.claude/agents/critic.md`
  - `src/server/claude_code/agents.py`（加载器）
  - `tests/test_claude_code_agents.py`（16 单测）
- **Acceptance**:
  - 5 个文件各有完整 YAML 前言：`name / description / model / tools / mcpServers` —— `test_every_agent_has_required_frontmatter_fields` 覆盖
  - 模型分配（使用别名不写死具体 ID）：
    - `paper-searcher` + `evidence-extractor` → `haiku`
    - `analyzer` + `writer` → `sonnet`
    - `critic` → `opus`
    —— `test_model_assignment_uses_aliases[*]` 5 个 parametrize 覆盖
  - **DP1 探针结论**：SDK 源码确认 `setting_sources=["user"]` 排除 project 层，CLI 不自动发现项目 `.claude/agents/`。已走 fallback 路径 B：程序化注入 `ClaudeAgentOptions.agents`，落地在 `src/server/claude_code/session_manager.py:_build_client`
  - `test_build_client_injects_agents_into_options` 单测通过：5 subagent 正确注入到 SDK options.agents，`setting_sources` 保持 `["user"]`
  - `pytest tests/test_claude_code_agents.py` 全绿（16 tests pass）
- **Supplementary manual（非 AC，不阻塞）**：Workbench 前端手测 `/agents` 命令列 5 subagent + 主 agent 真实委派 paper-searcher（ziang 自行跑 `python app.py` + 前端后验证；若发现问题另开 issue）

### [DONE] 4. 废弃 role_models（L4）

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

### [DONE] 5. Codex Workbench 集成 + MCP 兼容性验证（F 方案）

> **AC 重写记录 (2026-04-24)**：原 Task 5 基于 CCR + DeepSeek 路径已全部失效（CCR 退休，方向切为 F 方案——见 `docs/releases/v2.x-multi-subscription.md` 与 Decisions log 2026-04-24）。重写为 Workbench 后端原生集成官方 `codex app-server` + subagent 单一源 converter + 完整 MCP 兼容性验证。

- **What**: 扩展 Workbench 后端原生支持 Codex session（通过 spawn 官方 `codex app-server` + 自写 JSON-RPC 2.0 客户端，走 ChatGPT Plus/Pro 订阅 OAuth），并以 `.claude/agents/*.md` 为单一源生成 `.codex/agents/*.toml` 让 Codex 识别 subagent；端到端验证 Codex session 能调 ResearchAgent MCP skill + 委派 paper-searcher。
- **Files**:
  - `scripts/sync_subagents.py`（新增：`.md → .toml` converter，全部 model 映射为 `gpt-5.5`）
  - `.pre-commit-config.yaml` 或 `.git/hooks/pre-commit`（新增：提交 `.claude/agents/*.md` 时自动跑 sync）
  - `.gitignore`（追加 `!.codex/agents/**` 例外）
  - `src/server/codex/__init__.py`（新增）
  - `src/server/codex/session_manager.py`（新增：对偶 `src/server/claude_code/session_manager.py`）
  - `src/server/codex/app_server_client.py`（新增：JSON-RPC 客户端）
  - `src/server/routes/codex.py`（新增：对偶 `src/server/routes/claude_code.py`）
  - `app.py`（修改：`include_router(codex_route.router)`）
  - `frontend/src/components/workbench/shell/NewSessionModal.tsx`（修改：provider 下拉新增 `codex`）
  - `frontend/src/components/tabs/WorkbenchTab.tsx`（修改：按 `session.provider` 分派到 `/api/claude-code/` vs `/api/codex/`）
  - `frontend/src/components/workbench/shell/SessionListItem.tsx`（修改：pill 按 provider 区分色）
  - `.codex/agents/*.toml`（5 份，converter 生成 + commit）
  - `.codex/config.toml`（项目级 MCP 配置，指向 `scripts/dynamic_os_mcp_server.py`）
  - `tests/test_sync_subagents.py`（新增）
  - `tests/test_codex_session.py`（新增：fake subprocess fixture）
  - `docs/releases/v2.x-multi-model.md`（发现记录章节）
- **Acceptance**:

  **T5-A（Subagent converter）**
  - `scripts/sync_subagents.py` 读 `.claude/agents/*.md` → 生成 `.codex/agents/*.toml`；字段映射：`name → name`、`description → description`、`model → model=gpt-5.5`（统一映射，不分档）、markdown body → `developer_instructions`、`tools → tools`、`mcpServers` 语义映射
  - Pre-commit hook 在提交 `.claude/agents/*.md` 时自动触发 sync，`.codex/agents/*.toml` 进入 repo
  - `tests/test_sync_subagents.py` 覆盖：5 输入 → 5 输出、字段映射正确、空目录处理、frontmatter 格式错误显式抛 error

  **T5-B（Codex session manager）**
  - `src/server/codex/session_manager.py` 与 `src/server/claude_code/session_manager.py` 对偶：`create` / `delete` / `get_or_restore` / idle TTL sweeper / `PermissionState` HITL bridge
  - spawn `codex app-server --listen stdio://` 子进程，JSON-RPC 2.0 协议通信；运行时通过 `codex app-server generate-json-schema` 拿 schema 并校验客户端请求/响应结构
  - OAuth 透明：SDK 自动读 `~/.codex/auth.json`
  - `tests/test_codex_session.py` 覆盖：fake `codex app-server` subprocess fixture、create/delete/message 三路基础烟测
  - 现有 HITL / MCP 桥 / slash / 持久化相关 pytest（Claude Code 侧）全部通过不回归

  **T5-C（API + 前端）**
  - `POST /api/codex/sessions` / `GET /api/codex/sessions` / `POST /api/codex/sessions/{id}/messages`（SSE）接口形状跟 `claude_code.py` 对齐
  - 前端 `NewSessionModal` 下拉新增 `codex` 选项（通过 provider registry 预置条目，session 创建时按 provider 分派到对应后端 endpoint）
  - `SessionListItem` pill 区分显示 `claude` / `codex`
  - `tsc --noEmit` + `cd frontend && npm run build` 通过

  **T5-D（端到端 MCP 兼容性验证）**
  - Workbench 新建 Codex session 成功进入对话界面
  - 主 agent 成功调用 3 个 MCP skill（`clarify_intent` / `plan_research` / `search_papers`），每个返回合法 `structuredContent` 可解析
  - 成功委派 `paper-searcher` subagent 一次（依赖 T5-A 生成的 `.codex/agents/paper-searcher.toml` 被 Codex 正确加载）
  - 所有发现（tool_use schema 跑偏 / JSON 格式错 / 指令遵守度差异）按"可接受 / 需修复"分类记录到 `docs/releases/v2.x-multi-model.md` 的"Codex 兼容性发现"章节
  - DP8 兜底：如果 paper-searcher 委派机制在 Codex 侧不完全等价于 Claude Task tool，记录为已知限制不阻塞 Task 5 DONE（Codex 侧退化为"手动 `/agent` 切换"）





### [DONE] 5d. Codex E2E 验证 + 发现记录
> **2026-05-03 scope 调整**：F1 resolved-by-upgrade（codex 0.124.0 已废弃 .codex/agents/ 加载，详见 5a SUPERSEDED + v2.x-multi-model.md §5.2 F1）后 5d 范围收紧：AC 3 自然降级为 L2 已知限制（无需 subagent 委派验证）；AC 4/5 缩到 snapshot-only（只记录现状，不阻塞 5d DONE）。重测预算上限：3 prompt × <50 token，超出按 advisor 建议 STOP 转 Stage 5。
- **What**: 真实 python app.py 启动后，新建 Codex session，发简单 prompt 验证 SSE 帧链路 + assistant 输出可见；记录 console / SSE 实测到 v2.x-multi-model.md。F4（复杂 prompt 截断）/ F5（approval method 名）的复测留作未来独立任务，不在本次。
- **Acceptance**（重写 2026-05-03）:
  - **AC 1**：Workbench UI 新建 Codex session 成功进入对话界面（0 prompt 消耗）
  - **AC 2**：发 `reply OK` 简单 prompt → 看到 assistant 文本 + `codex_finished` 终止帧；console 无红错（消耗 1 prompt）
  - **AC 3**：~~paper-searcher subagent 委派~~ —— 自然降级为 L2 已知限制（详见 v2.x-multi-model.md §5.2 F1）；本次不验证
  - **AC 4 (deferred)**：HITL Modal——若 AC 1+2 顺利，可选触发；否则 defer 到独立任务
  - **AC 5 (snapshot-only)**：`/agents` 面板——只记录现状，F1 cleanup 后无 agent role file；不修
  - 实测数据 + console / SSE 帧 + 任何新发现按可接受 / 需修复分类追加到 v2.x-multi-model.md §5（不删既有 5.1–5.5 内容）

**STOP 条件**：AC 2 turn 截断（F4 重现）→ 文档化新证据后 STOP，5d 维持 PENDING-VERIFY，转 Stage 5；不在 5d 范围内启动 F4 debug。
### [DONE] 5c. Codex API 路由 + Workbench 前端对接
- **What**: src/server/routes/codex.py 新增 POST/GET /api/codex/sessions{/id/messages} 端点对齐 claude_code.py；app.py include_router；前端 NewSessionModal provider 下拉加 codex；WorkbenchTab 按 session.provider 分派端点；SessionListItem pill 区分色；tsc + build 通过。
- **Acceptance**:
  - src/server/routes/codex.py 新增：POST /api/codex/sessions / GET /api/codex/sessions / POST /api/codex/sessions/{id}/messages (SSE) 等，形状对齐 claude_code.py；app.py include_router(codex_route.router)
  - 前端 NewSessionModal.tsx provider 下拉新增 codex 选项（走 GET /api/claude-code/providers 既有端点，后端 provider registry 预置 codex 条目 internal://codex-app-server）
  - WorkbenchTab.tsx 根据 session.provider 分派请求到 /api/claude-code/ vs /api/codex/；SessionListItem pill 按 provider 显示 claude/codex 区分色
  - cd frontend && npx tsc --noEmit && npm run build 通过
### [DONE] 5b. Codex session manager 后端模块
- **What**: 在 src/server/codex/ 新增 session_manager.py 和 app_server_client.py，与 ClaudeSessionManager 对偶实现 create/delete/get_or_restore/idle TTL sweeper/HITL PermissionState；spawn 子进程 codex app-server --listen stdio://，通过 generate-json-schema 获取协议 schema 构建 JSON-RPC 客户端；配 FakeClient fixture 单测。
- **Acceptance**:
  - src/server/codex/__init__.py + session_manager.py + app_server_client.py 新增，CodexSessionManager 与 ClaudeSessionManager（src/server/claude_code/session_manager.py）对偶：create/delete/get_or_restore/idle TTL sweeper/HITL PermissionState
  - spawn 子进程 codex app-server --listen stdio://；运行时用 codex app-server generate-json-schema 拿协议 schema 校验兼容性，JSON-RPC 客户端含请求/响应类型 + SSE 适配
  - OAuth 透明：SDK 路径下自动读取 ~/.codex/auth.json
  - tests/test_codex_session.py 覆盖 fake codex app-server subprocess fixture + create/delete/message 三路冒烟
  - 现有 HITL / MCP 桥 / slash / 持久化相关 pytest 全部通过



### [DONE] 5bc. FakeClient fixture 与 Codex session 冒烟测试
- **What**: tests/test_codex_session.py 新增 FakeClient fixture（模拟 codex app-server subprocess 的 JSON-RPC 响应），覆盖 create/delete/message 三路基础冒烟；不启动真实 codex 二进制。
- **Acceptance**:
  - tests/test_codex_session.py 存在且 pytest 可跑通
  - FakeClient fixture 实现 Protocol 接口，无需真实 codex app-server 进程
  - 覆盖 CodexSessionManager.create / delete / send_message 三路，断言回包格式 + 状态机转换
### [DONE] 5bb. codex app-server JSON-RPC 客户端
- **What**: 在 src/server/codex/app_server_client.py 实现 spawn 子进程 codex app-server --listen stdio://；运行时用 codex app-server generate-json-schema 获取协议 schema 校验兼容性；JSON-RPC 请求/响应类型 + SSE 流适配。替换 5ba 的 stub 为真实实现。
- **Acceptance**:
  - spawn 子进程 codex app-server --listen stdio://，通过 stdin/stdout 收发 JSON-RPC 消息
  - codex app-server generate-json-schema 运行时跑一次，schema 字段非空检查（DP7：schema drift → 抛 CodexSchemaError 显式错误）
  - JSON-RPC 请求/响应类型齐全（createSession / sendMessage / deleteSession 等），流式事件适配为 async iterator
### [DONE] 5ba. CodexSessionManager 生命周期与 HITL 状态机
- **What**: 在 src/server/codex/__init__.py 与 session_manager.py 中实现 CodexSessionManager，与 src/server/claude_code/session_manager.py 对偶：create/delete/get_or_restore/idle TTL sweeper/HITL PermissionState。为保持可 import，同步创建 app_server_client.py 的 Protocol 抽象 + 最小可用 stub（真实 JSON-RPC 实现由 5bb 落地）。
- **Acceptance**:
  - src/server/codex/__init__.py + session_manager.py 新增，CodexSessionManager 与 ClaudeSessionManager 对偶：create/delete/get_or_restore/idle TTL sweeper/HITL PermissionState
  - OAuth 透明：SDK 路径下自动读取 ~/.codex/auth.json（通过环境变量 / 配置入口）
  - app_server_client.py 至少提供 Protocol/ABC 作为 session_manager 的依赖抽象，不阻塞本次提交可 import
  - 现有 HITL / MCP 桥 / slash / 持久化相关 pytest 全部通过
### [SUPERSEDED] 5a. Subagent 同步脚本 (.claude/agents → .codex/agents)
> **2026-05-03 superseded**：codex CLI 0.124.0 已废弃从 `.codex/agents/` 加载 agent role 的特性，`scripts/sync_subagents.py` 输出的 toml 文件成为无人消费的孤儿（详见 `docs/releases/v2.x-multi-model.md` §5.2 F1 resolved-by-upgrade）。8 份 `.codex/agents/*.toml` + `scripts/sync_subagents.py` + `tests/test_sync_subagents.py` + `.pre-commit-config.yaml` 的 sync hook + `.gitignore` 例外全部移除。Codex 侧 subagent 机制由 §5.3 L2 描述的"已知限制"承担。Task 5a 的历史 AC 仅作为决策溯源保留，不再代表现状。
- **历史 What**: 编写 scripts/sync_subagents.py，读取 .claude/agents/*.md 生成 .codex/agents/*.toml，字段映射 name/description/model=gpt-5.5/tools/mcpServers → sandbox_mode、developer_instructions=body；接入 pre-commit hook；生成产物进 repo；配套单元测试。
- **历史 Acceptance**:
  - scripts/sync_subagents.py 读 .claude/agents/*.md → 生成 .codex/agents/*.toml；字段映射 name/description/model=gpt-5.5/tools/mcpServers → sandbox_mode, developer_instructions=body
  - Pre-commit hook (.pre-commit-config.yaml 或 .git/hooks/pre-commit) 自动触发 sync；.codex/agents/*.toml 进 repo（.gitignore 加 !.codex/agents/**）
  - tests/test_sync_subagents.py 覆盖 5 输入→5 输出、字段映射、空目录、格式错误抛显式 error
### [DONE] 6. 架构文档 + README + 决策 log 落地

> **AC 重写记录 (2026-04-24)**：原 AC 含"三组 provider 配置样例"、"claude-code-router 命令清单"均为 CCR 方案产物，已失效。新 AC 拆分 release notes 为架构文档（`v2.x-multi-model.md`）+ 工作流文档（`v2.x-multi-subscription.md`，已存在）两份。

- **What**: 新建架构 release notes 讲清 v2.x multi-model 架构全貌（provider registry / subagent 分档 / Codex 集成 / role_models 废弃），更新 README 加 1 行特性描述，补录本 plan 的 Decisions log。工作流相关的"怎么用双订阅"已由 `v2.x-multi-subscription.md` 覆盖。
- **Files**:
  - `docs/releases/v2.x-multi-model.md`（新增：架构文档）
  - `docs/releases/v2.x-multi-subscription.md`（已存在，修改：加 cross-reference 并补 Task 3/5/6 落地状态）
  - `README.md`（修改：+1 行特性 + 链接）
  - `docs/plans/2026-04-23-multi-model-subagent.md`（本文件，Decisions log 补录）
- **Acceptance**:
  - `docs/releases/v2.x-multi-model.md` 新建且包含以下章节：
    1. Provider registry 架构（Task 1b）：`claude_code.providers` schema + anthropic 默认条目 + 未来扩 provider 样板
    2. Subagent 分档机制（Task 3）：5 个 subagent 定义索引 + 模型别名分配 + DP1 fallback 实际路径
    3. role_models 废弃（Task 4）：原因链条 + 迁移路径
    4. Codex Workbench 集成（Task 5）：`codex app-server` JSON-RPC 协议要点 + 跨 provider 路由
    5. **v1.0 role vs v2.0 subagent 对比表**（4 维度：LLM 意图驱动 vs 规则路由、独立 context 线程 vs 共享、原生载体 vs 自建运行时、stateless 按需 vs 永久身份）
    6. **Codex 兼容性发现**章节（由 T5-D.4 填充）
  - `docs/releases/v2.x-multi-subscription.md` 加 cross-reference 指向 `v2.x-multi-model.md` 的"架构层面"章节；底部补 Task 3/5/6 落地状态表
  - `README.md` 特性列表加 1 行：简述双订阅 + 多 provider 能力 + 链接到两份 release notes；不新增大段 section
  - 本 plan 的 Decisions log 追加 2026-04-24 的 4 条新决策





### [DONE] 6d. Decisions log 追加 4 条决议
- **What**: T6-D 在 docs/plans/2026-04-23-multi-model-subagent.md Decisions log 追加 4 条 2026-04-24 决议。
- **Acceptance**:
  - docs/plans/2026-04-23-multi-model-subagent.md Decisions log 追加 4 条 2026-04-24 决议（CCR 退休 / Workbench 扩 Codex / subagent 单一源 / Task 3 手测改单测）
### [DONE] 6c. README 特性列表追加 1 行
- **What**: T6-C README.md 特性列表加 1 行：双订阅 + 多 provider 提示，指 docs/releases/。
- **Acceptance**:
  - README.md 在特性列表加 1 行：双订阅 + 多 provider 提示，详见 docs/releases/v2.x-multi-model.md 与 v2.x-multi-subscription.md
### [DONE] 6b. v2.x-multi-subscription.md 补 cross-reference 与落地状态
- **What**: T6-B 给 docs/releases/v2.x-multi-subscription.md 加 cross-reference + 补 Task 3/5/6 落地状态。
- **Acceptance**:
  - docs/releases/v2.x-multi-subscription.md 加 cross-reference 指向 v2.x-multi-model.md 架构层面章节；补 Task 3/5/6 收尾后实际落地状态
### [DONE] 6a. 新建 v2.x-multi-model.md 架构文档
- **What**: T6-A 新建 docs/releases/v2.x-multi-model.md（已部分由 5d 落地：架构 4 章 + Codex 兼容性发现 5 章）。补 v1.0 role vs v2.0 subagent 对比表（如缺）。
- **Acceptance**:
  - docs/releases/v2.x-multi-model.md 已存在含 Provider registry / Subagent 分档 / role_models 废弃 / Codex Workbench 集成 4 章；含 v1.0 role vs v2.0 subagent 对比表；含 Codex 兼容性发现章节
## Out of scope

- claude-code-router 相关一切（2026-04-24 退休，见 Decisions log）
- 第三方 `openai-codex-sdk` Python 包——本 plan Task 5 走官方 `codex app-server` + 自写 JSON-RPC 客户端，不引入非官方依赖
- 动态语义路由（RouteLLM / OpenRouter Auto 风格）——本 plan 明确走静态分档
- `continues` session bridge 的 Workbench UI 集成——跨 CLI handoff 仍在 terminal 层操作，见 `docs/releases/v2.x-multi-subscription.md`
- subagent 跨 session 复用 / 模板市场 / 社区共享
- 主 agent 动态调 `effort` 级别（`low/medium/high/max`）——subagent 先写死默认档，后续再议
- skill 内部 LLM 差异化（已决策：不做，参见 Decisions log）
- Codex subagent 的 haiku/sonnet/opus 分档映射——统一用 `gpt-5.5`（2026-04-24 决策）

## Decision points

Anticipated execution-time forks with pre-defined strategies.

- **DP1**: If `setting_sources=["user"]` blocks loading project `.claude/agents/` → fall back to programmatic injection via `ClaudeAgentOptions.agents` passed at session build time. **（已触发并落地，Task 3 DONE）**
- **DP2**: ~~CCR + DeepSeek fallback~~ **已删除 (2026-04-24)**——CCR 退休，此 DP 不再适用
- **DP3**: ~~`/agents` 列 subagent 失败 STOP~~ **已删除 (2026-04-24)**——Task 3 AC 改为单测覆盖，手测 `/agents` 降为 supplementary，不再是硬性 AC
- **DP4**: If subagent evaluator in `/pipeline` returns invalid JSON for any task in this plan → STOP per `/pipeline` SKILL.md Phase 2.2 rule (FP triggered).
- **DP5**: If Task 4 (drop `role_models`) causes any existing skill to fail at import because it passed `role_id` as a required kwarg → STOP. Fix the caller to use the network's default provider routing instead of adding a compat shim. **（已通过，Task 4 DONE）**
- **DP7** (新增 2026-04-24): If `codex app-server generate-json-schema` output shape diverges from the JSON-RPC client we implement (missing required fields / renamed types) → STOP with reason `codex app-server schema drift — pin codex version or regenerate client types`.
- **DP8** (新增 2026-04-24): If Task 5 T5-D.3 fails (paper-searcher subagent cannot be spawned/delegated on Codex side because Codex's `/agent` semantics differ from Claude Task tool) → **do NOT stop**; record as known limitation in `docs/releases/v2.x-multi-model.md` "Codex 兼容性发现" 章节, downgrade Codex subagent usage to "user-initiated `/agent` switching" only, then mark Task 5 DONE.

## External preconditions

Physical prerequisites the user must satisfy before `/pipeline` starts processing this plan.

- **EP1**: Environment variable `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70` set — verify: `echo $CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` returns `70` — on-failure: STOP.
- **EP2** (重写 2026-04-24): For Task 5 — Codex CLI installed (≥ 0.124.0) + ChatGPT Plus/Pro OAuth logged in — verify: `codex --version` 返回 ≥ 0.124.0 且 `~/.codex/auth.json` 存在——on-failure: STOP (cannot spawn `codex app-server` without auth).
- **EP3**: Git working tree clean on `development` branch before kickoff — verify: `git status --porcelain` empty — on-failure: STOP (pipeline produces one commit per task; dirty state pollutes commits).
- **EP4**: `ANTHROPIC_API_KEY` present — verify: `[[ -n "$ANTHROPIC_API_KEY" ]]` — on-failure: STOP.
- **EP5** (新增 2026-04-24): For Task 5 — Python environment has PyYAML + toml packages (for converter) — verify: `python -c "import yaml, tomli_w"` (or `tomllib` + `tomli_w` depending on Python version) — on-failure: STOP, prompt to install.

## Failure policy

STOP conditions halting execution and surfacing the failure. **Not fallbacks** — no silent retry, no silent skip.

- **FP1**: If `pytest tests/` fails after 2 fix attempts within any task → STOP with stage `test`, reason `pytest tests/ failed for task <id>`; attach failing test name + last 20 lines of traceback.
- **FP2**: If `/review` flags issues 3 times in a row for the same task → STOP with stage `review`, reason `review loop exceeded for task <id>`; attach last review findings.
- **FP3**: If `git commit` produces a merge conflict → STOP with stage `commit`, reason `commit conflict on task <id>`; attach conflicting file list.
- **FP4**: If subagent evaluator for SSP returns non-JSON or missing keys → STOP with stage `evaluate`, reason `subagent evaluation returned invalid JSON for task <id>`.
- **FP5**: If `frontend/` build (`tsc --noEmit` then `npm run build`) fails on any frontend task → STOP with stage `test`, reason `frontend build failed for task <id>`; attach tsc/build error.
- **FP6**: If Phase 0 `check-sections` against this plan file fails → STOP at pre-flight (means DP/EP/FP/SSP missing or malformed).
- **FP7** (新增 2026-04-24): If `sync_subagents.py` output TOML files cause `codex app-server` to report agent parse errors on startup → STOP with stage `test`, reason `subagent TOML schema mismatch — fix converter field mapping`; attach codex stderr log.
- **FP8** (新增 2026-04-24): If Task 5 T5-D.2 (3 MCP skill 调用) has any skill returning non-parseable structuredContent after 2 fix attempts → STOP with stage `test`, reason `codex MCP structuredContent parse failure for <skill_name>`; attach response sample.

## Subtask split policy

When a task should be auto-split at execution time, and how the split is labeled.

- **Trigger**: task touches > 5 files across > 2 modules, **OR** has > 5 top-level acceptance criteria, **OR** its `What` describes > 2 independent concerns that can be implemented and reviewed in isolation.
- **Split rule**: split by module boundary when possible (backend / frontend / config); within a single module, split by independent concern (e.g., "registry schema" vs. "env injection" vs. "API endpoint").
- **Labeling**: append lowercase letters `a`, `b`, `c`, ... to the parent task id in declaration order (`1` → `1a`, `1b`, `1c`). The parent task transitions to `[DONE]` once split (container role); each sub-task is processed as a fresh leaf.

**Per-task split prediction** (informational — evaluator decides at runtime):
- Task 1 (backend provider): already split into 1a/1b/1c, all DONE.
- Task 2 (frontend UI): DONE（single-unit 实际足够）.
- Task 3 (subagent definitions): DONE（single-unit）.
- Task 4 (drop `role_models`): DONE（single-unit）.
- Task 5 (Codex Workbench 集成 + MCP 兼容性): **likely split into 5a-5d** — T5-A converter (scripts + tests)、T5-B session manager (server/codex/ module + fake fixture tests)、T5-C API + frontend (routes + UI)、T5-D E2E 验证 + 发现记录。4 个关注点、>5 文件跨 >2 模块，触发 SSP 拆分。
- Task 6 (文档): single-unit likely（架构 release notes + README + plan Decisions log）.

## Decisions log

- **2026-04-23**：代理层外挂（用户自启 claude-code-router），Workbench 不内嵌代理进程。理由：关注点分离、避免 Node 生态耦合、代理换了不影响 Workbench。
- **2026-04-23**：采用**按任务语义定义 subagent**（`paper-searcher / analyzer / critic` 等），不做 `cheap/default/premium` 档位抽象。理由：Claude Code 原生没有 tier 概念，`model` 字段直接用别名（`haiku/sonnet/opus`），参考 AI-Scientist-v2 分档经验（实验→Sonnet、写作→Opus 等）更贴合科研流程。
- **2026-04-23**：**废弃 `llm.role_models`**。Skill 是黑盒，内部 LLM 调用不做差异化；省 token 的决策权交给（a）用户的 session provider 选择、（b）subagent 分档。理由：v1.0 的角色-模型映射是静态硬编码，违背 v2.0 "LLM 决策权"精神；skill 内部差异化会导致"DeepSeek session 里偷偷调 Claude"的账单 surprise。
- **2026-04-23**：**v2.0 subagent 形似 v1.0 role 但本质不同**——LLM 意图驱动路由（非规则）、独立 context 线程（非共享）、Claude Code 原生载体（非自建运行时）、stateless 按需调用（非永久身份）。这是对"v2.0 砍老架构"的真正兑现，不是回到 v1.0。
- **2026-04-23**：v2.0 继续在 `development` 分支累积，不开新分支。整个 v2.0 里程碑稳定后一次性 merge 到 main + 打 tag。
- **2026-04-24**：**CCR 退休，方向切为 F 方案**（双官方 CLI + `continues` handoff）。理由：Anthropic 2026-01-09 封锁第三方工具消费 Claude 订阅 OAuth；OpenAI 明确允许 ChatGPT Plus/Pro OAuth 给第三方；原 Task 5 的 "CCR + DeepSeek" 路径不再有价值。完整决策记录见 `docs/releases/v2.x-multi-subscription.md`。副作用：Task 5/6 AC 重写，原 CCR / DeepSeek / GPT-4o-mini fallback 相关 DP/EP/FP 删除（DP2 / DP3 / 旧 EP2 / 旧 FP2），新增 DP7/DP8/新 EP2/EP5/FP7/FP8。
- **2026-04-24**：**Workbench 后端原生集成 Codex session**，走官方 `codex app-server --listen stdio://` + 自写 JSON-RPC 2.0 客户端。理由：不引入第三方 `openai-codex-sdk`（非官方 maintainer）依赖；`codex app-server` 是官方 `[experimental]` 入口，schema 可通过 `generate-json-schema` 自描述；工作量 1-2 天，比 PTY 驱动 / SDK 风险低。
- **2026-04-24**：**subagent 单一源 (.claude/agents/*.md) + converter**。`scripts/sync_subagents.py` + pre-commit hook 自动生成 `.codex/agents/*.toml`；**Codex 侧统一 `model=gpt-5.5` 不做 haiku/sonnet/opus 分档映射**。理由：Codex 无对等分档模型，统一用当前最强避免选择困惑；分档在 Claude 侧仍保留。
- **2026-04-24**：**Task 3 手测 AC 改写为单测覆盖**。原"Workbench `/agents` 列 5 subagent"+"真实对话委派 paper-searcher"改为 `pytest tests/test_claude_code_agents.py` 覆盖（16 tests），手测降为 supplementary 不阻塞 pipeline。理由：pipeline 要全自动跑；真实对话委派的"Claude 模型行为"不在我们架构验证边界内。
- **2026-04-25**：**pipeline `Skill` 工具语义改为 inline 而非 hand-off**。原 `~/.claude/skills/pipeline/SKILL.md` Phase 2.3 让 pipeline 通过 `Skill("dev"/"review"/"fix")` 触发子 skill，但 `Skill` 工具实际语义是"加载指令 + yield 给用户"，导致每个 stage 后 pipeline 停下等用户按命令键。改为 "Execution model — inline, do NOT hand off" 元规则：`Skill` 工具被禁用于 pipeline 内，sub-skill 视为内联程序文档；2.6 `/compact` 步骤删除（built-in 不可工具触发，由 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70` 兜底）。本次 5bc → 5c → 5d → 6 全程实现真正自动化。
- **2026-04-25**：**5d 实测产出 5 个 Codex 兼容性发现**（F1-F5）。F2 `thread/start` 嵌套响应 schema、F3 `_write_raw` check-then-use 竞态在本次会话内修复；F1 `.codex/agents/*.toml` 顶层 schema 与 codex 期望不符（"invalid type: sequence, expected a map"）+ F4 复杂 prompt 下 turn 异常截断 + F5 approval response format 未实测，需后续 follow-up。详见 `docs/releases/v2.x-multi-model.md` §5。F1 阻塞 Task 5d AC 3 (subagent 委派验证)，5d 状态保持 PENDING-VERIFY 不直接 DONE。
- **2026-04-25**：**`.codex/config.toml` 落地为项目级 MCP 桥配置**。挂载 `[mcp_servers.research_agent] command="python" args=["-m", "src.mcp_bridge.server"]`，与 Claude 侧 `configs/agent.yaml` 的 `mcp.servers` 段对偶但配置入口不同（Claude 走 SDK options 注入，Codex 走 CLI config 文件）。同一份 `src/mcp_bridge/server.py` 两边复用——skill 能力跨 CLI 一致。

## Reference

- [SakanaAI/AI-Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2) — 科研 agent 分档先例（实验/写作/citation/plot 各用不同模型）
- [Claude Code Sub-agents](https://code.claude.com/docs/en/sub-agents) — 官方 subagent 机制
- [Choosing a Model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model.md) — Anthropic 官方模型档位建议
- `docs/plans/2026-04-21-claude-code-workbench.md` — 前置 plan（Workbench 12 task）
