# Codex-first Backend Registry 技术设计

状态：待实施
前置条件：[Mamba Kernel 技术设计](01-Mamba-Kernel-技术设计.md) Batch 1 已通过
上层设计：[Mamba Kernel 插件化架构](../架构设计/mamba-kernel-plugin-architecture.md)

## 1. 本批决策

第一批只实现并启用 Codex：

~~~text
Mamba Kernel
  -> Backend Registry
  -> backend.codex
  -> Terminal / Auth / Conversation consumers
~~~

Claude adapter、Claude provider、skill mount 和 MCP config 拼装不进入本批。Backend seam
切换后，Claude 不再通过旧分支启动；历史 Claude conversation/segment/message 元数据仍可读取，
但不能新建或 resume。Codex 全链路验收后，再用同一个 <code>TerminalBackend</code> 合同补充
<code>backend.claude</code>。

这样可以用一个真实 backend 验证装配、API、前端和存储的完整纵向切片，同时不建立双路由或临时
兼容层。

## 2. 目标

把 <code>src/server/routes/terminal.py</code> 中 backend 名称集合和 Codex argv 构造移到
Codex backend adapter。终端 route 只处理 WebSocket、通用 cwd、PTY 和会话镜像。

完成后：

~~~text
WS /api/terminal/{backend_id}
  -> BackendRegistry.require(backend_id)
  -> backend.resolve_launch(request)
  -> PtyBridge(LaunchSpec)
~~~

未来添加 Claude 时，不修改终端 route、认证聚合器、前端 backend 类型或 SQLite schema。

## 3. 非目标

- 不实现 Claude backend 或保留 Claude 旧终端路径。
- 不迁移 Claude provider registry、skill mount、MCP config 和 credentials probe。
- 不统一外部 CLI transcript 格式。
- 不在 Kernel 内实现 agent/session runtime。
- 不改写 <code>PtyBridge</code> 或 WebSocket 帧协议。
- 不实现 Gemini/OpenCode；只用一个测试 backend 验证 seam。
- 不为单实现引入 factory、entry points 或远程插件发现。

## 4. 目标文件边界

~~~text
src/server/kernel/
  contracts.py                 # BackendDescriptor、LaunchRequest、LaunchSpec
  registry.py                  # BackendRegistry
src/server/plugins/
  backend_codex.py             # Codex adapter + plugin
src/server/routes/
  terminal.py                  # registry consumer
  capabilities.py              # inventory endpoint
src/server/auth/
  probe.py                     # registry-driven 聚合，只保留通用状态与 API key probe
src/server/projects/
  conversations.py             # 写入时按 registry 校验
  messages_store.py            # served_by 改为可扩展字符串
  db.py                        # append-only migration
frontend/src/api/
  terminal.ts                  # backend:string + capability fetch
  projects.ts                  # 动态 auth schema
~~~

只修改实际消费 backend 列表的现有前端组件；不新建前端插件框架。

## 5. Backend 合同

合同使用 Python 3.10 标准库，不新增依赖。

### 5.1 BackendDescriptor

~~~python
from dataclasses import dataclass


@dataclass(frozen=True)
class BackendDescriptor:
    id: str
    label: str
    supports_resume: bool
    supports_provider_selection: bool
~~~

约束：

- <code>id</code> 是 API、URL 和持久化使用的稳定 ID。
- 当前唯一 ID 为 <code>codex</code>，沿用已有数据值。
- <code>label</code> 只用于显示，不能作为查询 key。
- descriptor 不包含 argv、env、凭据或内部 class 名。

### 5.2 LaunchRequest

~~~python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LaunchRequest:
    cwd: Path
    resume_id: str | None
    provider_id: str | None
~~~

<code>conversation_id</code> 只用于 host 的 <code>TurnTeer</code>，不属于 CLI 启动合同。

进入 backend 前，terminal host 已完成：

- backend ID 的 trim/lower；
- cwd query 优先，否则 active project；
- cwd 必须是现有目录；
- conversation ID 和 mirror sentinel 处理。

Backend 负责：

- resume/provider 能力校验；
- CLI binary 解析；
- backend 自己的 argv/env。

### 5.3 LaunchSpec

~~~python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LaunchSpec:
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
~~~

<code>LaunchSpec</code> 可直接交给 <code>PtyBridge</code>。route 不再二次修改 argv/env。

### 5.4 认证合同

~~~python
from dataclasses import dataclass
from enum import Enum


class BackendStatus(str, Enum):
    LOGGED_IN = "logged_in"
    NOT_LOGGED_IN = "not_logged_in"
    CLI_NOT_FOUND = "cli_not_found"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BackendAuthProbe:
    status: BackendStatus
    detail: dict[str, str]
~~~

<code>detail</code> 只允许 binary 和 credentials 路径，不包含凭据内容、token 或完整环境变量。

### 5.5 TerminalBackend

~~~python
from typing import Protocol


class TerminalBackend(Protocol):
    descriptor: BackendDescriptor

    def resolve_launch(self, request: LaunchRequest) -> LaunchSpec:
        ...

    async def probe_auth(self) -> BackendAuthProbe:
        ...
~~~

当前 resolve 只做本地路径与配置读取，保持同步；PTY 启动由 host 异步执行。

## 6. Codex Adapter

### 6.1 Descriptor

~~~python
BackendDescriptor(
    id="codex",
    label="Codex",
    supports_resume=True,
    supports_provider_selection=False,
)
~~~

### 6.2 Launch 解析

<code>resolve_launch()</code> 的唯一顺序：

1. 若 <code>provider_id</code> 非空，抛 <code>BackendLaunchError</code>；Codex 本批不支持
   provider selection，不能静默忽略。
2. 依次用 <code>shutil.which</code> 查找
   <code>codex.cmd</code>、<code>codex.exe</code>、<code>codex</code>。
3. 未找到 binary 时返回当前已有的明确安装提示。
4. 无 resume 时 argv 为
   <code>[codex_bin, "--no-alt-screen"]</code>。
5. 有 resume 时 argv 为
   <code>[codex_bin, "resume", "--no-alt-screen", resume_id]</code>。
6. 沿用当前 <code>build_subprocess_env(provider=None)</code> 生成完整子进程环境。
7. 返回 immutable <code>LaunchSpec</code>。

实现直接移动当前 <code>_resolve_codex_bin()</code> 和 <code>_resolve_argv()</code> 的 Codex
分支，不另写第二套命令构造器。

### 6.3 Auth 探测

<code>probe_auth()</code> 直接复用当前 Codex 行为：

1. 查找 Codex binary。
2. 运行 <code>--version</code> 判断是否可执行。
3. 检查 <code>~/.codex/auth.json</code>。
4. 按当前规则返回 logged_in/not_logged_in/cli_not_found/unknown。

本批删除固定 <code>probe_all()</code> 中 Claude task，不实现空的 Claude probe。

### 6.4 插件生命周期

~~~python
class CodexBackendPlugin:
    manifest = PluginManifest(id="backend.codex")

    def register(self, context: KernelContext) -> None:
        context.capabilities.backends.register(
            plugin_id=self.manifest.id,
            backend=CodexTerminalBackend(),
        )

    async def start(self, context: KernelContext) -> AsyncDisposer | None:
        ...
~~~

如果现有 Codex session manager 是进程级资源，<code>start()</code> 启动它并返回 disposer；
否则 start 返回 <code>None</code>。每个 WebSocket 的 PTY 不放入插件全局生命周期。

Plugin ID 与 backend ID 是不同命名空间：

- plugin ID：<code>backend.codex</code>；
- backend ID：<code>codex</code>。

## 7. Backend Registry

~~~python
class BackendRegistry:
    def register(self, *, plugin_id: str, backend: TerminalBackend) -> None:
        ...

    def require(self, backend_id: str) -> TerminalBackend:
        ...

    def list(self) -> tuple[TerminalBackend, ...]:
        ...
~~~

规则：

- ID 从 <code>backend.descriptor.id</code> 取得。
- 重复 ID 在应用启动时失败，不允许覆盖。
- <code>require()</code> 对未知 ID 抛 <code>UnknownCapabilityError</code>，错误包含当前 IDs。
- <code>list()</code> 保持注册顺序并返回不可变快照。
- 第一批 list 只有 Codex；Registry 不为 Claude 预留空 slot。

## 8. Terminal WebSocket 改造

端点保持 <code>WS /api/terminal/{backend_id}</code>，帧协议不变。

### 8.1 新执行路径

~~~text
1. accept websocket
2. normalize backend_id
3. BackendRegistry.require(backend_id)
4. parse cwd/provider/resume/conversation_id
5. resolve common cwd
6. backend.resolve_launch(LaunchRequest)
7. create TurnTeer with assistant_served_by=backend_id when mirror enabled
8. async with PtyBridge(spec.argv, cwd=spec.cwd, env=spec.env)
9. run existing _pump()
10. close TurnTeer in finally
~~~

### 8.2 从 route 删除

- <code>SUPPORTED_BACKENDS</code>。
- <code>_resolve_codex_bin()</code>。
- <code>_resolve_argv()</code>。
- 所有 <code>backend == "claude"</code>/<code>backend == "codex"</code> 分支。
- provider registry、Claude skill mount 和 MCP config 拼装。

route 保留 cwd、WebSocket、<code>TurnTeer</code>、<code>PtyBridge</code>、
<code>_pump()</code> 和 control frame。

### 8.3 错误语义

| 错误 | fatal message | close code |
| --- | --- | --- |
| 未知/未启用 backend（包括 claude） | 包含请求 ID 与 registry 当前 IDs | 1003 |
| cwd 无效/无 active project | 保持当前明确错误 | 1011 |
| Codex 收到 provider | 明确“不支持 provider selection” | 1011 |
| Codex binary 不存在 | 保持当前安装提示 | 1011 |
| env 构建失败 | 保持 <code>env build failed</code> 语义 | 1011 |
| PTY 运行期异常 | 保持 <code>PTY crashed</code> 语义 | 1011 |
| 正常 PTY EOF | 正常关闭 | 1000 |

预期启动错误统一为 <code>BackendLaunchError</code>。不建立 fallback argv。

## 9. Capability Inventory

新增 <code>GET /api/capabilities</code>，只读取 Kernel snapshot 和 Backend Registry。

### 9.1 第一批响应

~~~json
{
  "api_version": 1,
  "enabled_plugins": ["core.http", "backend.codex"],
  "backends": [
    {
      "id": "codex",
      "label": "Codex",
      "supports_resume": true,
      "supports_provider_selection": false
    }
  ]
}
~~~

规则：

- backends 按 registry 注册顺序输出。
- enabled_plugins 按 Kernel 依赖顺序输出。
- 禁用 Codex 插件时返回空 backends。
- 不伪造 Claude descriptor。
- 不返回 auth、argv、env 或 credentials。

### 9.2 前端类型

~~~typescript
export interface BackendDescriptor {
  id: string;
  label: string;
  supports_resume: boolean;
  supports_provider_selection: boolean;
}

export interface CapabilityInventory {
  api_version: 1;
  enabled_plugins: string[];
  backends: BackendDescriptor[];
}
~~~

客户端遇到未知 <code>api_version</code> 时明确失败，不猜测 schema。

## 10. 认证探测

保留 <code>GET /api/auth/status</code>，响应改为动态 backend map。第一批只返回 Codex：

~~~json
{
  "backends": {
    "codex": {
      "status": "logged_in",
      "detail": {
        "binary": "C:\\path\\to\\codex.exe",
        "credentials_path": "C:\\Users\\name\\.codex\\auth.json"
      }
    }
  },
  "api_keys": {
    "openai": false
  }
}
~~~

实现：

1. 从 Backend Registry 获取当前 snapshot。
2. 并行调用每个 backend 的 <code>probe_auth()</code>。
3. 以 backend ID 为 key 组装结果。
4. 复用现有 OpenAI API key probe。

本批同步修改所有前端消费者，不保留旧顶层 <code>claude</code>/<code>codex</code> 字段，也不返回
假的 Claude 状态。

## 11. 前端迁移

### 11.1 API

<code>frontend/src/api/terminal.ts</code>：

- 删除 <code>TerminalBackend = 'claude' | 'codex'</code>。
- WebSocket 参数 backend 改为普通 <code>string</code>。
- 在同一模块增加 capability fetch；不为一个请求新建前端 Kernel 框架。
- URL 构造和帧协议不变。

<code>frontend/src/api/projects.ts</code>：

- <code>AuthStatus</code> 改为 backend map + api_keys map。
- 删除固定 Claude/Codex 字段。

### 11.2 选择规则

1. 当前 conversation backend 是 <code>codex</code> 且 inventory 含 Codex：使用它。
2. 新 conversation 默认使用 inventory 第一项；第一批即 Codex。
3. inventory 为空：禁用“新建会话”，显示“未启用 backend”。
4. 历史 conversation backend 为 <code>claude</code>：可显示历史元数据，但启动/resume 按钮
   禁用并提示“Claude 插件未启用”。
5. provider 控件按 <code>supports_provider_selection</code> 显示；第一批 Codex 为 false。

前端不能以硬编码 backend 列表判断是否可启动。Claude 专属入口在本批移除或禁用，不接回旧 API。

## 12. Conversation 与消息边界

### 12.1 写入校验

- 新建 conversation 时 backend ID 必须存在于 Backend Registry；第一批只有 Codex。
- resume/启动 terminal 时再次要求 backend 当前启用。
- 历史 Claude conversation 读取不要求插件启用。
- <code>conversation_segments.backend</code> 与 conversation backend 的现有一致性规则保持。
- <code>TurnTeer.assistant_served_by</code> 使用已由 registry 校验的 Codex ID。

### 12.2 Python 类型

<code>src/server/projects/conversations.py</code> 删除 Claude/Codex 固定集合，改为在请求边界读取
Backend Registry。

<code>src/server/projects/messages_store.py</code> 的固定 <code>ServedBy</code> Literal 改为
<code>str</code>。存储层只要求非空，调用边界负责：

- assistant 来源必须是已启用 backend ID；
- <code>user</code>、<code>system</code> 为平台保留来源；
- 遗留 <code>claude</code>、<code>mambaresearch_compact</code> 仍可读取，但本批新流程不写入。

存储层不反向依赖 Kernel registry。

## 13. SQLite 动态 ID Migration

当前 <code>MIGRATIONS</code> 为 append-only v1-v6。新增下一版本 migration，一次性重建四个含
固定 backend/source 枚举的表，不修改旧 migration。这样以后增加 Claude 插件不再改 schema。

### 13.1 新约束

以下字段改为非空、trim 后长度大于 0：

- <code>conversations.backend</code>
- <code>conversation_segments.backend</code>
- <code>mcp_calls.backend</code>
- <code>messages.served_by</code>

Registry 校验当前启用能力；数据库只校验字符串形状和索引。

### 13.2 迁移 SQL

~~~sql
BEGIN IMMEDIATE;

CREATE TABLE conversations_v7 (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT,
    created_at INTEGER NOT NULL,
    last_active_at INTEGER NOT NULL,
    backend TEXT NOT NULL DEFAULT 'codex'
        CHECK (length(trim(backend)) > 0),
    asset_kind TEXT
        CHECK (asset_kind IS NULL OR asset_kind IN (
            'experiment', 'literature', 'dataset', 'idea'
        )),
    asset_label TEXT
);
INSERT INTO conversations_v7
SELECT id, project_id, title, created_at, last_active_at,
       backend, asset_kind, asset_label
FROM conversations;
DROP TABLE conversations;
ALTER TABLE conversations_v7 RENAME TO conversations;
CREATE INDEX idx_conversations_project
    ON conversations(project_id, last_active_at DESC);
CREATE INDEX idx_conversations_asset
    ON conversations(asset_kind, last_active_at DESC);

CREATE TABLE conversation_segments_v7 (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    backend TEXT NOT NULL CHECK (length(trim(backend)) > 0),
    cli_session_id TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    handoff_prompt_path TEXT,
    UNIQUE(conversation_id, segment_index)
);
INSERT INTO conversation_segments_v7
SELECT id, conversation_id, segment_index, backend, cli_session_id,
       started_at, ended_at, handoff_prompt_path
FROM conversation_segments;
DROP TABLE conversation_segments;
ALTER TABLE conversation_segments_v7 RENAME TO conversation_segments;
CREATE INDEX idx_segments_conv
    ON conversation_segments(conversation_id, segment_index);

CREATE TABLE mcp_calls_v7 (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    segment_id TEXT,
    cli_session_id TEXT,
    backend TEXT NOT NULL CHECK (length(trim(backend)) > 0),
    server_name TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_use_id TEXT,
    input_json TEXT NOT NULL,
    output_json TEXT,
    is_error INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at INTEGER NOT NULL,
    duration_ms INTEGER
);
INSERT INTO mcp_calls_v7
SELECT id, conversation_id, segment_id, cli_session_id, backend,
       server_name, tool_name, tool_use_id, input_json, output_json,
       is_error, error, started_at, duration_ms
FROM mcp_calls;
DROP TABLE mcp_calls;
ALTER TABLE mcp_calls_v7 RENAME TO mcp_calls;
CREATE INDEX idx_mcp_calls_conv
    ON mcp_calls(conversation_id, started_at DESC);
CREATE INDEX idx_mcp_calls_tool
    ON mcp_calls(server_name, tool_name, started_at DESC);
CREATE INDEX idx_mcp_calls_session
    ON mcp_calls(cli_session_id, started_at DESC);

CREATE TABLE messages_v7 (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL
        CHECK (role IN ('user', 'assistant', 'system')),
    text TEXT NOT NULL,
    served_by TEXT NOT NULL CHECK (length(trim(served_by)) > 0),
    tool_use_summary TEXT,
    raw_payload TEXT,
    compacted INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
INSERT INTO messages_v7
SELECT id, conversation_id, role, text, served_by,
       tool_use_summary, raw_payload, compacted, created_at
FROM messages;
DROP TABLE messages;
ALTER TABLE messages_v7 RENAME TO messages;
CREATE INDEX idx_messages_conversation
    ON messages(conversation_id, created_at);

COMMIT;
~~~

说明：

- 默认值改为 <code>codex</code> 只影响未来省略 backend 的底层写入；应用请求仍必须显式传入并经
  registry 校验。
- 迁移必须保留已有 <code>claude</code>、<code>codex</code>、<code>sandbox</code> 和 legacy
  served_by 原值。
- 若实施前已有新 migration，版本号顺延，并以当时实际 schema 补齐新增列。
- 所有索引在 rename 后重建。
- 任一步失败时事务回滚，不做逐表部分提交。
- <code>PRAGMA user_version</code> 继续由现有 <code>_init_schema()</code> 在脚本成功后设置。

### 13.3 数据验证

1. 从真实 v6 schema 建立含 Claude/Codex/sandbox/legacy served_by 的样本库。
2. 记录四张表迁移前行数和所有字段。
3. 执行数据库初始化升级。
4. 确认行数、原值和索引完全保持。
5. 确认可写入第三个非空 backend ID，证明以后 Claude 插件无需 schema 迁移。
6. 确认空字符串和纯空白 backend/served_by 被拒绝。
7. 确认再次启动不重复迁移。

## 14. 唯一真相源

~~~text
configs/plugins.json
  -> Kernel selects backend.codex
  -> BackendRegistry
      -> GET /api/capabilities
      -> GET /api/auth/status
      -> conversation create validation
      -> WS /api/terminal/{backend_id}
  -> Codex LaunchSpec
  -> PtyBridge
  -> Codex CLI transcript
  -> optional TurnTeer mirror with served_by=codex
~~~

Backend Registry 是运行期唯一 backend 列表。API、auth、conversation 和 terminal 不各自维护
Codex/Claude 集合。

## 15. 最小检查矩阵

### 15.1 Contract 与 Registry

| 用例 | 期望 |
| --- | --- |
| 注册 Codex | inventory 只有 Codex |
| 注册重复 Codex ID | 启动时失败 |
| require claude/未知 ID | 错误包含当前可用 ID：codex |
| 注册 test backend | 不改 terminal route 即可 resolve launch |

### 15.2 Codex Adapter

| 用例 | 期望 |
| --- | --- |
| 新会话 | argv 为 <code>codex --no-alt-screen</code> |
| resume | argv 为 <code>codex resume --no-alt-screen ID</code> |
| 传 provider | 明确失败 |
| binary 不存在 | 明确安装提示 |
| auth 文件有效/缺失/损坏 | 保持当前 logged_in/not_logged_in/unknown 语义 |

### 15.3 Route 与前端

| 用例 | 期望 |
| --- | --- |
| Codex WS | 正常启动并收发 PTY |
| Claude WS | fatal + 1003，消息列出 codex |
| 无 cwd 且无 active project | 保持当前 fatal + 1011 |
| PTY EOF/崩溃 | 保持当前 close/fatal 语义 |
| inventory 为空 | 前端禁用新建会话 |
| 历史 Claude conversation | 元数据可读，启动/resume 禁用 |

### 15.4 Auth 与存储

| 用例 | 期望 |
| --- | --- |
| Codex enabled | capabilities/auth 都只有 codex backend |
| Codex disabled | capabilities/auth backend 均为空 |
| v6 升级动态 schema | 四表数据与索引保持 |
| 写入 test backend | 四个动态字段可保存非空 ID |

## 16. Batch 2 验收标准

- 默认 profile 只包含 <code>backend.codex</code>。
- <code>terminal.py</code> 不含 <code>SUPPORTED_BACKENDS</code>、Claude/Codex 名称分支或
  Claude 专属拼装。
- Codex 新建、resume、PTY、会话镜像和认证探测行为保持。
- <code>GET /api/capabilities</code> 完全由 Kernel/Backend Registry 生成且只返回 Codex。
- <code>GET /api/auth/status</code> 使用动态 backend map，不返回固定 Claude 字段。
- 前端 backend 选择来自 inventory，Claude 入口不接旧 API。
- 历史 Claude 数据可读，但新建/resume 被明确拒绝。
- SQLite 固定 backend/source 枚举被 append-only migration 移除，v1-v6 数据无损。
- test backend 只通过实现 contract + plugin/catalog/profile 注册接入，不修改消费者。
- 没有 feature flag、fallback、compatibility shim、双路由或空 Claude provider。

## 17. 实施顺序

1. 实现 Backend contract/registry 及最小检查。
2. 从 <code>terminal.py</code> 原样提取 Codex adapter，验证 argv。
3. 将 route 改为 registry consumer，删除旧 backend 分支和 Claude 路径。
4. 增加 capability API，迁移 Codex auth 聚合。
5. 迁移前端 capability/auth/backend 消费者。
6. 追加并验证 SQLite migration，删除固定 Python/TypeScript 类型。
7. 跑 backend、route、auth、database、frontend build 和 Codex smoke checks。

## 18. Claude 后续接入门槛

只有 Batch 2 全部验收后才新增 Claude 插件。后续 Claude 批次允许修改：

- 新增 <code>backend_claude.py</code>；
- catalog/profile 注册 <code>backend.claude</code>；
- Claude adapter 自己的 argv、provider、skill mount、MCP config 和 auth 检查。

后续 Claude 批次不得修改：

- Kernel loader/lifecycle；
- Backend Registry contract；
- terminal route 控制流；
- capability/auth 聚合 schema；
- 前端 backend 基础类型与选择规则；
- SQLite backend/source schema。

若接入 Claude 必须修改这些稳定边界，说明 Codex-first seam 未验证成功，应先修正合同，而不是为
Claude 添加特殊分支。
