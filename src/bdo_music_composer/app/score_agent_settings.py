"""Optional model connection and Windows current-user credential storage."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from ipaddress import ip_address
import json
import os
from pathlib import Path
import re
import sys
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from bdo_common.atomic_io import atomic_write_bytes
from bdo_music_composer.core.project_paths import USER_DATA_DIR


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL_NAMES = {
    "deepseek-flash": "DeepSeek V4.1 Flash",
    "deepseek-v4-pro": "DeepSeek V4 Pro",
}
DEEPSEEK_MODELS = tuple(DEEPSEEK_MODEL_NAMES)
DEEPSEEK_REASONING_EFFORTS = ("low", "high", "max")
DEFAULT_MODEL = DEEPSEEK_MODELS[0]
DEFAULT_REASONING_EFFORT = "high"
_DEEPSEEK_FLASH_ALIASES = frozenset({
    "deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp",
})
MAX_BASE_URL_LENGTH = 2048
MAX_MODEL_LENGTH = 256
MAX_API_KEY_LENGTH = 2048
_PROFILE_LIMIT = 16 * 1024
_PROFILE_SCHEMA = "bdo.score_agent.connection.v1"
_PROFILE_REQUIRED = frozenset({"schema", "base_url", "model", "api_key"})
_ENVIRONMENT_FIELDS = ("BDO_AGENT_BASE_URL", "BDO_AGENT_MODEL", "BDO_AGENT_API_KEY")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_IPV6_AUTHORITY = re.compile(r"\[[0-9a-fA-F:.]+\](?::[0-9]+)?\Z")


def _loopback_host(host: str) -> bool:
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def normalize_base_url(value: str) -> str:
    """Use the provider base path with explicit TLS or literal loopback HTTP."""
    if not isinstance(value, str):
        raise ValueError("base_url")
    value = value.strip()
    if (
        not 0 < len(value) <= MAX_BASE_URL_LENGTH
        or any(char.isspace() or not char.isprintable() for char in value)
        or any(char in value for char in "\\?#")
    ):
        raise ValueError("base_url")
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        port = parsed.port
    except (ValueError, UnicodeError):
        raise ValueError("base_url") from None
    if (
        parsed.scheme not in {"https", "http"}
        or not host
        or "@" in parsed.netloc
        or "%" in parsed.netloc
        or parsed.netloc.endswith(":")
        or port == 0
        or (parsed.scheme == "http" and not _loopback_host(host))
    ):
        raise ValueError("base_url")
    if ":" in host:
        if not _IPV6_AUTHORITY.fullmatch(parsed.netloc):
            raise ValueError("base_url")
        try:
            host = f"[{ip_address(host)}]"
        except ValueError:
            raise ValueError("base_url") from None
    elif len(host) > 253 or not all(_HOST_LABEL.fullmatch(label) for label in host.split(".")):
        raise ValueError("base_url")
    default_port = 443 if parsed.scheme == "https" else 80
    authority = host if port in {None, default_port} else f"{host}:{port}"
    path = parsed.path.rstrip("/") or ("/" if parsed.path else "/v1")
    for suffix in ("/chat/completions", "/models"):
        if path.endswith(suffix):
            path = path.removesuffix(suffix).rstrip("/") or "/"
            break
    if parsed.scheme == "https" and authority == "api.deepseek.com" and path in {"/", "/v1"}:
        return DEFAULT_BASE_URL
    normalized = urlunsplit((parsed.scheme, authority, path, "", ""))
    if len(normalized) > MAX_BASE_URL_LENGTH:
        raise ValueError("base_url")
    return normalized


def is_loopback_base_url(base_url: str) -> bool:
    return _loopback_host(urlsplit(base_url).hostname or "")


def normalize_api_key(base_url: str, value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("api_key")
    key = value.strip()
    if (
        len(key) > MAX_API_KEY_LENGTH
        or any(not 33 <= ord(char) <= 126 for char in key)
        or (not key and not is_loopback_base_url(base_url))
    ):
        raise ValueError("api_key")
    return key


def canonical_model_id(base_url: str, model: str) -> str:
    return DEFAULT_MODEL if base_url == DEFAULT_BASE_URL and model in _DEEPSEEK_FLASH_ALIASES else model


@dataclass(frozen=True, slots=True)
class ModelConnection:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    thinking: bool = False
    reasoning_effort: str = DEFAULT_REASONING_EFFORT

    def __post_init__(self) -> None:
        base_url = normalize_base_url(self.base_url)
        if not isinstance(self.model, str):
            raise ValueError("model")
        model = self.model.strip()
        if not 0 < len(model) <= MAX_MODEL_LENGTH or not model.isprintable():
            raise ValueError("model")
        key = normalize_api_key(base_url, self.api_key)
        if type(self.thinking) is not bool:
            raise ValueError("thinking")
        if self.reasoning_effort not in DEEPSEEK_REASONING_EFFORTS:
            raise ValueError("reasoning_effort")
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "model", canonical_model_id(base_url, model))
        object.__setattr__(self, "api_key", key)
        if not self.is_official_deepseek:
            object.__setattr__(self, "thinking", False)
            object.__setattr__(self, "reasoning_effort", DEFAULT_REASONING_EFFORT)

    @property
    def is_loopback(self) -> bool:
        return is_loopback_base_url(self.base_url)

    @property
    def is_official_deepseek(self) -> bool:
        return self.base_url == DEFAULT_BASE_URL


_session_connection: ModelConnection | None = None
_session_loaded = False


def _reasoning_from_environment(environ: Mapping[str, str]) -> tuple[bool | None, str | None]:
    thinking = {"1": True, "0": False}.get(environ.get("BDO_AGENT_THINKING", ""))
    effort = environ.get("BDO_AGENT_REASONING_EFFORT", "").strip().lower()
    if thinking is None:
        if effort == "none":
            thinking = False
        elif effort in DEEPSEEK_REASONING_EFFORTS:
            thinking = True
    return thinking, effort if effort in DEEPSEEK_REASONING_EFFORTS else None


def model_connection_from_environment(environ: Mapping[str, str]) -> ModelConnection | None:
    if not any(name in environ for name in (*_ENVIRONMENT_FIELDS, "DEEPSEEK_API_KEY")):
        return None
    try:
        base = normalize_base_url(environ.get("BDO_AGENT_BASE_URL", DEFAULT_BASE_URL))
        key = environ.get("BDO_AGENT_API_KEY")
        if key is None:
            endpoint = urlsplit(base)
            deepseek_origin = endpoint.scheme == "https" and endpoint.netloc == "api.deepseek.com"
            key = environ.get("DEEPSEEK_API_KEY", "") if deepseek_origin else ""
        thinking, effort = _reasoning_from_environment(environ)
        model = environ.get("BDO_AGENT_MODEL", DEFAULT_MODEL)
        if thinking is None:
            thinking = model.strip() == "deepseek-reasoner"
        return ModelConnection(base, model, key, thinking, effort or DEFAULT_REASONING_EFFORT)
    except ValueError:
        return None


def model_connection_path() -> Path:
    return USER_DATA_DIR / "score_agent_connection.dpapi"


def can_remember_model_connection() -> bool:
    return sys.platform == "win32"


def _dpapi(data: bytes, *, encrypt: bool) -> bytes:
    if not can_remember_model_connection():
        raise OSError("Windows credential storage is unavailable")

    import ctypes
    from ctypes import wintypes

    byte_pointer = ctypes.POINTER(ctypes.c_ubyte)

    class DataBlob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", byte_pointer)]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    operation = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    description_type = wintypes.LPCWSTR if encrypt else ctypes.POINTER(wintypes.LPWSTR)
    blob_pointer = ctypes.POINTER(DataBlob)
    operation.argtypes = [
        blob_pointer, description_type, blob_pointer, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, blob_pointer,
    ]
    operation.restype = wintypes.BOOL
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = DataBlob(len(data), buffer)
    target = DataBlob()
    cryptprotect_ui_forbidden = 0x01
    try:
        if not operation(source, None, None, None, None, cryptprotect_ui_forbidden, target):
            raise OSError("Windows could not access the saved model connection")
        if not 0 < target.size <= _PROFILE_LIMIT:
            raise OSError("Saved model connection exceeds its size limit")
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.memset(buffer, 0, len(data))
        if target.data:
            ctypes.memset(target.data, 0, target.size)
            local_free(target.data)


def load_saved_model_connection(path: Path | None = None) -> ModelConnection | None:
    if not can_remember_model_connection():
        return None
    try:
        with (path or model_connection_path()).open("rb") as stream:
            blob = stream.read(_PROFILE_LIMIT + 1)
        if not 0 < len(blob) <= _PROFILE_LIMIT:
            return None
        profile = json.loads(_dpapi(blob, encrypt=False))
        if not isinstance(profile, dict) or profile.keys() - {"thinking", "reasoning_effort"} != _PROFILE_REQUIRED:
            return None
        if profile["schema"] != _PROFILE_SCHEMA:
            return None
        model = profile["model"]
        return ModelConnection(
            profile["base_url"], model, profile["api_key"],
            profile.get("thinking", model == "deepseek-reasoner"),
            profile.get("reasoning_effort", DEFAULT_REASONING_EFFORT),
        )
    except (OSError, ValueError, RecursionError):
        return None


def load_model_connection(
    path: Path | None = None, *, environ: Mapping[str, str] | None = None,
) -> ModelConnection | None:
    environment = os.environ if environ is None else environ
    if any(name in environment for name in _ENVIRONMENT_FIELDS):
        return model_connection_from_environment(environment)
    saved = load_saved_model_connection(path)
    if saved is not None:
        thinking, effort = _reasoning_from_environment(environment)
        if thinking is None and effort is None:
            return saved
        return replace(
            saved, thinking=saved.thinking if thinking is None else thinking,
            reasoning_effort=saved.reasoning_effort if effort is None else effort,
        )
    return model_connection_from_environment(environment)


def get_session_model_connection() -> ModelConnection | None:
    """Lazy model connection for the current GUI process."""
    if not _session_loaded:
        set_session_model_connection(load_model_connection())
    return _session_connection


def set_session_model_connection(connection: ModelConnection | None) -> None:
    global _session_connection, _session_loaded
    _session_connection = connection
    _session_loaded = True


def save_model_connection(connection: ModelConnection, path: Path | None = None) -> None:
    profile = {
        "schema": _PROFILE_SCHEMA,
        "base_url": connection.base_url,
        "model": connection.model,
        "api_key": connection.api_key,
    }
    if connection.thinking:
        profile["thinking"] = True
    if connection.reasoning_effort != DEFAULT_REASONING_EFFORT:
        profile["reasoning_effort"] = connection.reasoning_effort
    payload = json.dumps(profile, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    atomic_write_bytes(path or model_connection_path(), _dpapi(payload, encrypt=True))


def clear_saved_model_connection(path: Path | None = None) -> None:
    (path or model_connection_path()).unlink(missing_ok=True)
