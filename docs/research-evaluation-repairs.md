# 原生 demo 评测问题修复

基线：v1.0-demo / 3e4e4c39a7a3b2a7b9437622d85c1367d393eca7。
仅维护原 Planner / DynamicResearchRuntime 一条生产路径；没有固定序列模式，没有新增模型依赖。

## 行为与 owner

| 问题 | 修复 owner 与合同 | 验证 |
|---|---|---|
| 前缀截断丢失证据 | extract_notes 使用问题、目标及完整提供文本，输出逐源摘要和经原文匹配的引用；build_evidence_map 保留完整笔记和引用；draft_report 不再把直接来源缩为摘要前缀 | 文末关键事实从输入到笔记、证据图保留；伪造引用拒绝 |
| 未回答却评审通过 | review_artifact 以任务完成、证据支持、评分三项共同决定 accept；NodeRunner 给普通及自动评审传原始证据 | 高分未完成/无证据仍修订；真实 runtime 自动评审收到原文 |
| 只能润色，不能补证据 | 原 Planner 按 verdict 决策，未通过时允许 researcher/analyst 补证据，再重写评审 | 高分 needs_revision 仍可规划补证据 |
| 已有报告覆盖异常状态 | 移除 runtime 的报告存在即 completed 分支；原始终止原因保留在事件中；CLI failed 返回非零 | 实际 runtime 装配：报告保留、预算终止状态为 failed |
| 请求后才发现额度超限 | PolicyEngine 统一在 planner 与技能 LLM 入口预留输入和输出；压低输出上限，不够发下一次请求时提前停止；NodeRunner 不吞掉预算异常 | 并发预留、超大输入零调用、未知 usage 保守记账 |
| 订阅参数与 schema | 原 provider 转发 reasoning_effort 并验证取值；开放字典 schema 关闭不兼容的 strict，同时技能端验证结构 | 离线 payload 合同检查，未新增订阅调用 |
| 评测脚本继续调度 | scripts/evaluate_research.py 是维护入口；首次额度/运行失败停止后续任务，无自动重试；需显式 max-runs、timeout、execute | exit 0 的 usage-limit 事件仍停；超预算清单零执行；超时保留日志 |
| 引用范围漏段 | 同一维护入口的 resolved_targets 处理带反引号与全限定端点，限制为同论文范围 | 6–8 包含 7；跨论文范围不扩张 |
| MCP 配置越过指定工作区 | 原 MCP 入口按 --root 读取 config/.env，不再从服务安装目录取用户配置 | 真实 stdio 工具发现使用临时配置，无用户凭据 |

请求预算使用已安装的 tiktoken o200k_base 本地估算，加 25% 与 1024 token 余量；这是跨 provider 的近似值，不宣称是 Astra 的精确 tokenizer 或订阅扣费上限。词表不可用时回退 UTF-8 字节预估。首次使用词表可能需要静态词表下载；之后使用本地缓存。usage 缺失/异常时占用预留预算，可能提前停止；长文本不会被静默截断，无法放入预算会明确失败。原始全文仍在 SourceSet，可在后续规划中缩小来源范围后再读。

## 评测入口与历史数据

历史 outputs/exp_20261026_astra_high 中的协议、脚本和结果为冻结证据，不再作为维护代码运行。当前工具不定义额外固定流程、不替换 Planner、不修改用户提示，也不把 process_completed 当作研究质量通过。

- 离线引用核对：python scripts/evaluate_research.py citations input.json。
- 清单为 JSON 数组，每项包含 command（原生命令 argv）和 cwd（已有工作目录）。
- 批调度默认不运行；明确预算后使用 run manifest.json --output <新目录> --max-runs <上限> --timeout <秒> --execute。
- output 必须是新目录；失败保留日志并停止，不能覆盖旧实验。
- 该工具不是新的 benchmark，也不模拟用户回答。带弹窗的产品验收仍使用原生界面，事先约定用户可补充的信息与轮数；不禁止澄清，不让用户提供研究答案。
- 本次没有运行真实研究、外部评分或修改订阅认证状态。

## 替换与测试清理

已移除：1000/240 字符笔记前缀路径、证据图摘要及写作来源截断、无效评审的伪造默认评分及旧 helper、仅平均分驱动的接受/后续规划、报告存在覆盖失败状态。调用方、技能合同、角色输入和界面同步更新。

KEEP：证据尾部与引用核验、独立评审门槛、真实 runtime 状态/评审集成、预算与错误边界、订阅 payload、评测停止和引用范围检查。
MERGE：沿用现有技能与配置测试 fixture，替换旧前缀摘要断言。
DELETE：旧评审 fallback 行为与测试预期，不保留跳过的旧实现测试。
原有真实服务测试仍按项目默认配置排除，不将其计为通过。

后续真实验证只使用原生流程；用户最新指定 Astra low，任务和调用预算沿用小样本限制。本批离线通过不代表真实研究质量已提升，也不等于弹窗 UI 已完成端到端验收。


## 本批验证记录

- 全量默认离线 Python 测试通过；真实外部服务标记用例不执行、不计入通过数。
- 前端 npm run lint 与 npm run build 通过，复用 demo 已安装依赖，未安装新依赖。
- 残留扫描：被替换的前缀抽取、伪造评审默认分及 completed 覆盖路径已删除；旧终止错误文本仅存在于 docs/manual-tests 的历史实测记录。
- 无真实模型研究、独立裁判调用或订阅登录操作；没有承诺修复后质量分数提升。


## 2026-10-27：真实失败案例后的最小修复

- 证据组装：存储层保留完整原始产物，writer/reviewer 共享完整正文去重视图；重复内容合并来源引用，同一文献的不同正文版本保留。
- 完成条件：ReviewVerdict 绑定 target_artifact_id 和 target_payload_sha256；只接受当前版本的有效 accept。未评审、旧版本评审、needs_revision、修订上限用尽都不能冒充完成。相同时间戳按存储顺序选择最新版本，覆盖写入排序一致；修订上限按内容版本计数，同 ID 重写不能绕过。
- 规划契约：允许 horizon=0 / nodes=[] / terminate=true；非终止空计划拒绝。明确 needs_review 字段，允许显式或自动评审；已接受的相同版本复用评审，不再次调用模型。旧版本评审不会再作为当前报告的规划提示。
- 格式：澄清产物 inferred_fields.output_format 传到 writer；默认 Markdown，显式 latex/pdf 沿用论文模板。报告记录格式并写正确扩展名；仅请求 PDF 且报告验收完成后编译，PDF 生成失败保留 failed。评审不再拼进交付正文。
- 收尾：预算异常记录失败观测和节点终态；取消/异常收尾关闭残留 running 节点。
- 界面：报告 API 返回内容指纹；审阅面板核对当前报告 ID 和指纹，不把旧版本 ACCEPT 显示成当前版本通过，并取消过期异步请求。

离线重放保存的 qasa_0096 失败案例：同一原文 4 份降为 1 份，第 24/27/28 段完整保留；新的输入预估 15,354，加 4,096 输出预留为 19,450，小于原来剩余的 41,174。修复后的预检放行。没有真实模型请求，不能把预估当成实际 token 用量，也不能据此宣称真实评审已通过。

验证：完整默认 Python 套件 158 passed，1 个真实服务测试按配置排除；前端 TypeScript 检查与 Vite 构建通过。格式传递/PDF 失败/预算节点收尾/取消/旧评审及被覆盖版本/API 指纹均有离线回归。PDF 分支使用编译器替身，不是本轮实机 PDF 编译验收。原始 main、demo 检出与历史评测证据未修改；不增加固定研究流程。
