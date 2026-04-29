---
name: idea-brainstorming
description: 想法探讨 pipeline。用户说"我有个 idea，帮我探讨" / "X 这个想法靠谱吗" / "帮我想想 ..." 时触发。串联 conductor → analyzer → critic，给"是否值得做"的诚实评估 + 风险点 + 下一步建议。不写实验脚本不写论文，纯思辨。
---

# Idea Brainstorming

帮用户把模糊的研究 idea 想清楚——值不值得做、有什么坑、跟现有工作的关系。

## 触发场景

- 用户带着一个粗略 idea 来："我想 ..."
- 用户问"X 这个方向有意义吗 / 有人做过吗 / 能 work 吗"
- 写 grant / proposal 之前的 sanity check

**不触发**：用户已经决定做、想知道怎么做 → 走 empirical-study；用户想要全面综述 → 走 structured-lit-review。

## Run ID 命名

`run_id = "brainstorm_" + YYYYMMDD_HHMMSS`，所有产物 `outputs/<run_id>/`。

## 步骤

### 1. conductor → `outputs/<run_id>/idea_unpacked.md`

```
spawn conductor(user_idea=<原话>, mode="idea_unpack")
```

期望产物：`idea_unpacked.md` 含：
- **Reformulated**：把模糊表达翻译成清晰的研究问题（一句话）
- **Decomposition**：把 idea 拆 2-4 个可独立验证的子问题
- **Assumptions**：idea 隐含的假设清单（"假设 X 可获取" / "假设 Y 不变"）

### 2. (可选) paper-searcher → `outputs/<run_id>/related_work_quick.json`

如果用户没明示"我已知道相关工作"，spawn 一次轻量搜索（3-5 篇）了解 prior art：

```
spawn paper-searcher(topic=<reformulated question>, max_results=5)
```

### 3. analyzer → `outputs/<run_id>/idea_assessment.md`

```
spawn analyzer(idea_unpacked=outputs/<run_id>/idea_unpacked.md, related_work=<可选 related_work_quick.json>, mode="idea_assessment")
```

期望产物：`idea_assessment.md` 含 4 段：
- **Novelty**：相比已知工作，这个 idea 新在哪？已经被做过吗？
- **Feasibility**：技术 / 数据 / compute 上可行吗？瓶颈在哪？
- **Impact**：如果 work，对领域 / 用户的价值？
- **Risks**：可能失败的方式（数据不可得 / 假设不成立 / 实验设计陷阱）

### 4. critic → `outputs/<run_id>/devils_advocate.md`

```
spawn critic(idea_assessment=outputs/<run_id>/idea_assessment.md, mode="devils_advocate")
```

critic 在本 pipeline 不是常规审；扮演 **"魔鬼代言人"**：
- 找 idea 的逻辑漏洞
- 反例 / 反假设
- "为什么大家都不做这个"的可能解释（已被否定？经济上不值？）
- 严格的"go / no-go"建议

期望产物：`devils_advocate.md`。

### 5. 综合回复用户

主 agent 综合 4 份产物给一段中文总结：

```markdown
## Idea Brainstorm 结果

**重新表述**: <一句话 from idea_unpacked.md>

**评估**:
- ✨ 新颖性：<1-3 句>
- ⚙️ 可行性：<1-3 句>
- 💡 影响：<1-3 句>
- ⚠️ 风险：<1-3 句>

**Devil's advocate 关键反驳**:
- <从 devils_advocate.md 挑 2-3 条>

**建议**: <go ahead with X / refine Y first / drop because Z>
```

## Artifact 命名约定

- `outputs/<run_id>/idea_unpacked.md`
- `outputs/<run_id>/related_work_quick.json`（可选）
- `outputs/<run_id>/idea_assessment.md`
- `outputs/<run_id>/devils_advocate.md`

## 失败 / 重启策略

- conductor 把 idea 标 ambiguous → 反问用户后再启动；不要硬猜
- paper-searcher 搜不到 prior work → 在 assessment 中标"该方向 evidence 极稀少"，让 critic 评估"是真新颖还是没人做的死路"

## 完成态

四份产物存在 + 主 agent 给出 go/no-go 建议。

## 不做的事

- **不**写实验脚本（go 后用户自己启 empirical-study pipeline）
- **不**写完整论文段（idea 阶段只产 markdown 思辨）
- **不**追求"鼓励性"评估——critic 必须严格挑刺，不要因为"这是用户的 idea"就放水
