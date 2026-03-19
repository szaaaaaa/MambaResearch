# ResearchAgent

ResearchAgent 是一个本地优先的自治研究系统，当前围绕 `dynamic_os` 运行时构建。输入一个主题或完整研究请求后，系统会按下面这条执行链路生成一次可追踪的研究运行：

`planner -> executor -> role -> skill -> tool`

当前仓库包含 FastAPI 后端、Vite/React 前端、命令行入口、本地检索与索引工具，以及用于工具后端的 stdio MCP 桥接。

## 当前仓库的有效实现

- `app.py`：FastAPI 入口。提供 API，并在 `frontend/dist/` 存在时挂载前端静态文件。
- `configs/agent.yaml`：后端与设置界面共用的权威运行时配置。
- `scripts/run_agent.py`：`dynamic_os` 的命令行运行入口。
- `scripts/build_index.py`：从 PDF 构建或刷新本地检索索引。
- `scripts/dynamic_os_mcp_server.py`：按 `server_id` 暴露工具后端的 stdio MCP 桥。
- `src/dynamic_os/`：planner、executor、roles、skills、tools、policy、storage 和 runtime 主体。
- `src/server/routes/`：运行、配置、凭据、模型目录和 OpenAI Codex OAuth 的 API 路由。
- `src/common/openai_codex.py`：OpenAI Codex OAuth、profile vault、模型发现与缓存逻辑。
- `src/ingest/` 与 `src/retrieval/`：文档解析、抓取、embedding、BM25、reranker 与索引支持。
- `frontend/`：会话、运行状态、路线图、遥测、设置、鉴权与模型管理界面。
- `tests/`：按 phase 组织的后端/运行时/API 测试。

`dynamic_os` 是当前活跃运行时。仓库里仍保留了一些检索相关辅助模块，但实时应用路径已经集中在 `app.py`、`scripts/run_agent.py`、`src/dynamic_os/` 和 `src/server/`。

## 当前能力

- 基于 planner 生成 DAG，再由 executor 按 role/skill/tool 执行。
- 内置技能覆盖研究规划、论文搜索、全文抓取、笔记提取、证据图构建、实验设计/执行、报告撰写与审阅。
- 通过 MCP 发现并接入工具后端，默认按 `llm`、`search`、`retrieval`、`exec` 四类 server id 拆分。
- 运行时与前端都支持多模型提供方：`openai_codex`、`openai`、`gemini`、`openrouter`、`siliconflow`。
- 后端与前端支持模型目录加载、API Key 持久化、OpenAI Codex OAuth 登录/回调/登出/校验。
- 后端通过 SSE 向前端流式发送 route plan、节点状态、产物和原始日志。
- 前端本地保存会话，并提供模型、对话、工具、外观、数据/存储、安全、关于等设置分区。

## 架构概览

主执行链路：

`planner -> executor -> role -> skill -> tool`

关键模块：

- `src/dynamic_os/runtime.py`：加载配置、启动 MCP 运行时、组装 policy/planner/executor/store，并写出运行产物。
- `src/dynamic_os/planner/`：生成并校验 route plan。
- `src/dynamic_os/executor/`：执行 DAG 节点、发送运行事件、在最终产物就绪后结束运行。
- `src/dynamic_os/roles/roles.yaml`：角色定义与技能白名单。
- `src/dynamic_os/skills/builtins/`：内置技能包。
- `src/dynamic_os/tools/`：工具注册、MCP 发现、统一 gateway 和 provider backend。
- `src/server/routes/runs.py`：`/api/run` SSE 流和 `/api/run/stop`。
- `src/server/routes/config.py`：配置与凭据持久化，以及 Codex OAuth 接口。
- `src/server/routes/models.py`：各 provider 的模型目录接口。

## 快速开始

### 1. 安装 Python 依赖

```bash
pip install -U pip
pip install -e .
```

### 2. 安装前端依赖

```bash
cd frontend
npm install
cd ..
```

### 3. 配置模型与凭据

有两种配置方式：

- 直接编辑 `configs/agent.yaml` 和 `.env`
- 启动前端，在设置界面中保存配置

当前实现中的行为：

- 运行时配置写回 `configs/agent.yaml`
- API 凭据写回 `.env`
- 仓库自带的 `configs/agent.yaml` 当前默认 provider 是 `openrouter`，默认模型是 Gemini
- UI 和后端同时支持 `openai_codex`、`openai`、`gemini`、`siliconflow`

后端识别的凭据键包括：

- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `OPENROUTER_API_KEY`
- `SILICONFLOW_API_KEY`
- `GOOGLE_API_KEY`
- `SERPAPI_API_KEY`
- `GOOGLE_CSE_API_KEY`
- `GOOGLE_CSE_CX`
- `BING_API_KEY`
- `GITHUB_TOKEN`

### 4. 可选：启用 OpenAI Codex OAuth

如果你想使用 `openai_codex` provider，而不是普通 API Key：

- 在 Models 设置中选择 `openai_codex`
- 模型名使用 `openai-codex/<model>` 形式，例如 `openai-codex/gpt-5.4`
- 从 UI 或 `/api/codex/login` 发起登录
- 完成浏览器回调后，再校验选定模型

Codex 鉴权默认保存在仓库外：

- Windows：`%LOCALAPPDATA%\ResearchAgent\auth\profiles.json`
- Linux/macOS：`$XDG_STATE_HOME/research-agent/auth/profiles.json` 或 `~/.research-agent/auth/profiles.json`

如果需要改位置，设置 `RESEARCH_AGENT_AUTH_DIR`。

### 5. 启动后端

```bash
python app.py
```

FastAPI 默认监听 `http://localhost:8000`。

### 6. 启动前端开发模式

```bash
cd frontend
npm run dev
```

开发服务器默认在 `http://localhost:3000`，并连接 `8000` 端口的后端。

### 7. 可选：由 FastAPI 直接托管前端构建产物

```bash
cd frontend
npm run build
cd ..
python app.py
```

如果 `frontend/dist/` 存在，`app.py` 会直接在 `http://localhost:8000/` 提供前端页面。

## CLI 用法

从命令行直接发起研究任务：

```bash
python -m scripts.run_agent --topic "retrieval augmented generation"
```

也可以传入完整请求：

```bash
python -m scripts.run_agent --user_request "Compare retrieval planning approaches for local research agents"
```

如有需要，可显式指定工作区内的输出目录：

```bash
python -m scripts.run_agent --topic "dynamic planning" --output_dir ./outputs
```

构建或刷新本地索引：

```bash
python -m scripts.build_index --papers_dir data/papers
```

只索引单个 PDF：

```bash
python -m scripts.build_index --papers_dir data/papers --pdf_path my_paper.pdf --doc_id paper_001
```

## 前端与 API 工作流

React 前端不是静态展示页，而是直接驱动运行时：

- 侧边栏负责本地会话管理
- 运行页可以启动/停止任务，并展示 route graph、事件时间线、产物和原始日志
- 设置弹窗负责编辑运行时配置、凭据、模型/provider 选择和安全/鉴权状态

重要接口：

- `GET /api/config`，`POST /api/config`
- `GET /api/credentials`，`POST /api/credentials`
- `POST /api/run`，`POST /api/run/stop`
- `GET /api/codex/status`，`POST /api/codex/login`，`POST /api/codex/callback`，`POST /api/codex/logout`，`POST /api/codex/verify`
- `GET /api/codex/models`
- `GET /api/openai/models`
- `GET /api/gemini/models`
- `GET /api/openrouter/models`
- `GET /api/siliconflow/models`

## 配置说明

`configs/agent.yaml` 是运行时行为的唯一事实来源。当前主要配置结构包括：

- `mcp.servers`：`llm`、`search`、`retrieval`、`exec` 四类 stdio MCP server
- `llm.provider` 与 `llm.role_models.*`：各角色的 provider/model 选择
- `agent.routing.planner_llm`：planner 专用模型配置
- `auth.openai_codex`：默认 profile、白名单、锁定策略和显式切换策略
- `sources.*`：检索源开关与上限
- `retrieval.*`：embedding、reranker 与检索行为
- `budget_guard.*`：token/API/运行时长预算限制

后端在读取和写入配置时，会把旧的 `critic` 角色自动规范为 `reviewer`。

## 输出目录

API 和 CLI 默认把运行结果写到仓库根目录下的 `outputs/`：

```text
outputs/run_<timestamp>/
```

每次运行通常会生成：

- `events.log`
- `run_snapshot.json`
- `artifacts.json`
- `research_report.md`
- `research_state.json`

## 测试

运行全部 Python 测试：

```bash
pytest
```

直接运行 phase 测试套件：

```bash
pytest tests/test_dynamic_os_phase1.py tests/test_dynamic_os_phase2.py tests/test_dynamic_os_phase3.py -q
```

检查前端 TypeScript 和构建：

```bash
cd frontend
npm run lint
npm run build
```

## 项目结构

```text
ResearchAgent/
|-- app.py
|-- configs/
|   `-- agent.yaml
|-- frontend/
|-- scripts/
|   |-- build_index.py
|   |-- dynamic_os_mcp_server.py
|   `-- run_agent.py
|-- src/
|   |-- common/
|   |-- dynamic_os/
|   |-- ingest/
|   |-- rag/
|   |-- retrieval/
|   |-- server/
|   `-- workflows/
`-- tests/
```
