import json
import os
from pathlib import Path
from typing import Dict, Optional

from openai import AsyncOpenAI, OpenAI

CONFIG_FILE = Path(__file__).resolve().parent / "config.json"


def _load_config() -> Dict[str, object]:
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _resolve_api_key(preferred_id: Optional[str] = None) -> str:
    """Витягти API ключ у пріоритеті: змінна оточення → активний ключ → перший у списку."""

    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key

    cfg = _load_config()
    keys = cfg.get("openai_keys", []) if isinstance(cfg, dict) else []
    active_id = preferred_id or (cfg.get("active_key_id") if isinstance(cfg, dict) else None)

    if isinstance(keys, list) and keys:
        if active_id:
            for item in keys:
                if str(item.get("id")) == str(active_id):
                    key_value = str(item.get("api_key", "")).strip()
                    if key_value:
                        return key_value

        first_key = str(keys[0].get("api_key", "")).strip()
        if first_key:
            return first_key

    raise RuntimeError("OpenAI API key не встановлено")


def get_openai_client(preferred_id: Optional[str] = None) -> OpenAI:
    api_key = _resolve_api_key(preferred_id)
    return OpenAI(api_key=api_key)


def get_async_openai_client(preferred_id: Optional[str] = None) -> AsyncOpenAI:
    """Return an initialized asynchronous OpenAI client using the configured API key."""

    api_key = _resolve_api_key(preferred_id)
    return AsyncOpenAI(api_key=api_key)
