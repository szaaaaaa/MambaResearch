# 复测清单 — bucket 空态按钮 → Claude Code 跑 /classify-workspace 全链路

**日期**: 2026-05-03
**关联改动**:
- `src/server/terminal/claude_mount.py`（新增）— 幂等创建 `.claude-mount/.claude/skills/<each>` junction
- `src/server/routes/terminal.py` — PTY spawn `claude` 时追加 `--add-dir <repo>/.claude-mount`
- `frontend/src/components/workbench/ClassifyHintBar.tsx` — 把 `HINT_PROMPT` 提为 export `CLASSIFY_WORKSPACE_PROMPT`
- `frontend/src/App.tsx` — 4 处 `onNavigateToWorkbench` 改用 `injectComposerPrompt(CLASSIFY_WORKSPACE_PROMPT)`
- `.gitignore` — 加 `.claude-mount/`

**状态**: 等待 ziang 手动复测——**前置：必须重启 `python app.py`** 让 `terminal.py` 改动生效

## 背景

截图显示 4 bucket 空态有按钮"去工作台运行 classify-workspace"，但点了只切 tab、Claude Code 里又看不到 `/classify-workspace` skill。两层根因：

1. **前端**: `onNavigateToWorkbench` 只调 `setActiveNav('bench')`，没把 prompt 注入 composer
2. **后端**: PTY spawn 的 `claude` cwd 是 active project（不在 mamba repo 内），看不见
   `D:\ResearchAgent\.claude\skills\` 下的 8 个 pipeline skill；跨卷 NTFS junction 不支持，
   user-global 投递也跨卷。唯一通路是 Claude CLI 的 `--add-dir <dir>` flag——传进去的目录里
   `.claude/skills/` 会被自动加载（[官方文档](https://code.claude.com/docs/en/skills.md) 
   "Skills from additional directories"）

修复：建最小 mount 目录 `.claude-mount/.claude/skills/<each>` 同卷 junction 指回 `.skills-shared/<each>`，
PTY argv 加 `--add-dir <mount>`。Claude 工具访问域只到这个 mount 目录，不暴露 mamba 源码。

## 自动化已过

- `pytest tests/test_terminal_pty_bridge.py tests/test_terminal_output_parser.py` — 33 passed
- `cd frontend && npx tsc --noEmit` — 无错
- `cd frontend && npm run build` — 成功
- CLI smoke：从仓外 cwd 跑 `claude --add-dir D:\ResearchAgent\.claude-mount -p "..."` 输出
  确认 `classify-workspace` 等 8 个 mamba skill 全在 skill list 里

## 复测前置

- **必须先杀掉旧后端 PID（pre-改动），重新跑 `python app.py`**
- 前端：`cd frontend && npm run dev`（dist 已 build 但 dev 模式才能 reload）
- 浏览器开 DevTools，Console / Network 备用
- 当前 active project：`G:\我的移动硬盘\project`——**这条路径在你机器上不存在**
  （`G:\` 实际只有"我的云端硬盘"）。这是独立的环境状态问题，不在本次修复范围。
  下面 Step 3 起请先在 Mamba 主页激活一个**真实存在**的项目（任意有几个文件的目录都行）

---

## 1. mount 目录确实建出来了（30 秒）

复测在仓库 PowerShell：

```powershell
Get-ChildItem 'D:\ResearchAgent\.claude-mount\.claude\skills\' | ForEach-Object { 
    "$($_.Name) [LinkType=$($_.LinkType)]" 
}
```

**预期**：8 行，每行 `<skill-name> [LinkType=Junction]`：artifact-review / classify-workspace / 
data-exploration / empirical-study / experiment-iteration / idea-brainstorming / 
method-comparison / structured-lit-review

随便挑一个验证 junction 通：

```powershell
Get-ChildItem 'D:\ResearchAgent\.claude-mount\.claude\skills\classify-workspace\'
```

**预期**：能看到 `SKILL.md`（证明 junction 正确指向了 `.skills-shared\classify-workspace\`）。

## 2. 前端按钮注入 prompt（前端改动验证）

1. 打开浏览器到 http://127.0.0.1:3000（或你的端口）
2. 进入一个有 active project 的 IDE 视图
3. 左侧导航点 "实验"（或 "文献" / "数据集" / "灵感"）任一 bucket
4. 该 bucket 应该是空态（除非已扫描过）
5. **触发场景 A — `awaiting_classification` tier**：先点右上 "扫描 workspace" 让它生成
   unknown 文件，扫完后空态会变成"Claude / Codex 还没分类完……"，中间出现按钮
   "去工作台运行 classify-workspace"
6. 点这个按钮

**预期行为**：
- 自动切到工作台 tab（不是停在 bucket）
- composer 输入框里**已经填好** `运行 classify-workspace skill 帮我整理 workspace`
- 用户**手动决定**是否回车（保留编辑权）

**回归点**：
- 4 个 bucket 都要试（exp / pap / data / idea），每个的按钮都应该工作
- 如果当前 bucket 已有文件（不是空态），按钮根本不显示——这是正常的，跳过

## 3. Claude Code session 真能看到 skill（后端 --add-dir 验证）

前置：active project 必须是真实存在的目录。

1. 进工作台，开个 Claude tab（左下角 + 新建或选已有 Claude 会话）
2. 输入框打 `/`，autocomplete 列表里**应该出现** `classify-workspace`
   - 也应能看到 `artifact-review` / `data-exploration` / `empirical-study` /
     `experiment-iteration` / `idea-brainstorming` / `method-comparison` /
     `structured-lit-review` 这 7 个其他 mamba pipeline skill
3. 选 `/classify-workspace`，回车

**预期**：Claude 开始按 SKILL.md 步骤跑——先调 `mamba_workspace.scan()`，再循环
`list(bucket="unknown")` + `classify_one(...)`。

**可能挂的位置**：
- 如果 active project 路径无效（如 `G:\我的移动硬盘\project`），`mamba_workspace` MCP server
  可能起不来或报"找不到目录"——不是本次修复范围内的 bug，记下并切到真实 project 重试
- 如果 `<active_project>/.mambaresearch/mcp_config.json` 不存在，看不到 `mamba_workspace`
  工具——重新激活 active project 触发写入；仍不行检查 `app.py` 日志

## 4. ClassifyHintBar 仍可用（回归）

进工作台不点上面的按钮路径，靠老的提示条触发：

1. 确保 active project 有 unknown > 20 文件（步骤 2 扫完肯定有）
2. localStorage 里把 `mamba_classify_hint_dismissed_at` 删了
3. 刷新工作台 tab
4. 顶部应有提示行 "工作区有 N 个文件还没分类。让 Claude / Codex 帮你扫一下？"
5. 点 "好"

**预期**：composer 注入同一句 prompt（共享常量 `CLASSIFY_WORKSPACE_PROMPT`，文案应跟步骤 2 完全一致）

## 5. 工具访问域确实只到 mount 目录（blast radius 验证）

在工作台 Claude tab 里打：

```
列出你能 Read 的目录（`--add-dir` 加进来的）
```

**预期**：Claude 应该说能访问 cwd（active project）和 `D:\ResearchAgent\.claude-mount`。
**不应该**说能访问 `D:\ResearchAgent` 整体——证明 B2 方案的范围隔离生效。

## 6. .gitignore 没漏（30 秒）

```powershell
git status --short | Select-String 'claude-mount'
```

**预期**：无输出（`.claude-mount/` 已被 gitignore 排除）。

---

## 报告反馈格式

每步用 ✅ / ⚠️ / ❌ 标注。出问题贴：

- 浏览器 Console 错（如有）
- `app.py` 终端日志最后 30 行
- `claude --version` 与 `claude --help | rg add-dir` 确认 flag 可用

如果某步过不去且不在已知"out of scope"清单里（active project broken / mcp_config 缺失），优先报根因
不要绕。
