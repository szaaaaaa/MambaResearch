# Plan: Asset-Centric UI 落地

**Created**: 2026-04-29
**Status**: in-progress
**Scope**: 把 UI 从"会话为中心"重构为"素材为中心"——侧栏去掉新建会话/最近会话，4 bucket 各自展开素材网格，点素材进双栏工作台（素材抽屉 + 对话主区），新增草稿箱视图与 backend-agnostic 的 run timeline 历史视图。

## 架构决策（与用户已确认）

- **D1**: 素材 = conversation + 关联 files，逻辑概念，无独立表
- **D2**: `conversations` 表追加 `asset_kind TEXT` + `asset_label TEXT`（默认 NULL），schema 追加 only
- **D3**: run timeline 走文件系统扫描 `outputs/<run_id>/`，不新建 runs 表；扫描器必须 backend-agnostic
- **D4**: 截图里的 9 条空会话作为最后一步清理，一次性脚本删除 segments + messages 都为空的 conversations 行
- **D5**: `(asset_kind, asset_label)` 不强制唯一——同名 label 可重复，互不干扰
- **D6**: 视觉令牌（Task 1）放在最前，作为最先可感知的"换装"；schema migration（Task 2）紧随其后保证后端基础设施先行

## Tasks

### [PENDING-VERIFY] 1. 设计令牌 + 主导航重构
- **What**: 替换现有 slate 系 CSS 变量为暖米色板（editorial calm）；`MambaSidebar.tsx` 删除"+ 新建会话"按钮、"最近会话"列表、"已归档"折叠区；侧栏底部加 Claude/Codex 连通状态条；`App.tsx` 移除 `handleCreateConversation`、`handleSelectConversation` 中切换到 `'hist'` 的副作用。
- **Files**:
  - `frontend/src/index.css` 或 `frontend/src/theme.css`（CSS 变量定义）
  - `frontend/src/components/MambaSidebar.tsx`
  - `frontend/src/App.tsx`
- **Acceptance**:
  - 浏览器侧栏不出现"+ 新建会话"按钮、"最近会话"列表、"已归档"区
  - 全应用主背景色为 `#F4EFE7` 系暖米调，侧栏文字色基本对应 `#1F1B16/#5A5247`，强调色 `#3F2E1F` 替换原来的 slate-blue 系
  - 侧栏底部条显示 Claude/Codex 两个状态点（颜色按连通状态变化）
  - `cd frontend && npm run build` 成功
  - `cd frontend && npx tsc --noEmit` 无错误
  - `pytest tests/` 全绿（不应受影响，确认未退化）

### [PENDING-VERIFY] 2. 后端 schema migration + asset 字段读写
- **What**: `mamba.db` `conversations` 表追加 `asset_kind TEXT`、`asset_label TEXT`（默认 NULL）；`routes/conversations.py` 读写新字段；新端点 `POST /api/conversations/{id}/promote-to-asset`；`GET /api/conversations` 支持 `?asset_kind=` 与 `?asset_kind=null` 过滤。
- **Files**:
  - `src/server/projects/db.py`（🟠 高风险，schema 追加 only）
  - `src/server/projects/conversations.py`
  - `src/server/routes/conversations.py`
  - `tests/test_conversations*.py`（追加新字段与 promote 端点测试）
- **Acceptance**:
  - 旧数据库（无新列）启动不崩，自动 migrate 加列
  - `POST /api/conversations` body 含 `asset_kind` + `asset_label` 时落库
  - `PATCH /api/conversations/{id}` 可改 `asset_kind`、`asset_label`
  - `GET /api/conversations?asset_kind=experiment` 仅返回 `asset_kind='experiment'` 的 conversations
  - `GET /api/conversations?asset_kind=null` 仅返回 `asset_kind IS NULL` 的草稿
  - `POST /api/conversations/{id}/promote-to-asset` body `{asset_kind, asset_label}` 成功后该对话从草稿移出
  - `pytest tests/` 全绿（必须，🟠 高风险区规则）

### [PENDING-VERIFY] 3. bucket 列表（grid 视图）+ 素材打开进 tab
- **What**: `BucketContainer.tsx` 升级为 3 列响应式 grid，每张素材卡显示素材名（asset_label 或 conversation.title fallback）+ 元数据 + 状态点 + 最近活动；点卡片调用 `openContextualTab` 打开素材 tab；`ContextualTabBar` 视觉对齐新令牌。tab 类型扩展（参考 DP1）。
- **Files**:
  - `frontend/src/components/buckets/BucketContainer.tsx`（重写为 grid）
  - `frontend/src/store/contextual.tsx`（新增 asset tab 类型）
  - `frontend/src/components/contextual/ContextualTabBar.tsx`
- **Acceptance**:
  - 点 🧪 实验 → 主区显示 `asset_kind='experiment'` 的素材网格
  - 网格每张卡显示素材名 + 最近活动时间 + 状态点
  - 单击素材卡：当前 tab 替换为该素材
  - Cmd+点击 / 中键点击：新 tab 打开该素材
  - tab 右键菜单可"关闭" / "关闭其他"
  - `npm run build` + `npx tsc --noEmit` 通过

### [PENDING-VERIFY] 4. 工作台双栏 — 素材抽屉 + 对话主区
- **What**: active 素材 tab 内显示双栏布局；左 320 是新组件 `AssetDrawer.tsx`（素材标识 72 + 关联文件树 + 底部关联管理按钮）；右是现有 `WorkbenchTab` 改造的对话主区。草稿 tab（无 asset_kind）走单栏（无 AssetDrawer）。AssetDrawer 文件树聚合：（a）该 conversation 关联的 `outputs/<run_id>/` 子目录；（b）classification.py 里位于该 asset_label 关联目录下的文件。显式"上传文件挂到素材"功能不在本 task 范围。
- **Files**:
  - `frontend/src/components/workbench/AssetDrawer.tsx`（新文件）
  - `frontend/src/components/tabs/WorkbenchTab.tsx`（条件双栏渲染）
- **Acceptance**:
  - 打开素材 tab 时主区为左 320 + 右自适应双栏
  - AssetDrawer 顶部展示 `素材图标 + asset_label + backend 徽章`
  - AssetDrawer 中部展示该素材关联的文件聚合（outputs 子目录 + classification 文件）
  - 打开草稿 tab 时主区单栏，无 AssetDrawer
  - `npm run build` + `npx tsc --noEmit` 通过

### [PENDING-VERIFY] 5. 草稿箱视图 + promote UI
- **What**: 新视图 `DraftsTab.tsx` 列出 `asset_kind IS NULL` 的所有 conversations；每条卡片含「继续对话」（开 contextual tab）+「转为素材」下拉（4 bucket → 弹小 modal 输入 label → 调 `POST /api/conversations/{id}/promote-to-asset`）。侧栏「💬 草稿箱」入口接通到此视图。
- **Files**:
  - `frontend/src/components/tabs/DraftsTab.tsx`（新）
  - `frontend/src/components/MambaSidebar.tsx`（加草稿箱入口 + 全部产物入口）
  - `frontend/src/App.tsx`（路由 `drafts` nav id）
  - `frontend/src/api/conversations.ts`（加 promote 调用）
- **Acceptance**:
  - 侧栏 💬 草稿箱 入口可点击进入对应视图
  - 列表展示所有 `asset_kind IS NULL` 的对话，按 `updated_at` 倒序
  - 点「继续对话」开 contextual tab，工作台进入草稿模式（单栏）
  - 点「转为素材」选 bucket + 输 label → POST 成功后该条从草稿箱消失，刷新对应 bucket 后出现
  - `npm run build` + `npx tsc --noEmit` 通过

### [PENDING-VERIFY] 6. run timeline 后端 + 前端（Codex 兼容必查项）
- **What**: 新文件 `src/server/routes/history_runs.py`：扫 active project workspace 根下 `outputs/<run_id>/` 子目录，按 CLAUDE.md 命名约定解析 kind（`lit_review_*`/`exp_*`/`method_cmp_*`/`iter_*`/`review_*`/`brainstorm_*`/`data_explore_*`），从 `plan.md` / `spec.md` 抽 title，从子目录文件存在情况推 status；返回 `[{run_id, kind, title, status, started_at, finished_at, artifacts:[filenames], source_asset?:{kind,label}}]`。`HistoryTab.tsx` 重写为按日分组的时间线 + 过滤栏。
- **Files**:
  - `src/server/routes/history_runs.py`（新，🟢）
  - `app.py`（include_router）
  - `tests/test_history_runs.py`（新）
  - `frontend/src/components/tabs/HistoryTab.tsx`（重写）
- **Acceptance**:
  - `GET /api/history/runs` 返回 active project 下所有 `outputs/<run_id>/` 列表
  - 扫描器零依赖 backend 标识：`grep -i "claude\|codex" src/server/routes/history_runs.py` 仅在注释/文档字符串里出现，逻辑代码不引用
  - 手测：分别用 Claude 触发一个 SKILL 跑出 outputs、用 Codex 触发一个 SKILL 跑出 outputs，**两个 run 同时出现在 timeline**
  - 前端 timeline 按日期分组，每条卡片含 kind 图标 / title / 状态 / artifact 列表 / 操作按钮
  - 顶部过滤栏：类型 chip + 状态筛选 + 搜索框
  - `pytest tests/` 全绿（含新 test_history_runs.py）
  - `npm run build` + `npx tsc --noEmit` 通过

### [PENDING-VERIFY] 7. 老数据清理 + 端到端联调
- **What**: 一次性脚本 `scripts/cleanup_empty_conversations.py`，删 active project 下 `segments` + `messages` 都为空的 conversations 行；在当前 MambaResearch 项目跑一次，确认截图里的 9 条空会话消失。然后浏览器端到端走完一遍验收清单。
- **Files**:
  - `scripts/cleanup_empty_conversations.py`（新）
  - 无代码改动，仅运行验收
- **Acceptance**:
  - 脚本幂等（再跑一次不报错、不误删）
  - 在 MambaResearch 跑完后，截图里 9 条空会话不见了
  - 浏览器端到端走通：进入项目 → 看到新侧栏 → 点 bucket → 网格 → 点素材 → 双栏 → 输入消息 → 发送收到响应 → 触发 SKILL → 产物在 timeline 出现
  - 最后一遍 `pytest tests/` + `npm run build` + `npx tsc --noEmit` 全绿

## Out of scope

- 显式的"上传文件挂到素材"功能（Task 4 仅做隐式聚合，未来 task）
- ⌘K 全局命令面板（设计稿提到但本期不做）
- 素材之间的关联管理（设计稿底部"+ 关联文献/数据集/灵感"按钮 UI 占位但不接通）
- 草稿箱"另存为"功能的复杂分支（仅做 4 bucket 简单转移）
- run timeline 的"再跑一次"按钮的 SKILL 触发逻辑（卡片仅做静态展示 + 打开主产物）
- 移动端适配
- A11y 完整性审计

## Decision points

- **DP1**: 如果 `ContextualTabBar` 现有 tab 类型 contract 不可扩展（无法标记某 tab 是 asset/drafts/history） → 改造为支持 `tabKind: 'asset'|'drafts'|'history'|...`，保持单一组件来源；**不**新建并行的 AssetTabBar。
- **DP2**: 如果 `mamba.db` 走的是手写 `_ensure_schema` 而非 alembic → 在该函数追加列检测 + ALTER TABLE 路径（与现有 migration 风格一致）；如果走 alembic → 追加新 revision。
- **DP3**: 如果 Codex 触发的 SKILL 不写 outputs/<run_id>/ 而走 Codex 自己的临时目录 → 视作 BUG，先补 SKILL 让 Codex 也写到 active project 的 outputs/，再继续 Task 6（这是 backend-agnostic 的真正压力测试）。
- **DP4**: 如果 `BucketContainer` 当前已有显著业务逻辑（不是占位） → 增量扩展为 grid 而非全部重写，保留已有功能。

## External preconditions

- **EP1**: active project 存在且 `mamba.db` 可写 — verify: `curl -fsS localhost:8000/api/projects/active` 返回非 null — on-failure: STOP
- **EP2**: MambaResearch 项目当前对话表里那 9 条空会话仍存在（用于 Task 7 验收） — verify: `sqlite3 <project>/.mambaresearch/mamba.db "SELECT COUNT(*) FROM conversations"` 返回 ≥ 9 — on-failure: 跳过 Task 7 截图清理子项，仅验证脚本幂等
- **EP3**: `pytest tests/` 在 plan 启动前为绿（baseline） — verify: `pytest tests/` 退出码 0 — on-failure: STOP，不在带病基线上做改动

## Failure policy

- **FP1**: 任何 task 跑完 `pytest tests/` 失败 → STOP，报告失败 test name + traceback
- **FP2**: `tsc --noEmit` 或 `npm run build` 报错 → STOP，报告 `file:line` + 错误
- **FP3**: 同一 task 内连续 2 次 fix attempt 后仍失败 → STOP，重新分析根因（implementation-discipline Step 6）
- **FP4**: schema migration 失败或不可逆 → STOP，立即 `git stash` 撤回，报告
- **FP5**: Task 6 手测发现 Codex 产出不出现在 timeline → STOP，按 DP3 分流（不容忍"Claude 能 Codex 不能"的悄悄退化）
- **FP6**: Task 7 端到端联调发现任何前面 task 的回归 → STOP 并回到对应 task 修，不容忍"先记一笔回头再说"

## Subtask split policy

- **Trigger**: task 修改 > 5 个文件跨 > 2 模块，或 acceptance > 5 条
- **Split rule**: 按模块边界拆（frontend / backend / migration / scripts），每个子任务一个模块
- **Labeling**: `1a` / `1b` / `1c` 后缀；原 task 保留为 umbrella，所有子任务完成后整体 [DONE]

## Decisions log

- 2026-04-29: 用户确认 4 项架构决策（D1–D4）后定 plan
- 2026-04-29: 增补 D5（asset 唯一性不强制）、D6（任务顺序：视觉先 / schema 紧随）
- 2026-04-29: Task 6 加入 grep 反向断言确保 history_runs.py 不引用 backend 标识，作为 backend-agnostic 的硬性可验证条件
