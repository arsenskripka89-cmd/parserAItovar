import json
from pathlib import Path
from openai import OpenAI

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

    return OpenAI(api_key=key)
