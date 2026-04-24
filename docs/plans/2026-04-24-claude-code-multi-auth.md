# Plan: Claude Code Multi-Auth (Anthropic + Codex OAuth + Multi-Provider Fork)

> **Status note (2026-04-24)**: 此 plan 的 fork 方向（**方案 A**）**暂不执行**。
> 当前采用**方案 F**（双官方 CLI + `continues` session bridge + NTFS junction 共享 skill），
> 详见 [`docs/releases/v2.x-multi-subscription.md`](../releases/v2.x-multi-subscription.md)。
> 本 plan 保留为 **archived blueprint**——未来若 F 方案遇到不可接受的限制（如无法无损
> 延续 tool 调用历史 / 需要同 session 秒切 provider / OpenAI 改变 OAuth 政策等），
> 可从此 plan 回到 A 方案执行。

**Created**: 2026-04-24
**Status**: archived (plan not executed; see release note above)
**Scope**: Fork `anthropics/claude-code` 为独立 GitHub 项目 `szaaaaaa/claude-code-multi-auth`，在保留官方 harness（`.claude/agents` / `SKILL.md` / slash 命令 / permission modes / hooks / `CLAUDE.md` / `Task` 委派）的前提下，新增 Codex OAuth（ChatGPT Plus/Pro 订阅）登录与多 LLM provider 切换。Anthropic 通路字节级保留官方行为以规避指纹识别；Codex / 其他 provider 通路作为增量新增，互不影响。

## Background

**动机链**：
1. Claude 订阅只能通过官方 `claude` CLI 使用（Anthropic 2026-01-09 起禁止第三方工具消费 Claude 订阅 OAuth）。
2. ChatGPT Plus/Pro 订阅的 Codex OAuth 是 OpenAI 明确支持第三方工具接入的。
3. 想在同一个 CLI 里"Claude 订阅 + Codex 订阅同时可用 + 会话内切换"，只能 fork 官方 Claude Code 并内嵌多 provider。
4. OpenCode / OpenClaw 虽然实现了多 provider，但它们不是 Claude Code 的 fork，harness（agents 定义、SKILL.md 自动发现、slash 命令、permission modes、CLAUDE.md 约定）跟官方不兼容。换用等于放弃本项目已投入的 `.claude/agents/` + slash 命令族 + hook 体系。

**关键事实**（2026-04-24 调研）：
- Anthropic **未上线** binary attestation（代码签名 / TPM / OS-level attestation 类）。
- Anthropic 现有封锁第三方工具的机制基于 **请求指纹**（User-Agent、`x-stainless-*` / `anthropic-*` header、OAuth token scope 校验），不是 binary 校验。
- 用户级 KYC（Persona 身份证+自拍，2026-04-14 上线）针对账号，与 fork 无关。
- Codex OAuth 机制：PKCE against `auth.openai.com`，token 存本地文件，OpenAI 明确允许第三方客户端接入。

## Tasks

### [TODO] 1. Fork 前置 + OAuth 可行性探测

- **What**: Fork `anthropics/claude-code` 到 `szaaaaaa/claude-code-multi-auth`，验证本地能 build + 启动行为跟官方一致；并行做 Codex CLI OAuth 的可借用性探测——这是整个项目最大不确定性来源，先探测再投入后续。
- **Files**:
  - 新 repo 根：`package.json` / `tsconfig.json` / `README.md` / `LICENSE`（遵守上游 Apache-2.0 或实际 license 的 attribution 要求）
  - `docs/oauth-probe-report.md`（探测结论）
- **Acceptance**:
  - Fork 仓库创建，README 含 fork 身份声明、法务 attribution、已知风险列表
  - `npm install && npm run build` 成功无错
  - `node dist/index.js "hello"` 启动行为跟官方 `claude` 一致（起 REPL / 打印同样 banner）
  - OAuth 探测报告产出，覆盖三条结论路径：(a) Codex CLI 的 client_id 能被 fork 复用；(b) 不能借用但可注册独立 OpenAI 应用；(c) 两者均不可行——每条给出证据（Codex 源码引用 / OpenAI 开发者后台截图 / 抓包 diff）

### [TODO] 2. Provider 抽象 + AnthropicProvider 字节级保留

- **What**: 抽出 `Provider` 接口，把现在直调 `api.anthropic.com` 的 HTTP 逻辑封装成 `AnthropicProvider`。铁律——**AnthropicProvider 发出的请求与官方 claude code 发出的请求字节级一致**（UA / header 顺序 / body 序列化 / client_id / SDK 版本字段），否则违反"fork 规避指纹识别"前提。
- **Files**:
  - `src/providers/index.ts`（接口定义）
  - `src/providers/anthropic.ts`（封装现有逻辑，不改行为）
  - 凡是现在直调 `api.anthropic.com` 的入口都改走 `Provider.send()` / `Provider.stream()` 接口
  - `tests/providers/anthropic.spec.ts`
- **Acceptance**:
  - `Provider` 接口定义覆盖 `send / stream / countTokens / refreshAuth` 四个方法
  - `AnthropicProvider` 单元测试：对同一请求，序列化后的 HTTP raw bytes 与官方 claude code 捕获的 raw bytes 完全一致（用 mitmproxy 或 `nock` 做基线对比）
  - Regression：`claude "hello world"` 跟官方 `claude "hello world"` 行为 diff 为零（输出内容可以不同，但请求 header / body 结构、SSE 事件流结构一致）
  - 现有所有 Claude Code 测试继续通过

### [TODO] 3. Codex OAuth 登录 + token 独立存储

- **What**: 新增 `claude auth login --provider codex` 子命令，实现 PKCE flow 对接 `auth.openai.com`，token 落到 `~/.claude/auth/codex.json`（与现有 Anthropic token 独立 namespace 不污染）；refresh token 自动续期；`claude auth status` 列出两个 provider 的登录状态。Task 1 探测结论决定具体实现路径（client_id 借用 vs 独立 app vs 降级）。
- **Files**:
  - `src/auth/codex.ts`（PKCE flow、token 管理、refresh）
  - `src/auth/index.ts`（统一 AuthManager，anthropic / codex 分离存储）
  - `src/commands/auth.ts`（`login --provider <name>` / `logout --provider <name>` / `status` 子命令）
  - `~/.claude/auth/{anthropic,codex}.json`（运行时产物）
- **Acceptance**:
  - `claude auth login --provider codex` 能启动浏览器 PKCE flow，用户在 ChatGPT Plus/Pro 账号登录后 token 写入 `~/.claude/auth/codex.json`
  - `claude auth status` 显示两个 provider：`anthropic: logged-in (expires YYYY-MM-DD)` / `codex: logged-in (expires YYYY-MM-DD)`
  - Token 过期时自动走 refresh，不打断会话
  - Anthropic 侧认证路径零改动：`claude auth login`（不带 `--provider`）跟官方行为一致
  - 单元测试覆盖 PKCE challenge / token parse / refresh / 过期拒绝四种路径

### [TODO] 4. CodexProvider + 格式翻译 MVP

- **What**: 实现 `CodexProvider` 调 OpenAI Responses API（Codex CLI 使用的那个内部端点）；从 `raine/claude-code-proxy` 移植 TypeScript 格式翻译层（Anthropic Messages ↔ OpenAI Responses API），覆盖 `tool_use/tool_calls`、SSE 事件、system prompt、thinking block、图片；启动参数 `claude --provider codex` 整个 session 走 Codex。MVP 阶段**不支持会话内切换**（M5 做）。
- **Files**:
  - `src/providers/codex.ts`（CodexProvider 实现）
  - `src/providers/codex-translator/`（从 `raine/claude-code-proxy` 移植，保留其 MIT license 声明）
    - `request.ts`（Anthropic → OpenAI 请求翻译）
    - `response.ts`（OpenAI → Anthropic 响应翻译）
    - `sse.ts`（SSE 事件结构转换）
  - `src/cli.ts`（解析 `--provider` 启动参数）
  - `tests/providers/codex.spec.ts` + `tests/providers/codex-translator/*.spec.ts`
- **Acceptance**:
  - `claude --provider codex "读一下 README.md 总结一下内容"` 能端到端完成：Codex 返回 tool_use → fork 解析 → 执行 Read tool → 结果塞回 → Codex 返回总结
  - SSE 事件流转换正确：前端 streaming UI 无 diff（逐 token 渲染）
  - 翻译层覆盖基础工具调用场景的单元测试：至少 10 条典型 request/response pair（采自真实 Anthropic 会话样本）
  - CodexProvider 跟 AnthropicProvider 在抽象层同构：交换 provider 对上层 session manager 透明

### [TODO] 5. `/model` 会话内热切

- **What**: `/model` slash 命令扩展——识别模型前缀（`claude-*` → Anthropic；`gpt-*` / `codex-*` → Codex；未来其他 provider 类推），切换时换 HTTP client 但保持 conversation history。切换后 next turn 由新 provider 接管。
- **Files**:
  - `src/commands/model.ts`（现有 `/model` 扩展）
  - `src/session/provider-router.ts`（前缀 → provider 路由逻辑）
  - `src/session/conversation.ts`（跨 provider 保持 history）
  - `tests/session/cross-provider.spec.ts`
- **Acceptance**:
  - 同一个 REPL session 内：先 `/model claude-sonnet-4.5` 发一轮 → `/model gpt-5-codex` 发下一轮 → `/model claude-sonnet-4.5` 再一轮，上下文完整延续（第三轮能引用第一轮内容）
  - 切换瞬间旧 provider 的 HTTP connection 被正确关闭，token 不泄漏到新 provider
  - 未知前缀模型（如 `/model grok-4`）返回清晰错误信息列出支持的 provider 前缀
  - 切换日志打点：`[provider-switch] from=anthropic to=codex at=<timestamp>`，便于 debug

### [TODO] 6. （可选）扩多 provider

- **What**: 把 `CodexProvider` 的翻译层泛化为 `OpenAICompatProvider`，复用接入 OpenRouter / DeepSeek / Kimi（所有 OpenAI 兼容端点）；每个 provider 有独立的 auth 配置（API key or OAuth）。完成后本项目 ResearchAgent 的 CCR 可退休，直接把 `configs/agent.yaml` 的 `claude_code.providers.*` 指向 fork 即可。
- **Files**:
  - `src/providers/openai-compat.ts`（泛化 CodexProvider）
  - `src/providers/openrouter.ts` / `src/providers/deepseek.ts` / `src/providers/kimi.ts`（具体 provider 配置）
  - `~/.claude/auth/<provider>.json`（各自 API key / OAuth 文件）
  - `docs/providers.md`（用户新增 provider 的指南）
- **Acceptance**:
  - 至少 3 个额外 provider 可用：OpenRouter（API key）、DeepSeek（API key 或 OAuth）、一个本地 OSS（如 Ollama）
  - `/model deepseek/deepseek-chat-v3.1` 能直接切到 DeepSeek
  - 用户能通过 `~/.claude/providers.toml`（或类似配置）添加自定义 OpenAI 兼容 provider
  - 本项目 ResearchAgent 的 `configs/agent.yaml` 能把 `deepseek` provider 从 CCR `http://localhost:3456` 改为 fork `http://localhost:<fork-port>` 继续跑通 multi-model plan Task 5 的 MCP 兼容性测试

### [TODO] 7. 打包发布 + 与官方并存

- **What**: 把 fork 打包为独立 npm package，命名不跟官方冲突；CLI entry 命令名改为 `claudex`（或用户选的其他名）避免覆盖官方 `claude`；CI 加每周 upstream sync check；README 含安装、迁移、fork attribution、known risks 四段。
- **Files**:
  - `package.json`（`"name": "@szaaaaaa/claude-code-multi-auth"`，`"bin": {"claudex": "./dist/cli.js"}`）
  - `.github/workflows/upstream-sync.yml`（每周 cron，diff 官方 claude-code 新 commit）
  - `README.md`（中文主文档）
  - `MIGRATION.md`（从官方 Claude Code 迁移指南：token 继承、配置复用、`.claude/` 共享）
  - `CHANGELOG.md`
- **Acceptance**:
  - `npm install -g @szaaaaaa/claude-code-multi-auth` 安装后 `claudex` 命令可用，跟官方 `claude` 并存不冲突
  - fork 能读取官方 `claude` 已经登录的 Anthropic OAuth token（共享 `~/.claude/` 存储），无需重新登录
  - README 明确标注："本 fork 未经 Anthropic 官方认可，使用 Claude 订阅通路存在未来被识别封锁的风险，详见 Known Risks 章节"
  - 上游每周 sync CI job 运行，有新 commit 自动开 PR 给 maintainer review
  - 首次 release v0.1.0 发布到 npm，tag 打上 GitHub

## Out of scope

- 用 Rust / Go / Python 重写（保持 TypeScript 跟上游一致，降低 rebase 成本）
- 修改 Claude Code 的 harness 语义——`.claude/agents/` 格式、`SKILL.md` 自动发现、slash 命令命名、permission modes、hooks 生命周期、`CLAUDE.md` 注入——全部保留官方行为
- 代理 Anthropic 订阅 OAuth token 给外部进程使用（这是 OpenClaw 被封的行为，fork 不做）
- 代理 Codex OAuth token 给外部进程（同上，尊重 OpenAI 的 per-client 鉴权语义）
- UI / TUI 改动（保持跟官方 Claude Code 一致的交互体验）
- Vendor 进本 repo（独立 repo 单独演进）
- 提供 Anthropic 订阅的"第三方 SDK"接入——fork 是一个 CLI，不是 library
- 逆向 Codex CLI 的 binary attestation（如果 OpenAI 未来加）——不做灰色地带破解

## Decision points

Anticipated execution-time forks with pre-defined strategies. Format: `DP<N>: If <condition> → <action>`.

- **DP1**: 如果 Task 1 探测结论为 Codex OAuth client_id 无法借用：
  - **DP1a**: 可以注册独立 OpenAI app 并拿到 Codex 同等 scope → 用独立 app（文档里告知用户需要到 OpenAI 开发者后台授权）
  - **DP1b**: 独立 app 拿不到 Codex scope，但可以让用户手动从 Codex CLI 提取 token → 添加 `claude auth import --provider codex --from ~/.codex/auth.json` 兜底命令
  - **DP1c**: 上述均不可行 → 项目降级为"API key 多 provider"，放弃 Codex 订阅接入能力；Task 3 改为"只做 API key 登录流程"；Task 4 改为"CodexProvider 只支持 OpenAI API key"
- **DP2**: 如果 OpenAI Responses API 对 `tool_use` 支持不完整（Task 4 验证期）：
  - **DP2a**: 特定 schema 错误（如 nested tool 输入）→ 在翻译层写 fallback 处理（简化 schema 后重试）
  - **DP2b**: 完全不支持工具调用 → Codex provider 暂时限定为"纯聊天"，禁用 `.claude/agents/` 对 Codex 的委派；在 `/model` 切换时提示
- **DP3**: 如果上游 `claude-code` 每周 rebase 冲突持续过大（超过 1 天工作量）：
  - **DP3a**: 改 merge 策略替代 rebase，定期 squash
  - **DP3b**: 锁定跟踪分支，只同步关键安全/bugfix commit
  - **DP3c**: 极端情况 → 放弃跟随上游，成为独立分叉（接受 feature 落后）
- **DP4**: 如果 Anthropic 未来加 binary attestation 或其他不可绕过的客户端身份验证：
  - **DP4a**（现在到 attestation 前）：保持 AnthropicProvider 请求字节级同步，包括 UA / `x-stainless-*` / client_id / SDK 版本字段。每次 upstream release 必 rebase 并重跑 Task 2 的 byte-diff regression 测试。
  - **DP4b**（attestation 加上后）：AnthropicProvider 降级为 API key 付费模式；用户可切回官方 `claude` CLI 继续走订阅，本 fork 仅作 Codex/其他 provider 客户端。这个降级路径在 Task 2 预留接口：Provider 接受 `authMode: "oauth" | "api-key"` 配置。
- **DP5**: 如果 Codex provider 在某些 skill 场景下性能 / 指令遵守度显著低于 Anthropic：
  - 记录到 `docs/known-limitations.md`，在对应场景给用户 warning，不自动禁用——让用户自己决定是否切
- **DP6**: 如果 fork 的 Claude 订阅通路被识别封锁（用户反馈 `"This credential is only authorized for use with Claude Code"` 类错误）：
  - 立即 issue tracker 公开；排查是哪一层指纹出了 diff（通常是上游新加了 header / 字段没跟）；修复后 release patch；DP4b 作为终极兜底

## External preconditions

Physical prerequisites the user must satisfy before execution starts.

- **EP1**: Node.js 20+ 与 npm 已安装 — 验证：`node --version` 返回 `v20.x+` — on-failure: STOP，文档指南装 Node
- **EP2**: 新 GitHub repo `szaaaaaa/claude-code-multi-auth` 已创建（空的即可）— 验证：`gh repo view szaaaaaa/claude-code-multi-auth` 返回 200 — on-failure: STOP
- **EP3**: ChatGPT Plus 或 Pro 订阅激活 — 验证：浏览器登 `chat.openai.com` 可见订阅状态 — on-failure: Task 3/4 必然失败，STOP
- **EP4**: 官方 `claude` CLI 已安装且通过 Anthropic OAuth 登录 — 验证：`claude auth status` 返回 logged-in — on-failure: Task 2 的 byte-diff regression 无法对比基线，STOP
- **EP5**: 本地能启动无头浏览器或用户在实体机器操作 — PKCE flow 需要浏览器回调 — on-failure: Task 3 无法完成登录测试，STOP
- **EP6**: `mitmproxy` 或 `wireshark` 或类似抓包工具可用（Task 2 的 byte-diff 验证需要抓官方 claude 的请求做基线）— on-failure: Task 2 acceptance 第二条无证据，STOP

## Failure policy

STOP conditions that halt execution. **Not fallbacks** — no silent retry, no silent skip.

- **FP1**: 如果 fork 的 `npm run build` 连续失败超过 2 次（尝试修但修不好）→ STOP；报告构建错误日志 + 推测上游依赖变动
- **FP2**: 如果 Task 1 OAuth 探测结论为 DP1c（三条路都不可行）→ 暂停整个 plan，重新评估项目可行性；如继续则按 DP1c 降级方案重写 Task 3/4 的 acceptance
- **FP3**: 如果 Task 2 的 byte-diff regression 测试 fail（AnthropicProvider 与官方不一致）→ STOP；不能在这种状态下进 Task 3/4/5，因为 fork 用 Claude 订阅的前提是"与官方不可区分"
- **FP4**: 如果 Task 4 的 Codex provider 端到端测试反复失败（翻译层 bug 修 3 次仍不通）→ STOP；检查是翻译层实现错误还是 OpenAI Responses API 变动；不要累积部分可用就发布
- **FP5**: 如果上游 rebase 冲突连续 1 周无法解决 → 触发 DP3 的三个分支，由 maintainer 决定走哪条
- **FP6**: 如果 fork 被 Anthropic 识别封锁 → 立即 STOP 发布，公开 issue；如果无法修复指纹 diff，触发 DP4b（AnthropicProvider 降级 API key）
- **FP7**: 如果 Task 7 发现 `~/.claude/` 共享导致官方 `claude` 与 fork `claudex` 互相污染 session state（比如 token 被错写）→ STOP；改用独立目录 `~/.claudex/` 并更新 Task 3/7 的 acceptance

## Subtask split policy

- **Trigger**: 单个 task 实际执行时触 > 5 文件 across > 2 模块，**或**有 > 5 条独立 acceptance 可分别验证，**或**其 `What` 描述包含 > 2 个可独立实现和 review 的关注点
- **Split rule**: 按层级边界拆——auth / transport / format translation / routing / CLI UX / packaging；同层内按关注点拆（比如 auth 层内：PKCE flow / token 存储 / refresh / status 命令各自独立）
- **Labeling**: `1` → `1a` / `1b` / `1c`；父 task 在拆分时转为 `[DONE]`（作为容器），每个 sub-task 作为 `[TODO]` 单独处理
- **Per-task 预测**（informational）：
  - Task 1：单元任务，预计不拆
  - Task 2：可能拆（Provider 接口抽象 vs AnthropicProvider 实现 vs regression 测试搭建）
  - Task 3：可能拆（PKCE flow / token 存储抽象 / auth 子命令 UX）
  - Task 4：大概率拆（translator 移植 / CodexProvider 实现 / 端到端 e2e 测试）
  - Task 5：单元任务，不拆
  - Task 6：如果真做，按 provider 拆（OpenAICompatProvider 基类 / OpenRouter / DeepSeek / Kimi 各独立）
  - Task 7：可能拆（npm 打包 / CI sync / 文档）

## Decisions log

- **2026-04-24**：选择 fork 而非从零重写或用 OpenCode，理由：保留官方 harness（`.claude/agents` / `SKILL.md` / slash 命令族 / permission modes / hooks / `CLAUDE.md`）是 ResearchAgent 长期投资所在。
- **2026-04-24**：独立 repo `szaaaaaa/claude-code-multi-auth`，不 vendor 进 ResearchAgent。理由：fork 定位是通用 CLI 产品，跟 ResearchAgent 的关系是"客户端 vs 应用"，解耦演进。
- **2026-04-24**：TypeScript 保持跟上游一致。理由：换语言等于重写，丧失 rebase 能力；后续 bug fix 和新功能跟不上官方节奏。
- **2026-04-24**：接受 Anthropic 未来加客户端 attestation 封 fork 的风险。理由：现有机制（2026-04）不区分官方 binary 与 fork，只要 fork Anthropic 那半请求字节级一致即不可识别。attestation 真加那天再触发 DP4b 降级即可，Codex 通路不受影响。
- **2026-04-24**：CCR（claude-code-router）将在本 fork Task 6 完成后从 ResearchAgent 栈中退休。理由：fork 内嵌多 provider 支持后，CCR 的外挂路由功能冗余。
- **2026-04-24**：Task 6（扩多 provider）定位为可选，优先级低于 Task 1-5。理由：先把 Codex OAuth 这条核心通路跑通，用户能同时用 Claude 订阅 + ChatGPT 订阅就是核心价值；多 provider 是锦上添花。

## Reference

- [raine/claude-code-proxy](https://github.com/raine/claude-code-proxy) — Anthropic ↔ Codex/Kimi 格式翻译参考实现（MIT 许可，移植时保留 attribution）
- [anthropics/claude-code](https://github.com/anthropics/claude-code) — fork 上游（Apache-2.0 或实际 license 以仓库为准）
- [openai/codex](https://github.com/openai/codex) — Codex CLI 官方源码，Task 1 OAuth 探测的参考对象
- [numman-ali/opencode-openai-codex-auth](https://github.com/numman-ali/opencode-openai-codex-auth) — OpenCode 的 Codex OAuth 插件，Task 3 PKCE flow 实现参考
- [Claude Code OAuth 封锁机制 (Issue #28091)](https://github.com/anthropics/claude-code/issues/28091) — 现有指纹识别机制背景
- [Anthropic 用户级 KYC (2026-04-14)](https://support.claude.com/en/articles/14328960-identity-verification-on-claude) — 跟 fork 无关但用户可能遇到
