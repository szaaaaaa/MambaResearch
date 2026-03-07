# 语义准确性问题分析与修复方案

## 1. 文档目标

本文档聚焦当前系统中最突出的语义准确性问题，并给出一套可执行、可验证、且带 no-regression 约束的修复方案。

本次修复目标不是“让报告更华丽”，而是优先解决以下四类高频问题：

1. `Claim-Evidence Mapping` 可读性与语义真实性下降
2. `References` 混入明显偏题论文，引用纯度不足
3. `experiment_reviewer` 持续告警，但主流程没有真正修复问题
4. `citation metadata` 长期缺失，导致 citation reviewer 持续 `warn`

本文档是后续代码修复的约束基线。

---

## 2. 当前症状

基于最近一次同 topic 运行结果 `outputs/run_20260307_132311`，当前系统存在以下具体现象：

### 2.1 Claim-Evidence Mapping 可读性显著变差

典型症状：

- claim 变成关键词拼接句
- claim 看起来像“为了通过 validator 而改写出来的句子”
- claim 不再像自然科研表述

代表性例子见：

- [research_report.md](/c:/Users/ziang/Desktop/ResearchAgent/outputs/run_20260307_132311/research_report.md)

其中最典型的是：

- `Regarding prototype, selection, prioritization, strategies, evidence suggests ...`

相比之下，旧版本：

- [research_report.md](/c:/Users/ziang/Desktop/ResearchAgent/outputs/run_20260222_222740/research_report.md)
- [research_report.md](/c:/Users/ziang/Desktop/ResearchAgent/outputs/run_20260222_192946/research_report.md)

里的 claim 句子虽然不完美，但更像正常英文命题句。

### 2.2 References 纯度不足

最新版虽然 papers / analyses 数量明显提升，但 references 中混入了明显偏题论文，例如：

- 蛋白设计
- 骨健康分类
- 与目标 topic 只有弱词面交集的边缘 time-series / edge computing 论文

这说明系统当前更擅长“提高召回”，不擅长“维持语义纯度”。

### 2.3 Experiment reviewer 持续发出 warn

在最近 run 的 [trace_summary.json](/c:/Users/ziang/Desktop/ResearchAgent/outputs/run_20260307_132311/trace_summary.json) 中，`experiment_reviewer` 持续报告：

- no train/test split mentioned
- single dataset only
- no ablation study

问题不是 reviewer 太严格，而是这些问题一直没有被真正消化。

### 2.4 Citation metadata 长期缺失

同样在 [trace_summary.json](/c:/Users/ziang/Desktop/ResearchAgent/outputs/run_20260307_132311/trace_summary.json) 中，`citation_validator` 报告：

- `38/38 sources missing year metadata`
- `38/38 sources missing author metadata`

这已经不是“轻微 warning”，而是典型的信息传递断裂。

---

## 3. 根因分析

## 3.1 Claim 退化的根因

当前 claim 生成逻辑主要集中在：

- [evidence.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/core/evidence.py)
- [synthesis.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/stages/synthesis.py)

问题链路如下：

1. `_build_claim_evidence_map()` 不是从稳定、完整的命题中抽 claim
2. 它先从 source 的 `key_findings` / `summary` 中选一句候选句
3. 如果候选句与 RQ token overlap 不够，就调用 `_align_claim_to_rq()`
4. `_align_claim_to_rq()` 会把 claim 改写成：
   - `Regarding <anchor terms>, evidence suggests that ...`

这一步的本意是提高 `claim_rq_relevance`，但副作用非常大：

1. 破坏自然语言可读性
2. 把原始命题改写成“RQ 锚点 + claim 残句”的拼接句
3. 制造一种“语义上像对齐了，但内容上不一定更准”的假象

结论：

**当前 claim 问题的根本不是 LLM 写得差，而是 deterministic 对齐策略在改坏句子。**

## 3.2 引用纯度不足的根因

相关模块：

- [retrieval_reviewer.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/reviewers/retrieval_reviewer.py)
- [source_ranking.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/core/source_ranking.py)
- [reporting.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/stages/reporting.py)

现状是：

1. retrieval reviewer 主要审：
   - source count
   - academic ratio
   - venue diversity
   - year coverage
   - RQ basic coverage
2. 但它不审“这篇论文是否语义上真的回答当前问题”
3. `_dedupe_and_rank_analyses()` 更依赖：
   - `relevance_score`
   - 学术源类型
4. 一旦上游 `relevance_score` 偏宽，reporting 阶段就会把这些 paper 合法地写入 references

因此现在系统实际上缺少一个关键过滤层：

`semantic purity filter`

也就是：

- 不是只判断“相关”
- 而是判断“是否是当前报告的核心证据”

结论：

**当前 reference 问题不是单纯 report prompt 问题，而是 retrieval + ranking + reporting 三层共同缺少“核心证据纯度”约束。**

## 3.3 Experiment reviewer 一直 warn 的根因

相关模块：

- [experiment_reviewer.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/reviewers/experiment_reviewer.py)
- [graph.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/graph.py)
- [prompts.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/prompts.py)

问题分两层：

### A. reviewer 规则确实抓到了真实缺陷

当前 reviewer 关注：

- baseline completeness
- metric completeness
- ablation completeness
- train/test split
- single-dataset risk

这些检查并不过分，而是符合正常科研标准。

### B. 主流程没有真正让 reviewer 生效

当前图中：

- `recommend_experiments -> review_experiment`
- 之后主要根据 `await_experiment_results` 路由

也就是说：

- reviewer 可以报 `warn`
- 但不会强制回退去修 plan

所以系统形成了：

`发现问题 -> 记录 warning -> 继续往下跑`

这也是为什么同类 warn 会在多轮 iteration 中反复出现。

另一个问题是 experiment prompt 仍然不够 schema-driven。当前 plan prompt 没把以下字段做成真正硬约束：

- split strategy
- cross-dataset validation
- ablation plan

结论：

**experiment reviewer 的问题不是 reviewer 太严，而是“review 结果没有控制主流程”，并且上游 schema 本身不完整。**

## 3.4 Citation metadata 缺失的根因

相关模块：

- [analysis.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/stages/analysis.py)
- [citation_validator.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/reviewers/citation_validator.py)

根因很直接：

1. `paper -> analysis` 转换时，保留了很多 metadata
2. 但没有把最关键的：
   - `authors`
   - `year`
   写进 `analysis`
3. citation validator 又是在 `analyses` 上做检查

结果就是：

- 原始 `papers` 里可能有 metadata
- 但 downstream 看不到

这是典型的数据传递 bug，而不是 reviewer 误报。

结论：

**citation metadata 警告的根因是 analysis 阶段丢字段。**

---

## 4. 问题优先级

从“修复难度 / 收益 / 风险”综合排序，建议优先级如下：

### P0

1. 修复 `authors/year` metadata 传递
2. 停止 claim 的 RQ 强制自然语言改写

### P1

3. 增加 reference 语义纯度过滤
4. 让 experiment reviewer 真正影响流程

### P2

5. 强化 synthesis / report 的结构化约束
6. 增加针对正文 claims 的更强 post-report review

---

## 5. 修复方案

## 5.1 修复一：停止 claim 的自然语言强制对齐

### 当前问题

`_align_claim_to_rq()` 直接改写 claim 文本本体。

### 目标

把“claim 可读性”和“claim 与 RQ 的相关性判断”分离。

### 修复策略

1. 保留原始 `claim_text`
2. 新增独立字段：
   - `rq_alignment_score`
   - `rq_alignment_terms`
   - `rq_alignment_status`
3. `_claim_has_rq_signal()` / `_claim_relevance_ratio()` 只用于：
   - 选择
   - 标注
   - 降级 `strength`
4. 不再把 anchor terms 拼回 claim 句子

### 结果预期

- claim 恢复成正常英文句子
- `claim_rq_relevance` 仍然可计算
- validator 不再逼迫 claim 变成关键词拼接句

---

## 5.2 修复二：给 reference 引入核心证据纯度过滤

### 当前问题

references 目前受“traceable + ranked + academic”驱动，但缺少“是否真回答 RQ”这层约束。

### 目标

把 source 分成：

1. `core`
2. `background`
3. `reject`

### 修复策略

1. 在 ranking / reporting 之间新增 `semantic_reference_filter`
2. 判定标准至少包含：
   - 是否直接支持某条 claim
   - 是否直接回答某个 RQ
   - 是否只是背景综述或边缘相似工作
3. references 默认只保留：
   - 全部 `core`
   - 少量 `background`
4. `reject` 源不进入 references

### retrieval reviewer 同步增强

新增检查：

- `semantic_purity_ratio`
- `background_ratio`
- `reject_ratio`

这样 retrieval reviewer 不再只关心“覆盖够不够”，也关心“污染多不多”。

---

## 5.3 修复三：让 experiment reviewer 真正控制流程

### 当前问题

reviewer 持续告警，但 graph 不据此回退。

### 目标

让 reviewer 的 verdict 真正驱动：

- 继续
- 修订后重试
- 阻断

### 修复策略

1. 在 [graph.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/graph.py) 中增加针对 `experiment_review.verdict` 的路由
2. 如果缺少：
   - split strategy
   - ablation plan
   - 基本 cross-dataset thinking
   则至少要回退到 `recommend_experiments`
3. 把 experiment plan prompt 升级成更强 schema，显式要求：
   - `split_strategy`
   - `validation_strategy`
   - `ablation_plan`
   - `dataset_generalization_plan`

### 结果预期

- reviewer 不再只是“写 warning”
- 同类 experiment issue 不会多轮重复出现

---

## 5.4 修复四：修复 analysis 阶段 metadata 丢失

### 当前问题

`analysis.py` 没把 `authors/year` 从 `paper` 传到 `analysis`。

### 目标

确保 citation validator 使用的 `analyses` 数据结构里具备最基本的 citation metadata。

### 修复策略

在 `paper -> analysis` 转换时，补充传递：

- `authors`
- `year`

必要时也可以顺便补充：

- `abstract`
- `source_url_canonical`

### 结果预期

- `citation_validator` 对 academic analyses 不再大面积误报 missing metadata
- `trace_summary.json` 的 citation warning 显著减少

---

## 6. No-Regression 约束

本次修复必须明确避免重新引入之前已经修过的问题。下面这些文档构成这次修复的历史约束：

- [final-no-regression-remediation-plan.md](/c:/Users/ziang/Desktop/ResearchAgent/docs/final-no-regression-remediation-plan.md)
- [run-20260223-115419-issues-and-fixes.md](/c:/Users/ziang/Desktop/ResearchAgent/docs/run-20260223-115419-issues-and-fixes.md)
- [claim-evidence-mapping-hardening.md](/c:/Users/ziang/Desktop/ResearchAgent/docs/claim-evidence-mapping-hardening.md)
- [claim-rq-alignment-and-reference-strategy.md](/c:/Users/ziang/Desktop/ResearchAgent/docs/claim-rq-alignment-and-reference-strategy.md)

## 6.1 绝对不能回归的历史问题

### A. 累积 state 被覆盖

历史问题：

- `fetch_sources` / `analyze_sources` 曾经只返回本轮增量，导致最终 `papers/analyses` 被覆盖为零或局部值

本次修复约束：

- 任何对 `analysis`、`claim_map`、`reference selection` 的修改，都不能重新引入 state 丢失问题
- 所有 patch 必须兼容当前已修复的 cumulative accumulation 语义

### B. reference URL 提取与 report validator 不一致

历史问题：

- report 中有 reference，但 validator 识别不到 URL，导致 `missing_references`

本次修复约束：

- 任何对 references 章节结构的修改，都必须保持和 `validate_run_outputs.py` / `reference_utils.py` 的解析一致
- 不允许为了“美观”而破坏 URL-first / resolvable references 的约束

### C. claim-evidence mapping 缺失导致 validator/critic 失效

历史问题：

- report 里没有稳定 claim-evidence section，导致 `claim_evidence_mapping_weak`

本次修复约束：

- 即使停止 claim 文本的强制 RQ 改写，也不能移除 claim-evidence mapping 本身
- 必须保留：
  - claim
  - evidence list
  - caveat
  - traceable identifiers

### D. experiment results gating 被弱化

历史问题：

- validated experiment results / waiting logic 曾发生软化或漂移风险

本次修复约束：

- 调整 experiment reviewer 路由时，不能破坏：
  - `await_experiment_results`
  - `validated experiment results`
  - pause / resume 语义

---

## 7. 测试与验收要求

本次修复不能只看最终 report，必须同时验证代码、artifact、validator、trace。

## 7.1 单元测试层

必须补 / 改的测试方向：

1. claim map 生成
   - claim 保持自然句，不出现 `Regarding ... evidence suggests ...`
   - 仍保留 RQ 对齐评分

2. analysis metadata
   - `authors/year` 从 `paper` 传递到 `analysis`

3. reference purity
   - 偏题 academic source 被标为 `background/reject`
   - reporting 不再无条件纳入 references

4. experiment review routing
   - `warn/fail` 条件下会回退或阻断

## 7.2 回归测试层

必须确保这些现有能力不回退：

1. `fetch_sources` / `analyze_sources` 的 cumulative accumulation
2. `reference_utils` 与 `validate_run_outputs` 的一致性
3. `claim_evidence_mapping` 章节仍然存在
4. `experiment pause/resume` 仍然正常

## 7.3 Run 输出层

目标不是所有 warning 一次清零，而是达到以下改进：

### 第一阶段目标

1. claim 不再出现关键词拼接句
2. citation reviewer 不再出现大面积 `missing year/authors`
3. references 中明显偏题论文显著减少

### 第二阶段目标

4. experiment reviewer 的 issue 能在流程中被真正修复，而不是反复出现
5. `critic` / `validator` 对报告质量的判断更一致

---

## 8. 推荐实施顺序

推荐按以下顺序做代码修复：

### Step 1

修 `analysis.py` 的 metadata 传递

原因：

- 最像 bug
- 改动小
- 收益立刻可见

### Step 2

重构 claim map 生成逻辑，停掉自然语言 RQ 改写

原因：

- 当前最明显的语义污染源

### Step 3

引入 reference purity 过滤

原因：

- 直接改善报告可信度

### Step 4

把 experiment reviewer verdict 接入 graph 路由

原因：

- 让 reviewer 从“旁观者”变成“控制器”

---

## 9. 结论

当前的语义准确性问题，本质上不是单一 prompt 失误，而是四个机制叠加：

1. claim 被 deterministic 对齐策略改坏
2. references 缺少核心证据纯度过滤
3. experiment reviewer 有检查、无执行力
4. citation metadata 在 analysis 阶段丢失

因此这次修复必须坚持一个原则：

`不再让系统先随意生成，再靠事后弱校验去补救，而是把“语义真值”和“流程控制”前移。`

如果后续按本文档实施，最先应该看到的改善是：

1. claim 恢复为正常可读句
2. references 更聚焦
3. citation warning 明显下降
4. experiment reviewer 不再只是反复报同样的 warn
