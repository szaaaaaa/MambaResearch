"""MCP 调用历史 HTTP routes（Stage 3 Task 2）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.server.mcp.call_logger import get_call_logger


router = APIRouter()


@router.get("/api/mcp/calls")
def list_calls(
    conversation_id: str | None = Query(default=None),
    cli_session_id: str | None = Query(default=None),
    server_name: str | None = Query(default=None),
    tool_name: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    items = get_call_logger().list_calls(
        conversation_id=conversation_id,
        cli_session_id=cli_session_id,
        server_name=server_name,
        tool_name=tool_name,
        limit=limit,
    )
    return {"calls": items}


@router.get("/api/mcp/calls/{call_id}")
def get_call(call_id: str) -> dict:
    item = get_call_logger().get_call(call_id)
    if item is None:
        raise HTTPException(status_code=404, detail="MCP call not found")
    return item
