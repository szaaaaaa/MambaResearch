from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = Path.home() / ".mambaresearch" / ".env"
FRONTEND_DIST = ROOT / "frontend" / "dist"
