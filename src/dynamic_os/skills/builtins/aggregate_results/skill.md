# aggregate_results

聚合多轮实验结果，生成跨迭代对比分析。

## 功能

- 从所有 ExperimentResults 和 ExperimentIteration 产物中提取指标历史
- 构建迭代对比表（每轮指标 + 成功/失败状态）
- 计算各指标的 min/max/avg/best 统计值
- 提取最佳配置和经验教训
- 调用 LLM 生成结构化分析文本

## 适用场景

当实验循环结束（ExperimentIteration.should_continue=false）且存在多轮实验数据时，
由 analyst 角色调用此技能生成统一的分析报告，供 draft_report 使用。
