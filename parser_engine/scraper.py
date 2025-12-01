from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser


@dataclass
class Category:
    name: str
    url: str


@dataclass
class ParsedProduct:
    name: str
    url: str
    price: Optional[float] = None
    raw_price: str | None = None


async def fetch_html(url: str) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def _get_first_text(node: Optional[HTMLParser], selectors: List[str]) -> str:
    if not node:
        return ""
    for selector in selectors:
        target = node.css_first(selector)
        if target and target.text():
            return target.text().strip()
    return ""


def _find_link(node: Optional[HTMLParser], selectors: List[str]) -> str:
    if not node:
        return ""
    for selector in selectors:
        target = node.css_first(selector)
        if target:
            href = target.attributes.get("href")
            if href:
                return href
    return ""


def _parse_price(text: str) -> Optional[float]:
    normalized = "".join(ch for ch in text if ch.isdigit() or ch in ",.")
    normalized = normalized.replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


async def discover_categories(root_url: str, rules: Dict[str, str] | None = None) -> List[Category]:
    html = await fetch_html(root_url)
    parser = HTMLParser(html)

    selectors = []
    if rules and rules.get("category_link"):
        selectors.append(rules["category_link"])
    selectors.extend(
        [
            "nav a",
            "ul a",
            "header a",
            "a[href*='catalog']",
            "a[href*='category']",
        ]
    )

    links: Dict[str, str] = {}
    for selector in selectors:
        for link in parser.css(selector):
            href = link.attributes.get("href") or ""
            name = link.text().strip()
            if not href or len(name) < 3:
                continue
            full_url = urljoin(root_url, href)
            links[full_url] = name
        if links:
            break

    return [Category(name=value, url=key) for key, value in links.items()]


async def scrape_category(category_url: str, rules: Dict[str, str]) -> List[ParsedProduct]:
    html = await fetch_html(category_url)
    parser = HTMLParser(html)

    item_selector = rules.get("product_item") or ".product, .product-card, .product-item"
    name_selectors = rules.get("name_selector", ".product-title,.title,h2,h3").split(",")
    price_selectors = rules.get("price_selector", ".price,.product-price").split(",")
    url_selectors = rules.get("url_selector", "a").split(",")

    products: List[ParsedProduct] = []
    for node in parser.css(item_selector):
        name = _get_first_text(node, name_selectors)
        if not name:
            continue
        price_text = _get_first_text(node, price_selectors)
        price_value = _parse_price(price_text)
        link = _find_link(node, url_selectors)
        full_url = urljoin(category_url, link) if link else category_url
        products.append(
            ParsedProduct(name=name, url=full_url, price=price_value, raw_price=price_text or None)
        )

    return products


async def scrape_multiple_categories(category_urls: List[str], rules: Dict[str, str]) -> Dict[str, List[ParsedProduct]]:
    async def _scrape(url: str) -> tuple[str, List[ParsedProduct]]:
        try:
            items = await scrape_category(url, rules)
            return url, items
        except Exception:
            return url, []

    tasks = [_scrape(url) for url in category_urls]
    results = await asyncio.gather(*tasks)
    return {url: items for url, items in results}
