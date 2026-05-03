# 复测清单 — MambaResearch 壳完成后 Zotero 全链路

**日期**: 2026-05-03
**关联 commits**: `a4422f0`（PTY MCP 注入）`e2848cd`（Zotero 下载 REST + MCP + UI）
`4a6ebf1`（凭据编辑面板 + ZOTERO_*）`fc2cfa8`（roles 死路径清理）
`6c81121`（新建项目自动 seed source_dir）`0506886`（bucket 空态一键加 root）
`<待补>`（保存后清空密码框）
**状态**: 等待 ziang 手动复测——**前置：必须重启 `python app.py` 让上述后端代码生效**

## 背景

ziang 给的两条主方向：
1. 给定工作目录 → 4-bucket 清晰分类与展示
2. 通过 MCP 调 Zotero 文献导入和管理自动化

本 session 把 shell 层面的 6 块缺口都补齐（PTY MCP / Zotero download / 凭据 UI /
死路径 / source_dir 默认 / bucket 一键 root）。前端渲染 smoke 已用 playwright
本地跑通（无 console 红错）；下面是用户视角的端到端验证。

## 复测前置

- **必须先杀掉旧后端 PID 67620（pre-a4422f0），重新跑 `python app.py`**
- 前端 dev 已起在 :3000；如未起：`cd frontend && npm run dev`
- 浏览器开 DevTools，Console / Network 备用
- 准备一个 Zotero 账号，到 https://www.zotero.org/settings/keys 拿 **userID**
  与一把 **API key**（key 至少给 library 读权限；下载附件不需要写权限）

---

## 1. 死路径清理验证（最简单，30 秒）

**操作**: 打开任意 project 进 IDE 视图，看左侧 Sidebar"能力"分组。

**预期**: 只有 4 项 — 技能 / MCP 工具 / 工作台 / Zotero 库。**没有 "Agent 角色"**。

**失败时报**: 截图 sidebar，告知是否仍能在某处看到"Agent 角色"占位入口。

---

## 2. 凭据面板 + Zotero 字段填入（先把后续测试的钥匙摆好）

**操作**:
1. 顶栏齿轮 → 设置 modal → 左侧选 "凭据"
2. 应见 12 个字段，分 3 组：LLM Provider / 搜索 工具调用 / Zotero（文献库）
3. 每行右上角 status badge：之前 .env 里有的（如 OPENAI_API_KEY / GITHUB_TOKEN）
   显示"已配置（.env）"或"已配置（env）"，其余"未配置"
4. **Zotero（文献库）组**两个字段都应是"未配置"（重启后端前后该状态都对）
5. 在 ZOTERO_USER_ID 输入数字 ID（裸文本可见），ZOTERO_API_KEY 输入密钥（masked）
6. 点底部"保存全部"

**预期**:
- 保存成功后，输入框立刻清空（advisor 提的 fix 已落 `<待补>` commit）
- ZOTERO_* 两行的 status badge 由"未配置"切到"已配置（.env）"
- 仓库根 `.env` 文件应新增两行 `ZOTERO_USER_ID=...` / `ZOTERO_API_KEY=...`

**失败时报**:
- 字段不出现 → 检查 `npx tsc --noEmit` + 是否真重启了后端 `python app.py`
- 保存按钮 disabled 或转圈不停 → Network tab 看 POST /api/credentials 返回
- status 不更新 → 后端 GET /api/credentials 返回 body 抓出来

---

## 3. 4-bucket 显示链路（MD #1 端到端）

### 3.1 已存在的 "毕业设计" 项目（pre-auto-seed 创建）

**操作**:
1. 顶栏左上点 "回到 Home" → 列表里点 "毕业设计" 进入
2. 左侧 sidebar 点"实验"

**预期**:
- 看到空态卡，提示"该项目尚未建立分类索引"+ hint
- 行动区有 **"把项目根加为源目录"** 主按钮（紫色） + "打开设置自定义" 灰色按钮
- 点主按钮 → 短暂 spinning → 卡文本变为 "已把项目根 G:\我的云端硬盘\project
  加为源目录——点上方'扫描 workspace'开始分类。"
- 顶部 header 出现"扫描 workspace"按钮，tier 已升到 never_scanned

### 3.2 用 Claude PTY 调 mamba_workspace.scan 让 Claude 自己分类

**操作**:
1. 切到"工作台"标签
2. 在终端给 Claude 发：`先调 mcp__mamba_workspace__list 看 source_dirs，然后
   mcp__mamba_workspace__scan 扫一遍。再用 mcp__mamba_workspace__set_user_override
   或 classify_one 给我把 G:\我的云端硬盘\project 下的文件分到 4 个 bucket。`
3. Claude 应**能看到** 6 个 mamba_* MCP server（这就是 a4422f0 的端到端验证）
4. 它会跑 scan 列出文件、再逐个分类

**预期**:
- Claude 终端里能直接列出工具（无 "tool not found" 类错误）
- scan 完成后回前端 4 个 bucket 标签，每个能看到对应文件

**失败时报**:
- Claude 报 `mcp__mamba_workspace__*: tool not found` → 后端没重启，PTY 没拿到
  --mcp-config flag。检查 `tasklist | grep python` 是否存在 a4422f0 之后的进程
- Claude 看到工具但 scan 报错 → 后端日志看 spawn argv 里是否真带了
  `--mcp-config <project>/.mambaresearch/mcp_config.json`

### 3.3 新建项目（auto-seed 行为）

**操作**:
1. 回 Home 新建一个项目（任意目录都行，譬如桌面 desktop_test）
2. 直接点任意 bucket

**预期**: 不看到"no_source_dirs"空态（auto-seed 已经填好），直接进 never_scanned
（"扫描 workspace"按钮就能用）。

---

## 4. Zotero 全链路（MD #2 端到端）

**前置**: 第 2 步已正确填入 ZOTERO_USER_ID + ZOTERO_API_KEY

**操作**:
1. Sidebar 点 "Zotero 库"
2. 应见远端 Zotero library 顶部带搜索框，items 列表加载出来（如果库非空）
3. 选一条**含 PDF 附件**的 item（journalArticle 类型最常见），点行末**"下载到 workspace"**按钮
4. 按钮转 pending →  ok  → 行下方显示文件名（emerald 色）

**预期**:
- 文件落到 `G:\我的云端硬盘\project\zotero_imports\<原 filename>.pdf`
- 切到任一 bucket → 点"重新扫描"→ 这个 PDF 进 unknown 桶或被识别为 literature
  （取决于 scanner LLM hint，但至少进 classification.db）

**失败时报**:
- 列表空白 + "credentials not configured" → 跳到上述第 2 步检查
- 点按钮 502 + "no PDF attachment child" → 这条 item 真没 PDF 附件，换一条
- 502 + "download HTTP 4xx" → API key 权限不足，重新生成 key 给 read access

### 通过 Claude PTY 调 download_pdf MCP 工具

**操作**: 在工作台终端：
```
查 Zotero library 第一条带 PDF 的 item，
用 mcp__mamba_zotero__download_pdf 把它存到
G:\我的云端硬盘\project\references\
```

**预期**: Claude 调 search → 找到 key → 调 download_pdf 落盘成功；目录会被自动 mkdir。

---

## 5. 凭据"删除"路径（保险测试，可选）

**操作**: 设置 → 凭据 → 把 ZOTERO_USER_ID 字段填入空白（什么都别打）→ 保存。

**预期**: .env 中 ZOTERO_USER_ID 那行被删除；status badge 变回 "未配置"。

---

## 通过判定

- 1, 2, 3.1, 3.3 全过 → 壳的"分类侧"完成
- 2 + 4 全过 → 壳的"Zotero 自动化侧"完成
- 3.2 走通 → 验证 PTY MCP 注入修复（a4422f0）真的端到端
- **以上**任一失败 → 在本 md 顶部追加"失败记录"段落贴现象，我会下一轮排查

## 已知不在此次修复范围

- 重命名 / 移动 zotero_imports 文件后再 scan 的去重行为（scanner 走 sha256+path 主键，
  改文件名会变成"新文件"）
- Zotero collection 维度的目录自动分级（目前所有 download 走 zotero_imports/ 平铺）
- 凭据 UI 的 client-side 强校验（譬如 ZOTERO_USER_ID 必须是数字）——目前只看
  后端是否拒绝
