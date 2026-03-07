# `src/agent/nodes.py` 拆分方案

> 日期：2026-03-06
> 适用范围：当前 `ResearchAgent` 主流程节点实现、helper 纯函数、测试 patch 面

## 1. 背景

当前 [src/agent/nodes.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/nodes.py) 已经达到约 2712 行，承担了过多职责：

- LangGraph 节点入口函数
- LLM 调用桥接与 JSON 解析
- query planning / retrieval routing
- evidence / claim map 构建
- experiment plan / results 处理
- report critic / repair / acceptance metrics
- reference 清洗与 report 渲染

这已经不只是“文件有点长”，而是出现了真实的工程问题：

- 纯函数和 graph-facing 节点函数混在一起，阅读和定位成本高。
- 一部分逻辑已经开始迁出到 `src/agent/core/`，但 `nodes.py` 里仍保留旧实现，存在重复。
- 现有测试大量 patch `src.agent.nodes.*`，导致重构时很容易破坏测试面。
- 后续要继续做 structured outputs、reviewer gate、artifact schema 时，`nodes.py` 会成为主要阻力。

## 2. 当前问题清单

### 2.1 文件职责过载

当前 `nodes.py` 同时包含：

- 9 个图节点入口：
  - `plan_research`
  - `fetch_sources`
  - `index_sources`
  - `analyze_sources`
  - `synthesize`
  - `recommend_experiments`
  - `ingest_experiment_results`
  - `evaluate_progress`
  - `generate_report`
- 大量仅服务于某一阶段的局部 helper
- 多个本应进入 `core/` 的纯逻辑函数

结果是：

- 节点边界不清晰
- helper 复用困难
- review/tracing/metrics 接入时改动面过大

### 2.2 已出现重复实现

当前已有重复或部分重复的函数族：

- `claim/evidence` 相关逻辑已经开始迁到 `src/agent/core/evidence.py`
- `report helper` 相关逻辑已经开始迁到 `src/agent/core/report_helpers.py`
- `tokenize/domain/tier` 相关逻辑已经开始迁到 `src/agent/core/source_ranking.py`

如果不继续收口，会长期存在“两套实现”：

- 改一处忘一处
- reviewer 和主流程看到的逻辑不一致
- 测试覆盖会逐渐失真

### 2.3 模块命名存在约束

当前已经存在文件：

- `src/agent/nodes.py`

因此后续不能直接新建同名目录：

- `src/agent/nodes/`

否则会与现有模块名冲突。拆分后的目录建议使用：

- `src/agent/stages/`

这是本次方案的硬约束之一。

### 2.4 测试 patch 面不能一次打断

当前已有测试直接 patch：

- `src.agent.nodes._llm_call`
- `src.agent.nodes.dispatch`
- `src.agent.nodes._critic_report`
- `src.agent.nodes._compute_acceptance_metrics`
- `src.agent.nodes._extract_reference_urls`

这意味着不能粗暴地“把函数搬走然后改 import”。如果不设计兼容层，测试会大面积失效。

## 3. 本次拆分目标

本次拆分的目标不是“把大文件拆小”这么简单，而是完成以下 5 件事：

1. 让 `nodes.py` 只保留 graph-facing 的兼容入口，不再承载大段业务逻辑。
2. 让纯函数逻辑优先收敛到 `core/`，避免重复实现。
3. 让节点按阶段拆分到 `stages/`，形成稳定的模块边界。
4. 保持现有 graph 和大多数测试在过渡期可运行。
5. 为后续 structured outputs、artifact schema、多 reviewer 协作留出清晰扩展点。

## 4. 非目标

以下内容不应与本次拆分强绑定：

- 不在本轮同时重写业务逻辑。
- 不在本轮同时替换全部 prompt。
- 不在本轮直接引入完整 supervisor-style 多 agent 编排。
- 不在本轮一次性移除所有 `src.agent.nodes` 测试 patch 点。

换句话说，本次拆分首先是结构重构，不是行为重写。

## 5. 设计原则

### 5.1 保持公共入口稳定

短期内继续保留：

- `from src.agent.nodes import plan_research, fetch_sources, ...`

也就是说，`graph.py` 第一阶段可以不改导入路径，降低迁移风险。

### 5.2 先抽纯逻辑，再搬节点入口

优先顺序应为：

1. 去掉重复 helper
2. 把纯函数迁到 `core/`
3. 再把 node entry functions 迁到 `stages/`
4. 最后再讨论是否让 `graph.py` 直接依赖 `stages/`

### 5.3 兼容层只做转发，不再承载业务

最终 [src/agent/nodes.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/nodes.py) 应成为一个薄 facade：

- 对外暴露旧 API
- 注入兼容依赖
- 转发到 `src/agent/stages/*`

它不应再包含核心业务算法。

### 5.4 避免过度碎片化

不建议拆成“一个节点一个文件 + 一个 helper 一个文件”。这样会制造另一种维护成本。

更合适的粒度是：

- `core/` 放跨节点纯逻辑
- `stages/` 放按阶段组织的节点实现

## 6. 目标目录结构

建议新增如下结构：

```text
src/agent/
  nodes.py                    # 兼容 facade，保留旧导入路径
  stages/
    __init__.py
    runtime.py                # LLM/executor/JSON 适配层
    planning.py               # plan_research 及其阶段 helper
    retrieval.py              # fetch_sources 及 query routing
    indexing.py               # index_sources
    analysis.py               # analyze_sources
    synthesis.py              # synthesize
    experiments.py            # recommend_experiments / ingest_experiment_results
    evaluation.py             # evaluate_progress
    reporting.py              # generate_report
```

同时扩充现有 `core/`：

```text
src/agent/core/
  query_planning.py           # 新增：query planning 纯函数
  evidence.py                 # 扩充：claim/evidence 纯函数
  report_helpers.py           # 扩充：report/reference/metrics 纯函数
  source_ranking.py           # 扩充：tokenize/domain/tier/ranking
```

## 7. 模块职责划分

### 7.1 `src/agent/stages/runtime.py`

职责：

- 提供阶段实现依赖的 runtime adapter
- 管理 `_llm_call`
- 管理 `_parse_json`
- 包装 `dispatch`

建议放入：

- `_llm_call`
- `_parse_json`

后续演进方向：

- 当 `llm_provider` 支持强 schema 时，这里变成一个很薄的 schema-aware adapter

### 7.2 `src/agent/core/query_planning.py`

职责：

- 纯 query planning 逻辑
- 不直接操作 graph，不直接写 state

建议迁入：

- `_infer_intent`
- `_default_sections_for_intent`
- `_compress_findings_for_context`
- `_expand_acronyms`
- `_with_synonym_hints`
- `_rewrite_queries_for_rq`
- `_expand_query_set`
- `_is_simple_query`
- `_is_simple_query_with_cfg`
- `_route_query`

保留在 stage 内的函数：

- `_load_budget_and_scope`

原因：

- 它直接读取配置和 state，虽然可以纯化，但第一轮可先留在 planning stage 内，避免迁移过宽。

### 7.3 `src/agent/core/source_ranking.py`

职责：

- 所有与 tokenization、source typing、轻量 ranking 相关的纯函数

建议收敛到这里：

- `_tokenize`
- `_extract_domain`
- `_source_tier`
- `_analysis_score_for_rq`

可选二期迁入：

- `_normalize_source_url`
- `_source_dedupe_key`
- `_dedupe_and_rank_analyses`

### 7.4 `src/agent/core/evidence.py`

职责：

- claim extraction / alignment / evidence map 构建
- evidence audit 构建

建议收敛到这里：

- `_claim_candidates`
- `_claim_has_rq_signal`
- `_claim_relevance_ratio`
- `_rq_anchor_terms`
- `_align_claim_to_rq`
- `_ensure_unique_claim_text`
- `_build_claim_evidence_map`
- `_build_evidence_audit_log`
- `_format_claim_map`

这类逻辑应该是 reviewer 与 synthesis 共用的核心能力，不应长期留在 `nodes.py`。

### 7.5 `src/agent/core/report_helpers.py`

职责：

- report 构造、cleaning、validation、acceptance metrics

建议收敛到这里：

- `_validate_experiment_plan`
- `_extract_reference_urls` 的 node 本地 wrapper 删除，统一使用 `reference_utils`
- `_critic_report`
- `_repair_report_once`
- `_compute_acceptance_metrics`
- `_clean_reference_section`
- `_strip_outer_markdown_fence`
- `_insert_chapter_before_references`
- `_claim_mapping_section_exists`
- `_claim_evidence_coverage_ratio`
- `_render_claim_evidence_mapping`
- `_ensure_claim_evidence_mapping_in_report`
- `_render_experiment_blueprint`
- `_render_experiment_results`

说明：

- `_critic_report` / `_repair_report_once` 虽然会调用 LLM，但它们仍然属于 reporting domain helper，而不是 graph node 本身。
- 如果后续希望进一步严格分层，可以在第三阶段再把 LLM-aware report helper 拆到 `stages/reporting_support.py`。

## 8. `stages/` 层具体划分

### 8.1 `src/agent/stages/planning.py`

职责：

- topic 意图识别
- 初始 research questions / search queries 生成
- scope / budget 组装

建议包含：

- `plan_research`
- `_load_budget_and_scope`

依赖：

- `core/query_planning.py`
- `stages/runtime.py`
- `state_access.py`
- `prompts.py`

### 8.2 `src/agent/stages/retrieval.py`

职责：

- source enablement 检查
- academic/web query routing
- search executor 调度
- fetch 阶段状态更新

建议包含：

- `fetch_sources`
- `_source_enabled`
- `_academic_sources_enabled`
- `_web_sources_enabled`

依赖：

- `core/query_planning.py`
- `executor_router.py`
- `state_access.py`

### 8.3 `src/agent/stages/indexing.py`

职责：

- 已下载 source 的索引构建
- indexed IDs 管理

建议包含：

- `index_sources`

说明：

- 这是一个单节点模块，但它和 retrieval / analysis 的依赖明显不同，值得单独成文件。

### 8.4 `src/agent/stages/analysis.py`

职责：

- source 分析
- topic relevance 过滤
- analysis ranking / dedupe

建议包含：

- `analyze_sources`
- `_extract_table_signals`
- `_build_topic_keywords`
- `_build_topic_anchor_terms`
- `_is_topic_relevant`
- `_has_traceable_source`
- `_uid_to_resolvable_url`
- `_normalize_source_url`
- `_source_dedupe_key`
- `_dedupe_and_rank_analyses`

依赖：

- `core/source_ranking.py`
- `stages/runtime.py`
- `prompts.py`

### 8.5 `src/agent/stages/synthesis.py`

职责：

- findings 汇总
- synthesis 生成
- evidence artifact 生成

建议包含：

- `synthesize`
- `_detect_domain_by_rules`
- `_detect_domain_by_llm`

依赖：

- `core/evidence.py`
- `stages/runtime.py`
- `prompts.py`

说明：

- domain detection 目前服务于 experiment planning 入口判断，但逻辑与 synthesis 强关联，放这里更合适。

### 8.6 `src/agent/stages/experiments.py`

职责：

- experiment plan 生成
- human result normalization
- experiment result validation

建议包含：

- `recommend_experiments`
- `ingest_experiment_results`
- `_limit_experiment_groups_per_rq`
- `_normalize_experiment_results_with_llm`
- `_validate_experiment_results`

依赖：

- `core/report_helpers.py` 中的 `_validate_experiment_plan`
- `stages/runtime.py`
- `prompts.py`

### 8.7 `src/agent/stages/evaluation.py`

职责：

- loop / stop 决策
- gap 汇总
- should_continue 决策

建议包含：

- `evaluate_progress`

说明：

- 它是流程控制节点，最好不要和 report 生成放在同一个文件里。

### 8.8 `src/agent/stages/reporting.py`

职责：

- 最终报告生成
- reference normalization
- report critic / repair
- acceptance metrics

建议包含：

- `generate_report`

依赖：

- `core/report_helpers.py`
- `stages/runtime.py`
- `prompts.py`

## 9. 旧函数到新模块的映射

| 当前函数 | 目标位置 | 说明 |
| --- | --- | --- |
| `_llm_call` | `stages/runtime.py` | 先保留旧签名 |
| `_parse_json` | `stages/runtime.py` | 二期再替换为 schema-aware parser |
| `_infer_intent` 等 query 规划函数 | `core/query_planning.py` | 纯逻辑 |
| `_source_enabled` / `_academic_sources_enabled` / `_web_sources_enabled` | `stages/retrieval.py` | retrieval stage 本地 helper |
| `_extract_domain` / `_source_tier` / `_tokenize` / `_analysis_score_for_rq` | `core/source_ranking.py` | 删除 `nodes.py` 重复实现 |
| claim/evidence 构建函数族 | `core/evidence.py` | synthesis 与 reviewer 共享 |
| experiment validation / report rendering 函数族 | `core/report_helpers.py` | 删除 `nodes.py` 重复实现 |
| `plan_research` | `stages/planning.py` | graph-facing node |
| `fetch_sources` | `stages/retrieval.py` | graph-facing node |
| `index_sources` | `stages/indexing.py` | graph-facing node |
| `analyze_sources` | `stages/analysis.py` | graph-facing node |
| `synthesize` | `stages/synthesis.py` | graph-facing node |
| `recommend_experiments` / `ingest_experiment_results` | `stages/experiments.py` | graph-facing node |
| `evaluate_progress` | `stages/evaluation.py` | graph-facing node |
| `generate_report` | `stages/reporting.py` | graph-facing node |

## 10. 兼容层方案

### 10.1 `src/agent/nodes.py` 过渡期职责

过渡期的 `nodes.py` 应只做三件事：

1. re-export graph 需要的 node function
2. 暴露旧测试 patch 点
3. 用 wrapper 把 patch 依赖注入到新 stage 实现

推荐形态：

```python
from src.agent.stages.runtime import llm_call as _llm_call
from src.agent.stages.runtime import parse_json as _parse_json
from src.agent.stages.planning import plan_research as _plan_research

def plan_research(state):
    return _plan_research(
        state,
        llm_call=_llm_call,
        parse_json=_parse_json,
    )
```

这样做的目的不是“优雅”，而是确保现有测试里 patch：

- `src.agent.nodes._llm_call`

仍然能影响新实现。

### 10.2 不建议立即让 `graph.py` 直接改用 `stages/*`

在第一轮拆分中，不建议立刻让 [graph.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/graph.py) 改为：

- `from src.agent.stages.planning import plan_research`

更稳的做法是：

- 先继续通过 `src.agent.nodes` 导入
- 等 wrapper、tests、trace、reviewer 全部稳定后，再决定是否切 graph import

### 10.3 facade 的最终目标

最终 [src/agent/nodes.py](/c:/Users/ziang/Desktop/ResearchAgent/src/agent/nodes.py) 应控制在：

- 100 到 200 行

并且不再定义复杂 helper。

## 11. 分阶段实施计划

### Phase 0：建立基线

目标：

- 在拆分前固定当前行为

动作：

1. 先修复当前已知的 tracing 落盘测试失败。
2. 跑全量测试，记录基线。
3. 标记当前 `nodes.py` 中与 `core/` 重复的函数。

完成标准：

- `pytest` 全绿
- 当前 run output 没有新增回归

### Phase 1：先去重，不拆节点

目标：

- 去掉 `nodes.py` 内部重复 helper

动作：

1. `nodes.py` 直接改为调用：
   - `core/evidence.py`
   - `core/report_helpers.py`
   - `core/source_ranking.py`
2. 删除 `nodes.py` 中对应的重复实现。
3. 保持所有 node 函数位置不变。

完成标准：

- 行为不变
- `nodes.py` 显著减重
- reviewer 与主流程开始共享同一套 helper

### Phase 2：引入 `stages/` 包

目标：

- 按阶段移动 graph-facing 节点实现

动作：

1. 新增 `src/agent/stages/`
2. 先迁最独立的节点：
   - `index_sources`
   - `evaluate_progress`
   - `generate_report`
3. 再迁复杂节点：
   - `plan_research`
   - `fetch_sources`
   - `analyze_sources`
   - `synthesize`
   - `recommend_experiments`
   - `ingest_experiment_results`
4. `src/agent/nodes.py` 改为 facade wrapper

完成标准：

- graph 仍可通过 `src.agent.nodes` 正常运行
- 原测试大体不需要大改即可通过

### Phase 3：测试 patch 面迁移

目标：

- 降低测试对 `nodes.py` 私有实现的耦合

动作：

1. 新测试优先 patch：
   - `src.agent.stages.runtime`
   - `src.agent.core.*`
2. 旧测试逐步从：
   - `src.agent.nodes._llm_call`
   - `src.agent.nodes.dispatch`
   转向新 patch 点
3. 对 helper 采用更细粒度单元测试，而不是穿过整份 `nodes.py`

完成标准：

- `tests/test_nodes_flow.py` 规模缩小
- `tests/test_nodes_helpers.py` 一部分被拆到 `tests/test_stage_*` 与 `tests/test_core_*`

### Phase 4：收尾与 API 清理

目标：

- 把 facade 变成真正的兼容层，而非第二份实现

动作：

1. 检查 `nodes.py` 是否还残留业务逻辑。
2. 决定 `graph.py` 是否切换为直接依赖 `stages/*`。
3. 若外部兼容已不重要，可减少对私有 patch 面的暴露。

完成标准：

- `nodes.py` 只剩 wrapper / re-export
- stage 边界清晰
- helper 所有权清晰

## 12. 建议的实际迁移顺序

按风险从低到高，推荐如下顺序：

1. `source_ranking` 去重
2. `evidence` 去重
3. `report_helpers` 去重
4. `runtime.py` 抽出 `_llm_call` / `_parse_json`
5. 提取 `indexing.py`
6. 提取 `evaluation.py`
7. 提取 `reporting.py`
8. 提取 `experiments.py`
9. 提取 `planning.py`
10. 提取 `retrieval.py`
11. 提取 `analysis.py`
12. 提取 `synthesis.py`

这样安排的原因：

- 先拆低耦合节点和纯 helper
- 最复杂的 retrieval / analysis / synthesis 留到后面
- 每一步都能保持较小 diff，便于回归

## 13. 测试改造计划

### 13.1 新增测试文件建议

建议新增：

- `tests/test_stage_planning.py`
- `tests/test_stage_retrieval.py`
- `tests/test_stage_indexing.py`
- `tests/test_stage_analysis.py`
- `tests/test_stage_synthesis.py`
- `tests/test_stage_experiments.py`
- `tests/test_stage_evaluation.py`
- `tests/test_stage_reporting.py`

### 13.2 现有测试如何迁移

现有测试大致分三类：

1. 真正的流程测试
2. helper 单元测试
3. patch-based compatibility 测试

迁移建议：

- 流程测试继续覆盖 `graph.py` 与 facade
- helper 测试迁到 `core/*`
- patch-based 测试逐步转到 `stages/runtime.py`

### 13.3 必跑测试集合

每个拆分阶段至少跑：

```text
python -m pytest tests/test_graph_runtime.py -q
python -m pytest tests/test_nodes_flow.py -q
python -m pytest tests/test_nodes_helpers.py -q
python -m pytest tests/test_recommend_experiments.py -q
python -m pytest tests/test_experiment_integration.py -q
python -m pytest tests/test_tracing.py -q
python -m pytest -q
```

## 14. 风险与规避

### 14.1 import cycle

风险：

- `stages/*` 反向 import `nodes.py`

规避：

- `nodes.py` 只能 import `stages/*`
- `stages/*` 不允许 import `nodes.py`
- 共享 helper 全部落到 `core/*` 或 `stages/runtime.py`

### 14.2 patch 失效

风险：

- 现有测试 patch `src.agent.nodes._llm_call` 后，对新 stage 实现不再生效

规避：

- facade wrapper 显式注入依赖
- 在彻底迁移测试前，不移除旧 patch 面

### 14.3 state namespace 行为漂移

风险：

- 新 stage 模块直接读写 namespaced state，旧逻辑仍依赖 flat alias

规避：

- 统一继续走 `state_access.sget()` 与 `to_namespaced_update()`
- 不允许 stage 直接私自拼两套 state 结构

### 14.4 不小心把拆分做成行为重写

风险：

- 拆文件时顺手改 prompt、ranking、默认阈值，导致回归定位困难

规避：

- 每个 PR 只做结构迁移或局部无行为变更
- 行为变更单独提交

## 15. 验收标准

完成本轮拆分后，应满足：

1. `src/agent/nodes.py` 不再包含大段业务实现。
2. `nodes.py` 行数降到 200 行以内，至少应显著低于当前规模。
3. 不再存在 `nodes.py` 与 `core/*` 的重复 helper。
4. graph 运行逻辑不变。
5. reviewer / tracing / checkpointing 相关测试无回归。
6. 后续继续做 structured outputs 时，无需再回到 `nodes.py` 做大面积切割。

## 16. 推荐的首批落地任务

如果按最稳方式开始，第一批我建议只做下面这些：

1. 修 tracing 测试失败，恢复全绿基线。
2. 把 `source_ranking` 相关重复函数从 `nodes.py` 收口到 `core/source_ranking.py`。
3. 把 `evidence` 相关重复函数从 `nodes.py` 收口到 `core/evidence.py`。
4. 把 `report helper` 相关重复函数从 `nodes.py` 收口到 `core/report_helpers.py`。
5. 新建 `src/agent/stages/runtime.py`，抽出 `_llm_call` / `_parse_json`。
6. 第一个真正拆出的节点建议选 `generate_report` 或 `index_sources`，不要先动 `fetch_sources`。

这是风险最低、收益最高的一条路径。

## 17. 结论

`nodes.py` 目前已经到了必须拆的阶段，但拆分方式不能是简单的“按功能切文件”。正确的做法是：

- 先统一纯逻辑归属
- 再建立 `stages/` 目录
- 用 `src/agent/nodes.py` 做兼容 facade
- 最后逐步迁移测试与 graph 依赖

如果按这套方案执行，拆分不会只是“看起来更整洁”，而是会直接改善后续的：

- 多 reviewer 扩展
- structured outputs 接入
- state schema 演进
- tracing / eval 稳定性
- 单元测试颗粒度

