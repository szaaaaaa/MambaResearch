# Frontend UI Plugin Registry 技术设计

状态：待实施（Batch 4；Phase 3 真实 Codex smoke 已通过）
依赖文档：[实施文档索引](00-实施文档索引.md)
上层设计：[Mamba Kernel 插件化架构](../架构设计/mamba-kernel-plugin-architecture.md)
强制规范：[代码实现规范](../代码规范/01-代码实现规范.md)、
[测试规范](../代码规范/03-测试规范.md)

## 1. 阶段结论与进入门禁

下一开发阶段是 **Phase 4 / Batch 4：Frontend UI seam**，不是 Phase 5 外部插件，也不是继续为
Research MCP 增加第二套前端隐藏逻辑。

截至 2026-08-17，Phase 3 的生产路径、删除项、自动化验证和真实已登录 Codex smoke 均已完成。
Codex 0.147.0 的 new/resume、项目 MCP 列表、Workspace cwd 和 PTY/MCP 进程清理均已实测；
严格 `pytest tests` 完成 34 项测试。Batch 3 已完成，Batch 4 进入门禁已开放。

Batch 4 开工前必须同时满足：

1. 在已登录 Codex 0.147.0 或当时项目支持版本上完成 new 和 resume。
2. `/mcp` 能看到项目所选 Mamba-managed servers。
3. Workspace 工具读取的项目路径等于会话 cwd。
4. 关闭会话后没有遗留 PTY/MCP 子进程。
5. 删除 `tests/.tmp_ship`，确认没有生产脚本继续向 `tests/` 写运行产物，并让严格
   `pytest tests` 完成收集和执行。

以上是 Batch 4 的进入门禁，不属于 Batch 4 UI 实现；本轮已全部满足。

## 2. 目标

把当前散落在 `App.tsx`、`MambaSidebar.tsx` 和 `SettingsModal.tsx` 的 UI 装配职责切换为一个
编译期 UI contribution registry，并让它只发布后端 `GET /api/capabilities` 声明为已启用的插件。

完成后的唯一生产流：

~~~text
Vite import.meta.glob 编译本地 plugin.tsx
  + GET /api/capabilities.enabled_plugins
  + GET /api/capabilities.backends
  -> 校验并过滤 UiPluginContribution
  -> 生成 nav / view / settings / backend UI registry
  -> Sidebar、App、Settings、Auth 消费同一 registry
~~~

本批必须达到：

- 插件模块独占声明自己的可见页面、导航、设置项和 backend UI 元数据。
- UI shell 只消费 contribution，不枚举具体插件 ID 或 view key。
- `GET /api/capabilities` 在浏览器应用生命周期内只有一个共享 inventory owner。
- 禁用 `research.workspace` 或 `research.zotero` 时，对应入口和页面同时从可选集合消失。
- 新增一个仓库内本地 view plugin 时，不修改 Sidebar、App 的页面 switch 或合法 key 列表。

## 3. 当前问题

当前 UI 已能消费 backend inventory，但插件启停没有贯穿页面装配：

1. `MambaSidebar.tsx` 用 `NavId` 和 `NAV_GROUPS` 枚举全部入口。
2. `App.tsx` 维护另一份合法 view key 列表，并用 `switch (activeNav)` 再枚举一次页面。
3. `SettingsModal.tsx` 用 `CATEGORIES` 和 `renderSection()` 第三次维护静态装配。
4. Sidebar、TopBar、Workbench 各自请求 `GET /api/capabilities`，同一 inventory 没有唯一 owner。
5. `App.tsx` 用字面量 `bench` 处理默认页和 composer 跳转，核心 shell 知道具体 backend 页面。
6. `AuthPopover.tsx` 用 `${backend.id} login` 猜测登录命令。
7. Bucket、Asset Drawer、Drafts 和 MCP call history 仍有 Codex/Claude 名称或颜色分支，新增
   backend 会被错误显示成 Claude 或落入固定联合类型。

只把 `NAV_GROUPS` 搬到另一个公共文件不会解决问题：App switch、Settings switch 和 capability
重复请求仍是第二入口。本批必须在同一替换中切换所有 consumer 并删除旧装配。

## 4. 非目标

- 不实现远程 UI、动态下载、npm 插件安装、插件市场、签名、沙箱或热重载。
- 不引入 Cordis、通用 DI、event bus、hook framework、renderer framework 或新状态库。
- 不移动、复制或重写 Workbench、Bucket、Library、History、MCP、Settings section 的业务实现。
- 不把 Home 和 Contextual Tabs 插件化；它们是当前应用 shell，不由 profile 控制。
- 不为 `research.experiment`、`research.paper_search`、`research.colab`、
  `research.mamba_history` 创建空 UI contribution；当前没有对应独立页面。
- 不修改 `/api/capabilities` schema，不新增数据库字段或配置格式。
- 不实现 Claude UI plugin；只有真实 backend 插件进入 profile 后才单独增加。
- 不给每个 backend 预建自定义 renderer。当前真实变化点只有工作台 view key 和登录命令。

## 5. 原子行为合同

### 5.1 Capability inventory owner

新增 `CapabilityInventoryProvider`，它是前端 capability inventory 的唯一网络 owner：

~~~typescript
interface CapabilityInventoryState {
  inventory: CapabilityInventory | null;
  loading: boolean;
  error: string | null;
  refresh(): Promise<void>;
}
~~~

规则：

- Provider 首次挂载时调用现有 `getCapabilityInventory()` 一次。
- Sidebar、TopBar、Workbench 和 App 通过 `useCapabilityInventory()` 读取同一快照。
- `refresh()` 重新读取并原子替换完整快照；请求失败保留明确 error，不退回静态插件列表。
- Provider 卸载后不得提交迟到请求结果。
- Provider 只拥有 capability inventory；现有 auth 请求和 Workbench 会话状态不并入新的全局 store。
- API schema 校验继续由 `frontend/src/api/terminal.ts` 拥有，Provider 不复制校验逻辑。

### 5.2 UI contribution

最小合同只覆盖当前四类真实 consumer：

~~~typescript
import type React from 'react';
import type { LucideIcon } from 'lucide-react';
import type { Project } from '../api/projects';
import type { UiPreferences } from '../components/settings/types';

export interface UiPluginContribution {
  pluginId: string;
  nav?: readonly NavContribution[];
  views?: readonly ViewContribution[];
  settings?: readonly SettingsContribution[];
  backends?: readonly BackendUiContribution[];
}

export interface NavContribution {
  viewKey: string;
  label: string;
  icon: LucideIcon;
  groupKey: string;
  groupLabel?: string;
  groupOrder: number;
  order: number;
}

export interface ViewContribution {
  key: string;
  default?: boolean;
  render(context: ViewRenderContext): React.ReactNode;
}

export interface SettingsContribution {
  key: string;
  label: string;
  description: string;
  icon: LucideIcon;
  order: number;
  default?: boolean;
  render(context: SettingsRenderContext): React.ReactNode;
}

export interface BackendUiContribution {
  backendId: string;
  viewKey: string;
  loginCommand: string;
}

export interface ViewRenderContext {
  activeProject: Project;
  openSettings(): void;
  openWorkbench(prompt: string): void;
}

export interface SettingsRenderContext {
  uiPreferences: UiPreferences;
  onUiPreferencesChange(nextValue: UiPreferences): void;
  onProjectActivated(project: Project): void;
}
~~~

这些是数据对象和纯 render function，不创建 class、factory 或通用 service locator。现有页面继续
接收原有 props；每个 `plugin.tsx` 只负责把 host context 适配给现有组件。

### 5.3 编译期发现和运行期过滤

`pluginRegistry.ts` 使用 Vite 可静态分析的字面量 glob：

~~~typescript
const modules = import.meta.glob('../plugins/*/plugin.tsx', { eager: true });
~~~

规则：

1. 只加载随前端一起构建的受信任本地模块，不解释服务端路径，不执行远程代码。
2. 每个模块用 default export 提供一个 `UiPluginContribution`。
3. 先校验所有编译模块的非空、唯一 `pluginId`，再按 `enabled_plugins` 过滤。
4. 已启用但没有 UI 模块的 Research plugin 合法，不创建空 adapter。
5. 只从启用模块构建 nav、view、settings 和 backend UI 快照。
6. inventory 请求失败或 schema 不支持时显示可重试错误，不启用全部编译插件作为 fallback。

### 5.4 Registry 校验

Registry 在渲染 shell 前一次性校验：

- plugin、view、settings、backend ID 必须是去除首尾空白后的非空字符串。
- plugin ID、view key、settings key、backend UI ID 不得重复。
- 每个 nav 的 `viewKey` 必须引用同一插件拥有的 view。
- 同一 `groupKey` 的 `groupLabel` 和 `groupOrder` 必须一致。
- 每个 backend UI 的 `viewKey` 必须引用同一插件拥有的 view。
- 启用 inventory 中的每个 backend 必须有且只有一个 backend UI contribution。
- 启用 views 和 settings 各自最多一个 `default`。
- `order` 必须是有限数值；group 按 `groupOrder`、item 按 `order` 排序，同序时保持 contribution
  声明顺序。

校验失败显示单一启动错误，不跳过坏 contribution，也不恢复旧静态列表。

### 5.5 当前 view 与导航行为

`App.tsx` 只保存 `activeViewKey: string | null`，并从 Registry 查找 renderer。合法 view 的选择规则：

1. `localStorage.mamba_last_nav` 指向当前启用 view 时沿用。
2. 否则选择唯一 `default` view。
3. 没有 default 时选择排序后的第一个启用 view。
4. 没有任何启用 view 时显示明确的“未启用 UI view”状态。

选择结果确定后再写回现有 `mamba_last_nav`；不迁移、不复制 localStorage key。插件被禁用或旧 key
已删除时直接按上述规则收敛，不保留兼容映射。

Sidebar 只接收 Registry 已排序的 nav groups。设置按钮仍是 shell chrome，继续打开
`SettingsModal`，不伪装成 view contribution。Contextual Tab 激活时继续覆盖主 view 展示；关闭后
回到当前 `activeViewKey`。

`openWorkbench(prompt)` 先写入现有 composer prompt，再通过 inventory 的首个启用 backend 查找
`BackendUiContribution.viewKey`。核心 shell 不再出现 `bench` 字面量。缺失映射属于 Registry
校验错误，不静默停留在原页面。

### 5.6 Settings 行为

`SettingsModal` 只消费 Registry 的 settings contributions：

- active key 存在时渲染对应 contribution。
- 首次打开或当前项因插件禁用而消失时，选择唯一 default；否则选择排序后的第一项。
- 没有 settings contribution 时显示明确空状态，关闭按钮仍可用。
- modal 的 Escape、body overflow、backdrop、布局和关闭行为保持现状。
- `UiPreferences` 继续由 App 持有；Registry 不保存设置值。

### 5.7 Backend UI 元数据

`BackendDescriptor` 继续拥有 backend ID、label 和能力布尔值；UI plugin 只补充当前 API 没有的：

- `viewKey`：composer/workbench 跳转目标。
- `loginCommand`：AuthPopover 展示和复制的准确命令。

Bucket、Asset Drawer、Drafts 等历史会话展示通过共享 inventory 按 backend ID 取 label；未知历史
backend 直接显示稳定 ID。颜色使用现有中性 token，不再用“Codex 否则 Claude”分支。MCP call
history 可以保留 `sandbox` 这一真实调用来源，但其他值按普通动态 backend ID 处理。

## 6. Owner 与现有页面映射

| Plugin ID | Nav / View contribution | Settings contribution | Backend UI |
| --- | --- | --- | --- |
| `core.http` | `drafts`、`skill`、`mcp`、`hist` | `project`、`mcp`、`credentials`、`skills`、`appearance`、`about` | 无 |
| `backend.codex` | `bench` / `WorkbenchTab`，当前 default | 无 | `codex` → `bench`，`codex login` |
| `research.workspace` | `exp`、`pap`、`data`、`idea` / 四个 `BucketContainer` adapter | 无 | 无 |
| `research.zotero` | `library` / `LibraryTab` | 无 | 无 |

说明：

- Home、TopBar、Contextual Tabs、Settings 按钮属于 shell，不登记为插件 view。
- `research.experiment` 等已启用 Research plugin 当前通过 MCP/Workspace 工作流提供能力，没有独立
  页面，因此不贡献 UI。
- 业务组件文件不移动；上述 owner 只改变可见入口和装配来源。
- 默认 profile 的页面、分组、标签和顺序必须与当前 UI 一致。

## 7. 目标文件边界

新增：

~~~text
frontend/src/kernel/pluginTypes.ts
frontend/src/kernel/pluginRegistry.ts
frontend/src/kernel/capabilityInventory.tsx
frontend/src/plugins/core/plugin.tsx
frontend/src/plugins/backend-codex/plugin.tsx
frontend/src/plugins/workspace/plugin.tsx
frontend/src/plugins/zotero/plugin.tsx
frontend/tests/kernel/pluginRegistry.test.ts
~~~

修改但不复制业务实现：

~~~text
frontend/src/App.tsx
frontend/src/components/MambaSidebar.tsx
frontend/src/components/settings/SettingsModal.tsx
frontend/src/components/settings/types.ts
frontend/src/components/layout/TopBar.tsx
frontend/src/components/layout/AuthStatusChip.tsx
frontend/src/components/layout/AuthPopover.tsx
frontend/src/components/tabs/WorkbenchTab.tsx
frontend/src/components/buckets/BucketContainer.tsx
frontend/src/components/contextual/asset/AssetDrawer.tsx
frontend/src/components/tabs/DraftsTab.tsx
frontend/src/components/mcp/CallsHistoryView.tsx
frontend/src/api/mcp.ts
frontend/src/api/terminal.ts
frontend/src/components/workbench/TerminalPane.tsx
~~~

`capabilityInventory.tsx` 使用 `.tsx` 是因为它提供 React Provider；不再额外拆 context、hook、service
三个文件。四个 plugin 文件只是 contribution 声明，不建立空目录、index re-export 或 package。

## 8. 同批替换与删除清单

Batch 4 只有切换完成并删除以下旧路径后才算完成。

### 8.1 生产装配

- 从 `App.tsx` 删除页面组件直接 import、`NavId` 依赖、合法 key 数组、`renderMain()` switch、
  `bench` 默认值和 `setActiveNav('bench')`。
- 从 `MambaSidebar.tsx` 删除 `NavId`、`NavItem`、`NavGroup`、`NAV_GROUPS` 及只为静态列表存在的
  icon import。
- 从 `SettingsModal.tsx` 删除 section 直接 import、`CATEGORIES` 和 `renderSection()` switch。
- 从 `components/settings/types.ts` 删除固定 `SettingsCategoryId` 联合类型；保留真实数据合同
  `UiPreferences`。
- 删除 Sidebar、TopBar、Workbench 对 `getCapabilityInventory()` 的独立 effect/state；只保留
  Provider 调用 API client。
- 从 `AuthPopover.tsx` 删除 `${backend.id} login` 推导，改读 backend UI contribution。

### 8.2 Backend 固定分支与失效说明

- 删除 `BucketContainer.tsx`、`AssetDrawer.tsx`、`DraftsTab.tsx` 中
  `backend === 'codex' ? ... : 'Claude'` 分支。
- 将 `api/mcp.ts` 的 `'claude' | 'codex' | 'sandbox'` 固定联合改为动态字符串；
  `CallsHistoryView.tsx` 只特判真实来源 `sandbox`。
- 删除或改写 `api/terminal.ts`、`TerminalPane.tsx`、Sidebar 等描述旧 Claude CLI、旧 provider
  默认值或 Codex-only shell 的失效注释。
- “Claude/Codex 产物统一展示”等真实产品语义不属于路由或状态分支，不为追求零文本命中而删除。

### 8.3 测试、配置与文档

- 当前没有覆盖静态 `NAV_GROUPS` / switch 的前端旧测试，因此没有兼容测试需要保留；若实施时
  出现此类测试，随旧路径删除。
- `configs/plugins.json` 和 `/api/capabilities` schema 不变，不增加 UI 专用 profile 或 feature flag。
- 实施完成后更新架构设计、本文档和索引状态，删除 `docs/live` 中“Sidebar/App 仍静态装配”的
  当前态描述。
- 不保留旧列表、alias、re-export、fallback、隐藏旧组件或注释掉的 switch。

## 9. 数据与状态处理

本批没有数据库 migration、服务端配置迁移或用户文件改写。

| 数据 | 处理 |
| --- | --- |
| `mamba_last_nav` | 沿用原 key；只接受当前 Registry 中启用的 view key，失效值按默认规则覆盖 |
| `research-agent-ui-preferences` | schema、默认值和 App owner 不变 |
| active project | 继续由 App/Home 流程持有，不搬入 Registry |
| conversation/backend 历史值 | 保持稳定字符串 ID；未知 backend 显示 ID，不伪装为 Claude |
| capability inventory | 内存共享快照；不写 localStorage，不缓存跨页面旧版本 |

## 10. 最小测试设计

只新增 `frontend/tests/kernel/pluginRegistry.test.ts`，使用已安装的 `tsx`、Node `node:test` 和
`node:assert/strict`，不引入 Vitest、Jest、Testing Library 或 DOM fixture。

该文件覆盖三个原子行为：

1. **成功路径**：编译 contributions 按 `enabled_plugins` 过滤，nav/settings 保序，backend 映射
   正确，合法持久化 view 被恢复。
2. **边界路径**：持久化 view 被禁用时依次选择 default、首个 view；无 view 返回明确空结果。
3. **失败路径**：参数化验证重复 plugin/view/settings/backend ID、悬空 nav/backend view 引用和
   多 default 明确抛错。

不测试 Vite 已保证的 glob 展开、不截图每个现有页面、不按 contribution 字段创建一组 getter
测试。UI smoke 负责确认现有页面仍可见和可操作。

## 11. 实施顺序

0. 先通过第 1 节 Phase 3 进入门禁。
1. 增加纯 contribution 类型、Registry 构造/选择函数及一个最小测试文件。
2. 增加共享 Capability Provider，并在 App 根部挂载。
3. 为 `core.http`、`backend.codex`、`research.workspace`、`research.zotero` 声明现有页面。
4. 一次切换 App、Sidebar、Settings、TopBar、Workbench、Auth consumer。
5. 删除全部静态列表、switch、重复 capability state 和 backend 固定分支。
6. 执行 test-prune、残留扫描、完整测试、前端 lint/build 和浏览器 smoke。
7. 更新架构与实施文档状态。

步骤 3-5 是同一个 replacement batch，不得合并“Registry 已存在但 shell 仍走旧 switch”的中间状态。

## 12. 验证命令

进入门禁：

~~~powershell
codex login status
pytest tests
~~~

Phase 4 最小与完整自动化：

~~~powershell
npm.cmd exec --prefix frontend -- tsx --test tests/kernel/pluginRegistry.test.ts
pytest tests
npm.cmd run lint --prefix frontend
npm.cmd run build --prefix frontend
git diff --check
~~~

`pytest tests` 必须在删除 ACL 污染目录后严格运行；不得用新增 ignore、skip、xfail 或只跑可访问
子集代替。实现完成后执行 test-prune，确认 Registry 分支没有重复或实现形状测试。

残留扫描至少执行：

~~~powershell
rg -n "NavId|NAV_GROUPS|SettingsCategoryId|CATEGORIES|renderMain|renderSection" frontend/src frontend/tests
rg -n "setActiveNav\('bench'\)|case 'bench'|\? 'Codex' : 'Claude'|=== 'codex'" frontend/src
rg -n "getCapabilityInventory\(" frontend/src
rg -n "claude --resume|Claude PTY|Anthropic 默认" frontend/src/api/terminal.ts frontend/src/components/workbench/TerminalPane.tsx
rg -n "legacy|deprecated|fallback|compat|xfail|skip" frontend/src frontend/tests docs/live
~~~

预期：

- 第一、二、四组无旧装配命中。
- `getCapabilityInventory(` 只剩 API client 定义和 `CapabilityInventoryProvider` 的唯一调用。
- 第五组只能保留与真实历史兼容或测试术语相关、经逐项确认的非生产旁路文本。

浏览器 smoke 使用默认 profile：

1. Home 激活项目后进入 Workbench；刷新后恢复当前合法 view。
2. 侧栏顺序、分组、标签、图标与替换前一致，十个现有 view 均能打开。
3. 六个 Settings section 均能打开；Appearance 修改仍持久化，Project 激活仍回到 IDE。
4. composer 分类提示能跳到当前 backend 的 Workbench，不依赖 `bench` 字面量。
5. TopBar、Sidebar、Workbench 同时展示同一 inventory；手动刷新后不出现不同步的 backend 列表。
6. AuthPopover 展示并复制 `codex login`。
7. 用测试 profile 禁用 `research.zotero` 后，Library nav/view 均不存在；重新启用后恢复，期间没有
   fallback 页面或隐藏保活组件。

## 13. 验收标准

| 范围 | 必须满足 |
| --- | --- |
| 进入门禁 | Phase 3 真实 Codex new/resume、MCP/cwd/进程清理 smoke 和严格 `pytest tests` 通过 |
| 唯一 owner | 四个 UI plugin 独占自己的 contribution；shell 不枚举具体插件页面 |
| 唯一入口 | 所有可见插件页面只从编译期发现 + capability inventory 交集进入 UI |
| Registry | 非空、重复、悬空引用、多 default、backend UI 缺失均在渲染 shell 前明确失败 |
| 导航 | 默认 profile 的页面、分组和顺序保持；禁用插件后入口与 view 同时消失 |
| 持久化 | 合法 `mamba_last_nav` 恢复；失效 key 收敛到 default/首项；无兼容 key 列表 |
| Settings | 六个现有 section 行为保持；Modal 不再维护 category union 或 render switch |
| Backend UI | Workbench 跳转和登录命令来自 `BackendUiContribution`；动态 backend label 不再落入 Claude 分支 |
| Capability | Sidebar、TopBar、Workbench、App 消费同一 Provider 快照；无静态 fallback |
| 生命周期 | view 切换仍只挂载一个主 Workbench；卸载继续关闭页面自身 PTY/effect |
| 数据 | 无 migration；UI preferences、项目、conversation 和历史 backend ID 不丢失 |
| 删除 | 第 8 节旧代码、类型、注释、测试和 live 文档在同一 Batch 删除或更新 |
| 验证 | 最小 Registry 测试、完整 pytest、lint、build、test-prune、残留扫描、browser smoke、`git diff --check` 全通过 |

任一项未满足时，Batch 4 必须保持“未完成”或“部分完成”，不得把旧 switch、重复 fetch 或
backend 固定分支推迟为后续清理。

## 14. Batch 4 完成定义

- `pluginRegistry.ts` 是 nav/view/settings/backend UI contribution 的唯一装配入口。
- `CapabilityInventoryProvider` 是 `/api/capabilities` 的唯一前端请求 owner。
- App、Sidebar、Settings 和 Auth 都不知道具体插件页面集合。
- 新增本地 view plugin 只需要新增一个编译模块并在服务端 profile 启用对应 plugin；不修改
  Sidebar/App 中央 switch。
- 当前业务页面行为和设计保持，未建立第二套前端、远程 loader 或未来扩展占位。
- 所有替换项、测试、配置、注释和 live 文档在同一 Batch 收口。
