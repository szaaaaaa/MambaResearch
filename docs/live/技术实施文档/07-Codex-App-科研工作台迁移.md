# Codex App 科研工作台迁移记录

更新：2026-10-09。完整 skill 化持续目标仍在联合验收；用户明确要求 Codex 已有原生能力不再由 MambaResearch 实现。

## 当前唯一生产路径

科研 skill → MCP App 界面 → 固定项目的领域操作 → 当前 Codex 聊天执行 → 实际研究产物 → nonce 校验的显式结果 → 工作台研究记录。

Codex 拥有模型/认证/聊天/推理、搜索/浏览、文件读写/通用预览、命令/进程会话/停止、Skills/Agents 和 MCP 配置/权限。工作台只拥有科研项目与资产分类、文献阅读/批注、Zotero、Colab 定位、研究记录和科研结果展示。通用能力没有第二套 UI 或执行入口。

core.http 拥有科研项目、记录、文献 API 和只读实验记录；core.workbench 拥有任务持久化与结果校验；工作台 SDK server 持有 ASGI client 与应用 lifespan。Kernel 只装配 typed HTTP/MCP capabilities，四个科研 provider 各自拥有领域实现。

## 本批删除

- MCP 控制台、配置发现/编辑、探测、Sandbox、通用调用日志与其前后端 API/组件/依赖。
- Skills/Agents 管理页和描述文件列表 API；保留科研职责及 pipeline 指令，直接使用 Codex 原生能力。
- 聊天输入和聊天外观配置；工作台仅投递文件/文献等领域动作并展示显式科研结果与既有研究记录。
- 实验 MCP、脚本启动器、线程/进程轮询与终止控制。旧实验记录 API/视图替换为只读，不提供 PID 或启动/停止。
- 自建论文搜索、模型/凭据 API、RAG、嵌入、重排、网页/图表入库、建索引脚本及对应依赖和测试。
- 通用 CSV/文本/图片预览组件及字节读取 API；文件打开交给 Codex，保留文献阅读与科研批注。
- 项目工具选择和用户 MCP 环境覆盖的运行代码及默认配置；工具配置与权限属于 Codex，科研项目/路径/记录归属校验仍存在。

科研界面现为四个栏目、草稿箱、工作台、Zotero 库和研究记录共八个导航入口；设置仅科研项目与关于两项。

## 用户数据与信任边界

用户 .env、既有项目配置、物理文献/脚本/数据/索引与研究数据库不清空。v1–v8 schema 保持不可变；v9 保存旧消息和关联归档，v10 保存实验事件。移除通用日志的写入与运行时入口，已存历史行继续保留，项目删除的归属清理仍处理其历史数据。

已有实验记录通过只读查询展示状态、指标和日志；不存在根据保存的 PID 接管或杀进程。新实验使用 Codex 原生命令工具，指标和日志写入 outputs/<run_id>/experiments/exp_<NNN>/，并核对实际退出码。

项目 ID/path/研究记录必须匹配；产物路径必须是固定项目 outputs 内已存在文件；任务结果与记录原子保存，拒绝错误 nonce、越界路径或覆盖最终结果。宿主消息确认只代表投递，不代表研究完成；超时不自动重发。

UI HTML 内联，资源 URI 使用完整 HTML 的 SHA-256。同一服务实例的资源内容不变，新构建在 MCP 重连后使用新资源身份。

## 自动化与 Test Prune

本批最终完整 Python 30 passed（32.03 秒），前端 13 passed，tsc 与生产构建通过。最终 JS 655.60 kB、CSS 40.66 kB，内联资源 696,575 字节。构建与真实工作台启动验证按依赖顺序执行，避免 Vite 清空 dist 与测试启动并发；未增加回退逻辑。实际 SDK stdio 使用插件 manifest 的启动配置与临时项目，保护任务事务、固定上下文、路径边界、PDF 阅读、记录隔离、旧实验记录只读和原始脚本保持。

Test-prune：两项已删除 RAG/图表模块测试 DELETE；实验 provider 两项参数化输入 DELETE；执行器生命周期测试替换为只读实验数据保持/跨项目拒绝，KEEP。通用 MCP 管理及调用日志断言 DELETE；profile 与项目/路径隔离验证 KEEP。前端通用 registry fixture 改用科研 view，既有宿主桥/资源销毁/状态和队列合同 KEEP。没有 skip/xfail 或第二测试框架。

## 已有真实 App 证据

正式分类任务 5457c2e8b1b04b8681c24769931747db 从真实界面进入当前聊天，使用原生 Workspace MCP 撤回用户纠正前的 25 条误分类；未覆盖人工校正，候选原文件 SHA-256 保持。工程仓库不按后缀强塞科研栏目；报告保存到 outputs/classify_20261009_094138/report.md。模型显式回传后，实际工作台显示模型结果已返回及报告路径。此证据仅覆盖这次分类闭环。

0.1.2 刷新连接、展开新面板后真实设置/关于页曾验证凭据入口移除。随后面板控制连接持续超时，未把 MCP 设置页当作验收通过；该通用设置页现已从产品删除。

## 当前安装与剩余门禁

当前插件 0.1.7，包含工作台和 Workspace/Zotero/Colab/History 四个领域 server。Windows x64 分发包内置 Python 3.13.16、依赖、应用源码快照、构建后的界面、八条流程/八个角色与 PDF 交付检查脚本；MCP cwd 和 skill 资源使用安装目录相对路径，不再依赖开发仓库或系统 Python/Node。

0.1.7 已通过本地市场安装。真实导航、文献批注及任务回传、分类纠正、科研展示和时间修复的 App 验收已完成，证据见下方逐批记录；用户确认原生编辑器和中文 PDF 预览正常。Zotero/Colab 配置与真实账号业务按用户最新要求暂不验收，保留原有领域入口。安装与真实 SDK 启动不等于当前聊天的旧 MCP 连接已刷新，不以工具 ready 代替界面验收。未提交、推送或对外发布。

本批最终残留扫描覆盖生产前后端、tests、配置、正式插件、技能与角色、README/CLAUDE 和 docs/live：被删除的实验执行器、通用 MCP/技能管理、项目工具选择、RAG 和通用预览生产引用零命中；负向路由断言是解释命中。不可变 schema 和项目删除清理中的旧调用日志/实验字段用于保留和清理既有数据，无新运行时 writer。导航默认值、React Suspense 和 Colab 原有手动上传模式的 fallback 不属于第二套执行入口。技能源与加载 junction 字节一致，三条改动 skill 的 quick_validate 通过，git diff --check 通过。

## 0.1.4：研究产物不推断执行状态

发现历史列表仅根据 report.md/plan.md 等文件存在就宣称任务完成或运行中。已从 history_runs 的唯一读取路径删除状态推断、伪完成时间及未实现的 source_asset 字段，同步删除前端类型、状态筛选和徽标。研究记录仍保留类型、标题、目录命名时间和产物列表；任务状态只使用工作台任务显式回传。没有修改数据库或既有科研文件。

新增 tests/server/routes/test_history_runs.py 的单一回归用例，使用未评审报告和未执行计划验证产物可见、无推断状态及原文件保持。Test-prune：1 KEEP，0 MERGE/DELETE/QUESTION；保护实际误报问题，不增加静态 UI 文案测试。完整 Python 31 passed（31.41 秒），前端 13 passed、tsc、生产构建通过；沙箱临时目录/realpath 权限失败后使用正常本地权限验证，未改变产品逻辑绕过错误。

最终内联资源 695,527 字节，SHA-256 为 7e22ed1b60fba1af0a778bcab5e955cf17452b9d6d3d3bbfdbbdc3a4aacda6c0。删除的状态 helper、标志集合、筛选字段在当前调用方和 live 文档中无生产引用；负向回归断言保留。流程审计另发现的产物命名与角色同步脚本引用问题已在 0.1.5 修正。

## 0.1.5：科研流程直接使用原生协作

七条 pipeline 统一引用主 skill 的角色编排约定：读取已有角色职责正文，使用 Codex 原生子代理工具，继承当前模型，不消费 Claude frontmatter 为 Codex 配置，不生成角色配置或启动另一套执行器。主聊天传入固定项目、输入、输出负责人和预算，核对实际产物后显式回传。删除不存在的角色同步脚本引用和过期实施队列。

文献综述的 critic 输出 critique.md；sweep 使用 experiments/exp_<NNN>/；数据探索统一写 analysis.md；方法比较合并 sources.json/evidence.json 并保留方法标签与实验条件；idea 使用 plan.md/analysis.md/critique.md，未检索时不要求 sources.json。原始文件不改名，既有产物不迁移。评审结果固定写 outputs，分析计算使用原生命令；来源 paper_id 贯穿证据与报告。LaTeX 按实际 report.tex 交给 critic，并使用原生编辑器的单文件编译。

独立只读推演覆盖三个学习率 sweep、方法比较、中文 LaTeX 综述、CSV 数据质量、不检索的 idea 与原始草稿评审六个场景。推演发现并修正了 reviewer 对 6 分区间无 verdict，以及 conductor 计划文件修改者冲突；该证据是指令验证，不是实际研究执行或宿主 UI 验收。

八个 skill 的 quick_validate 通过；七条 pipeline 的 Codex/Claude junction 与技能源解析路径及字节一致，共享编排引用存在。完整 Python 31 passed（32.14 秒）；本批没有前端行为改动，沿用 0.1.4 的前端 13 项测试、类型检查和构建证据，未重复构建。没有新增自动化测试：修改为指令与版本元数据，现有运行合同测试保留。残留扫描在当前技能、角色、正式插件与 CLAUDE.md 中未发现旧产物名、旧执行 MCP 或已删除同步脚本引用；artifact-review 向 critic 传入 reviewer_review 是有效输入，非 critic 输出。git diff --check 通过。

## 0.1.5 实跑：合成数据探索与实验迭代

本轮未改产品源码或依赖，使用两个明确标注的开发验收样例；产物仅写入项目 outputs，未创建工作台 task_id/nonce 或伪造结果回传。

- data-exploration：outputs/data_explore_20261009_112120_acceptance/inputs/data.csv 为 8 行 3 列合成 CSV。原生 analyzer 实际运行标准库 Python，生成 analysis.md；主聊天读取后委派 writer 生成 report.md。确认 1 个缺失值、1 条多余重复行，正确区分 IQR 与 MAD 判断差异，不将异常信号断言为数据损坏。主聊天独立核对统计并回读报告。
- experiment-iteration：outputs/iter_20261009_112120/inputs/ 保存只读 baseline。experimenter 写 sweep_plan.md，串行执行 exp_001..003 的 spec/script，各自保存 result.json 与 execution.log；analyzer 读取后写 sweep_analysis.md，reviewer 读取后写 review.md，结论 approve。主聊天逐阶段读取实际文件，未仅凭子代理完成消息判定成功。

实验为确定性标量目标 (theta-3)^2，初值 0、20 次梯度更新。学习率 0.01、0.1、0.4 的真实损失分别为 4.0113036355585585、0.0011963051962064115、9.941619558047801e-28，退出码均为 0；进程耗时分别约 0.182、0.160、0.167 秒，符合单次 5 秒/总计 30 秒预算。主聊天独立逐步复算与解析 theta 核对通过。0.01 未达指标门槛仍是执行成功；采样最优不被表述为全局最优或真实模型结论。

输入 SHA-256 前后保持：data.csv 为 57728a9dc1c4c8e39a144ecd3fdcac3b7eae2f6396407cbeea45c60b33a6ea0f；baseline script.py 为 24f6825d600779d4f196de401948e5412b8dd53e433b36d968cffe9f065b2499；baseline spec.md 为 5ecef1579ec2db960927fb55ac07bdd9613d808eee6245d4a4f09b81d715a733。数值、日志存在性与预算断言均通过。无产品代码变动，沿用上一批自动化回归，不重复运行无关测试。

该实跑只覆盖数据探索与实验迭代的成功路径，未覆盖超时、失败停止、文献检索/综述/LaTeX、其他 pipeline 或真实 MCP App UI。本轮侧栏 inventory 仍为空；用户展开面板的请求尚待回应，整体目标保持未完成。

## 原生失败处理与连接更新复核

outputs/iter_20261009_113225 为单独的合成负向验收：exp_001 实际退出码 7；exp_002 达到 0.2 秒预算后终止并 wait 回收，Windows 实际退出码 1。两者 metrics 均为空，总子进程耗时 0.4201503999065608 秒。2/3 失败超过计划半数后停止，exp_003 与 success marker 均不存在。主聊天核对结果、日志、计划、输入 SHA-256 和完整文件清单，断言通过；该记录是预期停止的开发验收，不是完成的科学 sweep。仅使用 Codex 原生命令及标准库，没有向产品加入执行器。

当前 Codex 工具清单已不再暴露 mamba_experiment，四个领域 server 的说明已更新为由 Codex 拥有执行与工具权限。实际 Zotero list_collections 返回缺少环境配置的新版提示，不再要求已删除的 Credentials 界面；真实资料库业务仍未通过。正式 open_workbench 再次返回 ready，但 MCP App 侧栏列表仍为空，未声称界面验收通过。

复核生产装配、五个正式 MCP server、八个导航与两个设置贡献项，并清理 src/server/mcp/__init__.py 唯一过时的 Sandbox 包说明。精确残留扫描未发现已删除的执行器、通用管理组件或旧配置字段引用；历史 schema/数据保持测试及禁止旧路径的说明属于已解释命中。本轮产品只改包说明，不重跑此前已通过且未受影响的 31 项 Python、13 项前端、类型检查和构建。

## 原生文献流程与 LaTeX 宿主限制

outputs/lit_review_20261009_113225 是五篇公开论文的开发验收样例。paper-searcher 使用原生浏览核对原始 arXiv 页面并写 sources.json；evidence-extractor 实际访问相关全文章节写 evidence.json；analyzer 写 analysis.md；writer 写中文 report.tex 与相同书目的 references.bib。各角色只写所属文件，主聊天逐阶段读取。RetNet 章节定位遗漏由证据负责人修正，分析负责人同步去掉过时问题；未伪造全文审计或性能复现。

主聊天独立断言五个 paper_id 在来源、证据、正文引用、内联书目和导出 bib 中完全一致，report.tex 无外部文件编译依赖。内置 LaTeX 编辑器打开请求已排队；主线程 compile_latex_document 实际返回 compile-failed，诊断为 “Unable to find standard directories for platform”。这是宿主编译环境失败，保留可编辑源码，不安装替代 TeX、不新增工作台编译器；PDF 编译、渲染和页数均未验收。文献流程不能因此标为完整通过。

critic 只读核对上述五份输入后写 critique.md，内容 verdict 为 approve，无发现的 Critical/Warning；主聊天已回读确认。该结论仅表示现有文件的论证、条件与引用一致，不代替独立性能复现、原生编译或真实工作台 UI 验收。

## 实验迭代指令修正与产物评审验收

核查发现 experimenter 角色仍要求把多轮迭代追加到原 spec，与 empirical-study 的逐轮目录合同冲突。已删除该指令：每轮递增 experiments/exp_<NNN>/，新 spec 说明配置变化，已完成轮次保持不变。empirical-study 完成态同时改为主聊天核对实际退出码、日志、指标、分析和报告；仅有文件或失败结果不能作为实验成功。修改只涉及现有指令，quick_validate 通过，Codex/Claude junction 均指向同一技能源，旧迭代表述零命中；未新增测试框架或执行器。

artifact-review 实跑产物位于 outputs/review_20261009_115550_data_report/：reviewer 读取已有合成 CSV 报告、分析和原数据，五维 6/8/8/8/8，因 novelty 6 触发规则中的 needs revision；critic 随后读取相同输入及 review.md，输出 critique.md，未发现内容缺陷（0 Critical/Warning/Nit）。主聊天逐阶段回读，保留两种结论：通用评分未达门槛、报告对开发验收用途合格；未虚抬分数或把该分数解释成统计错误。该用例覆盖条件触发的双层评审及只读输入合同，不证明产品 UI 通过。

empirical-study 实跑产物位于 outputs/exp_20261009_115550/：主聊天核对 spec 后，experimenter 使用原生命令执行一次无截距线性回归（合成 y=2x、互不重叠的训练/测试各四点、初值 0、学习率 0.4、20 步）；真实退出码 0，进程耗时 0.17542350001167506 秒，满足 5 秒预算。测试 MSE 从 1.25 降至 1.1368683772161603e-12，最终权重 1.9999980926513672。analyzer 回读 spec/script/result/log 写 analysis.md，writer 据此写 report.md，主聊天回读最终报告并独立用闭式解验证权重、MSE、阈值和日志；只有一轮实验，输入规格保持。该证据覆盖合成成功流程，不证明真实泛化或大型模型性能；未创建伪任务 ID/nonce。

本轮产品改动仅为共享角色与 skill 指令，既有生产实现和依赖未变；不重复此前有效的 Python/前端回归。真实 MCP App 侧栏列表仍为空，未重复安装或把历史分类闭环扩称为新版全界面通过。方法对比、想法探讨、新版 UI、实际外部资源及原生 LaTeX 编译门禁仍未关闭。

## 想法探讨的无检索分支验收

outputs/brainstorm_20261009_120744 使用明确标注的开发测试输入：已知 IQR/MAD 背景，仅思辨“原样与假设去重双视图”的价值，不另检索、不做实验或实现。conductor 写 plan.md，主聊天回读后委派 analyzer 写 analysis.md，再委派 critic 写 critique.md；三个文件分别由角色独占负责。主聊天核对并给出综合结论：解释性报告思路有条件 go，自动去重、准确率优势和创新声明 no-go。

分析引用既有合成案例，区分事实、推论与待验证项；critic 指出合法重复、处理假设未穷尽及额外阅读负担三类反例，没有把风险虚报为已发生缺陷。本 run 不生成 sources.json 是明确测试分支，不是缺失文件被误判成功；此证据不覆盖新的相关工作搜索或准确率实验。

安装复核：本机 0.1.5 缓存中的 plugin.json、.mcp.json 和主 SKILL.md 与仓库逐字节一致；正式配置恰为工作台与四个领域 server。MCP App 侧栏连续多轮返回空列表，没有可绑定的真实面板；现有工具不能创建 MCP App 侧栏，也不能用普通浏览器替代宿主验收。

## 方法对比的受限语料验收

outputs/method_cmp_20261009_120744 明确限定复用已核对的五篇论文语料。paper-searcher 只保留直接相关的 Mamba、Mamba-2 两篇原始论文，不为凑数量将背景论文计入；methods 双标签只标注同一比较来源的关系。evidence-extractor 复用对应选节证据并标明 provenance，主聊天逐字段断言原条件、局限与未知项保持。analyzer 写五维对比，writer 写 report.md；主聊天逐阶段回读，并验证引用 ID、证据链接及四份产物的文件清单。

最终结论为“证据不足以直接选型”，没有把 2–8× 内核速度外推为整模型优势。本场景验证固定语料复用与证据不足处理，没有新增检索、广泛文献覆盖或独立性能复现；本次明确范围不要求为每方法补足三篇。原生检索边界沿用此前真实文献综述证据，二者不混称为本轮检索。

想法流程的 conductor 已在主聊天回读及综合后更新自己的 plan checklist；主聊天确认该 run 仅有 plan.md、analysis.md、critique.md，没有伪造 sources.json 或新增实验脚本。两条限定场景流程均已完成，真实新版界面与外部宿主门禁仍未通过。

## 最终自动化补验与剩余阻塞

在已有真实 stdio 集成测试 test_panel_api_task_result_and_pdf_preserve_fixed_project_context 中补齐批注合同：临时 PDF 使用实际 SHA-256；中文批注经 MCP PUT 保存到固定项目 sidecar，再经 GET 回读；另一项目的 GET/PUT 均返回 404，既有批注及原 PDF 保持。没有增加测试文件、生产代码或第二实现。Test-prune：扩展现有业务流程 KEEP，不添加重复单元测试。目标文件 7 passed（24.89 秒），最终完整 Python 31 passed（32.02 秒）；前端未变，沿用既有 13 项、类型检查与构建证据。精确旧入口残留扫描零命中，git diff --check 通过。

完成审计仍不通过：新版八个导航、两个设置、文献动作和回传的真实 App 联合验收缺少可访问面板；连续至少三轮侧栏列表为空。Zotero 缺实际环境凭据，Colab 现有证据仅为资源定位，原生 LaTeX 编译器仍有已记录的宿主环境错误。代码、安装及自动化证据不能替代这些门禁，也不通过伪造回传、恢复自建执行器或额外模型来绕过。当前可独立完成的流程验收与自动化工作已收尾；需用户展开当前聊天的工作台侧栏及外部环境就绪后继续，整体目标未完成。

## 实际侧栏恢复与本地时间修复（2026-10-09）

此前侧栏不可访问的阻塞已解除。通过真实 MCP App 面板逐一打开八个导航及科研项目/关于两个设置页：凭据、模型、通用 MCP/技能管理入口均不存在；关于页明确模型执行与论文检索由 Codex App 提供。四个栏目均显示科研文件 0、未归入科研栏目 8008，未将工程目录强制归类。草稿与研究记录正常读取既有产物；Zotero 显示缺少环境配置，未宣称真实资料库调用成功。检查后已恢复原 MambaResearch 项目，未修改原研究文件。

真实研究记录页面暴露本地 12:07 的目录被显示成 20:07。根因是 history_runs 将目录本地时钟强制标为 UTC；现改为按主机本地时间转换时间戳，删除错误路径。新增一个确定性 UTC+8 跨日回归验证，目标测试 2 passed；完整 Python 32 passed（34.97 秒）。Test-prune：KEEP，该测试针对真实时区缺陷，不重复已有状态合同。前端未改动，沿用 13 项测试、类型检查与构建证据。生产源码、前端、正式插件和配置中的已删入口精确残留扫描零命中，git diff --check 通过。

运行中 MCP 进程仍加载修复前的 Python，实际时间显示需连接刷新后复核。当前已完成的是导航、设置和只读页面验收；PDF/批注的真实界面动作及新版联合回传仍待核对，既有 MCP 集成合同通过不能替代这些界面动作。Zotero/Colab 外部资源和原生 LaTeX 环境门禁仍保留，整体持续目标未标记完成。

## 真实文献与中文批注界面验收

开发验收项目 51ff532c3f4b4c5badfe8e7565553234 由真实新建项目 UI 注册，文件仅位于 outputs/ui_acceptance_20261009/project。明确标注的两页合成 PDF 经正式 Workspace MCP 建索引，真实界面完成文献打开、翻页、末页禁用、中文批注失焦保存、关闭后重开回读。独立检查 sidecar 精确内容和原 PDF SHA-256 保持通过；该结果覆盖阅读与批注交互，不是实际科研结论。证据见 outputs/ui_acceptance_20261009/report.md。

随后点击真实“提取实验设计”，界面显示“已保存，等待当前聊天处理”。任务消息尚待当前聊天接收，未读取内部会话、未伪造 nonce 或回传；该联合闭环仍未标记完成。本轮未改生产代码，无需重复已通过的自动化回归。

## 文献任务真实回传完成

此前等待的 MCP App 消息已实际到达当前聊天，固定项目 51ff532c3f4b4c5badfe8e7565553234、任务 5cc6fc7b8a954503aa46bb888076c612。主聊天读取 PDF 两页文字，按五段整理缺失信息，产物为该项目 outputs/literature_extract_20261009_131000/report.md；文档明确是开发样例，不补造实验细节。原 PDF 哈希再次验证不变。

使用收到的真实 nonce 调用 record_task_result，工具确认 completed；随后真实面板点击“检查任务结果”，看到“模型结果已返回”、准确摘要与报告路径。当前聊天未收到消息的阻塞已解除，按钮→当前原生聊天→读取与写作→正式 MCP 回传→界面结果的本次联合闭环通过。时间修复后的运行时显示及外部服务/LaTeX 环境门禁仍未关闭。

## 用户批准的真实科研展示案例

项目“科研展示：真实数据分类对比”（62a821d2faeb43f19463694413c01079）由真实 UI 创建，目录 outputs/research_showcase_wdbc；run 为该项目 outputs/exp_20261009_130000。采用 UCI WDBC 公开真实数据的 sklearn 随包副本，569×30，恶性212/良性357。experimenter 先写规格、主聊天读取后执行；analyzer 读取实际结果分析，writer 根据核验输入写 report.md，主聊天逐阶段回读。

三模型共享 seed42 分层五折，LR 标准化仅训练折拟合，固定参数且不调参。实际进程退出0，耗时5.752002000110224秒；LR/RF pooled OOF AUC分别0.9946884414143015/0.9881084509275408，恶性漏判12/14。主聊天从569行预测独立复算12项指标及混淆矩阵，并核对折归属、标签、数据哈希和预算。三图已视觉检查；报告解释Dummy折均AUC0.5与pooled AUC0.4954944241847683的区别，并保留单数据集与单次划分限制。没有伪造显著性或临床有效性。

正式 Workspace MCP 已按内容将数据副本归入数据集，脚本、规格、结果、预测与报告归入实验。真实 UI 核对数据集、实验和研究记录均可见。原生打开报告工具返回queued，不把排队声称为已渲染。本案例直接来自用户聊天，无 task_id/nonce，因此没有捏造工作台任务回传；该合同沿用此前已实际验收的文献按钮闭环。

真实记录仍把run目录13:00显示成21:00，证明旧MCP进程尚未加载本地时间修复；该运行时门禁继续待刷新。新增内容仅为研究产物、分类索引和验收记录，生产源码未变，不重复此前有效的32项Python及13项前端验证。

## 0.1.6 补丁安装与宿主更新诊断

用户要求解决剩余问题后，已安装本地0.1.6补丁；缓存manifest/MCP配置/主skill与仓库逐字节一致。生产行为仍为已通过32项Python回归的同一路径，本批仅版本清单变化，未加入热重载或第二编译器。

App官方更新检查返回restart_required：当前报告版本26.930.61225/build13232，而系统注册包为26.930.7945.0。旧面板刷新仍显示13:00为21:00，需正常重启加载宿主更新和插件连接；不能把安装成功视为已运行新版。原生LaTeX的标准目录错误与同一内置编译器在命令行进入bundle初始化的表现不同，问题收敛到宿主编译环境，但未宣称升级必然解决。Zotero在项目及进程、用户、系统环境均无必需配置，只检查布尔存在性，未暴露密钥。

详细只读诊断及边界见outputs/host_repair_20261009/diagnosis.md。已请求用户正常重启App并在本机配置Zotero，重启后继续实际验收；未修改签名App、关闭沙箱或安装替代TeX。

## 用户重启后的实际复核

新MCP App面板已显示正确时间：同一 exp_20261009_130000 从21:00变为13:00，时间修复的运行时验收完成。真实科研展示及用户数据保持。

原生最小LaTeX文档仍在标准目录初始化失败，不能通过改论文源码修复。更新工具仍报告旧版本及restart_required，因此宿主更新是否加载存在矛盾证据，不能声称已升级，也不否认用户已完成重启。Zotero仍缺用户配置。此轮未修改生产代码，更新验收状态与诊断即可，整体目标未完成。

## 原生 LaTeX 编译及 PDF 兼容性验收（2026-10-09）

后续日志确认 Store 修复仍返回0x80073d02，不能把官方修复描述为成功。包内owl-app.ini明确写应用版本26.930.61225，包标识26.930.7945.0与应用版本属于不同字段，不能仅凭差异判定用户没有重启或没有加载安装包。

本次重开后的原生编译不再出现标准目录错误，实际失败已进入default_bundle_v33资源下载。读取实际tectonic进程输出目录确认缓存根为用户Roaming目录下Codex/web/ChatGPT/latex/tectonic；使用App自带同一tectonic.exe补齐该缓存，保留--untrusted，没有安装替代TeX、修改签名程序或新增MambaResearch编译实现。

补齐缓存后，最小文档与中文报告的原生编译均成功；此前只验收编译与 Poppler 像素，未验证文字映射，不能视为 PDF 兼容性通过。用户指出显示异常后，检查确认默认 Fandol 的 Adobe-GB1 字体没有 ToUnicode，pypdf 提取零个中文字；编译器源码明确对此类字体跳过映射嵌入。额外 ActualText 也实测错误地将中文标为 c 等字符，导致 PDFium 提取乱码，不能使用它补救。

当前唯一路径为 UTF-8、fontset=none、显式 Microsoft YaHei / Bold TrueType、12pt/1.15 行距，并删除 ActualText 生成设置。微软雅黑是当前 Windows 已装字体，不分发字体文件；PDF 嵌入字形与 Unicode，阅读端无需字体或外部中文映射。使用 App 自带同一编译器为最终源码准备实际缓存，再调用原生编辑器，避免先尝试已知隔离下载失败路径。最新 report.pdf 为两页 A4、196888 字节，原生 compile_latex_document 返回 success；332种源码汉字在普通/粗体字体均覆盖，pypdf/PDFium 均保留全部1016个源码中文字，十个实际字体均嵌入且有 ToUnicode，Poppler/PDFium 两套140 DPI逐页检查无缺字、重叠或裁切。

共享 writer 和综述 skill 同步替换旧导言与仅编译完成判定。PDF 检查脚本现统一位于 plugins/mambaresearch/skills/mambaresearch/scripts/check_pdf_text.py，仅做字体与双引擎文字交付检查，不提供编译服务；所需 pypdf/pypdfium2 已随独立包提供，也可用 Codex 已有 Python。tests/scripts/check_pdf_selfcheck.py 手动验收真实报告，并在临时目录创建缺 Unicode、缺字体、缺短句、错误 ActualText 四类负向情形，全部被拒绝；损坏副本清除，真实报告保持。Test-prune：保留一个集中自检，不增重复测试或默认测试环境依赖。

当批共享指令由主 skill 动态读取，未重装插件；0.1.7 改为构建时从唯一源生成随包资源。扫描共享角色、技能、正式插件和脚本，旧自动 ctex 字体导言无生产命中；ActualText=1 唯一命中是禁止使用的说明。git diff --check 通过。随后用户明确确认原生编辑器及中文 PDF 预览“能看到，显示正常”，实际展示门禁关闭；Windows 以外编译宿主未验收，隔离环境的新资源网络下载仍失败，最初目录错误消失的确切原因未证实。没有修改签名 App、关闭隔离、另装 TeX 或新增工作台编译器。

## 0.1.7：独立分发与安装验收

scripts/build_plugin.py 是唯一构建入口，从 canonical 应用、前端 dist、共享科研流程及角色生成包内资源；固定白名单收集程序文件，数据库、账号凭据和用户研究产物不进入包。Python 使用官方 Windows x64 嵌入版 3.13.16，python.exe 发布者签名验证为 Valid / Python Software Foundation。嵌入版通过标准库 site.addsitedir 处理 pip target 的 .pth，解决 pywin32 初始化缺失；没有新增启动器、模型 CLI 或服务端口。

生产 MCP 的 cwd 改为插件根相对路径，使用包内 runtime/python.exe 执行现有领域模块；删除绝对仓库路径和 PYTHONPATH 配置。主 skill 从自身目录定位八条流程与八个角色，PDF 检查脚本移动到同一 skill 下并删除旧位置。凭据从进程环境或用户 ~/.mambaresearch/.env 读取；环境变量在 Zotero 原生 transport 内按明确名单转发，不复制进包。

分发包 outputs/plugin_acceptance_20261009/mambaresearch-0.1.7-windows-x64.zip 为 39248300 字节，SHA-256 为 0a0ae48e50a071b7d6b25e654f28c46b8e1067bce404335bfb558ba206289015。已用本地市场安装至 Codex 0.1.7 缓存；压缩包与安装缓存所有分发文件逐字节一致，压缩包完整性和资源相对链接全部通过。独立压缩包解压到含中文/空格的临时目录，PATH 仅留 Windows System32，PYTHONPATH 为空；解压包及安装缓存各自的五个 MCP 均真实 stdio 初始化并发布项目工具，工作台内联 UI/能力读取与 Workspace stats 成功。用户项目和数据库使用隔离临时目录，没有访问实际外部账号。

完整 Python 33 passed（33.86秒），目标 stdio 文件8 passed；前端13 passed、tsc和生产构建通过。随包 Python 运行 PDF 集中自检通过：真实报告接受，缺文字、缺映射、缺字体和错误 ActualText 均拒绝。Test-prune：新增搬迁集成测试 KEEP，保护独立安装的实际路径与运行时合同；没有重复的静态形状测试。本批旧绝对插件路径及共享目录依赖在正式 MCP/skill 资源中零命中，旧 PDF 脚本位置已删除，live 使用说明同步更新。

当前 App 工具 open_workbench 仍返回 ready；进程路径检查确认原生连接仍使用系统 Python，尚未加载新安装的随包运行时。新包安装和 SDK 验证不被声称为当前连接刷新，用户在插件设置刷新 MambaResearch MCP 连接后生效，无需再次退出等待。Zotero/Colab 按用户明确要求跳过配置与账号业务验收；报告预览已由用户直接确认正常。当前包仅验收 Windows x64；没有提交、推送或外部发布。
