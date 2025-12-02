from __future__ import annotations

import json
from typing import Dict, List

from selectolax.parser import HTMLParser

from config import get_openai_client


CategoryGroup = Dict[str, object]


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


def detect_category_tree(html: str) -> List[CategoryGroup]:
    try:
        client = get_openai_client()
    except Exception:
        return _heuristic_category_tree(html)

    prompt = (
        "Проаналізуй HTML сторінки та поверни лише JSON масив з групами категорій. "
        "Формат: [{group_name, items:[{name,url,children:[]}] }]. Без пояснень.\n" + html[:6000]
    )

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
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return parsed  # type: ignore[return-value]
    except Exception:
        return _heuristic_category_tree(html)

    return _heuristic_category_tree(html)
