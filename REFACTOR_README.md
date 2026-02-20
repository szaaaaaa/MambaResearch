# ResearchAgent 架构演进指南

## 一、当前架构现状评估

### 1.1 已完成的基础重构（Phase 1-4）

当前系统已从单体脚本演进为四层分离架构：

```
scripts/              ← App 层：CLI 入口、冒烟测试
src/agent/
├── core/             ← 契约层：Protocol 接口、TypedDict Schema、配置规范化、事件系统、工厂
├── plugins/          ← 插件层：可替换后端实现 + 注册表
│   ├── llm/          (openai_chat)
│   ├── search/       (default_search：多源编排)
│   └── retrieval/    (default_retriever)
├── providers/        ← 网关层：节点调用的唯一入口（含重试、参数解析）
├── infra/            ← 适配层：包装旧模块 src/rag/、src/ingest/
│   ├── llm/
│   ├── search/
│   ├── retrieval/
│   └── indexing/
├── graph.py          ← LangGraph 编排
├── nodes.py          ← 7 个节点函数 + 30+ 辅助函数
└── state.py          ← Schema 兼容导出层
```

**Graph 拓扑：**

```
plan_research → fetch_sources → index_sources → analyze_sources
    ↑                                               ↓
    └──── (should_continue) ←── evaluate_progress ← synthesize
                                     ↓ (done)
                               generate_report → [END]
```

**已落地能力：**
- LLM/Search/Retrieval 通过 `Protocol + Registry + Factory` 可插拔
- YAML + CLI 配置驱动（`core/config.py` 规范化 50+ 默认值）
- 节点级结构化事件（`node_start/node_end/node_error`）
- per-run 隔离（UUID run_id + SQLite 文档追踪 + Chroma allowed_doc_ids）
- 47 条单测全通过（配置、注册表、工厂、provider、节点辅助、节点流程、graph、事件、Schema、合约）

### 1.2 核心瓶颈诊断

当前架构对于**单一研究场景**足够优秀，但向**平台化 / 多工具链 / 重型外部系统**演进时存在三个结构性瓶颈：

| 瓶颈 | 现状 | 影响 |
|------|------|------|
| **节点职责过重** | `nodes.py` 1600+ 行，7 个节点 + 30+ helper，节点直接编排业务逻辑 | 接入新能力（Qlib 回测、代码执行）需侵入节点代码 |
| **状态扁平膨胀** | `ResearchState` 40+ 字段的扁平 TypedDict | 加入量化数据 / 工具日志 / 多 Agent 记忆时字段冲突、不可维护 |
| **缺乏运行时防护** | 无 Token 预算、无细粒度容错、无执行超时 | 复杂 topic 可能死循环或 Token 爆炸 |

---

## 二、演进路线图

```
Phase 5: Executor 解耦        ← 最高优先级，打通外部系统接入通道
Phase 6: State 命名空间隔离    ← 高优，防止状态爆炸
Phase 7: BudgetGuard 防护网    ← 中优，生产级安全
Phase 8: FailureRouter 容错    ← 中优，提升鲁棒性
```

每个 Phase 独立可交付、可测试、向后兼容。

---

## 三、Phase 5：Executor 解耦（最高优先级）

### 3.1 问题

当前节点（如 `fetch_sources`、`analyze_sources`）同时承担**决策**和**执行**两个职责：

```python
# 现状：fetch_sources 节点内部直接编排搜索策略 + 调用 provider
def fetch_sources(state):
    cfg = _get_cfg(state)
    # ... 50 行搜索逻辑 ...
    result = fetch_candidates(cfg=cfg, root=root, ...)  # 直接调用 provider
    # ... 40 行过滤/去重逻辑 ...
    return {"papers": new_papers, "web_sources": new_web}
```

如果未来要接入 Qlib 回测、代码沙盒执行等重型系统，**必须修改节点代码**，违反开闭原则。

### 3.2 目标架构

引入 **Executor 层**，节点只负责**生成结构化任务描述**，具体执行交给 Executor：

```
Node（决策层）           Executor（执行层）             Provider（网关层）
  │                        │                            │
  │ 生成 TaskRequest       │                            │
  ├───────────────────────→│                            │
  │                        │ 路由到具体 Executor         │
  │                        ├───────────────────────────→│
  │                        │                            │ 调用 Backend
  │                        │←───────────────────────────┤
  │ 返回 TaskResult        │                            │
  │←───────────────────────┤                            │
```

### 3.3 实施步骤

#### Step 5.1：定义 Executor 接口和任务 Schema

**新增文件：** `src/agent/core/executor.py`

```python
from __future__ import annotations

from typing import Any, Dict, List, Protocol


class TaskRequest:
    """节点生成的结构化任务描述。"""

    def __init__(
        self,
        action: str,              # 如 "search", "retrieve", "analyze_paper", "run_qlib_backtest"
        params: Dict[str, Any],   # 任务参数
        timeout_sec: float = 120.0,
    ):
        self.action = action
        self.params = params
        self.timeout_sec = timeout_sec


class TaskResult:
    """Executor 返回的执行结果。"""

    def __init__(
        self,
        success: bool,
        data: Dict[str, Any] | None = None,
        error: str | None = None,
        metadata: Dict[str, Any] | None = None,  # 耗时、Token 用量等
    ):
        self.success = success
        self.data = data or {}
        self.error = error
        self.metadata = metadata or {}


class Executor(Protocol):
    """执行器协议：接收任务描述，返回结果。"""

    def supported_actions(self) -> List[str]:
        """该 Executor 支持的 action 名称列表。"""
        ...

    def execute(self, task: TaskRequest, cfg: Dict[str, Any]) -> TaskResult:
        """执行任务，返回结果。"""
        ...
```

#### Step 5.2：实现 ExecutorRouter（任务路由器）

**新增文件：** `src/agent/core/executor_router.py`

```python
from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.agent.core.executor import Executor, TaskRequest, TaskResult

logger = logging.getLogger(__name__)

_EXECUTORS: List[Executor] = []


def register_executor(executor: Executor) -> None:
    _EXECUTORS.append(executor)


def dispatch(task: TaskRequest, cfg: Dict[str, Any]) -> TaskResult:
    """根据 task.action 路由到对应 Executor。"""
    for executor in _EXECUTORS:
        if task.action in executor.supported_actions():
            logger.info("Dispatching action '%s' to %s", task.action, type(executor).__name__)
            return executor.execute(task, cfg)
    return TaskResult(success=False, error=f"No executor registered for action '{task.action}'")
```

#### Step 5.3：将现有 Provider 包装为 Executor

**新增文件：** `src/agent/executors/search_executor.py`

```python
from src.agent.core.executor import Executor, TaskRequest, TaskResult
from src.agent.core.executor_router import register_executor
from src.agent.providers import fetch_candidates


class SearchExecutor:
    def supported_actions(self):
        return ["search"]

    def execute(self, task, cfg):
        try:
            result = fetch_candidates(
                cfg=cfg,
                root=task.params["root"],
                academic_queries=task.params.get("academic_queries", []),
                web_queries=task.params.get("web_queries", []),
                query_routes=task.params.get("query_routes", {}),
            )
            return TaskResult(success=True, data={"papers": result.papers, "web_sources": result.web_sources})
        except Exception as e:
            return TaskResult(success=False, error=str(e))


register_executor(SearchExecutor())
```

同理新增：
- `src/agent/executors/retrieval_executor.py`（包装 `retrieve_chunks`）
- `src/agent/executors/llm_executor.py`（包装 `call_llm`）
- `src/agent/executors/index_executor.py`（包装索引操作）

#### Step 5.4：改造节点函数

**改造前（`fetch_sources` 中 ~90 行执行逻辑）：**
```python
def fetch_sources(state):
    result = fetch_candidates(cfg=cfg, root=root, ...)
    # 过滤、去重 ...
    return {"papers": new_papers, "web_sources": new_web}
```

**改造后（节点只负责决策和状态组装）：**
```python
from src.agent.core.executor_router import dispatch
from src.agent.core.executor import TaskRequest

def fetch_sources(state):
    cfg = _get_cfg(state)
    task = TaskRequest(
        action="search",
        params={
            "root": str(Path(cfg.get("_root", "."))),
            "academic_queries": state.get("_academic_queries", []),
            "web_queries": state.get("_web_queries", []),
            "query_routes": state.get("query_routes", {}),
        },
    )
    result = dispatch(task, cfg)
    if not result.success:
        return {"status": f"Fetch failed: {result.error}"}

    # 节点只做过滤和去重（决策逻辑），不碰底层 API
    raw_papers = result.data.get("papers", [])
    raw_web = result.data.get("web_sources", [])
    # ... 过滤/去重（保持不变）...
    return {"papers": new_papers, "web_sources": new_web}
```

#### Step 5.5：新增测试

**新增文件：** `tests/test_executor.py`

测试覆盖：
- `TaskRequest` / `TaskResult` 构造
- `register_executor` + `dispatch` 路由正确性
- 未注册 action 返回失败
- SearchExecutor / RetrievalExecutor 委托调用

#### Step 5.6：验收标准

- [ ] 所有节点通过 `dispatch()` 调用执行逻辑，不再直接调用 Provider
- [ ] 新增 `QlibExecutor` 仅需新建文件 + 注册，无需修改任何 Node
- [ ] 原有 47 条测试 + 新增 Executor 测试全部通过
- [ ] smoke_test.py 仍正常工作

---

## 四、Phase 6：State 命名空间隔离（高优先级）

### 4.1 问题

当前 `ResearchState` 是扁平结构，40+ 字段混杂在同一层级：

```python
# 现状：core/schemas.py
class ResearchState(TypedDict, total=False):
    topic: str
    research_questions: List[str]
    papers: List[PaperRecord]
    web_sources: List[WebResult]
    analyses: List[AnalysisResult]
    findings: List[str]
    claim_evidence_map: List[Dict[str, Any]]
    evidence_audit_log: List[Dict[str, Any]]
    gaps: List[str]
    synthesis: str
    report: str
    iteration: int
    max_iterations: int
    should_continue: bool
    # ... 还有 20+ 字段
```

未来加入 `ext_quant`（Qlib）、`ext_memory`（长期记忆）、`ext_tools`（工具调用日志）时，字段冲突不可避免。

### 4.2 目标设计

```python
class ResearchState(TypedDict, total=False):
    # ── 核心路由/元数据（精简，所有 Node 共读） ──
    topic: str
    status: str
    run_id: str
    iteration: int
    max_iterations: int
    should_continue: bool
    error: str

    # ── 配置注入（内部使用） ──
    _cfg: Dict[str, Any]

    # ── 模块化扩展区 ──
    research: ResearchNamespace    # 研究相关：papers, web_sources, analyses, findings, ...
    planning: PlanningNamespace    # 规划相关：research_questions, search_queries, query_routes, scope, budget
    evidence: EvidenceNamespace    # 证据相关：claim_evidence_map, evidence_audit_log, gaps
    report: ReportNamespace        # 报告相关：report, report_critic, acceptance_metrics, repair_attempted
    # ext_quant: Dict[str, Any]   # 未来：Qlib 回测结果
    # ext_memory: Dict[str, Any]  # 未来：长期记忆
```

### 4.3 实施步骤

#### Step 6.1：定义命名空间 TypedDict

**修改文件：** `src/agent/core/schemas.py`

```python
class ResearchNamespace(TypedDict, total=False):
    papers: List[PaperRecord]
    indexed_paper_ids: List[str]
    web_sources: List[WebResult]
    indexed_web_ids: List[str]
    analyses: List[AnalysisResult]
    findings: List[str]
    synthesis: str
    memory_summary: str


class PlanningNamespace(TypedDict, total=False):
    research_questions: List[str]
    search_queries: List[str]
    query_routes: Dict[str, Dict[str, Any]]
    scope: Dict[str, Any]
    budget: Dict[str, int]
    _academic_queries: List[str]
    _web_queries: List[str]


class EvidenceNamespace(TypedDict, total=False):
    claim_evidence_map: List[Dict[str, Any]]
    evidence_audit_log: List[Dict[str, Any]]
    gaps: List[str]


class ReportNamespace(TypedDict, total=False):
    report: str
    report_critic: Dict[str, Any]
    repair_attempted: bool
    acceptance_metrics: Dict[str, Any]
```

#### Step 6.2：引入兼容访问层

为避免一次性改动所有 Node，提供兼容读写工具函数：

**新增文件：** `src/agent/core/state_access.py`

```python
"""兼容访问层：在迁移期间同时支持扁平和嵌套读取。"""

from typing import Any, Dict

# 字段到命名空间的映射
_FIELD_NS_MAP = {
    "papers": "research",
    "indexed_paper_ids": "research",
    "web_sources": "research",
    "indexed_web_ids": "research",
    "analyses": "research",
    "findings": "research",
    "synthesis": "research",
    "memory_summary": "research",
    "research_questions": "planning",
    "search_queries": "planning",
    "query_routes": "planning",
    "scope": "planning",
    "budget": "planning",
    "_academic_queries": "planning",
    "_web_queries": "planning",
    "claim_evidence_map": "evidence",
    "evidence_audit_log": "evidence",
    "gaps": "evidence",
    "report": "report",
    "report_critic": "report",
    "repair_attempted": "report",
    "acceptance_metrics": "report",
}


def sget(state: Dict[str, Any], key: str, default: Any = None) -> Any:
    """从 state 中读取字段，优先从命名空间读，兼容回退到扁平结构。"""
    ns = _FIELD_NS_MAP.get(key)
    if ns and ns in state and key in state[ns]:
        return state[ns][key]
    return state.get(key, default)
```

#### Step 6.3：逐节点迁移

分批将节点中的 `state.get("papers", [])` 替换为 `sget(state, "papers", [])`，同时更新返回值格式：

```python
# 迁移前
return {"papers": new_papers, "web_sources": new_web}

# 迁移后
return {
    "research": {
        "papers": new_papers,
        "web_sources": new_web,
    }
}
```

**迁移顺序建议（按依赖关系从下游到上游）：**

1. `generate_report` → 读 evidence + research，写 report 命名空间
2. `evaluate_progress` → 读 evidence + research，写顶层控制字段
3. `synthesize` → 读 research + planning，写 evidence + research
4. `analyze_sources` → 读 research，写 research
5. `index_sources` → 读 research，写 research
6. `fetch_sources` → 读 planning，写 research
7. `plan_research` → 读顶层，写 planning

#### Step 6.4：更新 LangGraph 状态合并逻辑

`graph.py` 和 `smoke_test.py` 中的 list-append 逻辑需要适配嵌套结构：

```python
# smoke_test.py 的 fallback graph 需要支持嵌套 dict 合并
if isinstance(v, dict) and isinstance(st.get(k), dict):
    merged = dict(st[k])
    for sub_k, sub_v in v.items():
        if isinstance(sub_v, list) and isinstance(merged.get(sub_k), list):
            merged[sub_k] = merged[sub_k] + sub_v
        else:
            merged[sub_k] = sub_v
    st[k] = merged
```

#### Step 6.5：验收标准

- [ ] `ResearchState` 顶层字段 <= 10 个（核心路由 + 命名空间入口）
- [ ] 新增 `ext_quant` 命名空间仅需在 Schema 加一行，不影响现有节点
- [ ] 兼容访问层 `sget()` 测试覆盖
- [ ] 全部 47+ 测试通过
- [ ] smoke_test 正常工作

---

## 五、Phase 7：BudgetGuard 防护网（中优先级）

### 5.1 问题

当前系统缺乏全局资源管控：
- 无 Token 用量追踪，复杂 topic 可能 Token 爆炸
- 无 API 调用次数限制
- 无绝对时间超时
- `max_iterations` 是唯一的终止条件，但单次迭代内的 LLM 调用次数不受限

### 5.2 目标设计

**新增文件：** `src/agent/core/budget.py`

```python
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict

logger = logging.getLogger(__name__)


@dataclass
class BudgetGuard:
    """全局资源预算守卫，任何一项超限即触发熔断。"""

    max_tokens: int = 500_000
    max_api_calls: int = 200
    max_wall_time_sec: float = 600.0  # 10 分钟

    # ── 运行时计数 ──
    tokens_used: int = field(default=0, init=False)
    api_calls: int = field(default=0, init=False)
    _start_time: float = field(default_factory=time.time, init=False)

    def record_llm_call(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.tokens_used += prompt_tokens + completion_tokens
        self.api_calls += 1

    def check(self) -> Dict[str, Any]:
        """检查预算，返回 {"exceeded": bool, "reason": str|None, "usage": dict}。"""
        elapsed = time.time() - self._start_time
        if self.tokens_used >= self.max_tokens:
            return self._exceeded(f"Token budget exhausted: {self.tokens_used}/{self.max_tokens}")
        if self.api_calls >= self.max_api_calls:
            return self._exceeded(f"API call budget exhausted: {self.api_calls}/{self.max_api_calls}")
        if elapsed >= self.max_wall_time_sec:
            return self._exceeded(f"Wall time exceeded: {elapsed:.0f}s/{self.max_wall_time_sec:.0f}s")
        return {"exceeded": False, "reason": None, "usage": self._usage(elapsed)}

    def _exceeded(self, reason: str) -> Dict[str, Any]:
        logger.warning("BudgetGuard: %s", reason)
        return {"exceeded": True, "reason": reason, "usage": self._usage(time.time() - self._start_time)}

    def _usage(self, elapsed: float) -> Dict[str, Any]:
        return {
            "tokens_used": self.tokens_used,
            "api_calls": self.api_calls,
            "elapsed_sec": round(elapsed, 1),
        }
```

### 5.3 实施步骤

#### Step 7.1：集成到配置

**修改文件：** `configs/agent.yaml`

```yaml
budget_guard:
  max_tokens: 500000
  max_api_calls: 200
  max_wall_time_sec: 600
```

**修改文件：** `src/agent/core/config.py`

在 `normalize_and_validate_config()` 中添加 budget_guard 默认值处理。

#### Step 7.2：注入 BudgetGuard 实例

**修改文件：** `src/agent/graph.py`

```python
def run_research(topic, cfg, root):
    cfg = normalize_and_validate_config(cfg)
    bg_cfg = cfg.get("budget_guard", {})
    guard = BudgetGuard(
        max_tokens=int(bg_cfg.get("max_tokens", 500_000)),
        max_api_calls=int(bg_cfg.get("max_api_calls", 200)),
        max_wall_time_sec=float(bg_cfg.get("max_wall_time_sec", 600)),
    )
    cfg["_budget_guard"] = guard  # 注入到 cfg 供 provider 层使用
    # ... 其余逻辑不变
```

#### Step 7.3：在 Provider 层记录用量

**修改文件：** `src/agent/providers/llm_provider.py`

在 `call_llm()` 成功返回后调用 `guard.record_llm_call()`。

#### Step 7.4：在 evaluate_progress 检查预算

**修改文件：** `src/agent/nodes.py` (`evaluate_progress` 函数)

```python
guard = cfg.get("_budget_guard")
if guard:
    status = guard.check()
    if status["exceeded"]:
        return {"should_continue": False, "status": f"Budget exceeded: {status['reason']}"}
```

#### Step 7.5：验收标准

- [ ] Token / API / 时间任一超限时自动终止研究循环
- [ ] `run_meta.json` 包含最终 usage 统计
- [ ] 新增 `tests/test_budget_guard.py` 覆盖三种超限场景
- [ ] 不影响正常流程（默认阈值足够宽松）

---

## 六、Phase 8：FailureRouter 细粒度容错（中优先级）

### 6.1 问题

当前错误处理策略粗放：

```python
# 现状：nodes.py 中的典型模式
try:
    hits = retrieve_chunks(...)
except Exception:
    pass  # 静默吞掉所有异常
```

所有错误被统一 catch，无法区分**可恢复**（网络超时→重试）和**不可恢复**（API Key 无效→终止）。

### 6.2 目标设计

**新增文件：** `src/agent/core/failure.py`

```python
from __future__ import annotations

from enum import Enum
from typing import Any, Dict


class FailureAction(Enum):
    RETRY = "retry"       # 网络超时、速率限制
    SKIP = "skip"         # 单个源解析失败
    BACKOFF = "backoff"   # LLM 拒答 → 降级模型
    ABORT = "abort"       # 不可恢复（认证失败）


def classify_failure(exc: Exception, context: str = "") -> FailureAction:
    """根据异常类型和上下文，返回推荐的容错动作。"""
    name = type(exc).__name__
    msg = str(exc).lower()

    if "timeout" in msg or "timed out" in msg:
        return FailureAction.RETRY
    if "rate" in msg and "limit" in msg:
        return FailureAction.RETRY
    if "429" in msg:
        return FailureAction.RETRY
    if "401" in msg or "403" in msg or "authentication" in msg:
        return FailureAction.ABORT
    if "refused" in msg or "content_policy" in msg:
        return FailureAction.BACKOFF
    if context in ("parse_html", "scrape", "pdf_extract"):
        return FailureAction.SKIP

    return FailureAction.SKIP  # 默认跳过，不阻塞流程
```

### 6.3 实施步骤

#### Step 8.1：在 Executor / Provider 层集成

```python
from src.agent.core.failure import classify_failure, FailureAction

try:
    result = backend.generate(...)
except Exception as exc:
    action = classify_failure(exc, context="llm_call")
    if action == FailureAction.RETRY:
        # 已有重试逻辑，直接继续
        ...
    elif action == FailureAction.BACKOFF:
        # 降级为更小模型
        result = backend.generate(..., model="gpt-4.1-mini")
    elif action == FailureAction.ABORT:
        raise
    else:  # SKIP
        logger.warning("Skipping due to: %s", exc)
        return default_result
```

#### Step 8.2：结构化错误日志

在 `events.py` 中扩展事件类型：

```python
emit_event(cfg, {
    "type": "failure_routed",
    "node": node_name,
    "exception": type(exc).__name__,
    "action": action.value,
    "context": context,
})
```

#### Step 8.3：验收标准

- [ ] 网络超时触发 RETRY，认证失败触发 ABORT
- [ ] 单个 PDF/网页解析失败不阻塞整个节点
- [ ] events.log 中可追溯每次 failure 的路由决策
- [ ] 新增 `tests/test_failure_router.py`

---

## 七、Plugin / Provider 边界判断口诀

在后续开发中严格遵守：

```
┌─────────────────────────────────────────────────────────────────┐
│  Provider（做苦力） │  Plugin（做大脑）                         │
│                     │                                          │
│  ✓ HTTP 请求        │  ✓ 请求路由策略                          │
│  ✓ 重试 / 超时      │  ✓ 检索结果融合排序 (Fusion / Ranking)    │
│  ✓ SDK 调用         │  ✓ 查询词改写策略                        │
│  ✓ API Key 管理     │  ✓ 多源结果去重与优先级                   │
│  ✓ 响应解析         │  ✓ 降级 / 回退决策                       │
│                     │                                          │
│  位置: providers/   │  位置: plugins/                          │
│  接口: 无 Protocol  │  接口: implements Protocol               │
│  注册: 无需注册     │  注册: registry.register_*               │
└─────────────────────────────────────────────────────────────────┘
```

**判断方法：**
- 如果代码里有 `import requests` / `import openai` → 属于 Provider 或 Infra
- 如果代码里有 `if source == "arxiv"` 这样的策略分支 → 属于 Plugin
- 如果两者都有 → 拆分

---

## 八、新增外部系统接入模板

完成 Phase 5 后，接入任何新系统（如 Qlib、OpenClaw）只需以下步骤：

### 8.1 新增 Executor（1 个文件）

```python
# src/agent/executors/qlib_executor.py
from src.agent.core.executor import Executor, TaskRequest, TaskResult
from src.agent.core.executor_router import register_executor


class QlibExecutor:
    def supported_actions(self):
        return ["run_qlib_backtest", "qlib_factor_analysis"]

    def execute(self, task, cfg):
        action = task.action
        params = task.params
        if action == "run_qlib_backtest":
            # 调用 Qlib SDK
            ...
            return TaskResult(success=True, data={"sharpe": 1.5, "max_drawdown": -0.12})
        ...


register_executor(QlibExecutor())
```

### 8.2 新增命名空间（1 行）

```python
# src/agent/core/schemas.py
class ResearchState(TypedDict, total=False):
    ...
    ext_quant: Dict[str, Any]  # ← 加这一行
```

### 8.3 新增配置（agent.yaml 加几行）

```yaml
executors:
  qlib:
    enabled: true
    data_dir: "data/qlib"
    market: "csi300"
```

### 8.4 在节点中使用（生成 TaskRequest 即可）

```python
task = TaskRequest(action="run_qlib_backtest", params={"strategy": "MACD", "period": "2020-2024"})
result = dispatch(task, cfg)
```

**不需要修改任何现有 Node、Provider、Plugin 代码。**

---

## 九、文件变更清单汇总

| Phase | 新增文件 | 修改文件 |
|-------|---------|---------|
| **5** | `core/executor.py`<br>`core/executor_router.py`<br>`executors/__init__.py`<br>`executors/search_executor.py`<br>`executors/retrieval_executor.py`<br>`executors/llm_executor.py`<br>`executors/index_executor.py`<br>`tests/test_executor.py` | `nodes.py`（节点改用 dispatch）<br>`plugins/bootstrap.py`（加载 executors） |
| **6** | `core/state_access.py`<br>`tests/test_state_access.py` | `core/schemas.py`（加命名空间 TypedDict）<br>`nodes.py`（逐节点迁移）<br>`graph.py`（状态合并适配）<br>`smoke_test.py`（嵌套 dict 合并） |
| **7** | `core/budget.py`<br>`tests/test_budget_guard.py` | `core/config.py`（默认值）<br>`configs/agent.yaml`（配置项）<br>`graph.py`（注入实例）<br>`providers/llm_provider.py`（记录用量）<br>`nodes.py`（evaluate 中检查） |
| **8** | `core/failure.py`<br>`tests/test_failure_router.py` | `providers/llm_provider.py`（集成分类）<br>`core/events.py`（failure 事件）<br>`nodes.py`（替换 bare except） |

---

## 十、开发规范

### 10.1 新增能力的标准流程

1. **Infra**：新增 SDK 适配器（`infra/xxx/`），只做 API 调用和响应解析
2. **Plugin**：新增可插拔后端（`plugins/xxx/`），实现 Protocol，调用 Infra
3. **Registry**：在 `plugins/registry.py` 注册，在 `bootstrap.py` 中懒加载
4. **Executor**（Phase 5 后）：新增执行器（`executors/xxx.py`），注册到 router
5. **Config**：参数先入 `configs/agent.yaml`，在 `core/config.py` 做 normalize
6. **Test**：最少一条单测 + smoke 路径覆盖

### 10.2 代码审查检查项

- [ ] 节点函数不直接 import infra / plugins 模块
- [ ] Provider 中无策略逻辑（不出现 `if source == "xxx"` 分支）
- [ ] Plugin 中无直接 HTTP 调用（不出现 `requests.get`）
- [ ] 新增字段归入正确的命名空间
- [ ] bare `except Exception: pass` 必须替换为 FailureRouter 分类处理
- [ ] LLM 调用必须经过 BudgetGuard 记录

### 10.3 目录结构（最终形态）

```
src/agent/
├── core/
│   ├── __init__.py
│   ├── interfaces.py       # Protocol 定义
│   ├── schemas.py           # TypedDict + 命名空间
│   ├── config.py            # 配置规范化
│   ├── events.py            # 结构化事件
│   ├── factories.py         # 后端工厂
│   ├── executor.py          # TaskRequest/TaskResult/Executor Protocol  [Phase 5]
│   ├── executor_router.py   # 任务路由器                                [Phase 5]
│   ├── state_access.py      # 兼容访问层                                [Phase 6]
│   ├── budget.py            # BudgetGuard                               [Phase 7]
│   └── failure.py           # FailureRouter                             [Phase 8]
├── plugins/
│   ├── registry.py
│   ├── bootstrap.py
│   ├── llm/
│   ├── search/
│   └── retrieval/
├── providers/
│   ├── llm_provider.py
│   ├── search_provider.py
│   └── retrieval_provider.py
├── executors/               # [Phase 5]
│   ├── __init__.py
│   ├── search_executor.py
│   ├── retrieval_executor.py
│   ├── llm_executor.py
│   └── index_executor.py
├── infra/
│   ├── llm/
│   ├── search/
│   ├── retrieval/
│   └── indexing/
├── graph.py
├── nodes.py
└── state.py
```
