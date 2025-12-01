from __future__ import annotations

import json
from typing import Dict

from selectolax.parser import HTMLParser

from parser_engine.scraper import fetch_html
from config import get_openai_client


DEFAULT_RULES = {
    "product_item": ".product-card,.product,.product-item",
    "name_selector": ".product-title,.title,h2,h3",
    "price_selector": ".price,.product-price",
    "url_selector": "a",
    "category_link": "nav a, .menu a, .catalog a",
}


def _heuristic_rules(html: str) -> Dict[str, str]:
    parser = HTMLParser(html)
    candidate_item = None
    for selector in [".product", ".product-card", "[class*='product']", "article"]:
        nodes = parser.css(selector)
        if len(nodes) > 3:
            candidate_item = selector
            break
    if not candidate_item:
        candidate_item = DEFAULT_RULES["product_item"]

    name_selector = DEFAULT_RULES["name_selector"]
    for selector in ["h2", "h3", "[itemprop='name']"]:
        node = parser.css_first(selector)
        if node:
            name_selector = selector
            break

    price_selector = DEFAULT_RULES["price_selector"]
    for selector in [".price", "[itemprop='price']", "[class*='price']"]:
        node = parser.css_first(selector)
        if node and any(ch.isdigit() for ch in node.text()):
            price_selector = selector
            break

    url_selector = DEFAULT_RULES["url_selector"]
    for selector in ["a.product-link", "a[href*='product']", "a"]:
        node = parser.css_first(selector)
        if node and node.attributes.get("href"):
            url_selector = selector
            break

    category_link = DEFAULT_RULES["category_link"]

    return {
        "product_item": candidate_item,
        "name_selector": name_selector,
        "price_selector": price_selector,
        "url_selector": url_selector,
        "category_link": category_link,
    }


def _request_ai_rules(html: str) -> Dict[str, str]:
    try:
        client = get_openai_client()
    except Exception:
        return _heuristic_rules(html)

    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ти допомагаєш визначати CSS-селектори для парсингу товарів. "
                        "Поверни валідний JSON з ключами product_item, name_selector, price_selector, url_selector, category_link."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Аналізуй HTML конкурентного магазину і поверни селектори для товарних карток. "
                        "Відповідай тільки JSON.\n" + html[:6000]
                    ),
                },
            ],
        )
        response = completion.choices[0].message.content or ""
        parsed = json.loads(response)
        cleaned = {key: str(value) for key, value in parsed.items() if key in DEFAULT_RULES}
        return {**DEFAULT_RULES, **cleaned}
    except Exception:
        return _heuristic_rules(html)


async def detect_rules_for_url(url: str) -> Dict[str, str]:
    html = await fetch_html(url)
    return _request_ai_rules(html)
