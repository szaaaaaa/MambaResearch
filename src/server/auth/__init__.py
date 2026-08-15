"""Registry 驱动的认证探测。"""

from src.server.auth.probe import probe_backends, probe_openai_api_key

__all__ = ["probe_backends", "probe_openai_api_key"]
