# Mandatory Skill Invocation

Before ANY code-related response (writing, modifying, reviewing, proposing, or debugging code), you MUST invoke the following skills in order. This is non-negotiable. Do not write or propose code until all applicable skills have been invoked.

1. **first-principles-thinking** — Invoke on EVERY user message. Understand the root problem before acting.
2. **solution-standards** — Invoke before proposing any code change, architecture change, or fix.
3. **implementation-discipline** — Invoke before writing or modifying code.
4. **session-discipline** — Invoke when the conversation involves multiple code changes. Review all prior changes for scope creep and consistency before proceeding.

If a response involves code, all four skills apply. Invoke them via the Skill tool before generating any code or file edits.

# 确认你真的读了CLAUDE.md

每次输出回答时，都要加上我的名字，ziang。例如:

我：帮我做一个xx事情
claude（你）：好的ziang。（你的回答）

# 你必须遵守的规则

回复尽量简洁，不要加无关的客套话
优先用简单方案，不要过度工程

# 常用命令

- 后端启动: `python app.py`
- 前端开发: `cd frontend && npm run dev`
- 前端构建: `cd frontend && npm run build`
- 运行测试: `pytest tests/`
- Docker 启动: `docker-compose up`

# 代码修改边界

修改代码前必须判断风险等级，按等级执行对应规则。

## 🔴 禁区 — 改之前必须告知用户并获得同意

这些文件被大量其他文件依赖，改动会引发全项目级联故障。

- `src/dynamic_os/contracts/` 下所有文件（route_plan.py, artifact.py, skill_io.py, observation.py, events.py, policy.py, skill_spec.py, role_spec.py）
- `src/dynamic_os/artifact_refs.py`

规则：
1. 先说明要改什么、为什么改
2. 列出会受影响的文件
3. 等用户确认后再改
4. 改完必须运行 `pytest tests/`

## 🟠 高风险 — 改完必须跑测试验证

这些是核心流程文件，改动可能影响上下游。

- `src/dynamic_os/runtime.py`
- `src/dynamic_os/executor/`
- `src/dynamic_os/planner/`
- `src/dynamic_os/policy/engine.py`
- `src/dynamic_os/tools/gateway/`
- `src/dynamic_os/tools/registry.py`
- `src/dynamic_os/roles/registry.py`

规则：
1. 改完运行 `pytest tests/`
2. 如果测试失败，必须修复后才能继续

## 🟢 安全区 — 可以直接修改

- `src/dynamic_os/skills/builtins/` 下的单个技能
- `src/dynamic_os/storage/` 存储实现
- `frontend/src/` 前端代码
- `configs/agent.yaml` 配置调整
- `scripts/` 脚本工具
- `docs/` 文档

# 架构约定 — 新功能加在哪

## 新技能（最常见）

在 `src/dynamic_os/skills/builtins/` 下创建新目录，包含 3 个文件：
- `skill.yaml` — 技能元数据（输入输出、允许的工具、超时等）
- `skill.md` — 技能文档
- `run.py` — 实现 `async def run(ctx: SkillContext) -> SkillOutput`

系统自动发现，不需要额外注册。

## 新 API 接口

1. 在 `src/server/routes/` 下创建新文件，用 `router = APIRouter()`
2. 在 `app.py` 中 `include_router()` 注册

## 新前端组件

在 `frontend/src/components/` 下创建 `.tsx` 文件，在父组件中引用。

## 新角色（慎重）

需要同时改两处：
1. `src/dynamic_os/roles/roles.yaml` — 定义角色
2. `src/dynamic_os/contracts/route_plan.py` — 在 RoleId 枚举中添加

第 2 步涉及 🔴 禁区，必须先获得用户同意。

## 新工具

通过 MCP 配置声明，系统自动发现。工具 ID 格式：`mcp.{server_id}.{tool_name}`

# 测试原则

核心理念：**只测"坏了看不见但后果严重"的东西。** 不要为了测试而测试，冗余测试用假数据制造"全绿"假象，反而掩盖真正的问题。

## 必须测的（致命问题）

- 数据模型拒绝无效输入 — 坏数据进入系统后一路传播，发现时已晚
- 权限/安全边界 — 权限被突破可能完全察觉不到
- 存储读写一致性 — 数据存了读不出来或读错
- 核心执行流能跑通 + 失败能恢复 — 断了系统直接废掉
- HITL 暂停/恢复 — 卡死后用户以为在正常运行

## 不要测的

- 第三方 API 对接细节（OAuth 参数、URL 拼接、响应格式）— 用假数据测了也没用，真 API 变了测试照过
- LLM 输出纠错的每种场景 — 假 LLM 犯的错和真 LLM 不一样，穷举没有意义
- 显示层小逻辑（标题 fallback、格式化）— 一用就能看到对不对
- 一次性验证（旧代码是否删干净）— 做完就没用了

## 编写规则

1. 测真实行为，不测假替身能不能配合。如果一个测试只有在 mock 和真实实现行为完全一致时才有意义，那这个测试就是脆弱的
2. 一个功能点保留 1-2 个测试即可，不要为同一逻辑写 5 种变体
3. 不强制新功能必须带测试。改了 🔴 禁区和 🟠 高风险代码时才必须确保现有测试通过
4. 前端不写测试，TypeScript 编译 + 构建通过即可

# 代码风格

## 语言规范

| 场景 | 语言 |
|------|------|
| 代码注释 | 中文 |
| Docstring | 中文，numpy 风格 |
| Git 提交信息 | 英文 |
| 日志/错误信息 | 英文 |
| 前端界面文字 | 中文 |
| LLM 提示词 | 中文 |
| README/用户文档 | 中文 |

Docstring 示例：

```python
def search_papers(query: str, max_results: int = 10) -> list[dict]:
    """根据查询检索候选论文。

    参数
    ----------
    query : str
        检索关键词。
    max_results : int, optional
        最大返回数量，默认 10。

    返回
    -------
    list[dict]
        论文元数据列表，每项包含 paper_id, title, abstract。

    异常
    ------
    PolicyViolationError
        当网络访问被策略禁止时抛出。
    """
```

## 命名规范

- 模块/文件名：`snake_case`（如 `route_plan.py`）
- 类名：`PascalCase`（如 `RoutePlan`）
- 函数/变量：`snake_case`（如 `load_yaml()`）
- 私有成员：`_` 前缀（如 `_REPO_ROOT`）