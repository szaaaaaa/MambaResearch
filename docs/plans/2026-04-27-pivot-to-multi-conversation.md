# 2026-04-27 架构枢转：层级 3 — 多对话并行 + 撤回 hybrid master transcript

**Status**: DONE（v3.3 multi-conversation 6 commit 链全落地 — 撤回 v3.2 hybrid MT + auto-compact / conversations 表加 backend 列 / mamba_history.* MCP server 上线 / messages 表降级为 read-only mirror）

## TL;DR

v3.2 的 hybrid master transcript（messages 表作为真相源 + 切换时 first-message 注入 + auto-compact）是为了维护"单对话无缝切 backend"这个**伪需求**而做的整套机制。真实科研工作流是多线并行的（找文献 / 跑实验 / 写报告），不同 backend 各自专精，强塞同一 conversation 反而乱。

**新方向**：
- 每条 conversation 绑死一个 backend（claude 或 codex），永不切换
- conversation 真相源回归 backend 自己（JSONL）；MambaResearch 仅持有目录索引 + read-only mirror（用于跨 conversation 查询）
- 跨 conversation 引用通过 MCP `mamba_history` tool 按需取（lazy pull，不预 push）

## Context

### 决策路径回顾

- v3.0 上线后 ziang 测出"切到 codex 再点 claude 不丝滑 + 上下文丢失"
- v3.2 hybrid MT 方案（5 commits, 443 测试, Settings UI, auto-compact）落地后，ziang 重新审视："实际上有点花里胡哨了"
- 4 层方案对比后，结论：层级 3（多对话并行，消除切换本身）是 token 维度的物理极限 + 最贴合科研真实工作流

### Decision points

- **DP1 真相源归属**：会话内容真相源 = backend 的 JSONL（不再是 mambaresearch 的 messages 表）
- **DP2 messages 表去留**：保留作 read-only mirror，用于跨 conversation 查询；**不再注入回 backend**，不再被切换逻辑读取
- **DP3 切换 UI**：删除"切换 backend"按钮；conversation 创建时绑定 backend，永不变
- **DP4 auto-compact 去留**：删除——单 backend session 由 backend 自己的原生 auto-compact 处理（claude `/compact`、codex 内置压缩）；mambaresearch 不再插手
- **DP5 跨 conversation 引用**：通过新 MCP server `mamba_history` 提供 `search_conversations(query, k)` / `get_conversation_messages(conv_id, last_n)` tool；用户在对话里说"把 A 那条线最后写的脚本贴过来" → backend 自己调 tool 取
- **DP6 老对话兼容**：v3.2 期间产生的 hybrid MT 对话仍能打开看（messages 表不删 schema），但不再支持切 backend；老切换路径走 fallback 提示"该功能已弃用"

### External preconditions

- `python app.py` 后端起得来；前端 `npm run dev` 起得来
- 至少装 claude / codex 之一；本 plan 不需要两个都装（每条对话只用一个）

### Failure policy

- 任何 task 后 `pytest tests/` 失败 → STOP
- 任何 task 后 `cd frontend && npx tsc --noEmit && npm run build` 失败 → STOP
- 删 v3.2 模块后老对话打不开（hydrate 报错）→ STOP，加只读路径再继续

### Subtask split policy

每个 task 单一关注点。Task 4（前端切换路径删除）+ Task 6（mamba_history MCP）是最大块但内聚，不再拆。

## Tasks

### [DONE] 1. 删除 v3.2 hybrid MT 注入路径 + auto-compact 后端模块

- **What**: 撤回 v3.2 的 5 个 commit 涉及的后端注入路径与 auto-compact runner，但**保留** messages 表 schema + `messages_store.append_message` / `list_by_conversation`（仅作 mirror 写入和跨 conv 查询用）
- **删除清单**:
  - `src/server/bridge/auto_compact_config.py`
  - `src/server/bridge/compact_runner.py`
  - `src/server/routes/claude_code.py` 的 `_maybe_run_compact` + `internal` body 字段处理 + compact_started/done 事件
  - `src/server/routes/codex.py` 的 `_maybe_run_compact_codex` + 同样的字段
  - `src/server/bridge/auto_compact.py` 的 TokenUsageTracker（v3.2 衔接路径）
  - `tests/test_auto_compact_config.py` / `tests/test_compact_runner.py` 全删
  - `configs/agent.yaml` 的 `ui.workbench.auto_compact` 段
- **保留**:
  - `src/server/projects/messages_store.py` 全部（mirror 写入仍要用）
  - `messages` 表 schema（v4 migration）
  - `tests/test_messages_store.py` 全部
- **Files**: 详见删除/保留清单
- **Acceptance**:
  - `pytest tests/` 全绿（删除约 16 个 v3.2 测试，剩约 425+）
  - 后端启动不报 import 错
  - 老对话仍能 `GET /api/conversations/{id}/messages` 拉到内容

### [DONE] 2. 删除前端切换 backend 路径 + Settings UI auto-compact 区块

- **What**: 删除 WorkbenchTab 的 `handleBackendSwitch` 与切换按钮、`ensureConversationForSession`、SSE compact 事件 handler；删除 ConversationSection 的"上下文自动压缩"Card；删除 ProjectConfig 的 `ui.workbench.auto_compact` 类型字段
- **Files**:
  - `frontend/src/components/tabs/WorkbenchTab.tsx`：删 `handleBackendSwitch`、`isSwitching`、切换按钮、CC_LAST_CONV_KEY 切换路径、cc_compact_started/done/recommended SSE handler
  - `frontend/src/components/settings/sections/ConversationSection.tsx`：删"上下文自动压缩"Card
  - `frontend/src/types.ts`：删 `ui.workbench.auto_compact` 字段
  - `frontend/src/store.tsx`：删 `defaultProjectConfig.ui` 段
  - `frontend/src/api/conversations.ts`：删 `serializeHistoryForBackend`
- **Acceptance**:
  - `cd frontend && npx tsc --noEmit && npm run build` 通过
  - 浏览器开 conversation：单 backend 模式正常对话；顶部不再有"切换 backend"按钮

### [DONE] 3. conversation 创建时绑定 backend，永不变

- **What**: `POST /api/conversations` 接受 `backend: 'claude' | 'codex'` 必传字段；存到 conversations 表；前端创建 conversation 时弹选择器
- **Files**:
  - `src/server/projects/db.py`：v5 migration `ALTER TABLE conversations ADD COLUMN backend TEXT NOT NULL DEFAULT 'claude'`（老对话默认 claude，避免 NOT NULL 失败）
  - `src/server/routes/conversations.py`：POST endpoint 接受 backend 参数
  - `frontend/src/api/conversations.ts` + `frontend/src/store.tsx`：createConversation 接受 backend
  - 新对话入口 UI（sidebar "新建对话" 按钮）：弹选 backend
- **Acceptance**:
  - `pytest tests/` 全绿
  - 新建 conversation 时必选 backend
  - 对话创建后顶部显示 backend tag（不可改）

### [DONE] 4. messages 表降级为 read-only mirror（语义文档化 + 移除注入路径）

- **What**: messages 表保留写入（SSE 路由仍 `append_message`），但**移除任何"读 messages 表 → 注入回 backend"** 的路径；语义降级为"跨 conversation 查询的本地 mirror"。`mamba.db` 不动 schema，仅注释 + 文档更新
- **Files**:
  - `src/server/projects/messages_store.py`：docstring 顶部加段说明"v3.3+ 起本表为 backend session 的 read-only mirror，不再是真相源；不要把 list_by_conversation 的结果注回任何 backend"
  - 删 `frontend/src/api/conversations.ts` 的 `serializeHistoryForBackend`（task 2 已做，此处仅校验）
- **Acceptance**:
  - grep 全仓 `serializeHistoryForBackend` 无引用
  - grep 后端 `internal: true` body 字段无引用

### [DONE] 5. mamba_history.* MCP server — 跨 conversation 引用工具

- **What**: 新 MCP server 暴露两个 tool：
  - `search_conversations(query: str, k: int = 5)` → `[{conv_id, title, backend, snippet, last_at}]`
  - `get_conversation_messages(conv_id: str, last_n: int = 20)` → `[{role, text, served_by, ts}]`
- **Files**:
  - `src/server/integrations/mamba_history/__init__.py`
  - `src/server/integrations/mamba_history/mcp_server.py`：standalone NDJSON stdio，每请求读 MAMBA_ACTIVE_PROJECT_PATH，从 mamba.db 查 conversations / messages 表
  - `src/server/mcp/registry.py:_read_builtin_helpers`：注册 mamba_history
  - `.codex/config.toml` + claude SDK programmatic config：mount mamba_history
  - `tests/test_mamba_history_mcp.py`：basic search + get
- **Acceptance**:
  - `pytest tests/test_mamba_history_mcp.py` 全绿
  - 浏览器对话里说"列一下我之前的对话标题" → backend 调 tool 返回

### [DONE] 6. 文档更新 + 清理

- **What**: README / CLAUDE.md / 大方向 plan 反映新架构；memory 更新
- **Files**:
  - `CLAUDE.md`：架构约定段去掉 backend 切换；conversation 段加"绑定 backend"说明
  - `README.md`：multi-conversation parallel 模型说明
  - 大方向 plan 文件：在末尾追加 "2026-04-27 pivot 决策日志"
  - memory `project_mamba_pivot_progress.md`：v3.3 多对话并行落地段
- **Acceptance**:
  - grep `hybrid master transcript` / `跨 backend 切换` / `auto-compact` 在 README/CLAUDE.md 中无残留

### [PENDING-VERIFY] 7. 验证 + 手测

- **自动**:
  - `pytest tests/` 全绿
  - `cd frontend && npx tsc --noEmit && npm run build` 通过
  - `python scripts/sync_subagents.py --quiet` 通过
- **手测**:
  1. 新建 conversation 选 claude → 发"你好" → 回正常
  2. 新建第二条 conversation 选 codex → 发"你好" → 回正常
  3. 在 codex conversation 里说"列一下我之前的对话" → codex 调 mamba_history.search_conversations 返回标题
  4. 在 codex 里说"把第一条对话最后一条消息内容贴过来" → codex 调 get_conversation_messages 返回
  5. 老 v3.2 对话打开仍能看 history，顶部 backend tag 显示其原 backend，不再有切换按钮
  6. 浏览器刷新对话不丢历史

## 不做的事

- **不删 messages 表 schema** —— 老对话仍要能拉历史；mirror 写入也要继续
- **不删 conversation_segments 表** —— 历史段记录仍有用（UI 时间线视觉分隔）
- **不删 continues 桥代码** —— 留作老对话 fallback；不被新代码调用
- **不做 conversation 内自动 compact** —— backend 自己有 native auto-compact，mambaresearch 不再 hook
- **不做 cross-conversation 自动注入** —— mamba_history MCP 是 backend 主动调，不是 mambaresearch 后台 push

## 复用现有代码

- `src/server/projects/messages_store.py`（mirror 写入路径已在）
- `src/server/projects/db.py` migration 框架（追加 v5）
- `src/server/mcp/registry.py` 内置 helpers 机制（mamba_history 注册）
- `src/server/integrations/` 目录约定（zotero/colab/experiment 已建立模式）
- conversations 表 + 现有 POST /conversations 端点（仅扩展 backend 字段）

## 验收

| 场景 | v3.2 现状 | v3.3 目标 |
|---|---|---|
| 单 backend 对话 | 同 v3.0 | 完全一样 |
| 跨 backend 切换 | 1-3s + 完整注入 + auto-compact | **不存在该 UI**——多对话并行 |
| 跨对话引用 | 不可能（同对话内才有上下文）| backend 主动调 mamba_history MCP tool |
| 跨对话 token 开销 | O(累积历史) per 切换 | **0**（仅按需 cross-ref 时付小量）|
| 浏览器刷新 | messages 表 hydrate | 同左（mirror 仍在）|
| 工程线数 | hybrid MT + auto-compact + cross-bridge | mirror only + cross-ref MCP |

## 工程量估算

| Task | LOC | 时间 |
|---|---|---|
| 1. 删 v3.2 后端 | -800 | 0.5d |
| 2. 删 v3.2 前端 | -500 | 0.5d |
| 3. conversation 绑 backend | +150 | 0.5d |
| 4. messages 表降级文档化 | +30 | 0.1d |
| 5. mamba_history MCP | +400 | 1d |
| 6. 文档更新 | +200 | 0.3d |
| 7. 验证 + 手测 | — | 0.5d |
| **总** | **-520** | **~3.5d** |

净删 LOC ≈ 520 行，工程债显著下降。

## 决策日志（2026-04-27）

- ziang："这算做自动方案。另一种选择是提示用户切换前就 compact，然后把 compact 后的信息给新 cli"
- 推演 4 层方案 + 物理极限分析，得出层级 3（多对话并行 + 消除切换）= 工程内可达极限 + 最贴科研工作流
- ziang："当前实际上有点花里胡哨了，没必要。"
- 共识：v3.2 hybrid MT 整套撤回，messages 表降级 mirror，conversation 绑 backend，新增 mamba_history MCP 提供跨对话引用
- 此 plan 起草后等 ziang 确认 GO 再执行
