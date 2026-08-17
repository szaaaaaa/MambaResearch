# Research MCP Registry 技术设计

状态：已完成（Batch 3，步骤 1-7 已实施）
依赖文档：[实施文档索引](00-实施文档索引.md)
上层设计：[Mamba Kernel 插件化架构](../架构设计/mamba-kernel-plugin-architecture.md)
强制规范：[代码实现规范](../代码规范/01-代码实现规范.md)、
[测试规范](../代码规范/03-测试规范.md)

实施记录（2026-08-17）：

- 已完成第 15 节步骤 1-7：六个 Research plugin、Kernel `McpRegistry`、项目选择校验、Codex
  new/resume 注入、合法 server ID TOML 编码、API 脱敏、旧入口删除和真实 smoke 均已完成。
- 已通过：完整测试集 `34 passed`；前端 lint/build；`git diff --check`；已登录 Codex CLI
  0.147.0 的 new/resume、`/mcp`、Workspace cwd 和会话关闭后进程清理 smoke。

当前要求核验：

| 要求 | 状态 | 证据或缺口 |
| --- | --- | --- |
| 六个 provider 的唯一 Research owner | 已实施 | Catalog/Profile 只注册 `research.*`，中央 helper 枚举已删除 |
| Workspace/Zotero MCP 与 HTTP 同 owner | 已实施 | plugin 原子测试和禁用 Zotero 集成流程通过 |
| project selection 在 PATCH/launch 生效 | 已实施 | 缺失/空/子集/重复/未知路径测试通过 |
| Codex new/resume 消费同一 Registry snapshot | 已实施 | 内建合法 server ID 由标准 TOML 解析并经真实 new/resume 验证 |
| secret 不进入 argv/list/detail | 已实施 | 生产序列化统一脱敏；集成测试显式断言列表、详情与 argv |
| 旧生产入口、flag、re-export 删除 | 已实施 | 静态配置、旧枚举、旧开关、例外规则和 UI 旧说明均已删除 |
| 完整自动化与构建 | 已实施 | `pytest tests` 34 passed，lint/build 与 `git diff --check` 通过 |
| 真实 Codex new/resume smoke | 已实施 | Codex 0.147.0 new/resume、MCP/cwd 与进程清理通过 |

## 1. 目标

让启用的 Research plugin 成为内建 MCP server 和所属 HTTP route 的唯一 owner，并让
`backend.codex` 在每次 new/resume 启动时只从 Kernel MCP Registry 取得 Mamba 托管的
server 快照。

本批必须一次完成六个内建 Research MCP server 的迁移。只迁移 Workspace/Zotero 会让其余
server 继续依赖旧 helper 枚举，形成两个 builtin 来源，不满足“一项能力只有一个入口”。

完成后的核心行为是：

~~~text
configs/plugins.json
  -> Kernel 选择 Research plugins
  -> Research plugins 注册 MCP provider / 自有 HTTP route
  -> McpRegistry 形成唯一 Mamba-managed snapshot
  -> project enabled_mcp_servers 选择本次会话子集
  -> CodexTerminalBackend 生成 -c mcp_servers.<id>=<inline table>
  -> PtyBridge 使用合并后的 LaunchSpec.env 启动 Codex
  -> Codex 启动所选 MCP 子进程
~~~

## 2. 当前问题

现有路径没有把“插件已启用”传递到真实 Codex 进程：

1. `src/server/mcp/registry.py` 直接 import 六个 `default_mcp_config()`，绕过 Kernel。
2. `.codex/config.toml` 手工镜像五个内建 server，且只在 Codex 认可该项目配置时生效。
3. Codex 实际以 active research project 为 cwd，不保证读取 MambaResearch 仓库的
   `.codex/config.toml`。
4. `CodexTerminalBackend` 不消费 Python MCP registry，插件启停不会改变 Codex 能力。
5. `CoreHttpPlugin` 直接枚举 Workspace/Zotero route，禁用 Research plugin 也不能移除 route。
6. `<project>/.mambaresearch/config.json` 已有 `enabled_mcp_servers`，但启动路径未消费。
7. `McpServerInfo.to_dict()` 原样返回 `env` 值，列表/详情 API 可能泄露 API key。

因此，继续补静态 TOML 或只增加一个 Python registry 都不能解决根因。唯一生产路径必须在
Codex `LaunchSpec` 生成前闭合。

## 3. 非目标

- 不实现 Claude backend、Claude SDK `mcp_servers` adapter 或 `.mcp.json` 注入 Claude。
- 不建立 frontend plugin registry；Research 前端入口迁移属于 Batch 4。
- 不移动或复制六个 MCP server、Workspace、Zotero 的业务实现文件。
- 不重写 MCP 协议、probe、sandbox、call logger 或现有 tool schema。
- 不实现远程插件、运行时热重载、通用 DI 容器或 MCP 进程常驻管理器。
- 不把用户自定义 `.mcp.json` 注入 Codex。本批继续保留其 MCP 控制台 probe/sandbox 用途；
  Codex 自定义 server 继续使用 Codex 原生 user/active-project config。
- 不为未来 HTTP/SSE provider 扩展合同；六个当前 provider 都是 stdio。

## 4. 原子行为合同

### 4.1 MCP provider

每个 provider 必须给出：

- 稳定 server ID 和显示名称；
- 非空 `command`；
- 有序 `args`；
- 当前启动需要转发的 `env` key/value；
- `stdio` transport。

provider 配置在每次 `resolve_launch()` 时解析，使 MCP env override 保存后可用于下一次 Codex
会话，不要求重启 MambaResearch。配置缺字段、ID 不一致或值类型非法时，启动明确失败。

最小合同只覆盖当前真实存在的 stdio provider：

~~~python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class McpStdioConfig:
    command: str
    args: tuple[str, ...]
    env: dict[str, str]


class McpServerProvider(Protocol):
    id: str
    label: str

    def resolve_config(self) -> McpStdioConfig:
        ...
~~~

`resolve_config()` 不接收 research project path。provider 自己解析 MambaResearch 代码根和
server-local env override；会话 cwd 由 Codex backend 以 `MAMBA_ACTIVE_PROJECT_PATH` 注入。
这两个路径不能共用一个 `root` 参数。

### 4.2 McpRegistry

~~~python
class McpRegistry:
    def register(self, *, plugin_id: str, provider: McpServerProvider) -> None:
        ...

    def require(self, server_id: str) -> McpServerProvider:
        ...

    def list(self) -> tuple[McpServerProvider, ...]:
        ...
~~~

规则：

- server ID 从 provider 取得，必须是可信内建 ID。
- 重复 server ID 在应用创建时抛 `DuplicateCapabilityError`，不覆盖。
- `require()` 对未知 ID 抛 `UnknownCapabilityError`，错误列出当前可用 IDs。
- `list()` 保持插件注册顺序，返回不可变快照。
- Registry 不读取文件、不启动 MCP 进程、不合并 secret，也不承担 backend 参数格式转换。

`CapabilityRegistry` 只增加一个明确字段：

~~~python
self.mcp = McpRegistry()
~~~

不增加通用 service map、factory 或 event bus。

### 4.3 Research plugin

Research plugin 的 `register()` 只注册 provider 和可选 HTTP router；`start()` 没有新增进程级
资源，返回 `None`。MCP 进程仍由 Codex 或 sandbox probe 按需创建和关闭。

六个薄插件放在一个 `src/server/plugins/research.py` 中，避免为只有十余行 wiring 的 adapter
预建六个 package。每个实例仍有独立 manifest、provider ID 和 contribution，owner 不合并。

## 5. Owner 与 ID 映射

| Plugin ID | MCP server ID | 复用实现 | HTTP contribution |
| --- | --- | --- | --- |
| `research.workspace` | `mamba_workspace` | `src.server.workspace.mcp_server` | Workspace router |
| `research.zotero` | `mamba_zotero` | `src.server.integrations.zotero.mcp_server` | Library/Zotero router |
| `research.experiment` | `mamba_experiment` | `src.server.integrations.experiment.mcp_server` | 无 |
| `research.paper_search` | `paper_search` | `paper_search_mcp.server` | 无 |
| `research.colab` | `mamba_colab` | `src.server.integrations.colab.mcp_server` | 无 |
| `research.mamba_history` | `mamba_history` | `src.server.integrations.mamba_history.mcp_server` | 无 |

默认 profile 按上表顺序在 `core.http`、`backend.codex` 后启用六个插件。Catalog 仍是仓库内
可信插件的唯一枚举位置；`app.py`、route 和 backend 不枚举 Research plugin 名称。

server 的 command/args 继续复用各 MCP 模块现有 `default_mcp_config()` 作为 server-local
配置构造器；本批删除其中 Claude 专属说明和环境 feature flag 分支。helper 只能被所属
Research plugin 调用，不再被中央 registry 或 package re-export 调用。

## 6. HTTP 所有权迁移

`research.workspace` 注册现有 Workspace router，`research.zotero` 注册现有 Library/Zotero
router。业务 route 文件与 handler 不移动。

`CoreHttpPlugin` 同批删除：

- `workspace_router` import 和中央 `include_router()`；
- `library_router` import 和中央 `include_router()`。

MCP 管理、project config、capability、auth、conversation、terminal 等跨插件平台 route 继续
由 `core.http` 拥有。禁用 `research.zotero` 后，MCP Registry 和 FastAPI route table 都不得
出现 Zotero；不通过 route 内判断或 feature flag 模拟禁用。

## 7. 项目级选择

`<launch cwd>/.mambaresearch/config.json` 的现有字段正式生效：

~~~json
{
  "enabled_mcp_servers": ["paper_search", "mamba_history"]
}
~~~

语义冻结为：

1. 字段缺失或空数组：选择当前 McpRegistry 的全部 provider，保持 registry 顺序。
2. 非空数组：按数组顺序选择对应 server ID。
3. 元素必须是非空字符串；重复、未知或当前 profile 未启用的 ID 明确失败。
4. project config 只能缩小 profile 已启用集合，不能重新启用被 profile 禁用的插件。
5. PATCH 边界立即校验；launch 边界再次校验磁盘内容，防止外部手工改坏文件。

项目配置读取必须以 `LaunchRequest.cwd` 为准，不能隐式读取另一个 active project。现有
`active_project_config()` 提取复用一个按 project root 读取的函数；HTTP PATCH 仍只修改当前
active project。

该字段此前未被生产启动路径消费，schema 不变，不需要数据库 migration。已有符合上述规则的
值直接生效；非法旧值不静默忽略，也不回退为“全部启用”。

## 8. Codex 启动注入

`CodexBackendPlugin.register()` 把 `context.capabilities.mcp` 注入
`CodexTerminalBackend`。Backend 持有 registry 引用，但只在每次 `resolve_launch()` 开始时调用
`list()` 取得快照；不能在 backend 注册时提前缓存空列表。这样 Research plugin 即使在 profile
中排在 `backend.codex` 后注册，启动时仍能看到完整 provider 集合。

### 8.1 参数位置

Codex 支持全局 `-c/--config key=value` override。每个被选 provider 生成一个完整 server
inline table：

~~~text
-c
mcp_servers.mamba_workspace={command="...",args=[...],env_vars=[...],enabled=true}
~~~

完整 table 覆盖同名 Codex 原生配置，Mamba 托管 ID 不与 user config 拼成半张表。字符串和数组
使用一个确定性 TOML literal formatter 生成；不经 shell 拼接，不新增 TOML 写依赖。

全局 override 必须位于 `resume` 子命令之前：

~~~text
new:
  codex -c <server-1> ... -c <server-n> --no-alt-screen

resume:
  codex -c <server-1> ... -c <server-n> resume --no-alt-screen <session-id>
~~~

new 和 resume 必须消费同一次调用取得的 provider snapshot 和 project selection，不能让 resume
走静态配置或另一套 helper。

### 8.2 环境与 secret

对所选 provider：

1. 解析 config，收集所有 provider env。
2. 不同 provider 对同一 key 给出相同值时合并一次；给出不同值时抛 `BackendLaunchError`。
3. 使用 `build_subprocess_env(extra=...)` 合并到 `LaunchSpec.env`。
4. 强制把 `MAMBA_ACTIVE_PROJECT_PATH` 设为 `str(LaunchRequest.cwd)`，覆盖进程中可能陈旧的
   active project 值。
5. 每个 Codex inline table 的 `env_vars` 都包含 `MAMBA_ACTIVE_PROJECT_PATH` 和该 provider 的
   env keys；只写 key，不写 value，让 Codex 从自己的环境转发给 MCP 子进程。

硬性安全合同：

- env value、API key、token 不得出现在 argv、日志或 capability payload。
- 未选择 provider 的 env 不合并到 Codex 进程。
- `PYTHONPATH` 继续指向 MambaResearch 代码仓库根，不能误用 research project cwd。
- provider 配置、project selection 或 env 合并失败时终止启动，不 fallback 到 `.codex/config.toml`。

本机已验证 Codex CLI 接受完整 inline table 和 `env_vars`：

~~~powershell
codex.cmd -c "mcp_servers.mamba_probe={command='python',args=['-V'],env_vars=['MAMBA_PROBE_SECRET'],enabled=true}" mcp list --json
~~~

## 9. MCP 管理 API

`src/server/mcp/registry.py` 保留外部配置读取、去重和 UI/probe 聚合职责，但不再发现内建
server。调用方把当前 Kernel McpRegistry snapshot 显式传入；聚合顺序为：

1. Mamba-managed snapshot；
2. active research project 的 Codex config；
3. Codex user config；
4. MCP 控制台使用的 `.mcp.json`。

同名条目仍以先出现的配置为准并累计 source 元数据。`builtin_helper` source label 改为
`mamba_managed`，旧 label 同批删除。

`src/server/mcp/config_io.py` 不再维护 `_BUILTIN_NAMES`。自定义 server 新增/删除操作从当前
McpRegistry snapshot 取得保护 ID 集合，不能覆盖任何已启用的 Mamba-managed provider。

### 9.1 Secret 响应合同

`GET /api/mcp/servers` 和 `GET /api/mcp/servers/{name}` 只返回 env key，所有 value 使用固定
脱敏值；不得调用 `dict(self.env)` 原样序列化。前端现有消费者只读取 key，可保持响应字段形状。

实际 user override value 只由专用端点读取和修改：

~~~text
GET/PATCH /api/mcp/servers/{name}/env
~~~

该端点继续只允许修改 env，不允许修改 command、args、url 或 transport。

## 10. Codex 原生配置边界

MambaResearch 只注入自身托管 provider。Codex 仍按自身规则加载 user config 和
`LaunchRequest.cwd` 下的 project config；未与 Mamba-managed ID 重名的原生 server 不受影响。

仓库 `.codex/config.toml` 当前只有内建 Research MCP 镜像，且不是 active research project 的
可靠配置源，因此本批删除整个文件。不得生成新的临时 TOML、修改用户 `~/.codex/config.toml`
或把 Mamba server 写入每个 research project。

`.mcp.json` 当前只服务 Mamba MCP 控制台的自定义 probe/sandbox，不宣称 Codex 会自动读取。
需要从 UI 管理 Codex 自定义 server 时另立真实需求，直接写 Codex 支持的配置格式，不增加镜像。

## 11. 错误语义

| 条件 | 结果 |
| --- | --- |
| 重复 MCP provider ID | 应用创建失败，`DuplicateCapabilityError` |
| project selection 类型错误/重复/未知/未启用 | PATCH 返回 400；launch 抛 `BackendLaunchError` |
| provider 返回空 command、错误 ID 或非法 env | `BackendLaunchError`，不启动 PTY |
| provider env key 值冲突 | `BackendLaunchError`，列出 key 和 provider IDs，不回显 values |
| TOML literal 无法生成 | `BackendLaunchError`，不 fallback |
| 无 active project 且未传 cwd | 保持现有 terminal fatal + 1011 |
| Codex binary 不存在 | 保持现有安装提示 |

错误消息可以包含 server ID、env key 和配置路径，不能包含 env value。

## 12. 旧实现删除清单

### 12.1 生产代码与装配

- `src/server/mcp/registry.py`
  - 删除 `_read_builtin_helpers()`；
  - 删除六个 `default_mcp_config` direct imports；
  - 删除固定 helper tuple 和 builtin-first 自发现分支。
- `src/server/mcp/config_io.py`
  - 删除 `_BUILTIN_NAMES`；
  - 删除“`.mcp.json` 会通过镜像被 Codex 识别”的失效说明。
- `src/server/plugins/core_http.py`
  - 删除 Workspace/Library router imports 和中央枚举。
- 六个 `default_mcp_config()`
  - 删除 `MAMBA_*_MCP_DISABLED` 分支；
  - 删除 Claude SDK、session manager 和旧双路径说明；
  - 保留并改为所属 plugin 独占消费的 server-local 配置构造逻辑。
- `src/server/integrations/paper_search/__init__.py`
  - 删除只服务旧入口的 `default_mcp_config` re-export。
- `src/server/integrations/mamba_history/__init__.py`
  - 删除只服务旧入口的 `default_mcp_config` re-export。

### 12.2 配置

- 删除仓库 `.codex/config.toml` 的整个内建 MCP 镜像文件。
- 删除以下环境 feature flags 及所有读取/文档：
  - `MAMBA_WORKSPACE_MCP_DISABLED`
  - `MAMBA_ZOTERO_MCP_DISABLED`
  - `MAMBA_COLAB_MCP_DISABLED`
  - `MAMBA_EXPERIMENT_MCP_DISABLED`
  - `MAMBA_HISTORY_MCP_DISABLED`

插件启停只由 profile 控制，会话内选择只由 `enabled_mcp_servers` 缩小；不保留第三条开关路径。

### 12.3 测试与文档

- 删除被新 registry/plugin/Codex launch 行为测试替代的旧 helper 枚举测试；当前测试树没有必须
  保留的专用 legacy MCP 测试文件。
- 更新 `README.md`、`CLAUDE.md` 和 `docs/live` 中 `_read_builtin_helpers`、Claude SDK 注入、
  静态 `.codex/config.toml` 镜像及旧 feature flag 说明。
- 删除注释中的 Stage/Task 旧装配叙述；保留仍解释业务协议的注释。

MCP server/domain 实现文件不移动、不复制、不保留第二份 adapter。

## 13. 数据与配置迁移

本批没有 SQLite schema 变化，也不新增 migration。

持久化处理只有现有 JSON 字段语义启用：

- 缺失/空 `enabled_mcp_servers` 继续表示全部 Mamba-managed server；
- 合法非空列表直接生效；
- 非数组、非字符串、重复和未知值在边界明确失败；
- 不自动改写用户文件，不把非法值静默删除。

`configs/mcp/env_overrides.json` 格式和数据保留。其值只进入所选 provider 的 launch env。

## 14. 最小测试矩阵

### 14.1 Kernel 与 plugin 原子测试

扩展 `tests/server/kernel/test_kernel.py`：

- McpRegistry 保持注册顺序并返回 snapshot；
- 重复 MCP server ID 失败。

新增一个 `tests/server/plugins/test_research.py`：

- 用参数化用例验证六个 plugin ID 到 server ID 的映射；
- Workspace/Zotero 各自同时贡献 MCP 与 HTTP，其余只贡献 MCP；
- 不为六个同构 provider 建六个测试文件。

### 14.2 Codex adapter 原子测试

扩展 `tests/server/plugins/backend_codex/test_backend.py`：

- new/resume 都在正确位置注入同一组 `-c`；
- project 缺失/空选择全部，非空按顺序选择子集；
- 重复、未知、未启用 server ID 明确失败；
- argv 不含 provider env value，只含 env key；
- provider env 冲突失败且错误不泄露 value；
- `LaunchSpec.env[MAMBA_ACTIVE_PROJECT_PATH]` 等于 request cwd。

字符串 escaping 使用包含空格和 Windows 反斜杠的一个代表用例，不复制等价测试。

### 14.3 Server 集成测试

新增 `tests/server/integration/test_research_plugins.py`，使用真实 Kernel/app 和 fake Codex/PTy
边界覆盖两个高价值流程：

1. 默认 profile 下，Codex launch snapshot 与六个 Research plugin 一致，Workspace/Zotero
   MCP 和 HTTP route 同时存在。
2. 禁用 `research.zotero` 后，`mamba_zotero` 和 Zotero API route 同时消失，project config
   不能把它重新启用。

同文件验证 `/api/mcp/servers` 与详情响应不包含已配置 secret value。更新
`tests/server/integration/test_codex_flow.py` 的默认 enabled plugin 断言。

不启动真实 Codex，不为 dataclass/getter、静态字段或六个同构 provider 重复写测试。

## 15. 实施顺序

1. 增加 MCP contract/registry 及 Kernel 最小测试。
2. 增加六个 Research plugin，更新 catalog/profile，迁移 Workspace/Zotero HTTP owner。
3. 让 MCP 管理 API 消费 Kernel snapshot，删除中央 builtin helper 枚举并完成 secret 脱敏。
4. 校验并消费 project `enabled_mcp_servers`。
5. 在 Codex adapter 生成 inline table、合并 env，并同时覆盖 new/resume。
6. 删除仓库 `.codex/config.toml`、旧 feature flags、re-export、旧测试和失效文档。
7. 执行 test-prune、残留扫描、完整测试、前端构建和真实 Codex smoke。

步骤 2-6 属于同一个 Batch，不允许在合并状态中保留静态 TOML 或 helper 自发现作为 fallback。

## 16. 验证命令

~~~powershell
pytest tests/server/kernel/test_kernel.py tests/server/plugins/test_research.py tests/server/plugins/backend_codex/test_backend.py tests/server/integration/test_research_plugins.py tests/server/integration/test_codex_flow.py
pytest tests
npm.cmd run lint --prefix frontend
npm.cmd run build --prefix frontend
git diff --check
~~~

残留扫描至少执行：

~~~powershell
rg -n "_read_builtin_helpers|builtin_helper|MAMBA_(WORKSPACE|ZOTERO|COLAB|EXPERIMENT|HISTORY)_MCP_DISABLED" src tests configs docs/live README.md CLAUDE.md
rg -n "default_mcp_config" src tests docs/live README.md CLAUDE.md
rg -n "mamba_workspace|mamba_zotero|mamba_experiment|paper_search|mamba_colab|mamba_history" .codex src/server/plugins src/server/mcp configs tests docs/live
rg -n "legacy|deprecated|fallback|compat|xfail|skip" src tests docs/live
~~~

`default_mcp_config` 的预期剩余命中只能是六个 server-local 构造器及其所属 Research plugin
调用；任何中央枚举、package re-export 或 Claude 注入命中都必须删除。

真实 smoke 使用已登录 Codex：从一个 active research project 启动 new 和 resume 会话，确认
`/mcp` 能看到项目选择的 Mamba-managed servers，调用 Workspace 工具时读取的项目路径等于
会话 cwd，关闭会话后没有遗留 PTY/MCP 子进程。

## 17. Batch 3 完成定义

- 六个内建 Research MCP server 都只由对应 plugin 注册。
- Codex new/resume 都只消费 McpRegistry snapshot，没有静态镜像或 helper 自发现旁路。
- `enabled_mcp_servers` 在 PATCH 和 launch 边界按冻结语义校验并生效。
- 禁用 Workspace/Zotero plugin 会同时移除其 MCP provider 和 HTTP route。
- secret 不出现在 argv、日志、server 列表或详情响应。
- `.codex/config.toml` 内建镜像、旧环境 feature flags、direct imports 和 re-export 已删除。
- 无数据库 migration；现有合法 project config 与 env override 数据保持。
- 最小原子测试、Research 集成流程、完整 `pytest tests`、frontend lint/build、残留扫描、
  `git diff --check` 和真实 Codex smoke 全部通过。
- 前端入口仍由当前静态 UI 负责，并明确留给 Batch 4；本批不增加硬编码隐藏分支伪装 UI 插件化。

任一项未满足，Batch 3 状态必须保持“未完成”或“部分完成”，不能把删除旧路径推迟为清理任务。

## 18. Codex CLI 依据

- [Developer commands](https://learn.chatgpt.com/docs/developer-commands)
- [Configuration precedence](https://learn.chatgpt.com/docs/config-file/config-basic#configuration-precedence)
- [One-off CLI overrides](https://learn.chatgpt.com/docs/config-file/config-advanced#one-off-overrides-from-the-cli)
- [Model Context Protocol](https://learn.chatgpt.com/docs/extend/mcp)
