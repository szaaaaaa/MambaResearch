# Setup: Claude Code 作为实验执行引擎

ResearchAgent 用 Claude Code CLI 作为 ML 实验的执行引擎（后端技能 `run_experiment` 通过子进程调用）。本文档说明本机准备工作。

多厂商路由（claude-code-router）当前**延后**——见 `docs/plans/2026-04-18-local-ml-experiment-execution.md` 中 `[SKIP] 1.5` 决策。

## 1. 安装

### 1.1 前置要求

| 组件 | 版本要求 | 检查命令 |
|---|---|---|
| Claude Code CLI | ≥ 2.0 | `claude --version` |
| Node.js | ≥ 18 | `node --version` |
| 操作系统 | Windows / macOS / Linux | — |

### 1.2 安装 Claude Code

官方文档：<https://docs.claude.com/en/docs/claude-code/>

- npm：`npm install -g @anthropic-ai/claude-code`
- macOS：`brew install anthropic/claude-code/claude-code`
- Windows：随 npm 方式；安装后二进制通常在 `%USERPROFILE%\.local\bin\claude` 或 `%APPDATA%\npm\claude.cmd`

### 1.3 认证（二选一）

**订阅授权（推荐，本项目当前采用）**

```bash
claude  # 首次运行会引导浏览器登录
```

登录一次后 CLI 自动续期。用 Claude Max / Pro 订阅时强烈推荐——不按 token 计费。

**API Key 授权**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

按 token 计费，适合团队共享或 CI 环境。

### 1.4 验证

```bash
claude -p "print hello"
```

应在 10 秒内返回包含 `hello` 的输出。非交互（`-p`）模式是 `run_experiment` 技能调用 Claude Code 的唯一入口。

## 2. 环境变量

| 变量 | 用途 | 本项目是否必需 |
|---|---|---|
| `ANTHROPIC_API_KEY` | API Key 认证（订阅授权时不用） | 否（订阅优先） |
| `ANTHROPIC_BASE_URL` | 指向 claude-code-router 等代理，启用多厂商路由 | 否（已延后） |
| `CLAUDE_CODE_DEFAULT_MODEL` | 默认模型（`sonnet` / `opus` / `haiku`） | 否（可选） |
| `CLAUDE_CODE_TIMEOUT` | 单次调用超时（秒） | 否（由 cc_adapter 自己控制） |

`.env.example` 已追加对应占位条目，使用时复制到 `.env` 填充（订阅模式可留空）。

## 3. 常见错误处理

### 3.1 `claude: command not found`

PATH 未包含 Claude Code 二进制目录。

- Windows (bash)：`echo $PATH` 应含 `/c/Users/<你>/.local/bin` 或 `/c/Users/<你>/AppData/Roaming/npm`
- macOS/Linux：`echo $PATH` 应含 `~/.local/bin` 或全局 npm bin 路径

### 3.2 `claude -p` 超时或挂起

顺序排查：

1. 网络：`curl -I https://api.anthropic.com`
2. 认证状态：交互启动 `claude` 后在 TUI 里执行 `/status`
3. 日志：`~/.claude/logs/*.log` 查 traceback
4. 在代码里调用 `claude -p` 时务必关闭 stdin（`subprocess.Popen(..., stdin=subprocess.DEVNULL)`），否则子进程会等待输入永久阻塞——cc_adapter 必须注意

### 3.3 认证过期

订阅会话过期会报 `Authentication failed`。重新 `claude login` 或交互启动 `claude` 走一次 `/login`。

### 3.4 子进程输出编码异常（Windows）

Windows 控制台默认 GBK，Python 子进程捕获 stdout 时可能 `UnicodeDecodeError`。cc_adapter 在调用时强制指定 `encoding="utf-8", errors="replace"`。

### 3.5 模型调用失败但无明确错误

用 `claude -p "hello" --debug` 打开调试日志，stderr 会打印具体 API 交互。
