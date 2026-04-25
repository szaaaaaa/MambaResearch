"""``codex app-server`` JSON-RPC 客户端（Task 5b）。

本模块包装官方 ``codex app-server --listen stdio://`` 子进程，通过 JSON-RPC 2.0
over newline-delimited JSON（NDJSON）收发消息，把 codex 的线程（thread）/ 回合
（turn）模型适配为 ``CodexSessionManager`` 使用的 ``AppServerClient`` Protocol。

模块结构
--------

* **Protocol** — ``AppServerClient``：session manager 依赖的最小表面。
* **真实实现** — ``CodexAppServerClient``（5bb）：NDJSON 帧格式 + JSON-RPC 2.0，
  spawn 子进程、维护 pending requests 表、reader loop 解复用响应 / 通知 / 服务端
  请求三类消息。
* **桩实现** — ``StubAppServerClient``：仅追踪连接状态的最小实现，session manager
  在测试注入的 fake client 路径上会用它做占位；也作为 5ba 阶段遗留的 "可 import
  可 create→delete 跑通" 的参考实现。
* **Schema 校验** — ``check_schema_compatibility``（module-level，进程内缓存）：
  ``connect`` 首次调用时跑一次 ``codex app-server generate-json-schema``，校验关
  键 schema 文件齐全——未齐全抛 ``CodexSchemaError``（plan DP7）。

OAuth 透明度
~~~~~~~~~~~~

codex 二进制原生读 ``~/.codex/auth.json`` 完成 ChatGPT 订阅 OAuth；Workbench 后端
不经手 token、不设 provider registry 中转层。调用方只需保证 ``~/.codex/auth.json``
存在即可（由 ``CodexSessionManager._check_codex_auth`` 在 ``create`` 时做浅层
pre-flight）。

协议快速参考
~~~~~~~~~~~~

经 ``codex app-server generate-json-schema`` 确认（2026-04 版本，70 个 ClientRequest
method + 58 个 ServerNotification）：

* 客户端请求：``initialize`` / ``thread/start`` / ``turn/start`` / ``turn/interrupt``
  / ``thread/unsubscribe`` / ``thread/read`` / ``model/list`` ...
* 客户端通知：``initialized``（仅这 1 个）
* 服务端通知：``item/agentMessage/delta`` / ``turn/started`` / ``turn/completed``
  / ``item/completed`` / ``thread/started`` / ``error`` ...
* 服务端请求（approval）：``ExecCommandApproval`` / ``ApplyPatchApproval`` /
  ``FileChangeRequestApproval`` / ``PermissionsRequestApproval`` / ...
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

__all__ = [
    "AppServerClient",
    "CodexAppServerClient",
    "CodexRpcError",
    "CodexSchemaError",
    "StubAppServerClient",
    "check_schema_compatibility",
    "reset_schema_cache",
]


class CodexSchemaError(RuntimeError):
    """``codex app-server generate-json-schema`` 输出与预期不兼容时抛出。

    典型场景：

    * 升级 codex 二进制后关键 schema 文件缺失——plan DP7：STOP with reason
      ``codex app-server schema drift — upgrade codex or pin schema version``
    * subprocess 非 0 退出（codex 二进制不在 PATH / 版本过老）
    """


class CodexRpcError(RuntimeError):
    """codex app-server 返回 JSON-RPC error 响应时抛出。

    Attributes
    ----------
    code : int
        JSON-RPC error code。
    data : Any
        服务端带回的 extra data（可能为 None）。
    """

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"codex RPC error {code}: {message}")
        self.code = code
        self.data = data


@runtime_checkable
class AppServerClient(Protocol):
    """``codex app-server`` 客户端的最小协议。

    ``CodexSessionManager`` 只依赖本 Protocol——具体传输实现由
    ``CodexAppServerClient`` 填入；测试场景可注入 fake。
    """

    async def connect(self) -> None:
        ...

    async def disconnect(self) -> None:
        ...

    def send_message(self, text: str) -> AsyncIterator[dict[str, Any]]:
        """返回本轮消息的异步迭代器（async generator）。

        注意：这里特意用 ``def`` 而非 ``async def``——async generator 调用时即返回
        迭代器（不需要先 ``await``）。用 ``async def`` 会让类型检查器推断为
        ``Awaitable[AsyncIterator]``，与实现语义不匹配。
        """
        ...

    async def interrupt(self) -> None:
        ...

    async def is_connected(self) -> bool:
        ...


# ---------------------------------------------------------------------------
# Schema 校验（进程内缓存，首次 connect 时跑一次）
# ---------------------------------------------------------------------------


_REQUIRED_SCHEMAS: tuple[str, ...] = (
    "v1/InitializeParams.json",
    "v2/ThreadStartParams.json",
    "v2/TurnStartParams.json",
    "JSONRPCRequest.json",
)
"""5bb 依赖的关键 schema 文件——任一缺失即视为 drift。

选择标准：我们实际使用的 JSON-RPC method 的 Params schema，加 JSON-RPC 基础帧
schema。不全量校验 70+ methods 是务实选择——只有"我们用到的"消失才真正 break
我们的代码；codex 删减不用的 methods 不应该让 Workbench 失败。
"""

_schema_checked: bool = False
_schema_check_lock = asyncio.Lock()


def reset_schema_cache() -> None:
    """清空"进程内 schema 已校验"缓存——供测试场景切换 codex 二进制时使用。"""
    global _schema_checked
    _schema_checked = False


def _resolve_codex_bin(codex_bin: str) -> str:
    """解析 codex 二进制为绝对路径——Windows 下 ``codex`` 是 npm 装的 ``.cmd``
    shim，``asyncio.create_subprocess_exec`` 不会走 shell 路径展开，需要先
    ``shutil.which`` 拿到完整路径。

    已是绝对路径（含 ``.cmd`` / ``.bat`` / ``.exe`` 后缀）直接回传；否则走 PATH
    查找。查不到抛 ``CodexSchemaError``，让调用方带着清晰错误消息 fail-fast。
    """
    if os.path.isabs(codex_bin) and os.path.isfile(codex_bin):
        return codex_bin
    resolved = shutil.which(codex_bin)
    if resolved is None:
        raise CodexSchemaError(
            f"codex binary {codex_bin!r} not found on PATH. "
            "Install codex CLI: https://github.com/openai/codex"
        )
    return resolved


async def check_schema_compatibility(codex_bin: str = "codex") -> None:
    """校验 ``codex app-server`` 协议 schema 文件齐全——DP7 守护。

    首次调用 subprocess 跑 ``codex app-server generate-json-schema --out <tmpdir>``，
    检查 ``_REQUIRED_SCHEMAS`` 全部存在；不全即抛 ``CodexSchemaError``。校验通过
    后缓存到 ``_schema_checked``，后续 connect 直接跳过（减少 subprocess 开销）。

    Parameters
    ----------
    codex_bin : str
        codex 二进制名或绝对路径。``_resolve_codex_bin`` 会做 PATH 解析——Windows
        的 ``.cmd`` shim 同样能处理；测试可通过 monkeypatch 替换本函数或注入假
        路径。

    Raises
    ------
    CodexSchemaError
        subprocess 失败、timeout、或输出的 schema 目录缺关键文件时抛。
    """
    global _schema_checked
    if _schema_checked:
        return
    async with _schema_check_lock:
        if _schema_checked:
            return
        resolved_bin = _resolve_codex_bin(codex_bin)
        with tempfile.TemporaryDirectory(prefix="codex-schema-") as tmpdir:
            try:
                proc = await asyncio.create_subprocess_exec(
                    resolved_bin,
                    "app-server",
                    "generate-json-schema",
                    "--out",
                    tmpdir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise CodexSchemaError(
                    f"codex binary not found ({resolved_bin!r}): {exc}. "
                    "Install codex CLI and ensure it is on PATH."
                ) from exc
            try:
                _, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=30.0
                )
            except asyncio.TimeoutError as exc:
                proc.kill()
                raise CodexSchemaError(
                    f"`{codex_bin} app-server generate-json-schema` timed out"
                ) from exc
            if proc.returncode != 0:
                raise CodexSchemaError(
                    f"`{codex_bin} app-server generate-json-schema` exited "
                    f"{proc.returncode}: "
                    f"{stderr.decode('utf-8', errors='replace')[:300]}"
                )
            missing = [
                rel
                for rel in _REQUIRED_SCHEMAS
                if not (Path(tmpdir) / rel).is_file()
            ]
            if missing:
                raise CodexSchemaError(
                    f"codex app-server schema drift — missing required files "
                    f"{missing}. Upgrade codex or pin schema version."
                )
        _schema_checked = True


# ---------------------------------------------------------------------------
# Stub（供测试 / 占位用）
# ---------------------------------------------------------------------------


class StubAppServerClient:
    """不与真实 codex 通讯的最小 ``AppServerClient`` 实现。

    用途
    ----
    1. 测试场景：5bc 的 FakeClient 会提供更丰富的行为；本 stub 只做"import 和
       基础 lifecycle 可跑通"的保底。
    2. 文档样板：展示 Protocol 的最小方法集。

    ``send_message`` 显式抛 ``NotImplementedError``——避免被误用为"实际跑对话"的
    入口；测试应注入带行为的 fake。
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
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_message(self, text: str) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError(
            "StubAppServerClient.send_message: inject a FakeClient in tests "
            "or use CodexAppServerClient in production."
        )
        yield {}  # pragma: no cover

    async def interrupt(self) -> None:
        return

    async def is_connected(self) -> bool:
        return self._connected


# ---------------------------------------------------------------------------
# 真实 JSON-RPC 客户端
# ---------------------------------------------------------------------------


# 服务端发起的"审批请求"方法集——reader loop 识别到这些 method+id 组合时
# 路由到 permission bridge。名单与 codex schema 的 ``ServerRequest.json`` 对齐
# （经 ``codex app-server generate-json-schema`` 实测导出：2026-04 版本 9 个
# ServerRequest 中这 7 个属 approval/elicitation，另 2 个 —
# ``account/chatgptAuthTokens/refresh`` / ``item/tool/call`` — 是 token 刷新
# 和 dynamic tool call，不走 bridge）。
_APPROVAL_METHODS: frozenset[str] = frozenset(
    {
        "applyPatchApproval",
        "execCommandApproval",
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
        "item/tool/requestUserInput",
        "mcpServer/elicitation/request",
    }
)


# permission_bridge 签名：(action_key, payload) -> {"decision": "allow/deny", "message": str | None}
PermissionBridge = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


# Reader loop 检测到的"本轮已结束"终止帧方法名——包括 reader 主动发的
# ``connection/lost`` 合成通知（codex 子进程中途 crash 时由 reader 推入 turn
# queue 让 send_message generator 自然收尾，而不是死等 queue.get）。
_TURN_TERMINAL_METHODS: frozenset[str] = frozenset(
    {
        "turn/completed",
        "turn/failed",
        "turn/aborted",
        "thread/closed",
        "connection/lost",
    }
)


class CodexAppServerClient:
    """真实 ``codex app-server`` JSON-RPC 客户端——NDJSON 帧 + subprocess。

    生命周期
    --------

    ``connect`` :
        1. 跑 ``check_schema_compatibility`` 守 DP7
        2. spawn ``codex app-server --listen stdio://``
        3. 启动 reader loop 消费 stdout
        4. 发 ``initialize`` 请求 + 等响应
        5. 发 ``initialized`` 客户端通知
        6. 发 ``thread/start`` 请求 + 等响应，记录 ``threadId``

    ``send_message`` :
        async generator——发 ``turn/start`` 请求（await 响应 ACK），然后从
        reader 推到 ``_current_turn_queue`` 的 notifications 里 yield，直到命中
        ``turn/completed`` / ``turn/failed`` / ``turn/aborted``。

    ``interrupt`` :
        发 ``turn/interrupt`` 请求。

    ``disconnect`` :
        best-effort ``thread/unsubscribe`` → 取消 reader → ``proc.terminate`` →
        ``proc.wait``。

    并发
    ----

    ``_pending`` Future 表 + ``_current_turn_queue`` 的读写都在 reader / 调用方
    同一 event loop 内完成——无需跨线程锁。stdin write 通过 ``_write_lock`` 串行，
    防止同一 loop 里多个协程同时写造成 NDJSON 帧错乱。
    """

    def __init__(
        self,
        *,
        cwd: str,
        model: str,
        sandbox_mode: str,
        permission_bridge: PermissionBridge | None = None,
        codex_bin: str | None = None,
        client_name: str = "ResearchAgent-Workbench",
        client_version: str = "2.x",
    ) -> None:
        self.cwd = cwd
        self.model = model
        self.sandbox_mode = sandbox_mode
        self._bridge = permission_bridge
        self._codex_bin = codex_bin or os.environ.get("CODEX_BIN", "codex")
        self._client_name = client_name
        self._client_version = client_version

        # 运行时状态
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id: int = 0
        self._current_turn_queue: asyncio.Queue[dict[str, Any]] | None = None
        self._thread_id: str | None = None
        self._connected: bool = False
        self._write_lock = asyncio.Lock()

    # -----------------------------------------------------------------------
    # Protocol 方法
    # -----------------------------------------------------------------------

    async def connect(self) -> None:
        """spawn + initialize + start thread。幂等——已连接直接返回。"""
        if self._connected:
            return
        await check_schema_compatibility(self._codex_bin)

        resolved_bin = _resolve_codex_bin(self._codex_bin)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                resolved_bin,
                "app-server",
                "--listen",
                "stdio://",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise CodexSchemaError(
                f"failed to spawn `{resolved_bin} app-server`: {exc}"
            ) from exc

        # 启动 reader + stderr drain
        self._reader_task = asyncio.create_task(
            self._reader_loop(), name=f"codex-reader-{id(self)}"
        )
        self._stderr_task = asyncio.create_task(
            self._stderr_drain(), name=f"codex-stderr-{id(self)}"
        )

        # initialize 握手
        await self._rpc_call(
            "initialize",
            {
                "clientInfo": {
                    "name": self._client_name,
                    "version": self._client_version,
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        # initialized 客户端通知（无 id）
        await self._write_raw(
            {"jsonrpc": "2.0", "method": "initialized", "params": {}}
        )

        # thread/start — 建立对话线程
        thread_result = await self._rpc_call(
            "thread/start",
            {
                "cwd": self.cwd,
                "model": self.model,
                "sandbox": self.sandbox_mode,
            },
        )
        # 实测 schema（5d E2E 发现）：``codex app-server`` 返回
        # ``{"thread": {"id": "<uuid>", "preview": "", "status": {...}, ...}}``
        # 而不是 flat ``{"threadId": "..."}``。下面按优先级解析，fallback 保留
        # 对旧/异构实现的兼容。
        thread_id: str | None = None
        if isinstance(thread_result, dict):
            thread_obj = thread_result.get("thread")
            if isinstance(thread_obj, dict):
                tid = thread_obj.get("id") or thread_obj.get("thread_id")
                if isinstance(tid, str) and tid:
                    thread_id = tid
            if thread_id is None:
                flat = thread_result.get("threadId") or thread_result.get(
                    "thread_id"
                )
                if isinstance(flat, str) and flat:
                    thread_id = flat
        if thread_id is None:
            raise CodexSchemaError(
                f"thread/start returned no parseable thread id: {thread_result!r}"
            )
        self._thread_id = thread_id
        self._connected = True

    async def disconnect(self) -> None:
        """best-effort 清理。幂等——未连接直接返回。"""
        if self._proc is None:
            return
        self._connected = False

        # 尝试优雅关闭（best effort，超时不等）
        if self._thread_id is not None:
            try:
                await asyncio.wait_for(
                    self._rpc_call(
                        "thread/unsubscribe", {"threadId": self._thread_id}
                    ),
                    timeout=2.0,
                )
            except Exception:
                logger.debug(
                    "thread/unsubscribe failed during disconnect",
                    exc_info=True,
                )

        # 取消 reader / stderr drain
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._reader_task = None
        self._stderr_task = None

        # 终止进程
        proc = self._proc
        self._proc = None
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                proc.kill()
                try:
                    await proc.wait()
                except Exception:
                    pass

        # 解除所有悬挂 Future
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(
                    ConnectionError("codex app-server disconnected")
                )
        self._pending.clear()

        self._thread_id = None

    async def send_message(
        self, text: str
    ) -> AsyncIterator[dict[str, Any]]:
        """发用户输入 + 流式 yield 服务端 notifications。

        每条 yield 的 dict 是原始 JSON-RPC notification 消息（含 ``jsonrpc`` /
        ``method`` / ``params`` 字段）；上层由路由转 SSE。

        终止条件：收到 ``turn/completed`` / ``turn/failed`` / ``turn/aborted``
        通知（``_TURN_TERMINAL_METHODS``），最后一帧也会 yield，迭代随之结束。
        """
        if not self._connected:
            raise RuntimeError("client not connected — call connect() first")
        if self._thread_id is None:
            raise RuntimeError("no active thread — connect() may have failed")

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._current_turn_queue = queue
        try:
            # turn/start 请求——响应是 ACK（含 turnId），真正的内容走 notification
            await self._rpc_call(
                "turn/start",
                {
                    "threadId": self._thread_id,
                    "input": [{"type": "text", "text": text}],
                },
            )
            while True:
                msg = await queue.get()
                yield msg
                method = msg.get("method")
                if method in _TURN_TERMINAL_METHODS:
                    break
        finally:
            self._current_turn_queue = None

    async def interrupt(self) -> None:
        if self._thread_id is None:
            return
        try:
            await self._rpc_call("turn/interrupt", {"threadId": self._thread_id})
        except Exception:
            logger.debug("turn/interrupt failed", exc_info=True)

    async def is_connected(self) -> bool:
        return self._connected and self._proc is not None and self._proc.returncode is None

    # -----------------------------------------------------------------------
    # 内部：JSON-RPC 原语
    # -----------------------------------------------------------------------

    async def _rpc_call(self, method: str, params: dict[str, Any]) -> Any:
        """发一条 request 并 await 响应。失败抛 ``CodexRpcError``。"""
        if self._proc is None:
            raise RuntimeError("subprocess not spawned")
        msg_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[msg_id] = fut
        payload = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }
        try:
            await self._write_raw(payload)
            return await fut
        finally:
            self._pending.pop(msg_id, None)

    async def _write_raw(self, payload: dict[str, Any]) -> None:
        """NDJSON 写盘——一行 JSON + ``\\n``，锁保护避免并发交错。

        5d 发现：check-then-use 必须在同一临界段内完成——否则 ``await
        self._write_lock`` 期间 disconnect 可能把 ``self._proc`` 置 None，
        锁外的 early-return 检查值已失效，进入锁后 ``self._proc.stdin.write``
        就抛 AttributeError。修法：把 None 检查移到锁内。
        """
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        async with self._write_lock:
            proc = self._proc
            if proc is None or proc.stdin is None:
                raise RuntimeError("subprocess stdin not available")
            proc.stdin.write(data)
            await proc.stdin.drain()

    async def _reader_loop(self) -> None:
        """持续读 stdout，按消息类型派发。

        Reader 有三条退出路径，必须**全部**触发 cleanup：

        1. EOF（``not line``）——codex 子进程自己退出
        2. ``asyncio.CancelledError``——我方 disconnect 调 ``task.cancel()``
        3. 其他读异常——``stdout.readline()`` IO 错误

        之前把 cleanup 放在 ``while`` 后只覆盖了 (1)(3)——CancelledError 会直接
        re-raise 跳过 cleanup，导致 ``send_message`` 上的消费者永远死等 queue。
        用 ``try/finally`` 把 cleanup 放在 finally 块里三条路径都跑。
        """
        assert self._proc is not None and self._proc.stdout is not None
        stdout = self._proc.stdout
        try:
            while True:
                try:
                    line = await stdout.readline()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("codex reader loop: stdout read failed")
                    break
                if not line:
                    # EOF — 进程退出
                    logger.info(
                        "codex app-server stdout closed (process exited)"
                    )
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    msg = json.loads(stripped)
                except json.JSONDecodeError:
                    logger.warning(
                        "codex reader: non-JSON line %r", stripped[:200]
                    )
                    continue
                await self._dispatch(msg)
        finally:
            # 把所有悬挂的 IO 对象解封：
            # 1. pending 请求置为失败，避免调用方 await Future 死等
            # 2. 当前轮 queue 推入合成终止帧 ``connection/lost``，让
            #    ``send_message`` generator 正常走到 break 退出
            # 用 ``put_nowait`` 而不是 ``await queue.put``——cleanup 可能运行在
            # 已被取消的上下文里，再 await 会被二次取消；asyncio.Queue 默认无界
            # 不会 QueueFull，单帧写入安全。
            self._connected = False
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(
                        ConnectionError("codex app-server closed connection")
                    )
            queue = self._current_turn_queue
            if queue is not None:
                try:
                    queue.put_nowait(
                        {
                            "jsonrpc": "2.0",
                            "method": "connection/lost",
                            "params": {
                                "reason": "codex app-server stdout closed"
                            },
                        }
                    )
                except asyncio.QueueFull:  # pragma: no cover
                    # 默认 Queue 无界，这条分支理论不触发；显式 catch 防未来
                    # 改动意外把 queue 改成有界版本时静默丢哨兵
                    logger.error(
                        "codex reader cleanup: turn queue full, "
                        "consumer may deadlock"
                    )

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        """按消息形状路由三类帧：响应 / 服务端请求 / 通知。"""
        has_id = "id" in msg
        has_method = "method" in msg
        if has_id and ("result" in msg or "error" in msg):
            await self._handle_response(msg)
        elif has_id and has_method:
            # 服务端请求（approval / elicitation）
            asyncio.create_task(
                self._handle_server_request(msg),
                name=f"codex-server-req-{msg.get('id')}",
            )
        elif has_method:
            await self._handle_notification(msg)
        else:
            logger.debug("codex reader: ignoring unknown frame %r", msg)

    async def _handle_response(self, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        fut = self._pending.pop(msg_id, None) if isinstance(msg_id, int) else None
        if fut is None or fut.done():
            logger.debug(
                "codex reader: no pending future for response id %r", msg_id
            )
            return
        if "error" in msg:
            err = msg["error"] or {}
            fut.set_exception(
                CodexRpcError(
                    code=int(err.get("code") or -32603),
                    message=str(err.get("message") or "unknown error"),
                    data=err.get("data"),
                )
            )
        else:
            fut.set_result(msg.get("result"))

    async def _handle_notification(self, msg: dict[str, Any]) -> None:
        """把 notification 推到当前轮队列——没有活跃轮则丢弃 + 日志。"""
        queue = self._current_turn_queue
        if queue is None:
            logger.debug(
                "codex reader: dropping notification outside turn %s",
                msg.get("method"),
            )
            return
        await queue.put(msg)

    async def _handle_server_request(self, msg: dict[str, Any]) -> None:
        """服务端发起的请求——目前只支持 approval；其余回 method-not-found。

        本协程作为 asyncio task 启动（fire-and-forget）；任何 ``_write_raw``
        失败（典型：subprocess 已退出 stdin 断）都用 logger.exception 吞掉——
        避免 "Task exception was never retrieved" 堆栈污染日志，且 reader
        loop 自己会探测到 EOF 走 cleanup 流程。
        """
        method = str(msg.get("method") or "")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method not in _APPROVAL_METHODS or self._bridge is None:
            await self._safe_write_response(
                msg_id,
                error={
                    "code": -32601,
                    "message": f"method {method!r} not supported",
                },
            )
            return

        action_key = _approval_action_key(method, params)
        try:
            decision = await self._bridge(action_key, params)
        except Exception as exc:  # noqa: BLE001
            logger.exception("permission bridge raised for %s", method)
            await self._safe_write_response(
                msg_id,
                error={
                    "code": -32603,
                    "message": f"permission bridge error: {exc}",
                },
            )
            return

        # codex 的 approval response 约定：``{"decision": "approve" | "deny", ...}``
        # 我们的 bridge 回 ``{"decision": "allow" | "deny", ...}``，映射一下即可。
        codex_decision = "approve" if decision.get("decision") == "allow" else "deny"
        await self._safe_write_response(
            msg_id,
            result={"decision": codex_decision},
        )

    async def _safe_write_response(
        self,
        msg_id: Any,
        *,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        """服务端请求的响应写回——吞所有写失败异常（subprocess 可能已退出）。"""
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result or {}
        try:
            await self._write_raw(payload)
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to write server-request response id=%r", msg_id
            )

    async def _stderr_drain(self) -> None:
        """持续读 stderr 防止缓冲填满——非致命，日志 DEBUG 级别。"""
        if self._proc is None or self._proc.stderr is None:
            return
        stderr = self._proc.stderr
        while True:
            try:
                line = await stderr.readline()
            except asyncio.CancelledError:
                raise
            except Exception:
                return
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logger.debug("codex stderr: %s", text)


def _approval_action_key(method: str, params: dict[str, Any]) -> str:
    """把 approval method + params 归一化为 bridge ``allowed_always`` 用的 key。

    目标是让"命中缓存"语义稳定——同一个命令 / 同一个文件路径不要反复弹窗。
    策略：method + 最关键参数（command / path / tool_name 等）。落地不要求完美，
    5d 可以基于实测数据微调参数字段名。
    """
    if method in ("execCommandApproval", "item/commandExecution/requestApproval"):
        command = params.get("command") or params.get("commandLine") or ""
        return f"{method}:{command[:120]}"
    if method in ("applyPatchApproval", "item/fileChange/requestApproval"):
        path = params.get("path") or params.get("filePath") or ""
        return f"{method}:{path}"
    if method == "item/permissions/requestApproval":
        return f"{method}:{params.get('scope') or params.get('resource') or 'global'}"
    return method
