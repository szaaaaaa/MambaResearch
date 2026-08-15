from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.server.kernel.lifecycle import build_lifespan
from src.server.kernel.loader import load_kernel
from src.server.plugins.catalog import builtin_plugins
from src.server.settings import FRONTEND_DIST

_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
]

_REPO_ROOT = Path(__file__).resolve().parent
_PROFILE_PATH = _REPO_ROOT / "configs" / "plugins.json"


def create_app() -> FastAPI:
    loaded_kernel = load_kernel(
        profile_path=_PROFILE_PATH,
        catalog=builtin_plugins(),
    )
    app = FastAPI(lifespan=build_lifespan(loaded_kernel))
    app.state.kernel = loaded_kernel
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for contribution in loaded_kernel.context.capabilities.http.list():
        app.include_router(contribution.router)
    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
