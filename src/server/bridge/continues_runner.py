"""调 ``continues`` CLI 生成 handoff markdown（Stage 3 Task 5）。

CLI 调用形态（continues v4.0.12）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``continues inspect <session-id> --write-md <out-path>`` —— 生成单 session 的
handoff markdown：含 chained predecessors + 当前 session 概览 + 最近消息。

返回的 markdown 可直接作为目标 backend 的 first user prompt 的核心内容；本模块
再加一层简短引导文字（"以下是上一段会话的 handoff，请基于此继续"）。

兜底
~~~~
``continues inspect`` 失败（命令不存在 / session 找不到 / 超时）时返回一段
固定模板 markdown，让用户至少能看到"我知道上次做了什么"的基本上下文，避免
卡住整个切换流。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger(__name__)


CONTINUES_BIN = "continues"
DEFAULT_TIMEOUT_S = 30.0
HANDOFF_TTL_SEC = 24 * 3600  # 24h 后清理


@dataclass
class HandoffResult:
    path: Path
    used_fallback: bool
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "used_fallback": self.used_fallback,
            "error": self.error,
        }


def _format_fallback(
    *,
    cli_session_id: str,
    source_backend: str,
    target_backend: str,
    error: str | None,
) -> str:
    """``continues`` 失败时返回的最小 handoff 模板。

    给目标 LLM 足够的上下文知道"我在接续，但具体细节不可考"，让它礼貌地
    询问用户接下来想做什么。
    """
    return (
        f"# Session Handoff (fallback)\n\n"
        f"上一段会话用 **{source_backend}** backend 跑（cli_session_id="
        f"`{cli_session_id}`）。`continues` 工具未能生成完整 handoff："
        f"{error or '未知原因'}。\n\n"
        f"请：\n"
        f"1. 简短地确认你已接手该会话\n"
        f"2. 询问用户希望继续推进的下一步\n\n"
        f"避免假设上次的具体细节——只继承用户当前想做什么。\n"
    )


async def generate_handoff(
    *,
    cli_session_id: str,
    source_backend: str,
    target_backend: str,
    out_path: Path,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> HandoffResult:
    """生成 handoff 文件——成功走 continues，失败走兜底模板。

    Parameters
    ----------
    cli_session_id : str
        当前活跃 segment 的 ``cli_session_id``——传给 ``continues inspect``。
    source_backend / target_backend : str
        仅用于 fallback 文案。``continues`` CLI 不需要 source 参数（按 session id
        识别）。
    out_path : Path
        markdown 输出路径。父目录会自动创建。
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if shutil.which(CONTINUES_BIN) is None:
        out_path.write_text(
            _format_fallback(
                cli_session_id=cli_session_id,
                source_backend=source_backend,
                target_backend=target_backend,
                error=f"`{CONTINUES_BIN}` 命令未安装",
            ),
            encoding="utf-8",
        )
        return HandoffResult(
            path=out_path,
            used_fallback=True,
            error=f"`{CONTINUES_BIN}` 不在 PATH",
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            CONTINUES_BIN,
            "inspect",
            cli_session_id,
            "--write-md",
            str(out_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            err = f"`continues inspect` 超时 (>{timeout_s}s)"
            out_path.write_text(
                _format_fallback(
                    cli_session_id=cli_session_id,
                    source_backend=source_backend,
                    target_backend=target_backend,
                    error=err,
                ),
                encoding="utf-8",
            )
            return HandoffResult(path=out_path, used_fallback=True, error=err)

        if proc.returncode != 0 or not out_path.exists():
            err = (
                stderr.decode("utf-8", errors="replace").strip()
                or f"`continues inspect` 退出码 {proc.returncode}"
            )
            out_path.write_text(
                _format_fallback(
                    cli_session_id=cli_session_id,
                    source_backend=source_backend,
                    target_backend=target_backend,
                    error=err[:200],
                ),
                encoding="utf-8",
            )
            return HandoffResult(path=out_path, used_fallback=True, error=err)
    except Exception as exc:  # noqa: BLE001
        out_path.write_text(
            _format_fallback(
                cli_session_id=cli_session_id,
                source_backend=source_backend,
                target_backend=target_backend,
                error=str(exc),
            ),
            encoding="utf-8",
        )
        return HandoffResult(path=out_path, used_fallback=True, error=str(exc))

    return HandoffResult(path=out_path, used_fallback=False, error=None)


def build_first_prompt(handoff_path: Path, target_backend: str) -> str:
    """读 handoff markdown + 加一层简短引导，作为 target session 的 first prompt。"""
    try:
        body = handoff_path.read_text(encoding="utf-8")
    except OSError as exc:
        body = f"(handoff 文件读取失败：{exc})"
    label = "Claude Code" if target_backend == "claude" else "Codex CLI"
    return (
        f"你正在 **{label}** 中接续一段之前的会话——上一段在另一个 backend 里跑。"
        f"以下是 `continues` 工具生成的 handoff 上下文，请基于此继续推进用户的需求。"
        f"如果 handoff 里有文件路径或 session ID 等结构化信息，可以直接引用。\n\n"
        f"---\n\n{body}"
    )


def cleanup_expired_handoffs(handoffs_dir: Path, *, ttl_sec: int = HANDOFF_TTL_SEC) -> int:
    """删除 ``handoffs_dir`` 下 mtime 超过 TTL 的 .md 文件。返回删了多少个。"""
    if not handoffs_dir.exists():
        return 0
    now = time.time()
    deleted = 0
    for path in handoffs_dir.glob("*.md"):
        try:
            if now - path.stat().st_mtime > ttl_sec:
                path.unlink()
                deleted += 1
        except OSError:
            logger.exception("cleanup handoff file failed: %s", path)
    return deleted
