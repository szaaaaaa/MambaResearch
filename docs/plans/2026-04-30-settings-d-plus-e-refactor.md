# Plan: 设置面板 D+E 方案重构

**Created**: 2026-04-30
**Status**: in-progress
**Scope**: 拆掉 `configs/agent.yaml`，把启动配置物理拆成 3 个 json 注册表；为 active project 加 lazy-write 的 `.research-agent/config.toml`；前端 SettingsModal 删 9 个错位 section，改成 4 个自描述视图（项目 / CLI / MCP / Skills&Agents）。目标是让"设置"成为系统真实结构的镜像，而不是再积累 dead 字段的全局 yaml。

## Tasks

### [DONE] 1. 配置 schema 拆分 + `configs/agent.yaml` 清退
- **What**: 写一次性迁移脚本读旧 yaml → 拆为 `configs/claude_code/providers.json`、`configs/mcp/servers.json`、`configs/codex/auth.json` → 物理删除 `configs/agent.yaml`。同步删除 90% dead 字段（yaml 没了自然消失）和 `src/server/routes/config.py` 中 `_normalize_config_shape` v2 迁移代码。改造 3 个加载点（`src/server/claude_code/providers.py`、`src/server/mcp/registry.py`、Codex 配置加载点 plan 时探测）从新 json 读取。
- **Files**:
  - `configs/agent.yaml`（删除）
  - `configs/claude_code/providers.json`（新建）
  - `configs/mcp/servers.json`（新建）
  - `configs/codex/auth.json`（新建）
  - `src/server/claude_code/providers.py`
  - `src/server/mcp/registry.py`
  - `src/server/codex/`（具体文件 plan 时确认）
  - `src/server/routes/config.py`（删 `_normalize_config_shape` 的 v2 迁移代码）
  - 一次性迁移脚本：`scripts/migrate_agent_yaml.py`（迁移完即可删）
- **Acceptance**:
  - 仓库不再有 `configs/agent.yaml`（`git ls-files | grep agent.yaml` 返回空）
  - 3 个 json 文件存在且包含从旧 yaml 抽出的 `claude_code.providers` / `mcp.servers` / `auth.openai_codex` 内容
  - `python app.py` 启动无 import error / config error
  - `pytest tests/` 全绿
  - 启动后调一次 paper_search MCP 工具能拿到结果（不返回 connection error）



### [DONE] 1a. 写迁移脚本 + 生成 3 个新 json（yaml 保留不动）
- **What**: 新建 `scripts/migrate_agent_yaml.py` 一次性读旧 `configs/agent.yaml`，拆出 `configs/claude_code/providers.json`、`configs/mcp/servers.json`、`configs/codex/auth.json` 三个新文件；运行脚本生成产物。**保留 `configs/agent.yaml` 不动**——loader 切换在 1b 处理，避免本步留下损坏中间态。仅动 configs/ 与 scripts/，不改任何 .py 加载点。
- **Acceptance**:
  - `configs/claude_code/providers.json` 存在且含原 `claude_code.providers` 内容
  - `configs/mcp/servers.json` 存在且含原 `mcp.servers` 内容
  - `configs/codex/auth.json` 存在且含原 `auth.openai_codex` 内容
  - `scripts/migrate_agent_yaml.py` 存在且可重复执行（幂等或明确 one-shot 标注）
  - `pytest tests/` 全绿（loader 未改、yaml 仍在，世界观未变）
### [DONE] 1c. paper_search 做成 builtin helper + env override 加载层 + 修正 1a 的 servers.json 错误
- **What**: 经 1a 之后发现的架构错位修正——`mcp.servers[]` 在 src/ 里 0 引用，registry.py 真实 source 是 builtin helpers + .codex/config.toml + .mcp.json。把 paper_search 从 yaml 死字段升级为 builtin helper：(i) 新建 `src/server/integrations/paper_search/mcp_server.py`，导出 `default_mcp_config(root)` 返回 hardcoded command/args（照 `mamba_history/mcp_server.py:499` 模板），并合并 env override；(ii) 新建 `src/server/mcp/env_overrides.py` 读 `configs/mcp/env_overrides.json`（仅 env keys 字典，不含 command/args）；(iii) 在 `src/server/mcp/registry.py:_read_builtin_helpers()` import 并 append 新 helper；(iv) 删 `configs/mcp/servers.json`（1a 错误产物）；(v) 改 `scripts/migrate_agent_yaml.py` 把 paper_search 的 env keys 子集迁到 `configs/mcp/env_overrides.json`；(vi) 跑 migrate script 生成 env_overrides.json。
- **Files**:
  - `src/server/integrations/paper_search/__init__.py`（新建）
  - `src/server/integrations/paper_search/mcp_server.py`（新建）
  - `src/server/mcp/env_overrides.py`（新建）
  - `src/server/mcp/registry.py`（改 5 行 import + append）
  - `scripts/migrate_agent_yaml.py`（修：servers.json → env_overrides.json）
  - `configs/mcp/servers.json`（删除）
  - `configs/mcp/env_overrides.json`（生成）
- **Acceptance**:
  - `configs/mcp/servers.json` 已删除（`git ls-files | grep mcp/servers.json` 返回空）
  - `configs/mcp/env_overrides.json` 存在且只含 paper_search 的 env keys 子集（不含 command/args）
  - `src/server/integrations/paper_search/mcp_server.py:default_mcp_config` 返回字典含 `paper_search` key 与 hardcoded command/args
  - 启动后端，`/api/mcp-servers` 列表里能看到 paper_search（不依赖 yaml）
  - env_overrides.json 修改一个 key 后重启后端，paper_search 子进程 env 反映新值
  - `pytest tests/` 全绿
### [DONE] 1b. 改造 2 个加载点（claude_code/providers + codex 段）从新 json 读取 + 清退 _normalize_config_shape + 物理删除 agent.yaml
- **What**: 1b 范围已 narrow——mcp loader 由 1c 独立处理。本 task 改 `src/server/claude_code/providers.py` 从 `configs/claude_code/providers.json` 读；改 `src/server/routes/config.py`（codex 段中转）从 `configs/codex/auth.json` 读；删除 `_normalize_config_shape` v2 迁移代码 + 90% dead 字段相关引用。loader 全部切完且 `pytest tests/` 通过后，**最后一步**物理删除 `configs/agent.yaml`，再跑一次 pytest 兜底。
- **Acceptance**:
  - 2 个加载点（claude_code/providers.py + routes/config.py codex 段）不再引用 `configs/agent.yaml`
  - `src/server/routes/config.py` 中已无 `_normalize_config_shape` 残留
  - `python app.py` 启动无 import error / config error
  - `git ls-files | grep agent.yaml` 返回空
  - `pytest tests/` 全绿（删 yaml 后兜底跑一次）
  - 启动后调一次 paper_search MCP 工具能拿到结果（依靠 1c 的 builtin helper，不依赖 yaml）
### [DONE] 2. 后端 settings 路由重构
- **What**: 删 `/api/config` GET/POST（旧 yaml 接口）。新增 `/api/cli-providers` GET/PATCH 操作 `providers.json`。扩展 `/api/mcp-servers` 支持编辑 env keys 写回 `configs/mcp/env_overrides.json`（user 层 env override，非 server 命令行定义；server 定义在 1c 引入的 builtin helper 里，不可被 PATCH 改动）。确认 `/api/projects` 与 `/api/skills` 满足 D 视图所需，缺什么补什么。
- **Files**:
  - `src/server/routes/config.py`（重写或拆分）
  - `src/server/routes/mcp_servers.py`（扩展 PATCH env，写 env_overrides.json）
  - `src/server/routes/skills.py`（确认列出 `.skills-shared/*` 与 `.claude/agents/*`）
  - `src/server/routes/__init__.py`（如新增 router 文件）
  - `app.py`（include_router 增删）
- **Acceptance**:
  - `curl localhost:8000/api/cli-providers` 返回 `providers.json` 内容（含 `anthropic` 条目）
  - `curl -X PATCH /api/mcp-servers/paper_search` 写入 env 后，`configs/mcp/env_overrides.json` 文件内 env 字段被更新；进程重启后 env 仍存在
  - PATCH 试图改 paper_search 的 command/args 应被拒绝（返回 400 或忽略），仅允许改 env
  - `/api/skills` 返回包含 path / size / mtime 的列表，覆盖 `.skills-shared/*/SKILL.md` 与 `.claude/agents/*.md`
  - 旧 `/api/config` GET/POST 返回 404
  - `pytest tests/` 全绿

### [DONE] 3. per-project config 层（lazy 写入）
- **What**: 在 `src/server/projects/registry.py` 加 `active_project_config()` 接口，读 `<project_workspace>/.research-agent/config.toml`；不存在返回空 dict（不主动写文件）。新增 `/api/project-config` GET/PATCH，PATCH 时如 toml 不存在才创建。schema 最小集：`{codex_profile: str, enabled_mcp_servers: list[str]}`。配置读取做 layered（project toml override 全局默认）。
- **Files**:
  - `src/server/projects/registry.py`（🟠 高风险，改完必须跑 `pytest tests/`）
  - `src/server/routes/projects.py` 或新 `project_config.py`
  - `tests/test_project_config.py`（新建，验证 lazy 写入行为）
- **Acceptance**:
  - 切到全新项目（无 `.research-agent/`），`/api/project-config` 返回空 dict 但**不创建**文件
  - PATCH `{enabled_mcp_servers: ["paper_search"]}` 后 `<project>/.research-agent/config.toml` 出现且只含这一字段
  - 切到另一个项目，前一项目设置不漏给当前项目
  - `pytest tests/` 全绿（含新增 `tests/test_project_config.py`）
  - `pytest tests/test_claude_code_session*` 通过（registry.py 是 🟠）

### [TODO] 4. Frontend SettingsModal 重写
- **What**: 删除 9 个旧 section 文件（`General/Conversation/Tools/DataStorage/Security/Experiment/KnowledgeGraph/Review/Models`）。新建 4 个 section：`ProjectSection`（项目列表+切换）、`CliSection`（Claude Code provider 编辑 + Codex OAuth 状态/登录）、`McpSection`（servers.json 列表 + env keys 编辑）、`SkillsSection`（只读列表 + 复制路径按钮）。`SettingsModal` `CATEGORIES` 改为 6 项（4 新 + 保留 Appearance / About）。`store.tsx` 重构 `projectConfig` 形状删除 99% 老字段，改为对应 4 个 API 的细分 state。
- **Files**:
  - `frontend/src/components/settings/SettingsModal.tsx`
  - `frontend/src/components/settings/sections/*`（删 9 建 4）
  - `frontend/src/components/settings/types.ts`
  - `frontend/src/store.tsx`
  - `frontend/src/types.ts`（如有 dead 类型一并删）
- **Acceptance**:
  - `frontend/src/components/settings/sections/` 下只剩 6 个文件（4 新 + Appearance + About）
  - `cd frontend && tsc --noEmit` 无 error
  - `cd frontend && npm run build` 成功
  - 启动前端打开设置弹窗，6 个分类全部可见且 console 无 error
  - 在 MCP 视图编辑一个 env key 点保存 → 后端 `configs/mcp/env_overrides.json` 文件真被修改

### [TODO] 5. 端到端验证
- **What**: 手动跑通真实工作流，确认枢转后核心功能（Codex OAuth、paper_search MCP、Claude Code 会话）没被打断。
- **Files**: 验收型 task，无文件变更
- **Acceptance**:
  - `pytest tests/` 全绿
  - frontend `tsc --noEmit` + `npm run build` 通过
  - 手动：Codex OAuth `login → logout → 重新 login` 全流程跑通
  - 手动：在 MCP 视图配置 paper_search MCP 的 `CORE_API_KEY` → 重启后端 → 发起一次包含学术搜索的会话，确认 key 被注入到 MCP 子进程 env
  - 手动：发起一次 Claude Code 会话（任意 skill），确认 `ANTHROPIC_API_KEY` 注入正确
  - 手动：切换 active project 后 settings 面板 `enabled_mcp_servers` 字段跟着切

### [TODO] 6. 文档同步
- **What**: 更新 `CLAUDE.md` 的"代码修改边界"和"架构约定—新功能加在哪"两段。修订或删除 `docs/` 中残留引用 `configs/agent.yaml` 死字段的文档。
- **Files**:
  - `CLAUDE.md`
  - `docs/`（grep 后定位）
- **Acceptance**:
  - `CLAUDE.md` 高风险清单移除 `configs/agent.yaml` 相关条目，加入 `configs/mcp/servers.json` / `configs/claude_code/providers.json`
  - 架构表里"新 MCP 注册方式"指向 `configs/mcp/servers.json`
  - `grep -r "agent\.yaml\|configs/agent" docs/` 无残留引用
  - `git diff` 只动文档，不动代码（无 `.py` / `.tsx` 文件 diff）

## Out of scope
- 重新引入旧的 in-process 研究循环 / 评审循环 / 实验循环（这些已被 sub-agent + skill markdown 替代，不回流）
- 修改 `.skills-shared/*/SKILL.md` 内的行为参数（markdown 主权区，不动）
- 修改 `.claude/agents/*.md` frontmatter（同上）
- 给 Skills & Agents 视图加 markdown 预览或编辑器（已选 3a 只读列表）
- per-project config schema 扩展（如 per-project model override）—— 留作未来 plan
- mamba.db schema 变更（本 plan 不动）

## Decision points
- **DP1**：Task 1 迁移过程中如发现 yaml 含本提案未列出的 active 字段（即 `src/` grep 有命中但 plan 没覆盖）→ STOP，把字段贴出来重新评估迁不迁，不擅自决定。
- **DP2**：Task 3 schema 后续如需扩展（例如 per-project model override）→ 不在本 plan 内追加，开新 plan。
- **DP3**：Task 1 探测 `src/server/codex/` 时如发现 Codex 配置实际不在 yaml 而在别处（例如已经走 codex CLI 自己的 toml）→ 跳过 `configs/codex/auth.json` 的拆分，只迁 yaml 里 `auth.openai_codex` 与新结构对应的部分。
- **DP4**：Task 4 `store.tsx` 重构如触及 store 与其他非 settings 路径的耦合（例如聊天页也在读 `projectConfig.agent.language`）→ 把那些读取点纳入本 task 一起改干净，但若耦合面超 5 个文件则触发 SSP 拆 4d。

## External preconditions
- **EP1**：开始前 `.env` 中 `ANTHROPIC_API_KEY` 已配置且有效——验证：`python -c "import os; assert os.getenv('ANTHROPIC_API_KEY')"`——on-failure：STOP（迁移不动 .env，但底线 key 必须在）。
- **EP2**：开始前 git working tree clean——验证：`git status --porcelain` 返回空——on-failure：STOP（避免迁移过程中和未提交改动混在一起）。
- **EP3**：当前 active project 的 mamba.db 健康——验证：`/api/projects` 返回 200 且 `active` 字段非 null——on-failure：STOP（Task 3 依赖 active project 概念）。

## Failure policy
- **FP1**：任一 task 后 `pytest tests/` 失败 → STOP，报告失败 test 名 + traceback。
- **FP2**：Task 1 yaml 删除后 `python app.py` 启动失败 → STOP（**不要回滚把 yaml 加回来**；定位哪个加载点没改干净并修根因）。
- **FP3**：Task 4 `tsc --noEmit` 报 error 经 2 轮修复仍未通过 → STOP，列出第一波 error 全集，疑为 store schema 设计有结构性问题。
- **FP4**：Task 5 任一手动验收项失败（如 Codex login 跑不通、env key 没注入）→ STOP，报现象 + 关联 task 编号。
- **FP5**：commit 触发 pre-commit hook 失败 → STOP，修 hook 反馈的根因，**不**用 `--no-verify` 绕过。

## Subtask split policy
- **Trigger**：单 task 触及 >5 个文件且跨 >2 个模块，或 acceptance criteria >5 条且彼此独立。
- **Split rule**：按文件归属模块切；每个 sub-task 独占一个模块/层（前端组件层 / store 层 / route 层 / 配置层）。
- **Labeling**：原 task 编号后追加 `a / b / c`（例：Task 4 拆成 4a 删旧 + store schema 收缩，4b 实现 Project + CLI + MCP + Skills 4 个 section，4c SettingsModal 重接线 + 端到端联调）。

## Decisions log
- 2026-04-30：选定 1b（删 yaml 拆 3 个 json）+ 2c（per-project lazy 写入 + layered 读取）+ 3a（Skills/Agents 视图只读列表）。理由：1b 让全局大杂烩 yaml 物理消失，未来不可能再积累 dead 字段；2c 不污染项目目录，toml 只记录用户主动偏离默认的部分；3a 与 ziang 自己写 markdown / git 管 skill 文件的工作流匹配，避免 UI ↔ markdown schema drift。
- 2026-04-30：per-project config schema 最小集定为 `{codex_profile, enabled_mcp_servers}`。其他 per-project 候选字段（model override 等）开新 plan 再加。
