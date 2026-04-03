# 开发学习笔记

> 记录每个阶段遇到的问题、解决方案和经验教训。后续开发时持续追加。

---

## 阶段一：LangGraph Agent 原型 (2026-02-19 ~ 2026-02-23)

### 问题 1：状态累积语义错误（致命）

**发生时间**：2026-02-23 run_20260223_115419

**现象**：运行结束后 papers/web_sources/analyses 全部为空列表，所有指标归零。但中间迭代其实找到了 18 篇论文、14 个分析、64 条发现。

**根因**：`fetch_sources` 和 `analyze_sources` 返回的是「本轮增量」而不是「累积结果」。当下一轮迭代找不到新内容时，返回空列表直接覆盖了之前的数据。

**解决**：
- 改为累积式返回：`papers = existing_papers + new_papers`
- 按 uid/url/title 去重，保持稳定排序
- 新增 `new_items_count` 字段用于观测本轮增量

**教训**：
- **多轮迭代循环中，状态语义必须是累积的，不能是增量覆盖**
- 这是整个项目遇到的第一个致命 bug，后续所有架构决策都受此影响
- 写迭代逻辑时先问自己：「如果本轮返回空，之前的数据还在不在？」

---

### 问题 2：引用格式不一致导致验证失败

**发生时间**：2026-02-22 ~ 2026-02-23

**现象**：报告中写的是 `[arXiv:2301.xxxxx]` 文本格式，但验证器只数 `http/https` 开头的 URL。导致 `missing_references: fail`。

**根因**：生成端（LLM）和验证端（规则）对「引用」的定义不同。LLM 习惯写学术引用格式，验证器只认 URL。

**解决**：
- 强制引用为 URL-first 格式：`arXiv:xxxx` → `https://arxiv.org/abs/xxxx`，`DOI` → `https://doi.org/<doi>`
- 创建共享的 `reference_utils.py`，生成和验证用同一套提取逻辑
- 只统计 References/Bibliography 章节中的 URL（排除实验蓝图中的数据集链接）

**教训**：
- **生成端和验证端的「同一概念」必须有统一定义**
- 验证器和评审器用不同的引用提取逻辑，会导致两者结论矛盾
- 引用格式用确定性规则转换，不要指望 LLM 自动遵循格式

---

### 问题 3：Claim-RQ 对齐破坏自然语言

**发生时间**：2026-02-22 run_20260222_222740，2026-03-07 复现

**现象**：报告中的声明读起来很机械——「Regarding prototype, selection, prioritization, strategies, evidence suggests...」。看起来像模板拼接，不像学术论文。

**根因**：`_align_claim_to_rq()` 把原始声明用确定性模板重写，提取 RQ 的关键词硬拼在前面。本意是提高 RQ 相关性得分，结果破坏了可读性。

**解决**：
- 停止文本层面的 RQ 对齐重写
- 保留原始 claim_text 不变
- 新增独立字段：`rq_alignment_score`、`rq_alignment_terms`、`rq_alignment_status`
- 验证器用分数字段判断相关性，不改原文

**教训**：
- **确定性文本操作比 LLM 随机性更糟——它破坏信任**
- 质量评估应该是「打分+标注」，不是「改原文」
- 生成的内容和评估的指标要解耦，不能为了过验证去篡改内容

---

### 问题 4：引用来源混入无关论文

**发生时间**：2026-02-22, 2026-03-07

**现象**：搜索「原型选择策略」，引用列表里出现蛋白质设计、骨骼健康、边缘计算的论文。参考文献域名分布预警。

**根因**：系统最大化召回（尽可能多找论文），但没有「核心 vs 背景 vs 无关」的分类层。检索评审器检查覆盖率但不检查纯度。

**解决**：
- 新增引用纯度过滤：将来源分为 core（直接回答 RQ）/ background（提供背景）/ reject（跑偏）
- References 章节只包含 core + 部分 background
- 检索评审器新增 `purity_ratio` 和 `background_ratio` 指标

**教训**：
- **引用质量 > 引用数量**
- 搜索引擎返回的结果不能全部当作有效证据
- 需要在检索后、进入分析前增加一层过滤

---

## 阶段二：多源搜索 & 工程加固 (2026-02-20 ~ 2026-03-07)

### 问题 5：HTTP 429/403/404 错误处理

**现象**：Semantic Scholar 429 限流、出版商 403 付费墙、PDF 链接 404 过期。系统因网络错误崩溃或卡住。

**根因**：
- 429：查询量太大 + `max_results_per_query` 设太高 + 重试退避叠加
- 403：出版商付费墙（Wiley/MDPI/IEEE）、反爬检测
- 404：元数据中的 PDF 链接过期

**解决**：
- 白名单下载策略（只从 `allowed_hosts` 下载 PDF）
- 403 域名短期负缓存（TTL 1800s，避免重复请求被封域名）
- 429 指数退避（Semantic Scholar 内置重试）
- **所有网络错误非致命**——记日志但不中断主流程

**教训**：
- **「搜到但下不了」是学术爬虫的常态**，不是异常
- 元数据优先、开源优先的策略比全量下载更稳定
- 429 是吞吐问题（减少查询量），403 是访问问题（无快速解决方案），404 是过期问题（跳过即可）

**最佳配置**：
```yaml
sources.semantic_scholar:
  max_results_per_query: 5     # 不要贪多
  polite_delay_sec: 3.0
  max_retries: 1
  retry_backoff_sec: 1.5
sources.pdf_download:
  only_allowed_hosts: true     # 白名单
  forbidden_host_ttl_sec: 1800 # 被封域名冷却
```

---

### 问题 6：nodes.py 膨胀到 2700+ 行

**发生时间**：2026-03-06

**现象**：所有图节点函数、纯辅助函数、LLM 调用全混在一个文件里。`evidence.py`、`report_helpers.py`、`source_ranking.py` 和 `nodes.py` 存在大量重复实现。

**解决**：
- 4 阶段拆分：先去重 → 提取到 stages/ → 迁移测试 → nodes.py 变薄包装
- 按耦合度从低到高拆：indexing → evaluation → reporting → experiments → planning → retrieval → analysis → synthesis
- nodes.py 保留为 100-200 行的 facade wrapper

**教训**：
- **拆大文件时，先去重再提取，按耦合度从低到高**
- Facade wrapper 在迁移期间保证测试兼容
- 纯逻辑先迁移，节点函数后迁移（依赖顺序）

---

### 问题 7：多模态处理的四个质量问题

**发生时间**：2026-03-06

| 问题 | 现象 | 解决 |
|------|------|------|
| Caption 边界太松 | 正则匹配吞掉整段正文 | 硬限 500 字符 / 3 句，加终止符 |
| LaTeX 清理破坏公式 | `\sqrt{d_k}` 变成 `d_k` | 占位符保护 `$...$` 和 `$$...$$` |
| 图片去重缺失 | 同一张图出现多个 chunk ID | 三阶段去重：生成时/索引前/检索后 |
| 检索不理解图表意图 | 问图表时返回纯文本 | 意图检测 + 图表 chunk 加分 |

**教训**：
- **PDF 布局提取的空白归一化问题很常见**，需要局部窗口方式处理
- LaTeX 清理必须尊重数学边界（先保护再清理）
- 去重要在多个阶段做（生成、分块、检索都要）
- 查询意图是可学习的信号，简单规则就够用

---

### 问题 8：没有断点续跑能力

**发生时间**：2026-03-06

**现象**：长时间运行的研究任务失败后，只能从头开始。没有 LangGraph checkpointer。

**解决**：
- 引入 SQLite checkpoint/resume
- Provider 级 circuit breaker（closed → open → half-open 状态机）
- LLM/fetch 失败有明确的降级语义

**教训**：
- **学术研究工作流天然是长时间运行的**，必须有断点续跑
- Provider 健康状态必须是有状态的（不能只 try/except 每次调用）
- 故障分类要细化：429 限流 vs 403 拒绝 vs 404 不存在 vs 5xx 服务端错误

---

## 阶段三：Research OS 架构转型 (2026-03-08 ~ 2026-03-12)

### 问题 9：架构瓶颈——图节点堆叠无法扩展

**发生时间**：2026-03-08

**现象**：LangGraph 图节点越加越多，节点间状态传递靠共享字典，耦合度高，隔离故障困难。每加一个功能就要改图结构。

**根因**：图节点模式适合简单管道，但不适合「AI 科学家」这种需要动态决策的场景。

**解决**：重新定义为 Research Operating System，5 层架构：
1. Research Runtime（生命周期、检查点、预算、artifact 持久化）
2. Agent Layer（角色协作，不是能力复制）
3. Skill Layer（稳定、可复用的研究动作）
4. Executor/Provider Layer（搜索、索引、LLM、代码执行）
5. Infra Layer（Chroma、BM25、PDF 解析、外部 API）

**关键决策**：
- **大模型不是「多一个 agent」，而是共享的认知内核**
- 角色区分靠策略+技能+artifact 约束，不靠模型
- 技能是真正的资产（版本化、可测试、可审计），不是内联 prompt

**教训**：
- **先想清楚 artifact 再做多 agent**——没有清晰的数据合约，多 agent 就是混乱
- 不要大爆炸重写，保留已有的基础设施层
- Skill-first, Agent-second（技能先行，角色后行）
- 冻结 MVP 范围再动手写代码（防止范围蔓延）

---

### 问题 10：评审器有意见但不影响流程

**发生时间**：2026-03-07 ~ 2026-03-08

**现象**：实验评审器检测到缺少 train/test split、单数据集、无消融实验，但只是记录警告，不影响执行流程。同样的警告重复出现。

**解决**：
- 评审结论必须接入路由决策
- `review_artifact` 的 verdict 控制是否继续/回退/重写
- 实验评审的 verdict 控制是否重新设计实验

**教训**：
- **评审如果不影响流程，就只是噪音**
- 验证器 → 确定性规则优先（元数据检查）
- 评审器 → LLM 判断（质量评估）
- 两者的 verdict 都必须接入路由控制

---

### 问题 11：引用元数据在传递中丢失

**发生时间**：2026-03-07

**现象**：38/38 个来源缺少 author/year 信息。引用验证器在下游看不到元数据。

**根因**：paper.authors/year 在 paper → analysis 传递时没有被携带。是管道问题不是智能问题。

**解决**：
- 确保 authors/year/abstract/canonical_url 从 paper 传到 analysis
- 引用验证器可以访问完整元数据

**教训**：
- **元数据传播是管道问题，不是 LLM 问题**
- 设计数据合约时就要声明哪些字段必须贯穿传递

---

## 阶段四：功能扩展期 (2026-03-16 ~ 2026-03-29)

### 问题 12：CI 环境依赖冲突

**发生时间**：2026-03-20, 2026-03-23, 2026-03-25, 2026-03-28（反复出现）

**现象**：本地测试通过但 CI 失败。networkx、matplotlib、numpy、websocket-client、httpx 等包在 CI 环境中未安装。MCP 服务器在 CI 中无法启动。

**解决**：
- 重型依赖统一用惰性导入（`networkx`、`matplotlib`、`numpy`）
- CI 安装步骤补全所有依赖
- 测试中 mock 掉 `load_yaml`、`_start_mcp_runtime`、`ToolRegistry` 等外部依赖

**教训**：
- **惰性导入是处理可选重型依赖的标准模式**
- CI 和本地环境差异是永恒问题，每次加新依赖都要想「CI 装了吗？」
- MCP 服务器等外部进程在测试中必须 mock

---

### 问题 13：前端 TypeScript 类型错误频繁

**发生时间**：2026-03-20（集中爆发）

**现象**：RouteGraph、store imports 等组件编译报错。新增字段后旧类型定义不匹配。

**解决**：逐一修复类型定义，确保 `types.ts` 与后端返回的数据结构同步。

**教训**：
- **后端加字段时要同步更新 `frontend/src/types.ts`**
- TypeScript 编译通过就是前端的「测试」——不需要额外写前端测试

---

### 问题 14：PDF 报告图片不显示——config 路径模板变量未解析

**发生时间**：2026-04-03

**现象**：生成的 `research_report.pdf` 中，所有 Figure 只显示文件路径文字（如 `figures/fig_00_bar_chart.png`），图片没有嵌入。

**根因**：`generate_figures/run.py` 从 `ctx.config["paths"]["outputs_dir"]` 读到的是未解析的模板字符串 `${project.data_dir}/outputs`。用这个字面量拼接出的目录路径在文件系统中不存在，导致图片实际上没有写入 `run_dir/figures/`。`_compile_latex_report` 编译时静默跳过缺失图片（`except Exception: pass`）。

**解决**：
- `generate_figures/run.py`：引入 `resolve_path()` 解析模板变量后再拼接 figure 输出路径
- 从 `ctx.config["workspace_root"]`（runtime 已设置的已解析路径）作为基准路径

**教训**：
- **config 中带 `${}` 模板变量的值不能直接当路径用，必须经过 `resolve_path()` 解析**
- runtime 层解析了路径但没有回写到 config dict，导致下游技能拿到的是原始模板字符串
- 遇到「文件应该存在但不存在」的问题时，先检查路径是否被正确解析

---

### 问题 15：PDF 报告表格溢出页面

**发生时间**：2026-04-03

**现象**：PDF 中 Table 1 右侧内容被截断，长文本列超出页面边界。

**根因**：`draft_report/run.py` 的 prompt 没有约束表格格式，LLM 生成的 LaTeX 使用 `\begin{tabular}{lllll}`，`l` 列不自动换行。

**解决**：
- `draft_report/run.py`：preamble 新增 `\usepackage{tabularx}`
- prompt 中新增表格格式规则：长文本列必须用 `tabularx` + `X` 列类型

**教训**：
- **LLM 生成的 LaTeX 表格默认不会考虑页面宽度，必须在 prompt 中明确约束**
- 对 LLM 输出格式有硬性要求时，要在 system prompt 中用具体示例说明，不能靠隐含假设

---

### 问题 16：无文献时 PDF 仍输出空 bibliography 段

**发生时间**：2026-04-03

**现象**：检索结果为零的报告中，文末仍有 `\bibliography{references}` 但无对应 `.bib` 文件，导致引用区域为空。

**根因**：`draft_report/run.py` 的 prompt 无条件要求输出 `\bibliography{references}`，而 `runtime.py` 只在 bib 内容非空时才写 `.bib` 文件。两者对「无引用」场景的处理不一致。

**解决**：
- `draft_report/run.py`：prompt 中新增规则——无 cite key 时不输出 `\bibliographystyle{}` 和 `\bibliography{}`

**教训**：
- **生成端和编译端对边界条件的处理必须一致**——这是问题 2「生成端和验证端概念定义统一」的又一个实例
- LLM prompt 中要覆盖「无数据」的降级路径，不能只写正常流程

---

### 问题 17：用户输入中格式要求污染搜索词导致零结果

**发生时间**：2026-04-03

**现象**：用户输入 `"一篇带图表引用的时序"`，系统生成的搜索词为 `"time series with figure and table citations"`，学术数据库返回零结果。整个流程在零结果基础上继续运行，最终写出一篇"关于检索失败的元分析"而非时序综述。

**根因**：`plan_research/run.py` 使用 ~300 行的规则过滤列表（`_EN_META_PHRASES`、`_ZH_META_PHRASES`、`_keywordize_text` 等）尝试从用户输入中提取主题词。但规则无法覆盖所有表达方式——`"带图表引用"` 不在任何过滤列表中，被当作主题的一部分传入搜索词。根本问题是：**用规则做语义理解是错误的架构选择**。用户输入混合了领域主题、格式要求、范围约束、内容要求等多种语义，需要 LLM 级别的理解能力来区分。

**解决**：
- 重写 `plan_research/run.py`：删除全部规则过滤代码（~300 行），改为 LLM 结构化输出
- 新 schema 增加 `domain_topic`、`format_requirements`、`scope_constraints`、`content_focus` 槽位
- LLM system prompt 明确要求区分领域主题 vs 格式/范围/指令，并给出示例
- 各槽位流向不同下游：`domain_topic` + `search_queries` → 搜索，`format_requirements` → 报告写作
- 更新 3 个相关测试用例适配新 schema

**教训**：
- **语义理解不要用规则列表——规则列表永远不够全，而且不可组合**
- 这是问题 3（确定性文本操作破坏自然语言）的又一个实例，但方向相反：问题 3 是规则篡改了 LLM 输出，问题 17 是规则无法理解用户输入
- 当一个模块有 300 行规则代码做"字符串 → 语义"的映射时，这就是在错误的抽象层解决问题
- 铁律第 5 条需要修正：确定性规则适用于**格式验证**，但不适用于**语义理解**

---

### 问题 18：检索层和路由层残留的硬编码语义词表

**发生时间**：2026-04-03

**现象**：问题 17 修复后全局排查发现，`retrieval/common.py` 的 `detect_query_intent()` 和 `plan_research/run.py` 的 `_query_prefers_web()` 仍使用硬编码词表做语义判断。

**根因**：
- `detect_query_intent()`：用 `_VISUAL_INTENT_TERMS`（figure/diagram/图表等 28 个词）和 `_FORMULA_INTENT_TERMS`（equation/proof/公式等 14 个词）判断查询意图，决定检索后处理是否 boost 图表/公式类 chunk。问题 17 修复后搜索词不再包含格式词，这个函数实际上变成了死代码。
- `_query_prefers_web()`：用 12 个硬编码词（github/repo/framework/开源等）判断查询是否应走 web 路由。LLM 的 `query_routes` 输出已覆盖此功能。

**解决**：
- `retrieval/common.py`：删除 `_VISUAL_INTENT_TERMS`、`_FORMULA_INTENT_TERMS` 词表，`detect_query_intent()` 保留签名但始终返回 `"general"`（兼容外部导入）
- `plan_research/run.py`：删除 `_query_prefers_web()` 函数，路由 fallback 默认 academic

**教训**：
- **清除一个反模式时要全局排查同类代码**——问题 17 只改了 `plan_research`，同类问题在检索层和路由层还有残留
- 当上游已经通过 LLM 做了语义拆分，下游不应该再用规则重新猜测同一个语义

---

## 阶段五：论文质量与访问扩展 (2026-04-03 ~)

### 功能：机构访问代理（EZproxy / HTTP 代理）

**时间**：2026-04-03

**需求**：用户希望下载 IEEE、ACM、Elsevier 等付费期刊论文，这些平台需要学校机构认证。

**方案**：在设置页增加"机构访问"配置区，支持两种代理方式：
- **EZproxy URL 改写**：用户填学校 EZproxy 地址，系统自动将 `ieeexplore.ieee.org/doc/123` 改写为 `ieeexplore-ieee-org.ezproxy.xxx.edu/doc/123`
- **HTTP/SOCKS 代理**：用户填代理地址，`requests.get` 通过 `proxies` 参数转发

**改动文件**：
- `configs/agent.yaml`：新增 `institutional_access` 配置段
- `frontend/src/types.ts` + `store.tsx`：类型定义和默认值
- `frontend/src/components/settings/sections/ToolsSection.tsx`：机构访问 UI 区块
- `src/ingest/fetchers.py`：`download_pdf` 支持 proxy/EZproxy 参数 + URL 改写函数
- `src/dynamic_os/tools/backends.py`：从 config 读取 `institutional_access` 传入

**开发中发现的问题**：
- EZproxy URL 改写不应对免费站点（arXiv 等）生效，否则可能被拒绝 → 加了 `_FREE_ACCESS_HOSTS` 白名单跳过
- `urlparse` 对无 scheme URL 返回 `hostname=None` 会导致崩溃 → 加了 None 检查

**教训**：
- **代理/改写功能必须区分"需要代理的站点"和"不需要的站点"**——全量改写会破坏本来能用的免费访问
- 处理 URL 时永远要防御 `urlparse` 返回 None 的情况

---

### 功能：多面板可拖拽布局（Batch 1）

**时间**：2026-04-03

**需求**：将单窗口 tab 切换布局改为多面板并行布局，支持同时查看对话和历史/技能。

**方案**：使用 `react-resizable-panels` v4 实现三列可拖拽布局：
- 侧栏面板（可折叠，12%-30%）
- 主面板（对话/监控，始终可见，≥35%）
- 工具面板（历史/技能，可折叠，20%-50%）

**改动文件**：
- `frontend/package.json`：新增 `react-resizable-panels@4.9.0`
- `frontend/src/App.tsx`：用 `Group`/`Panel`/`Separator` 替换 flex 布局
- `frontend/src/components/Sidebar.tsx`：移除固定宽度 `lg:w-[320px]`
- `frontend/src/components/tabs/RunTab.tsx`、`HistoryTab.tsx`、`SkillsTab.tsx`：`min-h-screen` → `h-full overflow-hidden`

**开发中发现的问题**：
- `react-resizable-panels` v4 API 与 v2 不同：`PanelGroup` → `Group`，`PanelResizeHandle` → `Separator`，`direction` → `orientation`，`autoSaveId` 不存在，`PanelRef` → `PanelImperativeHandle`
- 动态挂载/卸载 Panel 会导致 Group 布局跳动 → 改为始终挂载，用 `collapse()/expand()` 控制可见性
- `onResize` 参数是 `PanelSize` 对象（`{asPercentage, inPixels}`），不是 number

**教训**：
- **第三方库 major 版本升级后，先读类型声明文件确认 API 变更，再写代码**
- **可拖拽面板组件中不要动态增删 children**——始终挂载所有面板，用 collapse/expand 控制显隐

---

### 功能：多面板布局 Batch 2 — Sidebar toggle + compact 适配

**时间**：2026-04-03

**改动**：
- Sidebar "运行/历史/技能"三按钮改为"历史/技能"两个 toggle 按钮，点已激活按钮关闭工具面板
- HistoryTab/SkillsTab 加 `compact` prop：工具面板中隐藏大标题 header，去掉 `max-w-4xl` 宽度限制
- SkillsTab compact 模式保留过滤器 tab，隐藏"技能管理"大标题

---

### 功能：多面板布局 Batch 3 — 折叠/展开按钮 + 持久化

**时间**：2026-04-03

**改动**：
- 侧栏折叠后主面板左上角显示 `PanelLeft` 展开按钮
- 工具面板关闭时主面板右上角显示 `PanelRight` 打开按钮
- `useDefaultLayout` + localStorage 自动保存/恢复面板宽度

---

### 问题 19：布局持久化与面板状态不同步

**发生时间**：2026-04-03

**现象**：用户上次使用时打开了工具面板（30% 宽度），刷新页面后工具面板占 30% 宽度但内容为空白。

**根因**：`useDefaultLayout` 从 localStorage 恢复了 tools=30% 的布局，但 `toolPanelTab` 的初始值是 `null`。面板有宽度但 `toolPanelOpen` 为 false，内容不渲染。布局持久化（localStorage）和 React 状态（useState 初始值）各自独立，没有同步机制。

**解决**：
- `App.tsx`：挂载时加 `useEffect`，如果 `toolPanelTab` 为 null 则强制 `toolsPanelRef.current?.collapse()`

**教训**：
- **持久化布局尺寸时，必须同时持久化关联的 UI 状态**——或者在挂载时把尺寸同步到状态
- 这是问题 1（状态语义不一致）的 UI 版本：两个数据源（localStorage 的布局 vs useState 的 tab 状态）对同一个视觉状态有不同的理解

---

## 跨阶段总结：反复出现的模式

### 必须记住的 5 条铁律

1. **状态必须累积，不能增量覆盖**——多轮迭代的核心假设
2. **生成端和验证端的概念定义必须统一**——引用格式、指标口径
3. **评审结论必须接入路由控制**——否则就是噪音
4. **元数据必须贯穿传递**——管道问题比智能问题更常见
5. **确定性规则做格式验证，LLM 做语义理解**——不要用规则列表做语义分类

### 架构演进的关键转折点

| 时间 | 触发 | 决策 |
|------|------|------|
| 2026-02-23 | 状态归零 bug | 引入累积语义 + 统一引用提取 |
| 2026-03-07 | 语义准确性问题 | 停止确定性文本篡改，改用评分 |
| 2026-03-08 | 图节点无法扩展 | 转型 Research OS 五层架构 |
| 2026-03-12 | Dynamic OS 上线 | 7 角色 + 18 技能 + DAG 动态规划 |
| 2026-03-20 | PR #6 大合并 | HITL + 历史浏览 + artifact 浏览器 |
| 2026-03-23 | Tier 1 升级 | 实验循环 + 知识图谱 + 评审打分 |
| 2026-03-28 | 技能进化系统 | 技能自动创建/优化 + 跨 run 记忆 |
| 2026-04-01 | 端到端实验闭环 | 通用注册表模板 + 技能管理 UI |
| 2026-04-03 | 搜索词被格式要求污染 | 删除规则过滤，改用 LLM 语义拆分 |
| 2026-04-03 | 付费期刊无法下载 | 机构访问代理（EZproxy + HTTP proxy） |
| 2026-04-03 | 多工具并行查看需求 | 可拖拽多面板布局（react-resizable-panels） |

---

*最后更新：2026-04-03*
*持续追加中——后续开发遇到的问题和解决方案请追加到对应阶段或新建阶段*
