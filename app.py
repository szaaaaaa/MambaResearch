import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.server.claude_code.session_manager import session_manager as cc_session_manager
from src.server.codex.session_manager import codex_session_manager
from src.server.projects.db import init_mamba_db
from src.server.projects.registry import sync_active_project_env
from src.server.routes.auth import router as auth_router
from src.server.routes.claude_code import router as claude_code_router
from src.server.routes.codex import router as codex_router
from src.server.routes.config import router as config_router
from src.server.routes.conversation_switch import router as conversation_switch_router
from src.server.routes.conversations import router as conversations_router
from src.server.routes.library import router as library_router
from src.server.routes.literature import router as literature_router
from src.server.routes.mcp_calls import router as mcp_calls_router
from src.server.routes.mcp_servers import router as mcp_servers_router
from src.server.routes.models import router as model_router
from src.server.routes.projects import router as projects_router
from src.server.routes.runs import router as runs_router
from src.server.routes.skills import router as skills_router
from src.server.routes.workspace import router as workspace_router
from src.server.settings import FRONTEND_DIST

_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
]

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(model_router)
app.include_router(config_router)
app.include_router(projects_router)
app.include_router(workspace_router)
app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(conversation_switch_router)
app.include_router(runs_router)
app.include_router(skills_router)
app.include_router(claude_code_router)
app.include_router(codex_router)
app.include_router(mcp_servers_router)
app.include_router(mcp_calls_router)
app.include_router(literature_router)
app.include_router(library_router)


@app.on_event("startup")
async def _init_mamba_db() -> None:
    """启动时建好 ``~/.mambaresearch/mamba.db`` schema（migrations 幂等）。"""
    init_mamba_db()


@app.on_event("startup")
async def _sync_active_project_env() -> None:
    """启动时把 active project 路径同步到 ``MAMBA_ACTIVE_PROJECT_PATH`` env。

    后续 MCP server 子进程从 FastAPI 父进程继承 env，可读到该值。Stage 2 的
    workspace MCP server 依赖此 env 定位 active project。
    """
    sync_active_project_env()


@app.on_event("shutdown")
async def _shutdown_claude_code_sessions() -> None:
    """进程关停时关闭所有 Claude Code SDK 会话，避免孤儿 CLI 子进程。"""
    await cc_session_manager.shutdown()


@app.on_event("shutdown")
async def _shutdown_codex_sessions() -> None:
    """进程关停时关闭所有 Codex app-server 会话，避免孤儿子进程。"""
    await codex_session_manager.shutdown()

if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
