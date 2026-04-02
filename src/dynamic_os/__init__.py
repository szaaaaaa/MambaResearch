"""Dynamic Research OS 顶层包。

Dynamic OS 是一个 AI 驱动的研究自动化系统，核心理念是：
将复杂研究任务分解为 DAG（有向无环图）中的节点，
每个节点由特定角色使用特定技能执行，最终汇总生成研究报告。

包结构：
- contracts/: 类型基础层，定义所有核心数据结构
- planner/: 规划器，将用户请求转化为 RoutePlan（DAG）
- executor/: 执行器，按拓扑序驱动节点执行
- policy/: 策略引擎，强制执行预算和权限约束
- roles/: 角色注册表，管理 researcher/analyst/writer 等角色
- skills/: 技能注册表，发现和加载可执行技能
- tools/: 工具网关，为技能提供外部工具调用能力
- storage/: 存储后端，管理产物/观测/知识图谱的持久化
- experiment/: 实验工作区管理
- runtime.py: 运行时入口，组装所有组件并启动执行
"""
