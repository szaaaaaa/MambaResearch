"""``codex app-server`` JSON-RPC 客户端抽象（Task 5b）。

本模块定义 ``CodexSessionManager`` 依赖的客户端 Protocol 接口，把 session 层与
传输层解耦：

* **Protocol** — ``AppServerClient``：描述 session manager 调用的最小表面
  （connect / disconnect / interrupt / send_message / is_connected）。
* **Stub** — ``StubAppServerClient``：本次（5ba）阶段提供的最小可用实现，只能
  反映连接状态、不发消息。让 ``CodexSessionManager.create`` 能跑通 + 返回实例，
  满足"可 import / 冒烟"要求。
* **CodexSchemaError** — 供 5bb 使用的异常类型。``codex app-server
  generate-json-schema`` 输出的 schema 与当前 codex 二进制版本不兼容时抛
  （plan DP7）。5ba 阶段仅定义占位，5bb 的真实客户端会在启动期校验后抛。

真正的 JSON-RPC 2.0 over stdio 实现（spawn ``codex app-server --listen
stdio://``、消息 framing、流式事件适配为 async iterator）由 5bb 取代
``StubAppServerClient`` 落地——5bb 的实现类会同样满足 ``AppServerClient``
Protocol，``CodexSessionManager`` 侧无需改动。

OAuth 透明：codex 二进制自行读 ``~/.codex/auth.json`` 做 ChatGPT 订阅 OAuth。
Workbench 后端不需要也**不应该**在 env 里塞 token——这里不加 provider registry
中转层，保持单一事实源就是 codex 自己的凭据文件。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable

__all__ = [
    "AppServerClient",
    "CodexSchemaError",
    "StubAppServerClient",
]


class CodexSchemaError(RuntimeError):
    """``codex app-server generate-json-schema`` 输出与预期不兼容时抛出。

    典型场景（5bb 落地时真正触发）：

    * 升级 codex 二进制后 schema 字段缺失——plan DP7：``STOP with reason
      codex app-server schema drift — upgrade codex or pin schema version``
    * schema 解析失败（非法 JSON / 空响应）

    5ba 阶段只声明占位，不抛。
    """


@runtime_checkable
class AppServerClient(Protocol):
    """``codex app-server`` 客户端的最小协议。

    ``CodexSessionManager`` 只依赖本 Protocol——具体传输实现（subprocess +
    JSON-RPC over stdio）由 5bb 填入，测试场景可注入 fake。

    方法语义
    ~~~~~~~~

    ``connect`` / ``disconnect``
        启动 / 销毁传输通道。两者均幂等——已连接再 connect 不重复 spawn；未连接
        调 disconnect 静默返回。

    ``send_message(text)``
        发送一条用户消息，返回异步迭代器流式 yield 服务端事件
        （``{"type": "assistant_message", ...}`` / ``{"type": "tool_call", ...}`` /
        ``{"type": "permission_request", ...}``）。迭代结束 = 本轮对话结束。

    ``interrupt``
        打断当前推理（对应 codex JSON-RPC ``cancel`` 通知）。本轮 iterator
        会很快结束并抛 ``CancelledError`` 或返回 ``{"type": "interrupted"}``。

    ``is_connected``
        当前是否持有活跃传输通道；``disconnect`` 或子进程异常退出后变 False。
    """

    async def connect(self) -> None:
        ...

    async def disconnect(self) -> None:
        ...

    async def send_message(self, text: str) -> AsyncIterator[dict[str, Any]]:
        ...

    async def interrupt(self) -> None:
        ...

    async def is_connected(self) -> bool:
        ...


class StubAppServerClient:
    """5ba 阶段的最小 ``AppServerClient`` 实现——只追踪连接状态。

    用途
    ----
    1. 让 ``CodexSessionManager.create`` / ``delete`` 不依赖真实 codex 二进制也能
       跑完整条 create→delete 链路，便于本次提交在 CI / 单测环境通过。
    2. 作为 5bb 的结构样板：真实实现类也会提供同样的方法集，只是每个方法都走
       subprocess + JSON-RPC。

    ``send_message`` 显式抛 ``NotImplementedError``——避免被误用为"实际跑对话"的
    入口。5bc 的测试会用自己的 FakeClient 注入丰富行为，不应复用本 stub。
    """

    def __init__(
        self,
        *,
        cwd: str,
        model: str = "gpt-5.5",
        sandbox_mode: str = "read-only",
    ) -> None:
        self.cwd = cwd
        self.model = model
        self.sandbox_mode = sandbox_mode
        self._connected = False

    async def connect(self) -> None:
        """标记已连接。幂等——重复调用不报错。"""
        self._connected = True

    async def disconnect(self) -> None:
        """标记已断开。幂等——未连接时静默返回。"""
        self._connected = False

    async def send_message(self, text: str) -> AsyncIterator[dict[str, Any]]:
        """5ba 桩实现——真实对话能力由 5bb 落地。"""
        raise NotImplementedError(
            "StubAppServerClient.send_message: real transport pending task 5bb. "
            "Tests should inject FakeClient instead of using the stub."
        )
        # 下面这行让类型检查器识别为 async generator，但永远执行不到
        yield {}  # pragma: no cover

    async def interrupt(self) -> None:
        """桩：接收但不做任何事。"""
        return

    async def is_connected(self) -> bool:
        return self._connected
