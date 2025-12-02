from __future__ import annotations

import json
from typing import Dict

from selectolax.parser import HTMLParser

from config import get_openai_client
from parser_engine.scraper import DEFAULT_RULES, fetch_html


def _heuristic_rules(html: str, previous_rules: Dict[str, str] | None = None) -> Dict[str, str]:
    parser = HTMLParser(html)
    candidate_item = None
    for selector in [".product", ".product-card", "[class*='product']", "article"]:
        nodes = parser.css(selector)
        if len(nodes) > 3:
            candidate_item = selector
            break
    if not candidate_item:
        candidate_item = (previous_rules or {}).get("product_item", DEFAULT_RULES["product_item"])

    name_selector = (previous_rules or {}).get("name_selector", DEFAULT_RULES["name_selector"])
    for selector in ["h2", "h3", "[itemprop='name']"]:
        node = parser.css_first(selector)
        if node:
            name_selector = selector
            break

    price_selector = (previous_rules or {}).get("price_selector", DEFAULT_RULES["price_selector"])
    for selector in [".price", "[itemprop='price']", "[class*='price']"]:
        node = parser.css_first(selector)
        if node and any(ch.isdigit() for ch in node.text()):
            price_selector = selector
            break

    url_selector = (previous_rules or {}).get("url_selector", DEFAULT_RULES["url_selector"])
    for selector in ["a.product-link", "a[href*='product']", "a"]:
        node = parser.css_first(selector)
        if node and node.attributes.get("href"):
            url_selector = selector
            break

    category_link = (previous_rules or {}).get("category_link", DEFAULT_RULES["category_link"])

    return {
        "product_item": candidate_item,
        "name_selector": name_selector,
        "price_selector": price_selector,
        "url_selector": url_selector,
        "category_link": category_link,
    }


def _request_ai_rules(html: str, old_rules: Dict[str, str] | None = None) -> Dict[str, str]:
    try:
        client = get_openai_client()
    except Exception:
        return _heuristic_rules(html, old_rules)

    system_prompt = (
        "Ти допомагаєш визначати CSS-селектори для парсингу товарів. "
        "Поверни лише JSON з ключами product_item, name_selector, price_selector, url_selector, category_link."
    )
    user_prompt = (
        "Аналізуй HTML конкурента і поверни селектори. Використовуй старі правила як підказку: "
        f"{json.dumps(old_rules or {}, ensure_ascii=False)}. Відповідай тільки JSON.\n" + html[:6000]
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        response = completion.choices[0].message.content or ""
        parsed = json.loads(response)
        cleaned = {key: str(value) for key, value in parsed.items() if key in DEFAULT_RULES}
        return {**DEFAULT_RULES, **cleaned}
    except Exception:
        return _heuristic_rules(html, old_rules)


async def generate_rules(url: str) -> Dict[str, str]:
    """Generate initial CSS selectors for a competitor page."""
    html = await fetch_html(url)
    return _request_ai_rules(html, None)


def fix_rules(html: str, old_rules: Dict[str, str]) -> Dict[str, str]:
    """Recover scraping rules when the scraper breaks."""
    return _request_ai_rules(html, old_rules)
