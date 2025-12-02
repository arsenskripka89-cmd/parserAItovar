from __future__ import annotations

import json
from typing import Dict, List

from selectolax.parser import HTMLParser

from config import get_openai_client


CategoryGroup = Dict[str, object]

MAX_PROMPT_CHARS = 6000


def _heuristic_category_tree(html: str) -> List[CategoryGroup]:
    parser = HTMLParser(html)
    groups: List[CategoryGroup] = []
    collected: Dict[str, Dict[str, object]] = {}
    for selector in ["nav a", "ul a", "header a", "a[href*='catalog']", "a[href*='category']"]:
        try:
            links = parser.css(selector)
        except Exception:
            continue
        for link in links:
            href = link.attributes.get("href") or ""
            name = link.text().strip()
            if not href or len(name) < 3:
                continue
            group = collected.setdefault("Каталог", {"group_name": "Каталог", "items": []})
            group_items = group["items"]  # type: ignore[assignment]
            group_items.append({"name": name, "url": href, "children": []})
        if collected:
            break
    if collected:
        groups = list(collected.values())
    return groups


def _normalize_groups(raw: object) -> List[CategoryGroup]:
    normalized: List[CategoryGroup] = []
    if not isinstance(raw, list):
        return normalized

    for group in raw:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("group_name", "") or "").strip() or "Каталог"
        items = group.get("items", [])
        normalized_items: List[Dict[str, object]] = []

        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "") or "").strip()
                url = str(item.get("url", "") or "").strip()
                if not name:
                    continue
                normalized_items.append({"name": name, "url": url, "children": []})

        if normalized_items:
            normalized.append({"group_name": group_name, "items": normalized_items})

    return normalized


def _parse_ai_response(content: str) -> List[CategoryGroup]:
    try:
        parsed = json.loads(content)
    except Exception:
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(content[start : end + 1])
            except Exception:
                return []
        else:
            return []

    return _normalize_groups(parsed)


def detect_category_tree(html: str) -> List[CategoryGroup]:
    try:
        client = get_openai_client()
    except Exception:
        return _heuristic_category_tree(html)

    prompt_prefix = (
        "Проаналізуй HTML сторінки та поверни лише JSON масив з групами категорій. "
        "Формат: [{group_name, items:[{name,url,children:[]}] }]. Без пояснень.\n"
    )
    available_len = max(0, MAX_PROMPT_CHARS - len(prompt_prefix))
    prompt = prompt_prefix + html[:available_len]

    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Ти допомагаєш будувати дерево категорій конкурентів. Відповідай лише JSON."},
                {"role": "user", "content": prompt},
            ],
        )
        content = completion.choices[0].message.content or "[]"
        parsed = _parse_ai_response(content)
        if parsed:
            return parsed
    except Exception:
        return _heuristic_category_tree(html)

    return _heuristic_category_tree(html)
