# 复测清单 — 2026-05-17 session 6 commit

**日期**: 2026-05-17
**关联 commits**:
- `3a508c1` feat(asset): AssetWorkspace 右栏接通真实 WorkbenchTab
- `965a013` docs(plan): 标 asset-centric Task 4 DONE
- `6b23b14` fix(mcp): probe + sandbox 加 clientInfo → paper_search 57 tools
- `4e38987` fix(workbench): sidebar 残留修
- `c6079a8` fix(workbench): StrictMode hydrate IIFE 阻断修
- `0f1306b` feat(buckets): PreviewModal 按 subtype 接真预览

**状态**: 等 ziang 手动复测

## 前置阻塞

当前 active project `毕业设计` 的路径 `G:\我的云端硬盘\project` 在 ResearchAgent shell 不可访问（Google Drive Desktop mount 问题）。导致 workspace stats 持续 409 + Claude PTY fatal + bucket 整个流程跑不通。

**手测前必须**：
- (a) 恢复 Google Drive 路径可访问（重启 Drive Desktop / 检查同步状态），**或**
- (b) Home → 新建项目，路径填本地真实存在的目录（譬如 `D:\research\test`），切到这个 project 做下面所有手测

**重启服务**：本 session 改动包含 backend probe/sandbox.py 改动。手测前必须 `python app.py` 重启后端拿到新 code。

---

## 1. paper_search 满血 57 tools 可用（`6b23b14`）

**操作**：
1. 设置 → MCP 工具 → ServersView
2. 选 `paper_search` 看 status

**预期**：status = `running`，tools_count = 57（21 sources：arxiv / pubmed / biorxiv / semantic / crossref / openalex / pmc / core / europepmc / dblp / openaire / citeseerx / doaj / base / zenodo / hal / ssrn / unpaywall / iacr / google_scholar / medrxiv）。

**回归**：其它 5 个 builtin server（workspace / colab / experiment / mamba_history / zotero）也都 status=running，tools_count 不变。

**已知**：SandboxView 直接调 `paper_search.search_papers` 会触发 30s timeout（网络查询慢于默认）；Claude/Codex PTY 路径调用不受此限制。这是已知遗留 follow-up。

## 2. AssetWorkspace 右栏接通真实对话（`3a508c1` + `c6079a8`）

**操作**：
1. 任意 bucket（实验/文献/数据集/灵感）→ 点一张素材卡（需要至少有一条 promoted asset；新建项目可去草稿箱"转为素材"先制造一条）
2. 看右侧主区

**预期**：
- ContextualTabBar 出现该素材 tab
- 右侧主区渲染完整 WorkbenchTab：header（cwd / 会话列表 / 后端切换）+ PTY 终端区 + composer
- **不再是**"对话主区将在 T5/T6 阶段接通"占位文字
- 终端连接成功（如果 Claude backend 走 PTY），消息正常发送与回复

**双栏 vs 单栏**：
- 已素材化（asset_kind 非空）：左 AssetDrawer 320 + 右 WorkbenchTab
- 草稿（asset_kind=null，从草稿箱点"继续对话"）：单栏只 WorkbenchTab

## 3. sidebar 残留消除（`4e38987` + `c6079a8`）

**操作**：
1. 进 sidebar 工作台 nav，发一句消息（任一 backend），等回复
2. 切到某 bucket → 点另一张素材卡（asset tab 打开）
3. 关掉 asset tab
4. 切回 sidebar 工作台 nav

**预期**：
- 步骤 4 看到的是**步骤 1 那条 sidebar conversation 的内容**（hydrate from cc_last_conversation_id）
- **不是 step 2 那条 asset 的残留内容**

**回归（StrictMode 修复）**：
- 步骤 2 进 asset tab，hydrate 应该立刻填出该 asset conversation 的 messages（如果该 conv 在 DB 有 messages）
- 之前 `4e38987` 单独的修复在 React 18 StrictMode dev 模式下会被 mount→unmount→mount 阻断 IIFE，`c6079a8` 修了这个

## 4. FileItemRow PreviewModal 真预览（`0f1306b`）

**前置**：active project 路径必须可达 + workspace 必须 scan + 至少有几个不同 subtype 的文件已被 classify。

**操作**：在 bucket 中找一个文件 → 点行首 chevron 展开 → 点 "预览" action

**按 subtype 分别试**：

| subtype | 期望渲染 |
|---|---|
| `sketch`（png/jpg/svg 等图） | `<img>` embed，max-h-70vh 居中显示 |
| `markdown_note`（.md 笔记） | 复用 MarkdownBlock 渲染（含 GFM + 代码高亮） |
| `csv` | sticky-header `<table>`，前 200 行 + 文件过大时显示截断提示 |
| `parquet` / `npz` / `npy` | metadata 卡 + amber 提示"二进制 sample API 待接入"，**不试图渲染** |
| 其它 / 无 subtype | `<pre>` 显示前 200 行（256 KB 上限） |

**回归**：modal max-w-4xl + max-h-90vh + 头部含文件名 + 路径 + 关闭按钮。

**已知**：
- modal 关闭时 in-flight fetch 不被 abort（256KB 上限不大，可忽略）
- CSV 解析对 quoted field 内 CRLF 行结束符会保留 `\r` 在 cell text（MVP 用不修）

---

## 失败时报

每步 ✅ / ⚠️ / ❌ 标注；失败贴：
- 浏览器 Console / Network panel 截图
- 当前 active project 路径 + 后端日志最后 30 行
- 复测前是否真重启了 `python app.py`

任一步不通且不在已知 caveat 内 → 优先报根因，下一轮排查。
