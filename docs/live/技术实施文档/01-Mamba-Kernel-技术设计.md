# Mamba Kernel 技术设计

状态：待实施
依赖文档：[实施文档索引](00-实施文档索引.md)
上层设计：[Mamba Kernel 插件化架构](../架构设计/mamba-kernel-plugin-architecture.md)

## 1. 目标

把当前 <code>app.py</code> 直接导入路由、注册 startup/shutdown hook 的装配职责收敛到一个
薄 Kernel，使可选能力能够通过“manifest + register + lifecycle”接入，而不修改应用核心流程。

稳定边界是 Kernel 的装配顺序和生命周期语义；预期变化点是本地插件集合。第一批只为实际需要的
HTTP 和 backend 能力建立 typed registry，不提前实现 Research/UI/MCP 通用框架。

## 2. 非目标

- Kernel 不解析或保存 Codex transcript；未来 Claude 插件也遵守同一边界。
- Kernel 不调度 agent、不定义 conversation runtime、不接管 PTY 数据面。
- 不做 Python entry points、包扫描、远程下载和热重载。
- 不做通用依赖注入容器；插件只能拿到显式 <code>KernelContext</code>。
- 不把已有业务代码复制到插件目录；首批插件是现有模块的薄 adapter。
- 不保留旧 <code>app.py</code> 装配路径。

## 3. 目标文件边界

~~~text
src/server/kernel/
  contracts.py       # manifest、Plugin、KernelContext、KernelConfig
  registry.py        # HttpRegistry、BackendRegistry、CapabilityRegistry
  loader.py          # profile 解析、catalog 选择、依赖排序、纯注册
  lifecycle.py       # start、失败回滚、shutdown
src/server/plugins/
  catalog.py         # 仓库内受信任插件的唯一 catalog
  core_http.py       # 现有非 backend 路由的薄注册 adapter
  backend_codex.py   # Batch 2 使用
configs/
  plugins.json
app.py               # create_app()、lifespan、挂载 registry 贡献
~~~

不为每个插件创建独立 package；当单个 adapter 后续拥有多个内部模块时再拆目录。

## 4. 核心合同

合同使用 Python 3.10 已有的 <code>dataclasses</code>、<code>typing.Protocol</code> 和
<code>collections.abc</code>，不新增依赖。

### 4.1 Manifest 与配置

~~~python
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PluginManifest:
    id: str
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginConfig:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KernelConfig:
    profile: str
    plugin_ids: tuple[str, ...]
    plugins: dict[str, PluginConfig]
~~~

约束：

- plugin ID 必须匹配 <code>^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$</code>。
- <code>requires</code> 只表达插件启动顺序，不表达 Python 包依赖。
- manifest 的 ID 是持久化和 API 暴露的稳定 ID；重命名需要独立数据迁移。
- <code>PluginConfig.values</code> 只包含 profile 中对应插件的配置，不把整个环境变量表传入插件。
- profile 顶层未知字段和插件未知 ID 在启动前失败；插件内部配置字段由插件自己的解析函数校验。

### 4.2 Plugin 与 Disposer

~~~python
from collections.abc import Awaitable, Callable
from typing import Protocol, TypeAlias


AsyncDisposer: TypeAlias = Callable[[], Awaitable[None]]


class Plugin(Protocol):
    manifest: PluginManifest

    def register(self, context: "KernelContext") -> None:
        ...

    async def start(self, context: "KernelContext") -> AsyncDisposer | None:
        ...
~~~

统一使用 async disposer。同步关闭函数由 adapter 包成一个短 async 函数，避免 lifecycle 同时处理
四种返回形态。

<code>register()</code> 的硬约束：

- 只能把 immutable descriptor、provider 或 APIRouter 引用放入 registry。
- 不启动子进程、不打开数据库、不创建后台 task、不写项目文件。
- 不读取请求态或 active project。
- 注册失败时 <code>create_app()</code> 直接失败；未返回的 app 和局部 registry 被丢弃。

<code>start()</code> 的硬约束：

- 只启动该插件拥有的资源。
- 成功后返回释放这些资源的 disposer；没有资源时返回 <code>None</code>。
- start 抛错表示应用不能安全服务，Kernel 必须回滚，不静默禁用插件。

### 4.3 KernelContext

~~~python
from dataclasses import dataclass


@dataclass(frozen=True)
class KernelContext:
    config: KernelConfig
    capabilities: "CapabilityRegistry"

    def plugin_config(self, plugin_id: str) -> PluginConfig:
        return self.config.plugins[plugin_id]
~~~

Context 不提供 <code>get_service(name)</code>。以后新增 MCP 或 UI contribution 时，向
<code>CapabilityRegistry</code> 增加明确类型字段，而不是加入任意对象字典。

## 5. Capability Registry

第一条实施切片只建立两个 registry：

~~~python
class CapabilityRegistry:
    def __init__(self) -> None:
        self.http = HttpRegistry()
        self.backends = BackendRegistry()
~~~

### 5.1 HTTP Registry

~~~python
from dataclasses import dataclass
from fastapi import APIRouter


@dataclass(frozen=True)
class HttpContribution:
    id: str
    plugin_id: str
    router: APIRouter


class HttpRegistry:
    def register(
        self,
        *,
        contribution_id: str,
        plugin_id: str,
        router: APIRouter,
    ) -> None:
        ...

    def list(self) -> tuple[HttpContribution, ...]:
        ...
~~~

规则：

- <code>contribution_id</code> 全局唯一，重复立即抛 <code>DuplicateCapabilityError</code>。
- 保持成功注册顺序，<code>list()</code> 返回不可变快照。
- Registry 不调用 <code>include_router()</code>；应用工厂在全部插件注册成功后统一挂载。
- 路径冲突继续由显式 contribution ID 和 FastAPI 路由审查处理；本阶段不实现自定义路由解析器。

### 5.2 Backend Registry

Backend 的具体合同见
[Backend Registry 技术设计](02-Backend-Registry-技术设计.md)。Kernel 只要求：

~~~python
class BackendRegistry:
    def register(self, *, plugin_id: str, backend: "TerminalBackend") -> None:
        ...

    def require(self, backend_id: str) -> "TerminalBackend":
        ...

    def list(self) -> tuple["TerminalBackend", ...]:
        ...
~~~

- backend ID 从 <code>backend.descriptor.id</code> 取得并全局唯一。
- <code>require()</code> 对未知 ID 抛 <code>UnknownCapabilityError</code>，错误携带当前可用 ID。
- <code>list()</code> 保持注册顺序，供 capability API 和认证聚合共同消费。

## 6. Profile 与 Catalog

### 6.1 Profile 文件

<code>configs/plugins.json</code> 第一版只支持一个明确 schema：

~~~json
{
  "profile": "default",
  "plugins": [
    {"id": "core.http"},
    {"id": "backend.codex"}
  ]
}
~~~

允许插件项增加一个 <code>config</code> object；没有配置时省略。顶层只允许
<code>profile</code> 和 <code>plugins</code>，插件项只允许 <code>id</code> 和
<code>config</code>。

不读取 overlay、不做 deep merge、不从环境变量隐式增删插件。需要第二套真实部署组合时，再为
profile path 增加一个显式启动参数。

### 6.2 Built-in Catalog

<code>src/server/plugins/catalog.py</code> 是受信任本地插件的唯一发现入口：

~~~python
def builtin_plugins() -> tuple[Plugin, ...]:
    return (
        CoreHttpPlugin(),
        CodexBackendPlugin(),
    )
~~~

显式 catalog 比 import 扫描更可预测，也满足当前“添加一个文件并注册一次”的扩展成本。
<code>app.py</code> 不导入具体业务 router 或 backend。

Catalog 校验：

1. 每个对象必须满足 Plugin contract。
2. manifest ID 必须合法且唯一。
3. profile 中每个 ID 必须存在。
4. profile 不得重复启用同一个 ID。

## 7. 依赖解析

Loader 先完成所有校验，再调用任何 <code>register()</code>。

输入：

- catalog 中的插件；
- profile 中启用 ID 的顺序；
- 每个 manifest 的 <code>requires</code>。

输出：稳定的依赖拓扑序。依赖关系相同的插件保持 profile 顺序。

处理规则：

| 情况 | 结果 |
| --- | --- |
| profile 引用未知插件 | <code>UnknownPluginError</code>，列出未知 ID |
| catalog/profile 重复 ID | <code>DuplicatePluginError</code> |
| required 插件未启用 | <code>MissingPluginDependencyError</code>，包含 owner 与 dependency |
| 自依赖或依赖环 | <code>PluginDependencyCycleError</code>，包含闭环路径 |
| 合法 DAG | 返回每个插件一次，dependency 一定先于 consumer |

实现使用深度优先搜索的三色状态（unvisited/visiting/visited），因为插件数量很小且需要直接产出
闭环路径；不引入图算法依赖。

## 8. 应用装配顺序

<code>create_app()</code> 的完整顺序固定为：

~~~text
1. load configs/plugins.json
2. build and validate built-in catalog
3. select enabled plugins
4. validate dependencies and calculate stable order
5. create empty CapabilityRegistry
6. create KernelContext
7. call plugin.register(context) in dependency order
8. create FastAPI(lifespan=...)
9. include every registered HTTP contribution
10. expose app.state.kernel for route dependencies
11. return app
~~~

如果 1-7 任一步失败，应用对象不进入服务状态。步骤 9 不再与具体插件名称绑定。

<code>app.py</code> 最终只保留：

~~~python
def create_app() -> FastAPI:
    loaded = load_kernel(...)
    app = FastAPI(lifespan=build_lifespan(loaded))
    app.state.kernel = loaded
    for contribution in loaded.context.capabilities.http.list():
        app.include_router(contribution.router)
    return app


app = create_app()
~~~

实际实现沿用当前 FastAPI 参数和中间件；这里只冻结装配职责，不要求重建 app 配置。

## 9. 生命周期

### 9.1 正常启动与关闭

~~~text
lifespan enter:
  started = []
  for plugin in dependency order:
      disposer = await plugin.start(context)
      if disposer is not None:
          started.append((plugin.id, disposer))
  yield

lifespan exit:
  call every disposer in reverse started order
~~~

插件停止顺序必须与成功 start 顺序相反，保证 consumer 先于 dependency 释放。

### 9.2 部分启动失败

当第 N 个插件 start 失败：

1. 不进入 <code>yield</code>，应用不接收请求。
2. 对前 N-1 个插件返回的 disposer 逆序逐个调用。
3. 即使某个 disposer 失败，也继续释放剩余 disposer。
4. 所有 disposer 完成后重新抛出原始 start 异常。
5. disposer 异常作为原始异常的附加上下文记录，不替换根因。

Python 最低版本为 3.10，因此不依赖 <code>ExceptionGroup</code>。实现保留首个 start 异常，
清理异常只通过现有日志系统报告。

### 9.3 正常关闭中的 disposer 失败

正常 shutdown 仍尝试全部 disposer。结束后抛出第一个 disposer 异常，使进程退出失败可见；
后续异常通过现有日志系统报告。Kernel 不重试关闭，也不吞掉所有失败。

## 10. 现有资源归属

Batch 1 只改变 owner，不改资源实现：

| 当前资源/行为 | 新 owner | 处理 |
| --- | --- | --- |
| 固定业务 router 导入与挂载 | <code>core.http</code> | register 时贡献现有 router |
| MambaDb connect/close | <code>core.http</code> 或其最小 core resource adapter | lifespan start/disposer |
| Codex session manager | <code>backend.codex</code> | Batch 2 移入 start/disposer |
| Codex PTY 子进程 | 每个 WS 的 <code>PtyBridge</code> | 不变，不成为全局资源 |
| 外部 CLI transcript | 外部 CLI | 不变 |

若当前 app 还有其他 startup/shutdown hook，实施时逐个放入拥有该资源的插件；禁止为了过渡同时从
旧 hook 和插件启动同一资源。

## 11. Capability API 所需 Kernel 快照

Kernel 提供只读快照，不暴露内部对象：

~~~python
@dataclass(frozen=True)
class KernelSnapshot:
    api_version: int
    enabled_plugins: tuple[str, ...]
~~~

<code>api_version</code> 第一版固定为 <code>1</code>。Backend descriptor 由 Backend Registry
附加，最终响应见下一份文档。快照不得包含插件 config、环境变量、路径凭据或 disposer。

## 12. 错误类型

Kernel 定义一组窄错误，全部继承 <code>KernelConfigurationError</code>：

- <code>InvalidProfileError</code>
- <code>InvalidPluginIdError</code>
- <code>DuplicatePluginError</code>
- <code>UnknownPluginError</code>
- <code>MissingPluginDependencyError</code>
- <code>PluginDependencyCycleError</code>
- <code>DuplicateCapabilityError</code>
- <code>UnknownCapabilityError</code>

启动配置错误不转换成 HTTP 200 或空列表。请求期的
<code>UnknownCapabilityError</code> 由具体 route 转换成协议错误。

## 13. 最小检查矩阵

### 13.1 Loader

| 用例 | 期望 |
| --- | --- |
| profile 顺序 A、B，无依赖 | 输出 A、B |
| B requires A，profile 为 B、A | 输出 A、B |
| A requires X，X 未启用 | 启动前失败，未调用任何 register |
| A requires B，B requires A | 返回包含 A/B 的闭环错误 |
| profile 重复 A | 启动前失败 |
| 两个 catalog plugin ID 相同 | 启动前失败 |

### 13.2 Registry

| 用例 | 期望 |
| --- | --- |
| 注册两个 HTTP contribution | 快照保持注册顺序 |
| 重复 contribution ID | 第二次注册失败 |
| 重复 backend ID | 第二次注册失败 |
| require 未知 backend | 错误包含当前可用 backend IDs |

### 13.3 Lifecycle

| 用例 | 期望调用序列 |
| --- | --- |
| A、B 正常 | start A, start B, dispose B, dispose A |
| B start 失败 | start A, start B, dispose A, rethrow B error |
| dispose B 失败 | 仍调用 dispose A，最终 shutdown 失败 |
| register 失败 | 没有任何 start/dispose |

这些是 Kernel 非平凡逻辑的必要检查；不为纯 dataclass 或简单 getter 增加重复测试。

## 14. Batch 1 验收标准

- <code>app.py</code> 不再逐个导入业务 router。
- 所有 route 在完整注册成功后统一挂载。
- <code>create_app()</code> 期间没有数据库连接、子进程或后台 task。
- lifespan 负责所有进程级资源的启动和逆序释放。
- 重复 ID、缺失依赖、依赖环在服务启动前产生确定性错误。
- 失败启动能释放已经成功启动的资源。
- 禁用 profile 中一个插件时，不挂载该插件贡献；不修改业务 route。
- 现有 HTTP 路由行为保持。
- 默认 profile 只启用 <code>backend.codex</code>；不创建 Claude adapter 或兼容入口。
- 没有 Cordis、entry points、热重载、远程插件或通用 service locator。

## 15. 实施顺序

1. 先实现 contracts、registry、loader、lifecycle 及其最小检查。
2. 建立 <code>core.http</code> adapter，把现有 route 引用原样注册。
3. 将现有启动/关闭 hook 移到对应插件 lifecycle，并删除旧 hook。
4. 改造 <code>create_app()</code>，删除 <code>app.py</code> 中的业务枚举。
5. 跑现有后端测试与应用启动 smoke check。
6. 通过 Batch 1 验收后，再实施 Backend Registry。
