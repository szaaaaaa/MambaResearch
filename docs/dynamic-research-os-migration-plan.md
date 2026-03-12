# Dynamic Research OS 技术改造与迁移方案
> 日期：2026-03-12
> 状态：Draft v1

## 1. 目标

用新的 `planner` 主导运行时，彻底替换旧的固定阶段执行路径。

这次迁移是一次真正的切换，不是兼容层包装。目标系统保留 `planner + 6 roles`，但移除旧的硬编码工作流逻辑，替换为：

- 局部角色 `DAG` 规划
- 角色通过 `skills` 执行
- `skills` 通过 `tools` 执行
- `planner` 决定是否插入 `reviewer`
- 基于 `observation` 的重规划闭环

## 2. 硬约束

新运行时必须满足以下约束：

- 保留以下 6 个执行角色：
  - `conductor`
  - `researcher`
  - `experimenter`
  - `analyst`
  - `writer`
  - `reviewer`
- 在角色层动态路由
- 在工具层实际执行
- 采用局部规划，而不是全局一次性规划
- 保持 `planner` 与 `executor` 分离
- 只保留两类长期运行时约束：
  - 预算限制
  - 权限限制
- 不允许运行时覆盖配置
- 不允许危险命令和任意删除文件

## 3. 旧实现删除策略

迁移目标不允许依赖旧主执行链路。

新运行时稳定后，以下旧逻辑必须删除，而不是继续保留在兼容模式下：

- 旧 graph 主入口
- 旧 stage-based orchestration
- 旧硬编码角色执行分支
- 旧 mandatory critic 路径
- 旧 stage wrapper 执行路径

切换完成后计划删除的模块：

- [`src/agent/graph.py`](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/graph.py)
- [`src/agent/runtime/orchestrator.py`](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/runtime/orchestrator.py)
- [`src/agent/runtime/router.py`](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/runtime/router.py)
- 旧 `src/agent/stages/*`
- 旧 `src/agent/skills/wrappers/*`
- 旧 `src/agent/roles/*` 中的硬编码执行逻辑

可复用但需要迁移适配的底层能力包括：

- retrieval backend 实现
- ingest backend 实现
- provider adapter
- 通用 IO 工具

## 4. 目标架构

### 4.1 组件总览

建议将新运行时放入一个新的命名空间，例如：

```text
src/
  dynamic_os/
    planner/
    executor/
    contracts/
    policy/
    roles/
    skills/
    tools/
    storage/
```

### 4.2 核心组件

- `planner`
  - 读取用户请求、状态快照、artifacts、observations
  - 生成局部 `DAG`
  - 决定是否插入 `reviewer`
  - 决定是否终止任务

- `executor`
  - 执行 planner 生成的 ready 节点
  - 不自行修改 `DAG`
  - 产出 artifacts 与 observations

- `role registry`
  - 存储 6 个角色定义
  - 定义每个角色默认允许的 `skills`
  - 用角色规格替代旧的硬编码角色类

- `skill registry`
  - 发现内置与用户自定义 `skills`
  - 校验 `skill.yaml`
  - 加载 `run.py`
  - 检查角色适配关系

- `tool gateway`
  - 提供统一工具执行层
  - 接入 `MCP` 和允许的执行后端

- `policy engine`
  - 执行预算策略与权限策略
  - 阻止危险命令与受保护路径写入

- `artifact store`
  - 持久化正式输出，供下游节点使用

- `observation store`
  - 持久化执行阻塞、风险、不确定性、重规划上下文

## 5. 角色模型

6 个角色保留，但不再实现为 6 套完全不同的硬编码工作流分支。

相反，每个角色应变成一份运行时规格，包含：

- `role id`
- 角色提示词 / profile
- 默认允许的 `skills`
- 期望输入 `artifact` 类型
- 期望输出 `artifact` 类型

角色规格概念示例：

```yaml
id: researcher
description: 搜索、收集、阅读并结构化研究资料
default_allowed_skills:
  - search_papers
  - fetch_fulltext
  - extract_notes
  - build_evidence_map
input_artifacts:
  - TopicBrief
  - SearchQuerySet
output_artifacts:
  - SourceSet
  - PaperNotes
```

## 6. 规划模型

### 6.1 局部规划

`planner` 每次只生成局部 `DAG`，通常为 `2-4` 个节点。

原因：

- 更便宜
- 更稳定
- 更适合在执行不确定性下快速重规划
- 更适合 observation 驱动的闭环

### 6.2 Planner 职责

`planner` 负责：

- 选择角色
- 选择执行顺序和依赖关系
- 从角色 allowlist 中选择节点允许的 `skills`
- 决定是否插入 `reviewer`
- 决定是否终止
- 根据 `observation` 进行重规划

`planner` 不允许：

- 作为主运行路径直接执行底层工具
- 修改配置
- 绕过权限策略

## 7. 执行模型

运行时默认执行规则：

`planner -> executor -> role node -> skill -> tool`

### 7.1 Executor 职责

- 接收 planner 生成的 `DAG`
- 找出当前 ready 节点
- 通过通用角色执行逻辑执行节点
- 收集 artifacts
- 收集 observations
- 在需要重规划时把控制权交还给 planner

### 7.2 失败处理

`executor` 不允许偷偷自愈出一条隐藏恢复路径。

当执行受阻时，必须：

- 记录发生了什么
- 记录已经尝试了什么
- 给出候选修复方案
- 推荐一个动作
- 把控制权交回 `planner`

## 8. 核心 Contract

### 8.1 RoutePlan Contract

`planner` 输出的局部 `DAG contract`：

```json
{
  "run_id": "run_123",
  "planning_iteration": 2,
  "horizon": 3,
  "nodes": [
    {
      "node_id": "node_research_1",
      "role": "researcher",
      "goal": "收集并提取与 retrieval planning 相关的高信号论文笔记",
      "inputs": ["artifact:TopicBrief:tb_1"],
      "allowed_skills": ["search_papers", "fetch_fulltext", "extract_notes"],
      "success_criteria": ["at_least_5_relevant_sources", "at_least_5_note_records"],
      "failure_policy": "replan",
      "expected_outputs": ["SourceSet", "PaperNotes"],
      "needs_review": false
    }
  ],
  "edges": [
    {
      "source": "node_research_1",
      "target": "node_analysis_1",
      "condition": "on_success"
    }
  ],
  "planner_notes": [
    "先不插 reviewer，先确认检索质量。"
  ]
}
```

### 8.2 Observation Contract

`executor` 返回给 `planner` 的结构化汇报：

```json
{
  "node_id": "node_research_1",
  "role": "researcher",
  "status": "needs_replan",
  "error_type": "tool_failure",
  "what_happened": "主学术检索源连续返回 rate limit",
  "what_was_tried": ["retry_once", "fallback_source_attempt"],
  "suggested_options": ["switch_source", "narrow_query", "insert_reviewer"],
  "recommended_action": "switch_source",
  "produced_artifacts": ["artifact:SourceSet:ss_1"],
  "confidence": 0.62
}
```

### 8.3 Artifact Contract

正式可复用产物：

```json
{
  "artifact_id": "pn_001",
  "type": "PaperNotes",
  "producer_role": "researcher",
  "producer_skill": "extract_notes",
  "schema_version": "1.0",
  "content_ref": "artifacts/pn_001.json",
  "metadata": {
    "paper_count": 6
  }
}
```

### 8.4 SkillSpec Contract

机器可读的 `skill manifest`：

```yaml
id: arxiv_search
name: Arxiv Search
version: 1.0.0
applicable_roles:
  - researcher
description: 搜索 arXiv 并返回标准化后的论文候选结果
input_contract:
  required:
    - query
output_artifacts:
  - SourceSet
allowed_tools:
  - mcp.search.arxiv
permissions:
  network: true
  filesystem_read: false
  filesystem_write: false
  remote_exec: false
timeout_sec: 60
```

## 9. Skill 包规范

系统必须从如下结构发现 `skill`：

```text
skills/
  <skill_id>/
    skill.yaml
    skill.md
    run.py
```

### 9.1 必需文件

- `skill.yaml`
  - 规范声明文件
- `skill.md`
  - 给 planner 和开发者阅读的说明文档
- `run.py`
  - 执行入口

### 9.2 必需字段

`skill.yaml` 至少必须包含：

- `id`
- `name`
- `version`
- `applicable_roles`
- `description`
- `input_contract`
- `output_artifacts`
- `allowed_tools`
- `permissions`
- `timeout_sec`

### 9.3 用户自定义 Skill 规则

- 用户新增 `skill` 时必须声明 `applicable_roles`
- `planner` 只有在以下条件都满足时，才能选择某个 `skill`：
  - 该 `skill` 加载成功
  - 该 `skill` 属于该角色允许的范围
  - 该 `skill` 通过权限策略检查

## 10. Planner Meta-Skills

`reviewer` 的插入不能硬编码成运行时规则。

因此应提供给 `planner` 一组自己的元技能，例如：

- `build_local_dag`
- `replan_from_observation`
- `assess_review_need`
- `decide_termination`

这样 review 逻辑仍属于 `planner`，而不是重新回到硬编码流程。

## 11. Policy Engine

长期保留的运行时策略只有两类：

- 预算策略
- 权限策略

### 11.1 预算策略

至少应包含：

- 最大规划 / 执行迭代数
- 最大工具调用数
- 可选最大运行时长
- 可选最大模型预算

### 11.2 权限策略

至少应包含：

- 允许联网搜索
- 允许在权限范围内自主选择检索源
- 只允许在批准工作区内读写文件
- 允许沙箱执行
- 只允许访问显式批准的远端执行目标
- 拒绝危险命令
- 拒绝任意删除行为
- 拒绝覆盖配置

典型阻止命令示例：

- `rm -rf`
- `sudo`
- `su`
- PowerShell 中的破坏性删除等价命令
- 未经明确授权的破坏性 `git reset / checkout` 类命令

## 12. API 与前端改造

### 12.1 API

`/api/run` 可以保留外层入口路径，但内部必须切换到新运行时。

运行流应对外暴露：

- route plan 更新事件
- 节点状态变化
- `skill` 调用事件
- `tool` 调用事件
- 重规划事件
- `observation` 事件
- `artifact` 创建事件

### 12.2 前端

前端不应再展示旧的固定阶段图。

必须改成展示：

- 局部 `DAG`
- 角色节点状态
- 插入的 `reviewer` 节点
- `skill` 时间线
- `tool` 时间线
- `observation` 时间线
- `artifact` 面板

## 13. 建议目录结构

```text
docs/
skills/
  <user_skill>/
src/
  dynamic_os/
    planner/
    executor/
    contracts/
    policy/
    roles/
    skills/
    tools/
    storage/
frontend/
```

## 14. 迁移阶段

### Phase 0：冻结 Contract

- 定义 `RoutePlan`
- 定义 `Observation`
- 定义 `Artifact`
- 定义 `SkillSpec`
- 定义角色注册表 schema

交付物：

- 固定 schema 文档
- JSON / YAML 示例

### Phase 1：Skill Runtime 基础层

- 实现 `skills/` 目录发现
- 校验 `skill.yaml`
- 加载 `run.py`
- 向 `planner` 和 `executor` 暴露可用 skills

交付物：

- 可工作的 `skill registry`

### Phase 2：Tool Gateway 与 Policy Engine

- 建立基于 `MCP` 的工具网关
- 增加权限检查
- 增加命令黑名单
- 增加受保护路径检查
- 增加配置只读约束

交付物：

- 安全的工具执行层

### Phase 3：新 Planner

- 实现局部 `DAG` 规划
- 实现 planner 元技能
- 实现 reviewer 插入判断
- 实现终止判断

交付物：

- 能输出合法局部 `DAG` 的 `planner`

### Phase 4：新 Executor

- 实现 ready 节点执行
- 接入 `role registry`
- 接入 `skill registry`
- 产出 artifacts 与 observations
- 在需要重规划时把控制权交回 `planner`

交付物：

- 能执行 contract 化角色节点的 `executor`

### Phase 5：首批内置 Skills

建议首批内置：

- `search_papers`
- `fetch_fulltext`
- `extract_notes`
- `build_evidence_map`
- `run_experiment`
- `analyze_metrics`
- `draft_report`
- `review_artifact`

交付物：

- 在新运行时上打通最小可用研究闭环

### Phase 6：前端切换

- 替换旧固定 route graph
- 展示局部 `DAG` 与重规划事件
- 展示 artifacts 与 observations

交付物：

- 与真实运行时一致的前端 UI

### Phase 7：删除旧实现

- 删除旧 graph runtime
- 删除旧 stage-based orchestration
- 删除旧 wrapper 路径
- 删除旧 mandatory critic gate
- 删除依赖旧架构的旧测试

交付物：

- 单一运行时代码库

## 15. 测试策略

必须覆盖的测试层：

- contract 校验测试
- `skill` 发现测试
- 角色 allowlist 测试
- 权限拒绝测试
- `planner` 输出 schema 测试
- `executor-observation-replan` 闭环测试
- 新运行时端到端测试

关键不变量测试：

- `planner` 不能为角色分配 allowlist 之外的 `skill`
- `executor` 不能执行被阻止的命令
- 运行时不能覆盖配置
- `reviewer` 是可选且由 `planner` 插入
- 执行失败必须返回 `observation`，不能静默 fallback
- 新主执行链路不得再调用旧 `stages` 或旧 `graph`

## 16. 切换标准

满足以下条件时，才算新运行时切换完成：

- `/api/run` 主执行路径只进入新运行时
- 主 CLI 执行路径只进入新运行时
- 旧 orchestration 路径被删除
- 代码库不再依赖旧工作流抽象

## 17. 明确技术决策

这次迁移的目标不是一个通用的单智能体 `LLM + tools` 运行时。

它的目标是：

- 一个 `planner`
- 六个有边界的执行角色
- 一组可复用 `skills`
- 一个由 `tools` 驱动的执行层
- 由 `planner` 自己决定 `review` 与 `replan`

这就是本次替换后的目标架构。

