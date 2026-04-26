---
name: artifact-review
description: 单 artifact 评审 pipeline。用户说"审一下这份 X" / "review 这个 report" / "找漏洞" 时触发。串联 reviewer → critic 双层评审，给可执行修改清单 + 严格质量 verdict。
---

# Artifact Review

对一份独立 artifact（report.md / sources.json / experiment 结果 / 用户自己写的草稿）做双层评审。

## 触发场景

- 用户提供具体文件路径 + 说"审一下"
- 上一段 pipeline 完成后用户说"看看 report 怎么样"
- 写完 paper 草稿想找盲点

## Run ID 命名

`run_id = "review_" + YYYYMMDD_HHMMSS` + "_" + <被审 artifact 的简短名>，例：`review_20260426_103000_lit_review_report`。

## 步骤

### 1. reviewer (流程内审) → `outputs/<run_id>/review.md`

```
spawn reviewer(target_artifact=<path>, context=<可选 evidence/source files>)
```

期望产物：`review.md` 含 5 维评分 + standard issue 列表 + modification suggestions + verdict。

### 2. (可选) critic (重度评审) → `outputs/<run_id>/critique.md`

如果 reviewer verdict ≠ ✅ approve **或** 用户明示"也让 critic 看看" **或** artifact 是高 stake（要发表的 paper / 要交付的 report）：

```
spawn critic(target_artifact=<path>, reviewer_review=outputs/<run_id>/review.md, context=<...>)
```

期望产物：`critique.md` 含 🔴/🟠/🟡 严重度分级 issue + 详细 reasoning。critic 的输出**比 reviewer 更深**——专门挑逻辑跳跃 / 隐藏陷阱。

### 3. 综合 verdict → 直接回复用户

不写额外文件——主 agent 综合 review.md + critique.md（如有）给用户：

```markdown
## 评审 Verdict for <artifact>

**reviewer (流程门)**: <verdict>
- 5 维分数：novelty=X / soundness=X / clarity=X / significance=X / completeness=X

**critic (深度审)**（如调用）: <count> 🔴 / <count> 🟠 / <count> 🟡

### Top issues
- <从 review.md / critique.md 摘前 3-5 条>

### Suggested next action
- <修订 → 重交本 pipeline / 大改 → 回上游 / approve>
```

## Artifact 命名约定

- `outputs/<run_id>/review.md`（reviewer 出，必有）
- `outputs/<run_id>/critique.md`（critic 出，可选）

## 失败 / 重启策略

- artifact 文件不存在 → 直接报错让用户检查路径，不创建空 review
- artifact 是 binary（pdf / image） → reviewer / critic 用 Read 工具看内容；超大 PDF 提示用户先转 markdown
- reviewer 与 critic verdict 严重冲突（reviewer ✅ critic 🔴）→ 在最终回复中**双方意见都展示**，让用户判断

## 完成态

`review.md` 存在；critic 调用时 `critique.md` 也存在；用户已收到综合 verdict。

## 不做的事

- **不**直接修改被审 artifact（修订是 writer / analyzer 的事）
- **不**反复跑同一个 artifact（一次给完整 verdict 后等用户改完再传新版本）
- **不**为了"鼓励"虚抬分数（reviewer / critic 的价值是真问题）
