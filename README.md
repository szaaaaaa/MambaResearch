# MambaResearch

**直接在 Codex App 中使用的科研工作台。** 通过 `$mambaresearch` 打开界面，在同一个 Codex 聊天中完成文件整理、文献研究、实验、分析与报告写作，研究产物留在自己的项目中。

当前插件版本：**0.1.7**。独立运行包适用于 **Windows x64**，需要支持 MCP Apps 的 Codex App。包内包含 Python、依赖、前端界面、科研流程与角色指令，安装后不需要开发仓库、系统 Python 或 Node.js。

## 可以做什么

- **管理科研项目**：按项目组织实验、文献、数据集和灵感，保留草稿及研究记录。
- **按内容分类文件**：由 Codex 阅读内容、判断实际科研用途，再写入分类索引；工程代码和研究无关文件不强行归类，原始文件不移动或删除。
- **阅读与批注文献**：在工作台打开 PDF、翻页、保存中文批注，并把分析任务发送到当前 Codex 聊天。
- **开展科研流程**：检索文献、整理证据、设计及执行实验、分析数据、比较方法、评审研究产物。
- **保存可追溯产物**：来源、证据、实验规格、脚本、真实结果、分析和报告写入项目的 `outputs/<run_id>/`，研究记录展示已有产物。
- **确认任务结果**：面板发起的任务完成后由 Codex 显式回传，界面显示摘要和产物路径；投递成功不代表研究完成。

| 科研任务 | 流程 |
| --- | --- |
| 整理项目文件 | `classify-workspace` |
| 结构化文献综述 | `structured-lit-review` |
| 实验设计、复现与验证 | `empirical-study` |
| 已有实验迭代与调参 | `experiment-iteration` |
| 文献方法对比 | `method-comparison` |
| 数据集初探 | `data-exploration` |
| 想法探讨与反例分析 | `idea-brainstorming` |
| 单份科研产物评审 | `artifact-review` |

## 安装

### 从源码构建

仓库保存源码；运行时、依赖和前端构建文件由构建脚本生成，不直接提交到 Git。构建需要 Windows x64、Python 3.10+ 和 Node.js 20+，首次构建需要网络下载依赖。

在 PowerShell 中运行：

```powershell
git clone --branch main https://github.com/szaaaaaa/MambaResearch.git
cd MambaResearch
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
npm ci --prefix frontend
.\.venv\Scripts\python.exe scripts/build_plugin.py
```

构建输出位于 `dist/`：

```text
mambaresearch-0.1.7-windows-x64.zip
mambaresearch-0.1.7-windows-x64.zip.sha256
```

ZIP 只包含程序、依赖和科研流程资源，不包含账号凭据、研究数据库或用户文件。

### 安装到 Codex

将 ZIP 解压到一个固定目录。在 Codex 中将**解压根目录**添加为本地插件市场，安装 `mambaresearch@mambaresearch-local`。市场文件位于解压目录的 `.agents/plugins/marketplace.json`，实际插件位于其下的 `mambaresearch/`。

也可使用 Codex 的原生插件管理命令，将下面路径替换为实际解压根目录：

```powershell
codex plugin marketplace add "C:\Tools\MambaResearch"
codex plugin add mambaresearch@mambaresearch-local
```

安装或升级后刷新 MambaResearch MCP 连接，使当前聊天加载新配置。

## 开始使用

在 Codex 聊天中输入：

```text
$mambaresearch
```

工作台打开后，创建或选择科研项目，再从界面发起任务，也可以在聊天中描述研究需求。例如：

```text
整理这个项目，只将确实属于科研的文件归入实验、文献、数据集或灵感。
阅读这篇论文，提取实验设计，并指出复现所缺的信息。
比较逻辑回归和随机森林，使用相同的数据划分，保存脚本、结果、图表和报告。
```

界面任务绑定发起时的项目；随后切换页面或项目不会改变任务目标。科研流程使用 Codex 原生子代理协作，每份产物由一个角色负责，主聊天核对实际结果后回传。直接从聊天发起、没有面板任务 ID 的请求不会伪造任务回传。

## 能力分工

| Codex 原生能力 | MambaResearch 科研能力 |
| --- | --- |
| 模型、认证、聊天、推理 | 科研项目、资产分类索引与任务结果 |
| 搜索、浏览、文件读写和通用预览 | 文献阅读、批注和科研产物展示 |
| 命令执行、进程会话和停止 | 实验规格、结果文件及已有实验记录的只读展示 |
| Skills/Agents、MCP 配置和权限 | 科研流程指令、项目研究记录和产物时间轴 |

插件提供五个 MCP 服务：

| 服务 | 职责 |
| --- | --- |
| `mamba_workbench` | 工作台界面、固定项目任务及显式结果回传 |
| `mamba_workspace` | 科研文件分类索引 |
| `mamba_history` | 项目研究记录 |
| `mamba_zotero` | Zotero 资料库访问 |
| `mamba_colab` | Colab notebook 资源定位 |

模型调用、论文检索、脚本执行和 LaTeX 编译直接使用 Codex 原生能力。工作台不保留另一套模型 API、凭据管理页、聊天输入、通用 MCP 控制台、检索/嵌入系统或实验执行器。

Zotero 为可选功能，使用 `ZOTERO_USER_ID`、`ZOTERO_API_KEY` 环境变量或用户 `~/.mambaresearch/.env`，参见 [.env.example](.env.example)。Colab 工具只定位 notebook，不表示上传或远程执行成功。这两项实际账号业务尚未验收，不是核心科研流程的安装前置条件。

## 验证范围

- 已完成真实工作台的分类、文献阅读与中文批注，以及“界面任务 → 当前聊天 → 科研产物 → 显式回传 → 界面结果”的闭环验收。
- 已运行七条科研流程的限定用例，并用真实 WDBC 公开数据完成逻辑回归与随机森林对比：569 个样本、30 个特征、固定分层五折；保留脚本、逐样本预测、图表和报告，独立复算结果。
- 中文 LaTeX 报告已通过原生编译、字体嵌入、Unicode 映射、双引擎文本提取和逐页视觉检查，App 原生编辑器/PDF 预览显示正常。未缓存的 LaTeX 资源仍需按 writer 指令预先准备。
- 独立包和实际安装缓存的五个 MCP 均通过真实启动验证；中文/空格安装路径和无系统 Python 的运行已验证。
- 当前自动化回归：后端 **33 项**、前端 **13 项**通过，类型检查和生产构建通过。

目前仅验收 Windows x64；Zotero/Colab 实际账号业务与其他平台未验证。演示实验用于科研方法展示，不作临床用途或性能普适性结论。

## 开发

```text
frontend/                     工作台前端和宿主交互
src/server/                   科研项目、领域服务、MCP 和任务结果
plugins/mambaresearch/         Codex 插件清单、主 skill 和 PDF 检查脚本
.skills-shared/                分类及七条科研流程的唯一源码
.claude/agents/               科研角色职责正文
scripts/build_plugin.py       独立 Windows 插件构建入口
tests/                        后端及真实 stdio 合同测试
docs/live/                    当前实现规范、设计和验收记录
```

构建器从唯一源码生成包内应用和流程资源，不分别维护副本。工作台界面以单个内联 HTML MCP 资源提供，科研 API 经进程内 ASGI 调用，无额外 UI 端口。`python app.py` 仅用于 API 开发，普通浏览器没有 Codex 宿主桥。

完成上述安装与构建后，执行回归检查：

```powershell
.\.venv\Scripts\python.exe -m pip install pytest httpx pypdf
.\.venv\Scripts\python.exe -X utf8 -m pytest -q tests -p no:cacheprovider
npm test --prefix frontend
npm run lint --prefix frontend
npm run build --prefix frontend
git diff --check
```

用户研究记录保存在 `~/.mambaresearch/mamba.db`，项目元数据保存在项目目录。已有数据库、文献、脚本、数据和索引保持；新研究产物写入项目 `outputs/<run_id>/`。

实现合同与验收证据见[实施索引](docs/live/技术实施文档/00-实施文档索引.md)和[迁移记录](docs/live/技术实施文档/07-Codex-App-科研工作台迁移.md)。

## License

MIT License
