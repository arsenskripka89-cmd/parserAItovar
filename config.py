import json
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI, OpenAI

CONFIG_FILE = Path(__file__).resolve().parent / "config.json"


def get_openai_client():
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        raise RuntimeError("Не знайдено config.json")

    keys = cfg.get("openai_keys", [])
    key = keys[0].get("api_key", "").strip() if keys else ""
    if not key:
        raise RuntimeError("OpenAI API key не встановлено")

    api_key = _resolve_api_key()
    return OpenAI(api_key=api_key)


def get_async_openai_client() -> AsyncOpenAI:
    """Return an initialized asynchronous OpenAI client using the configured API key."""

    api_key = _resolve_api_key()
    return AsyncOpenAI(api_key=api_key)
