# ResearchAgent 多 Agent 升级方案

## 1. 文档目标

本文档用于：

1. 基于当前 `ResearchAgent` 代码结构，评估升级为多 agent 科研助手的可行路径。
2. 区分哪些能力适合做成独立 reviewer agent，哪些能力更适合做成确定性校验器。
3. 给出一条可渐进落地、可测试、可回归的升级路线。

目标不是把当前系统推翻重做，而是在现有 LangGraph + RAG + ingest 基础上，把系统从：

`生成驱动的科研助手`

升级为：

`生成 + 审核 + 证据验证 + 持续评测驱动的科研助手`

---

## 2. 当前系统真实现状

当前 `ResearchAgent` 并不是“白板式单 agent demo”，而是已经具备较强基础能力的工程化系统。

### 2.1 已有的核心能力

1. 单图编排：
   - `plan_research -> fetch_sources -> index_sources -> analyze_sources -> synthesize -> recommend_experiments -> evaluate_progress -> generate_report`
   - 已支持 checkpoint / resume。

2. 多源检索与文献处理：
   - arXiv / OpenAlex / Semantic Scholar / web 搜索。
   - PDF / LaTeX / figure extraction / figure captioning。
   - dense + BM25 + RRF + reranker。

3. 基础审核与验证能力已经存在一部分：
   - `claim_evidence_map`
   - `evidence_audit_log`
   - `experiment_plan`
   - `experiment_results`
   - `acceptance_metrics`
   - `validate_run_outputs.py`

4. 工程化基础较完整：
   - executor router
   - provider abstraction
   - checkpointing
   - circuit breaker
   - runtime mode
   - tests

### 2.2 当前真正的短板

当前系统的主要问题不是“不会做科研任务”，而是：

1. 质量控制没有彻底从主生成链路中独立出来。
2. LLM 输出仍缺少强 schema 约束。
3. claim-level 事实支持检查还不够硬。
4. citation 校验还没有形成确定性校验链。
5. experiment 方案有生成，但 reviewer 逻辑还不独立。
6. 缺少专门针对 agent 工作流的 benchmark / trace grading。

---

## 3. 原始多 Agent 思路中合理的部分

下面这些方向是正确的，应该保留。

### 3.1 从“生成驱动”转向“审核驱动”

这是升级方向里最重要的判断。

当前 `Evaluate` 节点仍在主流程内部，容易形成：

1. generator 和 evaluator 共享上下文与偏好
2. 自我确认偏误
3. 错误来源不易定位

把 review 从主生成流程中独立出来是合理的。

### 3.2 增加 Retrieval Reviewer

当前系统擅长：

1. 在已有候选中排序
2. 做 retrieval + rerank

但不擅长：

1. 判断“有没有漏掉关键论文”
2. 判断“source diversity / year coverage / venue coverage 是否合理”

因此，`retrieval_reviewer` 是最值得优先增加的 reviewer。

### 3.3 增加 Claim-level 支持检查

当前系统已经有引用与 evidence mapping，但还没有形成稳定的 claim-level support verdict。

目标方向应该是：

`claim -> evidence candidates -> support decision`

支持结果至少应包含：

1. `SUPPORTED`
2. `PARTIAL`
3. `UNSUPPORTED`
4. `CONTRADICTED`

### 3.4 增加 Experiment Reviewer

当前系统已经能生成实验方案，但还没有独立 reviewer 去检查：

1. baseline completeness
2. metrics 是否匹配任务
3. ablation 是否缺失
4. data leakage 风险
5. compute feasibility

这个 reviewer 非常有价值，而且和当前代码中的 experiment_plan / experiment_results 结构天然兼容。

### 3.5 建立 Agent Eval 体系

如果没有 agent eval，后面每加一个 reviewer 都很难证明系统变好了。

因此：

1. trace logger
2. trace grading
3. benchmark dataset

都值得做。

---

## 4. 原始多 Agent 方案考虑不周的部分

下面这些问题如果不先解决，直接上“多 agent 协作”会让系统更脆弱。

### 4.1 没有定义 agent 间的状态边界

当前系统是单一 `ResearchState` 驱动的 LangGraph。

如果直接加入多个 reviewer agent，同时读写同一份大 state，会出现：

1. reviewer 彼此覆盖字段
2. planner 与 reviewer 写入冲突
3. 回溯时难以知道哪个 agent 改坏了什么

结论：

多 agent 之前，必须先定义明确的 artifact 和 handoff contract，而不是让所有 agent 直接改总 state。

### 4.2 把 reviewer 都做成 agent，不够稳

原始思路里：

1. hallucination_checker
2. citation_validator
3. experiment_reviewer

都被视为 review agents。

这不完全合理。

其中至少两类能力更适合优先做成“确定性校验器”：

1. citation metadata validation
   - DOI
   - authors
   - year
   - venue
   - citation links

2. experiment basic policy checks
   - 是否有 baseline
   - metric 是否为空
   - ablation 是否缺失
   - 是否声明数据切分

如果这些先交给 LLM reviewer，会引入不必要的不稳定性。

### 4.3 忽略了 Structured Outputs 是前置条件

当前系统中，节点输出很多地方仍依赖宽松 JSON 解析。

如果没有先把关键 agent / reviewer 的输出做成强 schema：

1. reviewer 会输出格式漂移
2. handoff 会不稳定
3. trace grading 会很难做
4. checkpoint/resume 后状态也容易不一致

结论：

先做 artifact schema，再做多 agent。

### 4.4 缺少“review 结果如何影响主流程”的定义

原始思路只说要加 reviewer，但没有定义 reviewer 的控制语义。

每个 reviewer 至少要输出：

1. `status`
   - `pass`
   - `warn`
   - `fail`

2. `action`
   - `continue`
   - `retry_upstream`
   - `degrade`
   - `block`

3. `issues`
4. `suggested_fix`
5. `confidence`

否则 reviewer 只会变成“额外写一段评论”，无法真正驱动工作流。

### 4.5 Agent Eval 放得太靠后

如果在没有 benchmark / trace grading 的情况下先加多个 reviewer：

1. 你无法证明质量提升
2. 你无法定位是哪一个 reviewer 导致退化
3. prompt / model / retrieval 调整都会变成黑盒

结论：

最小版 agent eval 应提前，而不是等全部 reviewer 做完再补。

---

## 5. 推荐的目标架构

不建议直接做“多个平级 agent 群聊式协作”。

更适合当前仓库的目标架构是：

`单 Planner + Reviewer Gates + Deterministic Validators + Shared Artifacts`

### 5.1 总体结构

```text
Planner
  -> Retrieval / Fetch / Index / Analyze
  -> Retrieval Reviewer
  -> Synthesis
  -> Claim Extractor
  -> Citation Validator
  -> Experiment Reviewer
  -> Report Generator
  -> Final Critic / Acceptance Gate
```

### 5.2 核心原则

1. Planner 负责推进任务，不负责证明自己是对的。
2. Reviewer 只读上游 artifact，只写 review artifact。
3. Validator 优先用确定性规则，不优先用 LLM。
4. State 中不直接混写 reviewer 结果，而是收敛为独立 artifact。
5. 所有 reviewer 都必须有可测试的 pass/fail contract。

---

## 6. 推荐的 Artifact 设计

先定义工件，再定义 agent。

### 6.1 建议新增的核心工件

1. `ResearchPlan`
   - research_questions
   - search_queries
   - scope
   - budget

2. `RetrievalBundle`
   - selected_papers
   - selected_web_sources
   - retrieval_stats
   - query_coverage_hints

3. `RetrievalReview`
   - status
   - missing_key_papers
   - diversity_issues
   - year_coverage
   - venue_coverage
   - suggested_queries

4. `ClaimSet`
   - claim_id
   - claim_text
   - claim_type
   - cited_refs

5. `CitationValidationReport`
   - reference_id
   - doi_valid
   - year_valid
   - author_valid
   - venue_valid
   - support_status

6. `ExperimentReview`
   - status
   - baseline_issues
   - metric_issues
   - ablation_issues
   - leakage_risks
   - compute_risks

7. `TraceGrade`
   - stage_scores
   - primary_failure_type
   - fix_recommendations

### 6.2 工件设计原则

1. 工件必须结构化。
2. 工件必须可以落盘。
3. 工件必须支持 checkpoint / resume。
4. 工件之间只允许单向依赖，不允许双向回写。

---

## 7. 推荐的 Agent / Reviewer 拆分

### 7.1 Planner Agent

职责：

1. 生成研究问题
2. 规划搜索
3. 调度主流程
4. 根据 reviewer 返回决定是否重试上游

不负责：

1. 自证正确
2. citation metadata 校验
3. experiment 规则审查

### 7.2 Retrieval Reviewer

职责：

1. 检查是否漏关键论文
2. 检查来源多样性
3. 检查年份覆盖与 venue 覆盖
4. 给出 query rewrite / source expansion 建议

输入：

1. `ResearchPlan`
2. `RetrievalBundle`

输出：

1. `RetrievalReview`

### 7.3 Claim Extractor

职责：

1. 从 synthesis / draft report 中抽取可验证 claim
2. 规范化 claim 粒度

这一步可以是 agent，也可以是强 schema 的 LLM node。

### 7.4 Citation Validator

职责：

1. 验证引用元数据
2. 验证 claim 与 evidence 的支持关系

推荐拆成两层：

1. 确定性 metadata validator
2. 小型 support classifier

不建议一开始就做成纯 LLM reviewer。

### 7.5 Experiment Reviewer

职责：

1. 检查方案完整性
2. 检查指标匹配
3. 检查 ablation
4. 检查 leakage 风险
5. 检查算力可行性

输入：

1. `ExperimentPlan`

输出：

1. `ExperimentReview`

### 7.6 Final Critic / Acceptance Gate

职责：

1. 汇总 retrieval / citation / experiment review 结果
2. 产生最终 acceptance decision
3. 决定是否允许生成最终报告

---

## 8. 基于当前代码的推荐落地顺序

### Phase 0：先补基础设施，不先上多 agent

目标：

让系统具备支撑 reviewer 的稳定基础。

先做：

1. 关键节点 structured outputs
2. artifact schema
3. reviewer contract
4. trace event 扩展

如果这一步不做，后面的多 agent 会放大当前弱 schema 问题。

### Phase 1：Retrieval Reviewer

这是最适合最先上线的 reviewer。

原因：

1. 复用现有 fetch / retrieve / rerank 能力
2. 不需要先解决所有 claim-level 难题
3. 能快速改善“漏重要论文”问题

建议能力：

1. missing key paper detection
2. source diversity review
3. year coverage review
4. venue coverage review
5. suggested query rewrite

### Phase 2：Claim Extractor + Citation Validator

这一步比“自由形态 hallucination checker”更稳。

建议流程：

1. 从 synthesis / report 抽 claim
2. 抽取对应 citation
3. 用 metadata validator 检查 DOI / author / year / venue
4. 做 support status 判断

输出：

1. `claim_support_matrix`
2. `citation_validation_report`

### Phase 3：Experiment Reviewer

在已有 `experiment_plan` 结构上补 reviewer。

建议检查：

1. baseline completeness
2. metric-task match
3. ablation completeness
4. leakage indicators
5. compute feasibility

### Phase 4：Trace Logger + Trace Grading

这一步不应再拖。

至少要有：

1. 每个阶段的 artifact 快照
2. reviewer 决策日志
3. 失败类型分类
4. benchmark task set

### Phase 5：再考虑更强的多 agent 协同

只有在前面 reviewer + validator + eval 体系稳定后，才值得考虑：

1. planner / analyst / writer 分体
2. 子问题并行 agent
3. domain specialist agent

否则复杂度上涨会快于收益上涨。

---

## 9. 不建议立即做的事情

### 9.1 不建议立即上“多个平级 agent 自由对话”

原因：

1. 当前状态管理不适合
2. reviewer 契约还未明确
3. 调试成本会陡增

### 9.2 不建议把所有 review 都交给 LLM

原因：

1. metadata 验证适合确定性规则
2. LLM reviewer 成本高且不稳定
3. reviewer 本身也会产生幻觉

### 9.3 不建议先拆微服务

当前更大的瓶颈不是 deployment，而是：

1. artifact 不清晰
2. review contract 不清晰
3. eval 不足

---

## 10. 推荐的最小可行升级方案

如果只做一个“最值得先做”的版本，建议是：

### MVP 目标

在现有系统上增加三项能力：

1. `retrieval_reviewer`
2. `claim_extractor + citation_validator`
3. `trace grading`

### MVP 成功标准

系统能做到：

1. 自动发现明显漏掉的关键论文
2. 自动标注 report 中 unsupported / contradicted claims
3. 自动发现明显错误的 citation metadata
4. 把失败分类为 retrieval / reasoning / citation / experiment

---

## 11. 最终建议

这次升级不应理解为“把单 agent 变成多个会聊天的 agent”。

更准确的方向应该是：

1. 先把当前系统变成 `artifact-driven`
2. 再把关键审核能力变成 `review gates`
3. 再把确定性验证能力嵌入流程
4. 最后才考虑更强的多 agent 协作

因此，推荐的总路线是：

`单 Planner`
`+ Retrieval Reviewer`
`+ Citation Validator`
`+ Experiment Reviewer`
`+ Trace Grading`

而不是一开始就做：

`多个平级 agent 自由协作`

前者更符合当前代码基础，也更容易逐步验证收益。

---

## 12. 下一步建议

建议按下面顺序进入实现：

1. 定义 reviewer artifacts 与 schema
2. 把 retrieval reviewer 接入现有 LangGraph
3. 增加 claim extractor 与 citation validator
4. 增加 experiment reviewer
5. 扩展 trace logging 与 benchmark

如果需要，我下一步可以继续把这份方案细化成：

1. 文件级改造清单
2. 新增 schema 草案
3. LangGraph 新节点与边的设计稿
4. 第一阶段 `retrieval_reviewer` 的实现任务列表
