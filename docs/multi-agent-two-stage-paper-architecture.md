# ResearchAgent v2 Lite: 5-Agent 两阶段论文生成升级方案

## 1. 文档定位

本文档定义 `ResearchAgent` 的下一阶段升级方案。

目标不是一次性做出“最终形态的超复杂多 agent 系统”，而是在当前代码库基础上，落地一个：

- `5` 个以内核心 agent
- `2` 个清晰阶段
- `2` 次强制挑错 / 辩论审查
- `1` 个受控实验执行层

的可实施版本。

这份文档明确取代此前偏重的“大而全蓝图”，改为 `v2-lite` 方案。

---

## 2. 为什么要收缩方案

之前的规划存在两个问题：


1. agent 数量过多
2. 基础设施目标过重

对当前代码库来说，以下设计都过于超前：

- 十几个 specialist agent 同时协作
- 一次上齐完整 artifact registry / lineage / version store
- 一次支持 `local + ssh + slurm + k8s + ray`
- 一开始就做全量 reviewer 群

这会直接带来：

1. 研发周期过长
2. 调试和测试复杂度激增
3. 很难判断到底是哪一层出错
4. 容易做成“看起来先进，但实际不稳定”

因此 v2 应先压缩成一个可以稳定跑通的结构。

---

## 3. 总体目标

`ResearchAgent v2 Lite` 的目标是：

1. 让系统从“单次生成研究报告”升级为“两阶段生成论文”
2. 让系统从“单主流程 + reviewer gate”升级为“少量核心 agent + 结构化挑错”
3. 让实验设计不止停留在文本建议，而是可以进入受控执行层
4. 让最终论文生成之前，必须经过对抗式审查环节

一句话概括：

`先生成，再挑错，再修正，再成稿。`

---

## 4. 标准论文骨架

最终论文默认采用通用科研论文骨架：

1. `Title`
2. `Abstract`
3. `Introduction`
4. `Related Work`
5. `Background / Problem Formulation`
6. `Method / Proposed Approach`
7. `Experimental Setup`
8. `Results`
9. `Discussion`
10. `Limitations`
11. `Conclusion`
12. `References`
13. `Appendix / Supplementary`

但不是所有章节在同一时刻生成。

---

## 5. 两阶段论文生成

## 5.1 阶段一：前实验阶段

阶段一的目标是：

- 完整介绍 topic 所属领域
- 形成结构化 related work
- 分析 gap 与机会点
- 给出 hypothesis / method idea
- 生成可执行的实验设计
- 写出论文前半部分草稿

阶段一重点章节：

1. `Introduction`
2. `Related Work`
3. `Background / Problem Formulation`
4. `Method Idea / Hypothesis`
5. `Experimental Setup Plan`

阶段一不是定稿。

阶段一产出的内容必须明确区分：

- 已由文献支持的内容
- 研究假设
- 尚未验证的实验预期

严禁在阶段一把“预期结果”写成“已证明结果”。

## 5.2 阶段二：后实验阶段

阶段二在真实实验结果回写后启动。

阶段二的目标是：

- 吸收实验结果
- 写出 `Results`
- 写出 `Discussion`
- 写出 `Limitations`
- 写出 `Conclusion`
- 最后重写 `Abstract`
- 统一润色成稿

阶段二重点章节：

1. `Results`
2. `Discussion`
3. `Limitations`
4. `Conclusion`
5. `Abstract`

这里有一个硬规则：

`Abstract` 必须最后重写。

原因很简单：

如果没有真实结果约束，Abstract 很容易写成“看起来像论文摘要，但事实上没有完成闭环”。

---

## 6. 5 个核心 Agent

v2 Lite 只保留 5 个核心 agent。

## 6.1 Planner

职责：

- 理解用户 topic
- 决定任务类型
- 生成研究计划
- 划分阶段一 / 阶段二目标
- 给出停止条件与预算约束

输入：

- topic
- 用户约束
- 运行配置

输出：

- `TopicBrief`
- `ResearchPlan`
- `SectionPlan`

说明：

`Planner` 不是写作者，也不是 reviewer。它只负责把任务拆对。

## 6.2 Researcher

职责：

- 负责检索
- 负责阅读文献
- 负责构建 related work
- 负责 gap 分析
- 负责提出 idea 候选

输入：

- `TopicBrief`
- 检索结果
- 论文全文 / 摘要 / figure / metadata

输出：

- `CorpusSnapshot`
- `PaperNote[]`
- `RelatedWorkMatrix`
- `GapMap`
- `IdeaCandidates`

说明：

这个 agent 实际上吸收了原本过细的：

- retrieval strategist
- corpus curator
- reader
- related work synthesizer
- gap analyst
- idea generator

这些职责，但对外仍表现为一个统一的研究 agent。

## 6.3 Experimenter

职责：

- 把 idea 转成 `ExperimentSpec`
- 定义 baseline、指标、数据集、ablation
- 将实验提交给受控执行层
- 收集和整理实验结果

输入：

- `IdeaCandidates`
- `GapMap`
- 可用资源配置

输出：

- `ExperimentSpec`
- `ExecutionPlan`
- `ExperimentResultBundle`

说明：

`Experimenter` 可以在资源配置完整时自动跑实验，也可以只生成实验方案，等待人工执行。

## 6.4 Writer

职责：

- 负责阶段一文稿生成
- 负责阶段二结果写作
- 负责最终整稿
- 负责学术化表达和章节拼装

输入：

- 阶段一：`RelatedWorkMatrix`、`GapMap`、`ExperimentSpec`
- 阶段二：`ExperimentResultBundle`

输出：

- `Stage1Draft`
- `Stage2Draft`
- `FinalDraft`

说明：

`Writer` 负责写，不负责判定自己写得对不对。

## 6.5 Critic

职责：

- 专门挑错
- 不负责正向生成
- 在阶段一后和阶段二后分别做对抗式审查

输入：

- 当前 draft
- supporting artifacts
- reviewer / validator 结果

输出：

- `CritiqueReport`
- `RevisionDecision`

说明：

这是 v2 Lite 的关键 agent。  
你提出的“多个大模型进行辩论审查，也就是挑错”，在系统架构里就收敛到这个 agent。

它可以内部调用多个模型角色，但对外只表现为一个 `Critic`。

---

## 7. 挑错 / 辩论审查机制

## 7.1 为什么必须有挑错环节

如果系统只有“生成”，没有“反驳”，就会出现典型问题：

1. related work 看起来完整，实际漏关键工作
2. gap 看起来合理，实际只是换个说法
3. experiment plan 看起来专业，实际无法验证 hypothesis
4. results 看起来漂亮，实际讨论过度外推
5. final paper 看起来像论文，实际有大量 reviewer 会抓住的问题

因此 v2 Lite 要明确加入两个强制 gate。

## 7.2 Stage 1 Critique Gate

发生时机：

- 阶段一草稿完成后
- 阶段二开始前

检查对象：

- `RelatedWorkMatrix`
- `GapMap`
- `IdeaCandidates`
- `ExperimentSpec`
- `Stage1Draft`

重点问题：

1. 是否漏关键相关工作
2. gap 是否真实存在
3. idea 是否只是已有方法换皮
4. hypothesis 是否可检验
5. experiment design 是否能真正回答研究问题
6. draft 中是否把“猜测”写成“事实”

输出：

- `Stage1CritiqueReport`

可能动作：

- `pass`
- `revise_then_continue`
- `block`

## 7.3 Stage 2 Critique Gate

发生时机：

- 阶段二草稿完成后
- 最终润色前

检查对象：

- `ExperimentResultBundle`
- `Results`
- `Discussion`
- `Conclusion`
- `FinalDraft`

重点问题：

1. 结果文字是否与真实实验一致
2. Discussion 是否过度外推
3. Conclusion 是否超出证据
4. 引用和 claim 是否一致
5. 是否有 reviewer 一眼会抓住的漏洞

输出：

- `Stage2CritiqueReport`

可能动作：

- `pass`
- `revise_then_continue`
- `block`

## 7.4 多模型辩论如何落地

不建议做开放式、无限轮次的“模型群聊辩论”。

更稳的做法是把它做成一个受控流程：

1. `Writer / Researcher / Experimenter` 先产出 draft
2. `Critic-A` 站在“苛刻 reviewer”角度找错
3. `Critic-B` 站在“反方评审 / rebuttal 审稿人”角度找错
4. `Judge` 汇总两个 critique，给出统一 verdict

这里的 `Judge` 不必作为独立 agent 对外暴露。

实现上可以作为 `Critic` 内部的一个模式：

- mode A: novelty / completeness critic
- mode B: empirical / logic critic
- mode C: judge

因此系统层面仍然只有 5 个 agent。

---

## 8. 受控实验执行层

## 8.1 设计原则

实验执行不能直接建立在“让 agent 拿远程 shell”上。

必须满足：

1. 可审计
2. 可限制资源
3. 可恢复
4. 可记录 artifact
5. 可人工介入

因此实验执行层要独立于认知层。

## 8.2 v2 Lite 范围

v2 Lite 不做全量 runner 矩阵。

只做两种：

1. `local_runner`
2. `ssh_runner`

原因：

- `local_runner` 方便开发和小实验
- `ssh_runner` 足以覆盖“配置服务器和显卡资源后由 agent 自动跑实验”的主要诉求

先不做：

- `slurm_runner`
- `k8s_runner`
- `ray_runner`

这些可以作为后续扩展。

## 8.3 Resource Profile

UI 中要支持配置服务器与计算资源，但先只支持最小必要字段。

建议结构：

```yaml
resource_profile:
  profile_id: gpu-server-01
  runner_type: ssh_runner
  host: 10.0.0.8
  port: 22
  username: research
  auth_mode: key
  gpu_count: 1
  gpu_type: RTX4090
  cpu_cores: 16
  ram_gb: 64
  workspace_root: /data/researchagent_runs
  max_wall_time_hours: 12
  max_parallel_jobs: 1
```

## 8.4 ExperimentSpec

`Experimenter` 输出的实验描述必须结构化。

最低建议字段：

```yaml
experiment_spec:
  experiment_id: exp-001
  hypothesis_id: hyp-001
  task_type: classification
  objective: validate robustness improvement
  codebase:
    repo: git@github.com:org/project.git
    commit: abc123
    entrypoint: train.py
  datasets:
    - dataset_a:v1
  baselines:
    - erm
    - method_x
  metrics:
    - accuracy
    - macro_f1
  ablations:
    - remove_module_a
  resources:
    profile_id: gpu-server-01
    gpus: 1
    max_hours: 12
  expected_artifacts:
    - metrics.json
    - config.yaml
    - train.log
```

## 8.5 HITL 控制

以下动作建议必须人工确认：

1. 首次提交远程训练任务
2. 使用高成本 GPU profile
3. 覆盖已有结果
4. 扩增实验规模

也就是说，系统可以自动做实验，但不是“无限制自动化”。

---

## 9. 核心 Artifact 设计

v2 Lite 不做重型 artifact registry，但必须有清晰工件。

先保留 6 个核心 artifact：

1. `TopicBrief`
2. `RelatedWorkMatrix`
3. `GapMap`
4. `ExperimentSpec`
5. `ExperimentResultBundle`
6. `ManuscriptDraft`

## 9.1 TopicBrief

字段建议：

- topic
- task_type
- scope
- target_style
- language
- constraints

## 9.2 RelatedWorkMatrix

字段建议：

- paper_id
- title
- year
- task
- method family
- dataset
- metrics
- main contribution
- limitations
- relevance

## 9.3 GapMap

字段建议：

- gap_id
- gap_type
- description
- evidence
- affected papers
- confidence

## 9.4 ExperimentSpec

字段见上一节。

## 9.5 ExperimentResultBundle

字段建议：

- run_id
- experiment_id
- metrics
- artifacts
- logs
- best_run
- failed_runs
- notes

## 9.6 ManuscriptDraft

字段建议：

- phase
- sections
- claims
- references
- linked_artifacts

---

## 10. 对当前代码库的映射

v2 Lite 必须建立在现有实现之上，而不是推翻重做。

## 10.1 当前可复用模块

直接复用：

- [graph.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/graph.py)
- [stages](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/stages)
- [reviewers](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/reviewers)
- [trace_logger.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/tracing/trace_logger.py)
- [trace_grader.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/tracing/trace_grader.py)
- [schemas.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/core/schemas.py)

## 10.2 现有模块如何对应到 5 agent

### Planner

可落在：

- [planning.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/stages/planning.py)
- [query_planning.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/core/query_planning.py)

### Researcher

可落在：

- [retrieval.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/stages/retrieval.py)
- [analysis.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/stages/analysis.py)
- [synthesis.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/stages/synthesis.py)

### Experimenter

可落在：

- [experiments.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/stages/experiments.py)
- 后续新增 `execution/*`

### Writer

可落在：

- [reporting.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/stages/reporting.py)

### Critic

可组合现有：

- [retrieval_reviewer.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/reviewers/retrieval_reviewer.py)
- [experiment_reviewer.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/reviewers/experiment_reviewer.py)
- [post_report_review.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/reviewers/post_report_review.py)

再新增：

- `src/agent/reviewers/stage1_critic.py`
- `src/agent/reviewers/stage2_critic.py`

---

## 11. 建议流程图

## 11.1 阶段一

```text
topic_intake
  -> plan_research
  -> fetch_sources
  -> index_sources
  -> analyze_sources
  -> review_retrieval
  -> synthesize_related_work
  -> analyze_gaps
  -> generate_ideas
  -> design_experiment
  -> stage1_critic_gate
      -> revise stage1 artifacts
      -> or approve stage1 draft
```

## 11.2 阶段二

```text
ingest_experiment_results
  -> validate_results
  -> analyze_results
  -> write_results_discussion
  -> write_conclusion
  -> rewrite_abstract
  -> stage2_critic_gate
      -> revise manuscript
      -> or approve final draft
  -> final_polish
```

---

## 12. Critic 的统一契约

所有 Critic 输出必须统一结构：

```json
{
  "critic_name": "stage1_critic",
  "status": "warn",
  "action": "revise_then_continue",
  "issues": [
    "missing key baseline paper",
    "experiment does not test main hypothesis"
  ],
  "suggested_fixes": [
    "add 2 recent benchmark papers",
    "introduce ablation for module A"
  ],
  "severity": "medium",
  "confidence": 0.87
}
```

允许动作：

- `pass`
- `revise_then_continue`
- `block`

说明：

这里不再沿用过细的 reviewer 动作集合，而是收口为更容易执行的 3 类。

---

## 13. UI 影响

v2 Lite 的 UI 不必一次做成完整研究工作台，但至少要支持：

## 13.1 Run 页

- topic
- phase
- run / resume
- 当前阶段状态

## 13.2 Models 页

- planner/researcher/writer/critic 的模型配置
- API 凭证状态

## 13.3 Resources 页

- `local_runner`
- `ssh_runner`
- GPU profile
- 提交策略

## 13.4 Artifacts 页

- `RelatedWorkMatrix`
- `GapMap`
- `ExperimentSpec`
- `ExperimentResultBundle`
- draft 预览

## 13.5 Critique 页

- Stage 1 Critique
- Stage 2 Critique
- 每个 issue 的修复建议
- 人工批准 / 继续修订

---

## 14. 推荐实施顺序

## Milestone 1: 两阶段流程固化

目标：

- 明确 `stage1` / `stage2`
- 把当前报告链路拆成两段

验收：

- 可以在没有实验结果时只产出 `Stage1Draft`
- 有实验结果时再补 `Stage2Draft`

## Milestone 2: 6 个核心 artifact

目标：

- 在现有 state 里落入 6 个核心 artifact

验收：

- 每次 run 都能导出结构化 artifact JSON

## Milestone 3: 5 个 agent 收口

目标：

- 把现有 stages/reviewers 重新组织成 5-agent 模式

验收：

- 对外的系统角色只有 `Planner / Researcher / Experimenter / Writer / Critic`

## Milestone 4: Stage 1 Critique Gate

目标：

- 阶段一完成后强制挑错

验收：

- 没有通过 critique 时不能进入下一阶段

## Milestone 5: SSH 实验执行

目标：

- 新增 `ssh_runner`
- 支持提交受控实验

验收：

- 可从 UI 或 CLI 提交一个远程实验并回写结果

## Milestone 6: Stage 2 Critique Gate

目标：

- 在最终成稿前做第二次挑错

验收：

- final draft 必须经过结果一致性和论文级 red-team 审查

---

## 15. 明确不做什么

为了避免 v2 Lite 再次膨胀，本阶段明确不做：

1. 不做超过 5 个公开角色 agent
2. 不做群聊式自由辩论系统
3. 不做全量分布式 runner 矩阵
4. 不做过重的 artifact 平台化基础设施
5. 不做 OpenClaw 深度绑定主流程

这些都可以在 v3 再考虑。

---

## 16. 结论

`ResearchAgent v2 Lite` 的最优路线不是“更多 agent”，而是“更强闭环”。

推荐最终收口为：

- `5` 个核心 agent
- `2` 个论文生成阶段
- `2` 次强制 critique / debate review gate
- `1` 个受控实验执行层

一句话版本：

`Planner 定方向，Researcher 找证据，Experimenter 产与跑实验，Writer 负责成稿，Critic 专门挑错。`

这套结构已经足够支持你想要的目标：

- 先形成综述和 related work
- 再提出 idea 和实验方案
- 配好服务器和 GPU 后由系统自动执行实验
- 回写结果后完成后半篇论文
- 在成稿前经过多模型挑错审查

这比十几个 agent 的方案更克制，也更适合当前代码库继续演进。
