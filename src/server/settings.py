from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"
FRONTEND_DIST = ROOT / "frontend" / "dist"
TMP_DIR = ROOT / ".tmp"
ACTIVE_RUNS_PATH = TMP_DIR / "active_runs.json"

APP_RUNTIME_MODE = "dynamic-os"
RUN_STATE_PREFIX = "[[RUN_STATE]]"
RUN_EVENT_PREFIX = "[[RUN_EVENT]]"
RUN_LOG_PREFIX = "[[RUN_LOG]]"

CREDENTIAL_KEYS = (
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "SILICONFLOW_API_KEY",
    "GOOGLE_API_KEY",
    "SERPAPI_API_KEY",
    "GOOGLE_CSE_API_KEY",
    "GOOGLE_CSE_CX",
    "BING_API_KEY",
    "GITHUB_TOKEN",
    "ZOTERO_USER_ID",
    "ZOTERO_API_KEY",
)
