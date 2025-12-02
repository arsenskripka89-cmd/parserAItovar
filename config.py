"""Configuration utilities for OpenAI client initialization."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI, OpenAI

CONFIG_FILE = Path(__file__).with_name("config.json")


def _load_api_key_from_env() -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    return api_key or None


def _load_api_key_from_file() -> Optional[str]:
    if not CONFIG_FILE.exists():
        return None

    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    api_key = str(data.get("openai_api_key", "")).strip()
    return api_key or None


def _resolve_api_key() -> str:
    api_key = _load_api_key_from_env() or _load_api_key_from_file()
    if not api_key:
        raise RuntimeError(
            "OpenAI API ключ не налаштований. Заповни його в config.json або встанови змінну середовища OPENAI_API_KEY."
        )
    return api_key


def get_openai_client() -> OpenAI:
    """Return an initialized OpenAI client using the configured API key."""

    api_key = _resolve_api_key()
    return OpenAI(api_key=api_key)


def get_async_openai_client() -> AsyncOpenAI:
    """Return an initialized asynchronous OpenAI client using the configured API key."""

    api_key = _resolve_api_key()
    return AsyncOpenAI(api_key=api_key)
