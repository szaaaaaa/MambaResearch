# Agent 可靠性评测清单

## 1. 目标
用统一流程评估当前 `agent` 模式是否“可用、稳定、可信”。

## 2. 评测环境
- Python 环境已安装并可运行项目
- 已设置 `OPENAI_API_KEY`
- 网络可访问 arXiv / Semantic Scholar / DuckDuckGo / OpenAI

## 3. 冒烟测试（先确认链路打通）
```powershell
python -m scripts.run_agent --topic "retrieval augmented generation" --max_iter 2 --papers_per_query 3 --language zh -v
```

检查项（全部通过才进入下一步）：
- 生成 `outputs/run_*/research_report.md`
- 生成 `outputs/run_*/research_state.json`
- `research_state.json` 中 `iterations >= 1`
- `research_state.json` 中 `sources_enabled` 符合预期

## 4. 准确性测试（已知答案题集）
准备 5-10 个你熟悉的主题，每题运行一次：

```powershell
python -m scripts.run_agent --topic "<你的测试题>" --max_iter 3 --papers_per_query 5 --language zh
```

每题打分（0/1）：
- 结论正确（`correct`）
- 命中关键文献（`key_paper_hit`）
- 无明显幻觉/伪造引用（`no_hallucination`）
- 证据支持结论（`evidence_aligned`）
- 有边界与局限说明（`limits_noted`）

## 5. 稳定性测试（同题重复）
同一个 topic 连跑 3 次：

```powershell
python -m scripts.run_agent --topic "<同一个题目>" --max_iter 3 --papers_per_query 5 --language zh
```

检查：
- 核心结论是否一致
- 关键引用是否大体重合
- 是否出现一次好一次差的“漂移”

## 6. 消融测试（定位问题来源）
同一题运行三组：

```powershell
# 全源
python -m scripts.run_agent --topic "<题目>" --sources arxiv,semantic_scholar,web

# 仅学术
python -m scripts.run_agent --topic "<题目>" --sources arxiv,semantic_scholar --no-web

# 仅网页
python -m scripts.run_agent --topic "<题目>" --sources web
```

比较三组报告质量，判断问题在：
- 学术检索召回
- 网页噪声
- 综合推理阶段

## 7. 对抗测试（抗误导）
选 2-3 个争议/营销信息多的主题，重点看：
- 是否区分高/中/低可信来源
- 是否明确“不确定”与“证据不足”
- 是否避免单一低质量来源主导结论

## 8. 建议通过阈值
- 幻觉率 <= 10%
- 关键文献命中率 >= 70%
- 证据-结论一致率 >= 80%
- 同题三次核心结论一致率 >= 80%

> 注：阈值可按你的业务风险等级调整。高风险场景应更严格。

## 9. 评分模板（可直接复制）
```text
题目:
运行命令:
报告文件:
状态文件:

correct(0/1):
key_paper_hit(0/1):
no_hallucination(0/1):
evidence_aligned(0/1):
limits_noted(0/1):
总分(0-5):

主要问题:
改进建议:
```

## 10. 推荐测试题（示例）
- Retrieval-Augmented Generation 的主要局限是什么？
- LoRA 与全量微调在小样本场景的取舍？
- Agentic RAG 与传统 RAG 的关键差异？
- Tool-using LLM 在可靠性上的常见失败模式？
- 多模态大模型评测中，benchmark leakage 风险如何识别？
