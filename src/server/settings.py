from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "agent.yaml"
ENV_PATH = ROOT / ".env"
FRONTEND_DIST = ROOT / "frontend" / "dist"
TMP_DIR = ROOT / ".tmp"
ACTIVE_RUNS_PATH = TMP_DIR / "active_runs.json"

APP_RUNTIME_MODE = "dynamic-os"
RUN_STATE_PREFIX = "[[RUN_STATE]]"
RUN_EVENT_PREFIX = "[[RUN_EVENT]]"
RUN_LOG_PREFIX = "[[RUN_LOG]]"

OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
SILICONFLOW_MODELS_URL = "https://api.siliconflow.com/v1/models?type=text"

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
)
