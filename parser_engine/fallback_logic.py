from __future__ import annotations

from typing import Callable, Dict, List, Tuple
from urllib.parse import urlparse

from parser_engine import category_ai, self_heal
from parser_engine.rule_detector_ai import DEFAULT_RULES
from parser_engine.scraper import Category, ParsedProduct, ScraperError, fetch_html, scrape_categories


def _find_or_create(nodes: List[Dict[str, object]], name: str) -> Dict[str, object]:
    for node in nodes:
        if node.get("name") == name:
            return node
    new_node: Dict[str, object] = {"name": name, "url": None, "children": []}
    nodes.append(new_node)
    return new_node


def build_category_groups(categories: List[Category]) -> List[Dict[str, object]]:
    groups: Dict[str, Dict[str, object]] = {}

    for cat in categories or []:
        if cat is None:
            continue

        cat_data = (
            cat
            if isinstance(cat, dict)
            else {"name": getattr(cat, "name", None), "url": getattr(cat, "url", None)}
        )

        url = str(cat_data.get("url", "") or "").strip()
        name = str(cat_data.get("name", "") or "").strip()

        if not url or not name:
            continue

        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]

        if parts and parts[0] in {"ru", "ua", "uk"}:
            parts = parts[1:]

        group_key = parts[0] if parts else "Інше"
        remaining_parts = parts[1:]

        if group_key not in groups:
            groups[group_key] = {"group_name": group_key, "items": []}

        current_level = groups[group_key]["items"]

        for part in remaining_parts:
            current_node = _find_or_create(current_level, part)
            current_level = current_node.setdefault("children", [])  # type: ignore[assignment]
        current_level.append({"name": name, "url": url, "children": []})

    return sorted(groups.values(), key=lambda item: str(item.get("group_name", "")))


async def collect_categories_with_fallback(root_url: str, rules: Dict[str, str]) -> List[Dict[str, object]]:
    categories: List[Category] | None = None
    try:
        categories = await scrape_categories(root_url, rules)
    except ScraperError:
        categories = []

    groups: List[Dict[str, object]] = []
    if categories:
        groups = build_category_groups(categories)
        if groups:
            return groups

    html = await fetch_html(root_url)
    ai_groups = category_ai.detect_category_tree(html)
    return ai_groups


async def scrape_products_with_self_heal(
    category_url: str,
    rules: Dict[str, str],
    save_rules: Callable[[Dict[str, str]], None] | None = None,
) -> Tuple[List[ParsedProduct], Dict[str, str]]:
    items, updated_rules = await self_heal.try_scrape(category_url, rules)
    if save_rules and updated_rules != rules:
        save_rules({**DEFAULT_RULES, **updated_rules})
    return items, updated_rules
