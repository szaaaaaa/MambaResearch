# Frontend UI Plugin Registry 技术设计

更新：2026-10-09。Registry 是导航、view、Settings 和工作台入口的唯一装配 owner。

通过 Vite 的字面量 `import.meta.glob('../plugins/*/plugin.tsx', {eager:true})` 编译本地受信任 contributions；先校验全部模块，再与 capability 的 `enabled_plugins` 求交。服务端插件没有 UI contribution 合法。

Registry 拒绝重复 plugin/view/settings ID、悬空或跨 owner 的 nav/workbench 引用、不一致分组、非法排序值和多个 default。`workbench` 是一个可选 view key，最多一个，必须由本插件拥有。当前 core.workbench 贡献默认 bench；core.http 贡献草稿、研究记录和科研项目/关于设置；Workspace 贡献四个 bucket；Zotero 贡献 Library。

Sidebar、App 和 Settings 只遍历已校验 Registry，不枚举页面。当前 view 优先沿用合法持久化 key，再选 default、首项或明确空状态。禁用插件在一个 runtime transition 内移除 view 和对应 contextual tabs。

CapabilityInventoryProvider 是 inventory 的唯一请求 owner，首次失败显示错误；刷新失败保留 last-good 快照。API schema 由 `api/capabilities.ts` 校验。插件不会增加第二套前端 loader 或远程代码入口。

自动化使用现有 node:test + tsx，覆盖 Registry 引用完整性和默认选择。真实 App 验收需要检查八个科研导航页、两个设置页、contextual tabs 及工作台任务投递。
