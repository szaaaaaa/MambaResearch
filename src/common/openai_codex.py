from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

if os.name == "nt":
    import msvcrt
else:
    import fcntl


ROOT = Path(__file__).resolve().parents[2]
OPENAI_CODEX_LEGACY_AUTH_PATH = ROOT / ".auth" / "openai_codex.json"


def _default_auth_root() -> Path:
    override = str(os.environ.get("RESEARCH_AGENT_AUTH_DIR") or "").strip()
    if override:
        return Path(override)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "ResearchAgent"
    xdg_state_home = str(os.environ.get("XDG_STATE_HOME") or "").strip()
    if xdg_state_home:
        return Path(xdg_state_home) / "research-agent"
    return Path.home() / ".research-agent"


OPENAI_CODEX_AUTH_PATH = _default_auth_root() / "auth" / "profiles.json"
OPENAI_CODEX_MODELS_CACHE_PATH = _default_auth_root() / "auth" / "openai_codex_models.json"

AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
SCOPE = "openid profile email offline_access"
REDIRECT_URI = "http://localhost:1455/auth/callback"
OPENAI_CODEX_OAUTH_ORIGINATOR = "pi"

OPENAI_CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
OPENAI_CODEX_RESPONSES_WS_URL = "wss://chatgpt.com/backend-api/codex/responses"
OPENAI_CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models"
OPENAI_CODEX_SSE_BETA_HEADER = "responses=experimental"
OPENAI_CODEX_WS_BETA_HEADER = "responses_websockets=2026-02-06"
OPENAI_CODEX_TRANSPORT_OPTIONS = ("auto", "websocket", "sse")
DEFAULT_OPENAI_CODEX_TRANSPORT = "auto"
OPENAI_CODEX_MODEL_REF_PREFIX = "openai-codex/"
DEFAULT_OPENAI_CODEX_PROFILE = "default"
OPENAI_CODEX_CLIENT_VERSION = str(os.environ.get("OPENAI_CODEX_CLIENT_VERSION") or "1.0.0").strip() or "1.0.0"
DEFAULT_OPENAI_CODEX_INSTRUCTIONS = (
    "You are Codex, a coding and research assistant. Follow the user's instructions carefully, "
    "use available context, and respond with the requested result only."
)

_KNOWN_OPENAI_CODEX_MODELS = [
    {"value": "gpt-5.4", "label": "GPT-5.4", "priority": 10, "source": "openclaw"},
    {"value": "gpt-5.2-codex", "label": "GPT-5.2 Codex", "priority": 20, "source": "openai_docs"},
    {"value": "gpt-5.1-codex-max", "label": "GPT-5.1 Codex Max", "priority": 30, "source": "openai_docs"},
    {"value": "gpt-5.1-codex", "label": "GPT-5.1 Codex", "priority": 40, "source": "openai_docs"},
    {"value": "gpt-5.1-codex-mini", "label": "GPT-5.1 Codex Mini", "priority": 50, "source": "openai_docs"},
    {"value": "gpt-5-codex", "label": "GPT-5 Codex", "priority": 60, "source": "openai_docs"},
]

_PENDING_LOGIN_LOCK = threading.Lock()
_PENDING_LOGIN: dict[str, Any] = {}
_CALLBACK_SERVER: ThreadingHTTPServer | None = None
_CALLBACK_THREAD: threading.Thread | None = None


def _now_epoch_seconds() -> int:
    return int(time.time())


def normalize_openai_codex_transport(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text in {"ws", "websocket"}:
        return "websocket"
    if text in {"http", "stream", "sse"}:
        return "sse"
    if text in {"auto", ""}:
        return "auto"
    return DEFAULT_OPENAI_CODEX_TRANSPORT


def normalize_openai_codex_model_discovery(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text in {"account", "remote", "account_plus_cached", "live"}:
        return "account_plus_cached"
    if text in {"known", "known_plus_cached", "cache"}:
        return "known_plus_cached"
    return "account_plus_cached"


def _normalize_model_id(value: str) -> str:
    return str(value or "").strip()


def bare_openai_codex_model_name(value: str) -> str:
    normalized = _normalize_model_id(value)
    if normalized.lower().startswith(OPENAI_CODEX_MODEL_REF_PREFIX):
        return normalized[len(OPENAI_CODEX_MODEL_REF_PREFIX):].strip()
    return normalized


def is_openai_codex_model_ref(value: str) -> bool:
    normalized = _normalize_model_id(value)
    return normalized.lower().startswith(OPENAI_CODEX_MODEL_REF_PREFIX)


def parse_openai_codex_model_ref(value: str) -> str:
    normalized = _normalize_model_id(value)
    if not is_openai_codex_model_ref(normalized):
        raise RuntimeError("openai codex model must use openai-codex/<model>")
    bare = normalized[len(OPENAI_CODEX_MODEL_REF_PREFIX):].strip()
    if not bare:
        raise RuntimeError("openai codex model ref is missing model name")
    return bare


def openai_codex_model_ref(value: str) -> str:
    bare = bare_openai_codex_model_name(value)
    if not bare:
        return ""
    return f"{OPENAI_CODEX_MODEL_REF_PREFIX}{bare}"


def _normalize_profile_id(value: Any) -> str:
    return str(value or "").strip()


def _normalize_profile_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates = value.replace("\r", "\n").replace(",", "\n").split("\n")
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []

    seen: set[str] = set()
    normalized: list[str] = []
    for item in candidates:
        profile_id = _normalize_profile_id(item)
        if not profile_id or profile_id in seen:
            continue
        seen.add(profile_id)
        normalized.append(profile_id)
    return normalized


def _openai_codex_binding(config: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_auth = {}
    if isinstance(config, dict):
        auth = config.get("auth") or {}
        if isinstance(auth, dict):
            raw_auth = auth.get("openai_codex") or {}
            if not isinstance(raw_auth, dict):
                raw_auth = {}

    default_profile = _normalize_profile_id(raw_auth.get("default_profile")) or DEFAULT_OPENAI_CODEX_PROFILE
    allowed_profiles = _normalize_profile_ids(raw_auth.get("allowed_profiles"))
    if not allowed_profiles:
        allowed_profiles = [default_profile]

    return {
        "default_profile": default_profile,
        "allowed_profiles": allowed_profiles,
        "locked": bool(raw_auth.get("locked", True)),
        "require_explicit_switch": bool(raw_auth.get("require_explicit_switch", True)),
    }


def _resolve_openai_codex_profile(
    *,
    config: dict[str, Any] | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    binding = _openai_codex_binding(config)
    requested_profile = _normalize_profile_id(profile_id)
    resolved_profile = requested_profile or binding["default_profile"]
    if not resolved_profile:
        raise RuntimeError("openai codex default profile is not configured")
    if requested_profile and binding["locked"] and requested_profile != binding["default_profile"]:
        raise RuntimeError(
            f"openai codex profile switch is locked to '{binding['default_profile']}' for this agent"
        )
    if resolved_profile not in binding["allowed_profiles"]:
        raise RuntimeError(f"openai codex profile '{resolved_profile}' is not allowed for this agent")
    return {
        "profile_id": resolved_profile,
        "binding": binding,
    }


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = str(token or "").split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1].strip()
    if not payload:
        return {}
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{payload}{padding}".encode("utf-8")).decode("utf-8")
        data = json.loads(decoded)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _token_profile(access_token: str, id_token: str = "") -> dict[str, str]:
    access_payload = _decode_jwt_payload(access_token)
    id_payload = _decode_jwt_payload(id_token)
    auth_claims = (
        id_payload.get("https://api.openai.com/auth")
        or access_payload.get("https://api.openai.com/auth")
        or {}
    )
    profile_claims = access_payload.get("https://api.openai.com/profile") or {}
    email = str(id_payload.get("email") or profile_claims.get("email") or "").strip()
    name = str(
        id_payload.get("name")
        or id_payload.get("preferred_username")
        or access_payload.get("name")
        or profile_claims.get("name")
        or ""
    ).strip()
    account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()
    plan_type = str(auth_claims.get("chatgpt_plan_type") or "").strip()
    user_label = name or email or account_id
    return {
        "user_name": name,
        "user_email": email,
        "user_label": user_label,
        "plan_type": plan_type,
        "account_id": account_id,
    }


def _lock_file_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


@contextmanager
def _file_lock(path: Path, *, timeout_seconds: float = 10.0, create: bool = True):
    lock_path = _lock_file_path(path)
    if not create:
        if not lock_path.parent.exists() or not lock_path.exists():
            yield
            return
        mode = "r+b"
    else:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a+b"

    with lock_path.open(mode) as lock_file:
        if lock_path.stat().st_size < 1:
            lock_file.write(b"0")
            lock_file.flush()
        started_at = time.monotonic()
        while True:
            try:
                lock_file.seek(0)
                if os.name == "nt":
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if (time.monotonic() - started_at) >= timeout_seconds:
                    raise RuntimeError(f"timed out waiting for auth store lock: {lock_path}")
                time.sleep(0.05)
        try:
            yield
        finally:
            lock_file.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_json_file_unlocked(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_file_unlocked(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _empty_openai_codex_auth_store() -> dict[str, Any]:
    return {
        "version": 1,
        "providers": {
            "openai_codex": {
                "profiles": {},
            }
        },
        "updated_at": 0,
    }


def _normalize_openai_codex_auth_store(payload: dict[str, Any]) -> dict[str, Any]:
    store = _empty_openai_codex_auth_store()
    if not isinstance(payload, dict):
        return store

    providers = payload.get("providers")
    if isinstance(providers, dict):
        provider_entry = providers.get("openai_codex") or {}
        if isinstance(provider_entry, dict):
            raw_profiles = provider_entry.get("profiles") or {}
            if isinstance(raw_profiles, dict):
                normalized_profiles: dict[str, dict[str, Any]] = {}
                for raw_profile_id, raw_entry in raw_profiles.items():
                    profile_id = _normalize_profile_id(raw_profile_id)
                    if not profile_id or not isinstance(raw_entry, dict):
                        continue
                    normalized_profiles[profile_id] = {
                        "provider": "openai_codex",
                        "profile_id": profile_id,
                        "tokens": dict(raw_entry.get("tokens") or {}),
                        "profile": dict(raw_entry.get("profile") or {}),
                        "updated_at": int(raw_entry.get("updated_at") or 0),
                    }
                store["providers"]["openai_codex"]["profiles"] = normalized_profiles
                store["updated_at"] = int(payload.get("updated_at") or 0)
                return store

    if isinstance(payload.get("tokens"), dict):
        store["providers"]["openai_codex"]["profiles"][DEFAULT_OPENAI_CODEX_PROFILE] = {
            "provider": "openai_codex",
            "profile_id": DEFAULT_OPENAI_CODEX_PROFILE,
            "tokens": dict(payload.get("tokens") or {}),
            "profile": dict(payload.get("profile") or {}),
            "updated_at": int(payload.get("updated_at") or 0),
        }
        store["updated_at"] = int(payload.get("updated_at") or 0)
    return store


def read_openai_codex_auth_file(path: str | Path | None = None) -> dict[str, Any]:
    auth_path = Path(path) if path is not None else OPENAI_CODEX_AUTH_PATH
    with _file_lock(auth_path, create=auth_path.exists()):
        raw_payload = _read_json_file_unlocked(auth_path)
        normalized = _normalize_openai_codex_auth_store(raw_payload)
        if auth_path.exists() and normalized != raw_payload:
            _write_json_file_unlocked(auth_path, normalized)
        return normalized


def _write_openai_codex_auth_file(payload: dict[str, Any], path: str | Path | None = None) -> None:
    auth_path = Path(path) if path is not None else OPENAI_CODEX_AUTH_PATH
    normalized = _normalize_openai_codex_auth_store(payload)
    with _file_lock(auth_path):
        _write_json_file_unlocked(auth_path, normalized)


def _openai_codex_profiles_from_store(store: dict[str, Any]) -> dict[str, dict[str, Any]]:
    providers = store.get("providers") or {}
    if not isinstance(providers, dict):
        return {}
    provider_entry = providers.get("openai_codex")
    if not isinstance(provider_entry, dict):
        return {}
    profiles = provider_entry.get("profiles")
    return profiles if isinstance(profiles, dict) else {}


def _openai_codex_profile_from_store(store: dict[str, Any], profile_id: str) -> dict[str, Any]:
    profiles = _openai_codex_profiles_from_store(store)
    payload = profiles.get(profile_id) or {}
    return dict(payload) if isinstance(payload, dict) else {}


def _set_openai_codex_profile_in_store(
    store: dict[str, Any],
    *,
    profile_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_openai_codex_auth_store(store)
    profiles = _openai_codex_profiles_from_store(normalized)
    profiles[profile_id] = {
        "provider": "openai_codex",
        "profile_id": profile_id,
        "tokens": dict(payload.get("tokens") or {}),
        "profile": dict(payload.get("profile") or {}),
        "updated_at": int(payload.get("updated_at") or _now_epoch_seconds()),
    }
    normalized["updated_at"] = _now_epoch_seconds()
    return normalized


def _delete_openai_codex_profile_from_store(store: dict[str, Any], *, profile_id: str) -> dict[str, Any]:
    normalized = _normalize_openai_codex_auth_store(store)
    profiles = _openai_codex_profiles_from_store(normalized)
    profiles.pop(profile_id, None)
    normalized["updated_at"] = _now_epoch_seconds()
    return normalized


def _profile_summary(profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    tokens = payload.get("tokens") or {}
    if not isinstance(tokens, dict):
        tokens = {}
    profile = payload.get("profile") or {}
    if not isinstance(profile, dict):
        profile = {}
    return {
        "profile_id": profile_id,
        "user_label": str(profile.get("user_label") or ""),
        "user_name": str(profile.get("user_name") or ""),
        "user_email": str(profile.get("user_email") or ""),
        "plan_type": str(profile.get("plan_type") or ""),
        "account_id": str(tokens.get("account_id") or profile.get("account_id") or ""),
        "updated_at": int(payload.get("updated_at") or 0),
    }


def _available_openai_codex_profiles(store: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = [
        _profile_summary(profile_id, payload)
        for profile_id, payload in _openai_codex_profiles_from_store(store).items()
        if isinstance(payload, dict)
    ]
    return sorted(
        summaries,
        key=lambda item: (-int(item.get("updated_at") or 0), str(item.get("profile_id") or "").lower()),
    )


def _openai_codex_request_headers(*, access_token: str, account_id: str = "") -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "originator": OPENAI_CODEX_OAUTH_ORIGINATOR,
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id
    return headers


def read_openai_codex_models_cache(path: str | Path | None = None) -> dict[str, Any]:
    cache_path = Path(path) if path is not None else OPENAI_CODEX_MODELS_CACHE_PATH
    with _file_lock(cache_path, create=cache_path.exists()):
        return _read_json_file_unlocked(cache_path)


def _write_openai_codex_models_cache(payload: dict[str, Any], path: str | Path | None = None) -> None:
    cache_path = Path(path) if path is not None else OPENAI_CODEX_MODELS_CACHE_PATH
    with _file_lock(cache_path):
        _write_json_file_unlocked(cache_path, payload)


def _token_expired(tokens: dict[str, Any], *, skew_seconds: int = 60) -> bool:
    expires_at = int(tokens.get("expires_at") or 0)
    if expires_at <= 0:
        return False
    return expires_at <= (_now_epoch_seconds() + skew_seconds)


def _pending_login_snapshot(profile_id: str | None = None) -> dict[str, Any]:
    with _PENDING_LOGIN_LOCK:
        pending = dict(_PENDING_LOGIN)
    expires_at = int(pending.get("expires_at") or 0)
    if expires_at and expires_at <= _now_epoch_seconds():
        return {}
    if profile_id and _normalize_profile_id(pending.get("profile_id")) != _normalize_profile_id(profile_id):
        return {}
    return pending


def _status_from_payload(
    payload: dict[str, Any],
    *,
    profile_id: str,
    binding: dict[str, Any],
    available_profiles: list[dict[str, Any]],
    error: str = "",
) -> dict[str, Any]:
    tokens = payload.get("tokens") or {}
    if not isinstance(tokens, dict):
        tokens = {}
    access_token = str(tokens.get("access_token") or "").strip()
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    profile = payload.get("profile") or {}
    if not isinstance(profile, dict):
        profile = {}
    expires_at = int(tokens.get("expires_at") or 0)
    expired = _token_expired(tokens, skew_seconds=0)
    pending = _pending_login_snapshot(profile_id)
    usable = bool(access_token) and not expired
    auth_mode = "chatgpt" if access_token or refresh_token else "missing"
    return {
        "installed": True,
        "logged_in": usable,
        "chatgpt_logged_in": usable,
        "auth_mode": auth_mode,
        "executable": "",
        "available": usable,
        "active_profile": profile_id,
        "default_profile": str(binding.get("default_profile") or ""),
        "allowed_profiles": list(binding.get("allowed_profiles") or []),
        "profile_locked": bool(binding.get("locked", True)),
        "require_explicit_switch": bool(binding.get("require_explicit_switch", True)),
        "available_profiles": available_profiles,
        "user_name": str(profile.get("user_name") or ""),
        "user_email": str(profile.get("user_email") or ""),
        "user_label": str(profile.get("user_label") or ""),
        "plan_type": str(profile.get("plan_type") or ""),
        "account_id": str(tokens.get("account_id") or profile.get("account_id") or ""),
        "expires_at": expires_at,
        "expires_in_sec": max(expires_at - _now_epoch_seconds(), 0) if expires_at > 0 else 0,
        "expired": expired,
        "has_refresh_token": bool(refresh_token),
        "login_in_progress": bool(pending),
        "last_error": error or str(pending.get("last_error") or ""),
    }


def _token_request(fields: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode(fields).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"openai codex token request failed: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"openai codex token request failed: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("openai codex token request returned invalid payload")
    return payload


def _stored_openai_codex_auth_payload(
    token_payload: dict[str, Any],
    *,
    profile_id: str,
) -> dict[str, Any]:
    access_token = str(token_payload.get("access_token") or "").strip()
    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    id_token = str(token_payload.get("id_token") or "").strip()
    if not access_token:
        raise RuntimeError("openai codex token response did not include access_token")
    expires_in = int(token_payload.get("expires_in") or 0)
    profile = _token_profile(access_token, id_token)
    return {
        "provider": "openai_codex",
        "profile_id": profile_id,
        "tokens": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id_token": id_token,
            "expires_at": _now_epoch_seconds() + expires_in if expires_in > 0 else 0,
            "account_id": str(token_payload.get("account_id") or profile.get("account_id") or ""),
        },
        "profile": profile,
        "updated_at": _now_epoch_seconds(),
    }


def _persist_token_response(token_payload: dict[str, Any], *, profile_id: str) -> dict[str, Any]:
    stored = _stored_openai_codex_auth_payload(token_payload, profile_id=profile_id)
    with _file_lock(OPENAI_CODEX_AUTH_PATH):
        store = _normalize_openai_codex_auth_store(_read_json_file_unlocked(OPENAI_CODEX_AUTH_PATH))
        store = _set_openai_codex_profile_in_store(store, profile_id=profile_id, payload=stored)
        _write_json_file_unlocked(OPENAI_CODEX_AUTH_PATH, store)
    return stored


def refresh_openai_codex_tokens(
    *,
    config: dict[str, Any] | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    resolved = _resolve_openai_codex_profile(config=config, profile_id=profile_id)
    bound_profile_id = resolved["profile_id"]
    with _file_lock(OPENAI_CODEX_AUTH_PATH):
        store = _normalize_openai_codex_auth_store(_read_json_file_unlocked(OPENAI_CODEX_AUTH_PATH))
        current = _openai_codex_profile_from_store(store, bound_profile_id)
        tokens = current.get("tokens") or {}
        refresh_token = str(tokens.get("refresh_token") or "").strip()
        if not refresh_token:
            raise RuntimeError(f"openai codex refresh token is missing for profile '{bound_profile_id}'")
        payload = _token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
            }
        )
        if "refresh_token" not in payload:
            payload["refresh_token"] = refresh_token
        if "account_id" not in payload and tokens.get("account_id"):
            payload["account_id"] = str(tokens.get("account_id") or "")
        stored = _stored_openai_codex_auth_payload(payload, profile_id=bound_profile_id)
        store = _set_openai_codex_profile_in_store(store, profile_id=bound_profile_id, payload=stored)
        _write_json_file_unlocked(OPENAI_CODEX_AUTH_PATH, store)
        return stored


def ensure_openai_codex_auth(
    *,
    config: dict[str, Any] | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    resolved = _resolve_openai_codex_profile(config=config, profile_id=profile_id)
    bound_profile_id = resolved["profile_id"]
    store = read_openai_codex_auth_file()
    payload = _openai_codex_profile_from_store(store, bound_profile_id)
    tokens = payload.get("tokens") or {}
    if not isinstance(tokens, dict) or not str(tokens.get("access_token") or "").strip():
        raise RuntimeError(f"openai codex oauth is not logged in for profile '{bound_profile_id}'")
    if _token_expired(tokens):
        payload = refresh_openai_codex_tokens(config=config, profile_id=bound_profile_id)
    return payload


def openai_codex_login_status(
    *,
    config: dict[str, Any] | None = None,
    profile_id: str | None = None,
    refresh_if_needed: bool = True,
) -> dict[str, Any]:
    binding = _openai_codex_binding(config)
    resolved_profile_id = _normalize_profile_id(profile_id) or binding["default_profile"]
    error = ""
    try:
        resolved_profile_id = _resolve_openai_codex_profile(
            config=config,
            profile_id=profile_id,
        )["profile_id"]
    except RuntimeError as exc:
        error = str(exc)

    store = read_openai_codex_auth_file()
    payload = _openai_codex_profile_from_store(store, resolved_profile_id) if resolved_profile_id else {}
    if refresh_if_needed and not error:
        tokens = payload.get("tokens") or {}
        if isinstance(tokens, dict) and str(tokens.get("access_token") or "").strip() and _token_expired(tokens):
            try:
                payload = refresh_openai_codex_tokens(config=config, profile_id=resolved_profile_id)
            except Exception as exc:
                error = str(exc)
    return _status_from_payload(
        payload,
        profile_id=resolved_profile_id,
        binding=binding,
        available_profiles=_available_openai_codex_profiles(store),
        error=error,
    )


def _code_verifier() -> str:
    return secrets.token_urlsafe(64)


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def _redirect_parts() -> tuple[str, int, str]:
    parsed = urllib.parse.urlparse(REDIRECT_URI)
    host = parsed.hostname or "localhost"
    port = int(parsed.port or 80)
    path = parsed.path or "/auth/callback"
    return host, port, path


class _OpenAICodexCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        _, _, callback_path = _redirect_parts()
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != callback_path:
            self._send_html(404, "Invalid callback", "This OAuth callback URL is not active.")
            return
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        error = str((params.get("error") or [""])[0]).strip()
        description = str((params.get("error_description") or [""])[0]).strip()
        code = str((params.get("code") or [""])[0]).strip()
        state = str((params.get("state") or [""])[0]).strip()
        if error:
            try:
                _complete_pending_login(error=description or error)
            except RuntimeError:
                pass
            self._send_html(400, "Login failed", description or error)
            return
        if not code or not state:
            try:
                _complete_pending_login(error="oauth callback is missing code or state")
            except RuntimeError:
                pass
            self._send_html(400, "Login failed", "The callback did not include a valid authorization code.")
            return
        try:
            _complete_pending_login(code=code, state=state)
        except Exception as exc:
            self._send_html(500, "Login failed", str(exc))
            return
        self._send_html(200, "Login complete", "OpenAI Codex OAuth login succeeded. You can return to the app.")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _send_html(self, status_code: int, title: str, message: str) -> None:
        body = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{title}</title></head><body>"
            f"<h1>{title}</h1><p>{message}</p></body></html>"
        ).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _ensure_callback_server() -> None:
    global _CALLBACK_SERVER, _CALLBACK_THREAD

    if _CALLBACK_SERVER is not None and _CALLBACK_THREAD is not None and _CALLBACK_THREAD.is_alive():
        return

    host, port, _ = _redirect_parts()
    try:
        server = ThreadingHTTPServer((host, port), _OpenAICodexCallbackHandler)
    except OSError as exc:
        raise RuntimeError(f"unable to bind OpenAI Codex callback server on {host}:{port}: {exc}") from exc
    thread = threading.Thread(target=server.serve_forever, name="openai-codex-oauth-callback", daemon=True)
    thread.start()
    _CALLBACK_SERVER = server
    _CALLBACK_THREAD = thread


def _complete_pending_login(*, code: str = "", state: str = "", error: str = "") -> None:
    with _PENDING_LOGIN_LOCK:
        pending = dict(_PENDING_LOGIN)
        _PENDING_LOGIN.clear()
    if not pending:
        raise RuntimeError("no pending OpenAI Codex login flow was found")
    if error:
        with _PENDING_LOGIN_LOCK:
            _PENDING_LOGIN.update(
                {
                    "profile_id": pending.get("profile_id") or DEFAULT_OPENAI_CODEX_PROFILE,
                    "last_error": error,
                    "expires_at": _now_epoch_seconds() + 60,
                }
            )
        raise RuntimeError(error)
    if state != str(pending.get("state") or ""):
        raise RuntimeError("OpenAI Codex login state mismatch")

    verifier = str(pending.get("code_verifier") or "").strip()
    if not verifier:
        raise RuntimeError("OpenAI Codex login verifier is missing")

    payload = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "client_id": CLIENT_ID,
        }
    )
    login_profile_id = _normalize_profile_id(pending.get("profile_id")) or DEFAULT_OPENAI_CODEX_PROFILE
    _persist_token_response(payload, profile_id=login_profile_id)


def _parse_openai_codex_callback_input(callback_input: str) -> dict[str, str]:
    text = str(callback_input or "").strip()
    if not text:
        raise RuntimeError("callback input is required")

    if text.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(text)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    elif text.startswith("/"):
        parsed = urllib.parse.urlparse(f"http://localhost{text}")
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    elif text.startswith("?") or "=" in text:
        params = urllib.parse.parse_qs(text.lstrip("?"), keep_blank_values=True)
    else:
        return {"code": text, "state": "", "error": "", "error_description": ""}

    return {
        "code": str((params.get("code") or [""])[0]).strip(),
        "state": str((params.get("state") or [""])[0]).strip(),
        "error": str((params.get("error") or [""])[0]).strip(),
        "error_description": str((params.get("error_description") or [""])[0]).strip(),
    }


def complete_openai_codex_login(
    callback_input: str,
    *,
    config: dict[str, Any] | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    resolved = _resolve_openai_codex_profile(config=config, profile_id=profile_id)
    bound_profile_id = resolved["profile_id"]
    params = _parse_openai_codex_callback_input(callback_input)
    error = str(params.get("error") or "").strip()
    description = str(params.get("error_description") or "").strip()
    code = str(params.get("code") or "").strip()
    state = str(params.get("state") or "").strip()

    if error:
        _complete_pending_login(error=description or error)

    if not code:
        raise RuntimeError("callback input did not include an authorization code")

    if not state:
        pending = _pending_login_snapshot(bound_profile_id)
        state = str(pending.get("state") or "").strip()
    if not state:
        raise RuntimeError("callback input did not include state and no pending login was found")

    _complete_pending_login(code=code, state=state)
    return openai_codex_login_status(config=config, profile_id=bound_profile_id, refresh_if_needed=False)


def start_openai_codex_login(
    *,
    config: dict[str, Any] | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    resolved = _resolve_openai_codex_profile(config=config, profile_id=profile_id)
    bound_profile_id = resolved["profile_id"]
    pending = _pending_login_snapshot()
    if pending:
        pending_profile = _normalize_profile_id(pending.get("profile_id")) or DEFAULT_OPENAI_CODEX_PROFILE
        if pending_profile != bound_profile_id:
            raise RuntimeError(
                f"another OpenAI Codex login flow is already pending for profile '{pending_profile}'"
            )
        return {
            "authorize_url": str(pending.get("authorize_url") or ""),
            "status": openai_codex_login_status(
                config=config,
                profile_id=bound_profile_id,
                refresh_if_needed=False,
            ),
        }

    _ensure_callback_server()
    verifier = _code_verifier()
    state = secrets.token_urlsafe(32)
    challenge = _code_challenge(verifier)
    authorize_params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": OPENAI_CODEX_OAUTH_ORIGINATOR,
    }
    authorize_url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(authorize_params)}"
    with _PENDING_LOGIN_LOCK:
        _PENDING_LOGIN.clear()
        _PENDING_LOGIN.update(
            {
                "profile_id": bound_profile_id,
                "state": state,
                "code_verifier": verifier,
                "authorize_url": authorize_url,
                "expires_at": _now_epoch_seconds() + 600,
                "last_error": "",
            }
        )
    return {
        "authorize_url": authorize_url,
        "status": openai_codex_login_status(
            config=config,
            profile_id=bound_profile_id,
            refresh_if_needed=False,
        ),
    }


def logout_openai_codex(
    *,
    config: dict[str, Any] | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    resolved = _resolve_openai_codex_profile(config=config, profile_id=profile_id)
    bound_profile_id = resolved["profile_id"]
    with _file_lock(OPENAI_CODEX_AUTH_PATH):
        store = _normalize_openai_codex_auth_store(_read_json_file_unlocked(OPENAI_CODEX_AUTH_PATH))
        store = _delete_openai_codex_profile_from_store(store, profile_id=bound_profile_id)
        _write_json_file_unlocked(OPENAI_CODEX_AUTH_PATH, store)
    with _PENDING_LOGIN_LOCK:
        if _normalize_profile_id(_PENDING_LOGIN.get("profile_id")) == bound_profile_id:
            _PENDING_LOGIN.clear()
    return openai_codex_login_status(config=config, profile_id=bound_profile_id, refresh_if_needed=False)


def remember_openai_codex_model(model: str, *, label: str | None = None, source: str = "verified") -> None:
    normalized_model = bare_openai_codex_model_name(model)
    if not normalized_model:
        return

    try:
        with _file_lock(OPENAI_CODEX_MODELS_CACHE_PATH):
            payload = _read_json_file_unlocked(OPENAI_CODEX_MODELS_CACHE_PATH)
            raw_models = payload.get("models") if isinstance(payload.get("models"), list) else []
            models_by_id: dict[str, dict[str, Any]] = {}

            for item in _KNOWN_OPENAI_CODEX_MODELS:
                models_by_id[_normalize_model_id(str(item.get("value") or ""))] = dict(item)
            for item in raw_models:
                if not isinstance(item, dict):
                    continue
                model_id = _normalize_model_id(str(item.get("value") or ""))
                if not model_id:
                    continue
                models_by_id[model_id] = {**models_by_id.get(model_id, {}), **item}

            entry = models_by_id.get(normalized_model, {})
            entry.update(
                {
                    "value": normalized_model,
                    "label": str(label or entry.get("label") or normalized_model),
                    "source": str(entry.get("source") or source),
                    "priority": int(entry.get("priority") or 999),
                    "seen_at": _now_epoch_seconds(),
                }
            )
            models_by_id[normalized_model] = entry
            _write_json_file_unlocked(
                OPENAI_CODEX_MODELS_CACHE_PATH,
                {
                    "models": list(models_by_id.values()),
                    "fetched_at": _now_epoch_seconds(),
                },
            )
    except (OSError, RuntimeError):
        return


def _openai_codex_model_label(model_id: str, display_name: str = "") -> str:
    candidate = str(display_name or "").strip() or model_id
    candidate = candidate.replace("gpt", "GPT", 1)
    candidate = candidate.replace("-codex", " Codex").replace("-mini", " Mini").replace("-max", " Max")
    candidate = candidate.replace("-", "-")
    return candidate


def _request_openai_codex_models(
    *,
    access_token: str,
    account_id: str,
    client_version: str,
) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"client_version": client_version})
    request = urllib.request.Request(
        f"{OPENAI_CODEX_MODELS_URL}?{query}",
        headers={
            **_openai_codex_request_headers(access_token=access_token, account_id=account_id),
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"openai codex models request failed: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"openai codex models request failed: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("openai codex models request returned invalid payload")
    models = payload.get("models") or []
    return models if isinstance(models, list) else []


def refresh_openai_codex_model_catalog(
    *,
    config: dict[str, Any] | None = None,
    profile_id: str | None = None,
    client_version: str | None = None,
) -> dict[str, Any]:
    auth_payload = ensure_openai_codex_auth(config=config, profile_id=profile_id)
    tokens = auth_payload.get("tokens") or {}
    if not isinstance(tokens, dict):
        raise RuntimeError("openai codex oauth token payload is invalid")
    access_token = str(tokens.get("access_token") or "").strip()
    account_id = str(tokens.get("account_id") or "").strip()
    if not access_token:
        raise RuntimeError("openai codex oauth access token is missing")

    remote_items = _request_openai_codex_models(
        access_token=access_token,
        account_id=account_id,
        client_version=str(client_version or OPENAI_CODEX_CLIENT_VERSION).strip() or OPENAI_CODEX_CLIENT_VERSION,
    )
    models_by_id: dict[str, dict[str, Any]] = {}
    for item in remote_items:
        if not isinstance(item, dict):
            continue
        model_id = _normalize_model_id(str(item.get("slug") or item.get("value") or ""))
        if not model_id or not bool(item.get("supported_in_api", True)):
            continue
        models_by_id[model_id] = {
            "value": model_id,
            "label": _openai_codex_model_label(model_id, str(item.get("display_name") or "")),
            "priority": int(item.get("priority") or 999),
            "source": "chatgpt_account",
            "visibility": str(item.get("visibility") or ""),
            "display_name": str(item.get("display_name") or ""),
            "description": str(item.get("description") or ""),
            "supported_in_api": bool(item.get("supported_in_api", True)),
            "minimal_client_version": str(item.get("minimal_client_version") or ""),
            "base_instructions": str(item.get("base_instructions") or ""),
            "prefer_websockets": bool(item.get("prefer_websockets", False)),
            "seen_at": _now_epoch_seconds(),
        }

    _write_openai_codex_models_cache(
        {
            "models": list(models_by_id.values()),
            "fetched_at": _now_epoch_seconds(),
            "source": "chatgpt_account",
            "client_version": str(client_version or OPENAI_CODEX_CLIENT_VERSION).strip() or OPENAI_CODEX_CLIENT_VERSION,
        }
    )
    return openai_codex_model_catalog(config=config, profile_id=profile_id, refresh_remote=False)


def _openai_codex_cached_model_map() -> dict[str, dict[str, Any]]:
    try:
        payload = read_openai_codex_models_cache()
    except (OSError, RuntimeError):
        payload = {}
    raw_models = payload.get("models") if isinstance(payload.get("models"), list) else []
    merged: dict[str, dict[str, Any]] = {}

    for item in _KNOWN_OPENAI_CODEX_MODELS:
        model_id = _normalize_model_id(str(item.get("value") or ""))
        if not model_id:
            continue
        merged[model_id] = dict(item)

    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = _normalize_model_id(str(item.get("value") or ""))
        if not model_id:
            continue
        merged[model_id] = {**merged.get(model_id, {}), **item}
    return merged


def openai_codex_model_metadata(
    model: str,
    *,
    config: dict[str, Any] | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    bare_model = bare_openai_codex_model_name(model)
    if not bare_model:
        return {}
    merged = _openai_codex_cached_model_map()
    if bare_model in merged:
        return dict(merged[bare_model])
    try:
        refresh_openai_codex_model_catalog(config=config, profile_id=profile_id)
    except Exception:
        return dict(merged.get(bare_model) or {})
    merged = _openai_codex_cached_model_map()
    return dict(merged.get(bare_model) or {})


def openai_codex_model_catalog(
    *,
    config: dict[str, Any] | None = None,
    profile_id: str | None = None,
    refresh_remote: bool = True,
) -> dict[str, Any]:
    discovery_mode = normalize_openai_codex_model_discovery(
        (config or {}).get("llm", {}).get("openai_codex", {}).get("model_discovery")
        if isinstance((config or {}).get("llm"), dict)
        else None
    )
    try:
        payload = read_openai_codex_models_cache()
    except (OSError, RuntimeError):
        payload = {}
    error = ""
    if refresh_remote and discovery_mode == "account_plus_cached":
        try:
            return refresh_openai_codex_model_catalog(
                config=config,
                profile_id=profile_id,
            )
        except Exception as exc:
            error = str(exc)
            try:
                payload = read_openai_codex_models_cache()
            except (OSError, RuntimeError):
                payload = {}

    merged = _openai_codex_cached_model_map()

    models = sorted(
        (
            {
                "value": openai_codex_model_ref(model_id),
                "label": str(item.get("label") or model_id),
                "priority": int(item.get("priority") or 999),
            }
            for model_id, item in merged.items()
        ),
        key=lambda item: (item["priority"], item["label"].lower(), item["value"].lower()),
    )
    options = [{"value": item["value"], "label": item["label"]} for item in models]

    return {
        "vendors": [{"value": "openai", "label": "OpenAI"}] if options else [],
        "modelsByVendor": {"openai": options} if options else {},
        "vendor_count": 1 if options else 0,
        "model_count": len(options),
        "loaded": True,
        "fetched_at": int(payload.get("fetched_at") or 0),
        "transport_default": DEFAULT_OPENAI_CODEX_TRANSPORT,
        "discovery_mode": discovery_mode,
        **({"error": error} if error else {}),
    }
