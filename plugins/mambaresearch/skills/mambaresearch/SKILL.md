---
name: mambaresearch
description: 在 Codex App 打开 MambaResearch 科研工作台，管理科研项目、阅读文献、整理文件、开展实验并保存研究结果。用于科研工作台及其界面发起的研究任务。
---

调用 `mamba_workbench.open_workbench` 打开工作台。界面运行在 MCP App 内，任务通过 `ui/message` 投递到当前聊天；Codex App 负责模型执行和原生交互。

## 处理界面任务

任务消息包含固定的 `project_id`、`project_path`、研究记录 ID、`task_id` 和 nonce。整次任务使用该上下文；界面之后切换项目不会改变任务目标。

- 所有科研 MCP 调用传 `project_id`；`mamba_workspace` 另外传相同项目的绝对 `project_path`。可用 `conversation_id` 关联任务研究记录，History 消息查询的该参数指向所查询的记录。项目/路径/研究记录归属由服务端校验，工具配置与权限由 Codex 管理。
- `mamba_history` 可查询该项目已有研究记录。保存的研究摘要与历史消息可供复用；当前 Codex 聊天由 App 管理。
- 产物写入该项目 `outputs/<run_id>/`，保持原始数据、PDF 和已有脚本不变。分类只写索引，文献标注只写项目元数据。
- 完成实际工作后调用 `mamba_workbench.record_task_result(task_id, nonce, status, summary, artifacts)`。`status` 为 `completed` 或无法继续时的 `error`；`artifacts` 为已存在的 `outputs/` 内文件相对路径。总结实际结果，不把任务投递成功视为研究完成。结果已保存时重复相同回传可安全重试。
- 投递超时代表结果未知：核对当前聊天，避免自动重复执行。工具或宿主不可用时报告具体失败，不启动另一套模型 CLI 或读取 App 的会话文件。

## 科研流程

以本次加载的 SKILL.md 所在目录定位资源。按任务读取同目录 `references/workflows/<skill>.md`，沿用科研流程及文件产物约定；这些资源随安装包提供，不依赖开发仓库：

| 任务 | Skill |
| --- | --- |
| 整理、分类项目文件 | classify-workspace |
| 结构化文献综述 | structured-lit-review |
| 实验设计、复现和验证 | empirical-study |
| 已有实验迭代或调参 | experiment-iteration |
| 文献方法对比 | method-comparison |
| 数据集初探 | data-exploration |
| 想法探讨 | idea-brainstorming |
| 单份科研产物评审 | artifact-review |

使用该流程要求的角色分工；角色间通过 `outputs/<run_id>/` 文件交接，主聊天负责检查产物并继续编排。模型推理、图表解读与论文检索直接使用 Codex 原生模型、搜索和浏览能力，核对论文的原始来源后写入 sources.json；不配置额外模型 API 或论文检索 MCP。脚本运行、会话进度、停止、文件读写与通用搜索使用 Codex 原生工具；工作台不再提供这些工具的管理页或独立执行器。科研 MCP 仅保留 Workspace（分类索引）、Zotero（资料库）、Colab（资源定位）和 History（研究记录）；以实际工具 schema 为准。Zotero/Colab 等外部服务需要用户已有的环境配置和资源。

直接从聊天发起科研任务且没有固定项目时，先从工作台选择项目。没有界面任务 ID/nonce 时正常完成用户请求，不捏造任务回传。

## 角色编排

流程中的 `spawn <role>(...)` 是任务分工示例。主聊天读取本 skill 目录的 `references/roles/<role>.md` 职责正文，使用 Codex 当前可用的原生子代理工具委派；继承当前模型，不把文件中的 Claude frontmatter 当作 Codex 模型或工具配置，不生成另一套 agent 配置。委派时传入所需资源的绝对路径，不能让子代理猜测安装目录。

每次委派明确固定项目绝对路径、run_id、输入文件、负责输出的文件清单和资源预算，每份文件只有一个负责人。所有新产物写入该项目 `outputs/<run_id>/`，原始文件只读；同一文件的后续修订交回原负责角色。主聊天逐步等待原生任务完成并读取产物核对内容，不仅凭文件存在判断成功；子代理之间不直接调度或消息交接。原生子代理工具不可用时报告受阻，不启动其他模型进程。

`sources.json` 条目保留 title/authors/year/venue/abstract/url，并提供稳定唯一的 `paper_id`，供 evidence.json、分析和报告逐项引用。角色只写分配给自己的文件；任务回传由主聊天在核对最终产物、实际执行结果及评审结论后完成。

## 安装环境

当前分发包适用于 Windows x64，科研 MCP 使用随包 Python 和依赖；使用时不需要开发仓库、系统 Python 或 Node。科研项目与记录保存在用户目录及项目目录，安装包不包含账号凭据或用户研究数据。Zotero 使用环境变量或 `~/.mambaresearch/.env` 中的 ZOTERO_USER_ID/ZOTERO_API_KEY；密钥不发到聊天。Colab 工具只定位 notebook，由 Codex 原生浏览器打开；不把 URL 生成当作远端执行成功。
