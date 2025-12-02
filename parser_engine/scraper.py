from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser


class ScraperError(Exception):
    """Raised when scraping fails because of invalid selectors or missing data."""


DEFAULT_RULES = {
    "product_item": ".product-card,.product,.product-item",
    "name_selector": ".product-title,.title,h2,h3",
    "price_selector": ".price,.product-price",
    "url_selector": "a",
    "category_link": "nav a, .menu a, .catalog a",
}


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


def _validate_selector(parser: HTMLParser, selector: str) -> List[HTMLParser]:
    try:
        return parser.css(selector)
    except Exception as exc:  # pragma: no cover - selectolax specific errors
        raise ScraperError(f"Invalid selector: {selector}") from exc


def _get_first_text(node: Optional[HTMLParser], selectors: List[str]) -> str:
    if not node:
        return ""
    for selector in selectors:
        try:
            target = node.css_first(selector)
        except Exception as exc:  # pragma: no cover - selectolax specific errors
            raise ScraperError(f"Invalid selector: {selector}") from exc
        if target and target.text():
            return target.text().strip()
    return ""


def _find_link(node: Optional[HTMLParser], selectors: List[str]) -> str:
    if not node:
        return ""
    for selector in selectors:
        try:
            target = node.css_first(selector)
        except Exception as exc:  # pragma: no cover - selectolax specific errors
            raise ScraperError(f"Invalid selector: {selector}") from exc
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


def parse_products(html: str, base_url: str, rules: Dict[str, str]) -> List[ParsedProduct]:
    parser = HTMLParser(html)
    item_selector = rules.get("product_item") or DEFAULT_RULES["product_item"]
    name_selectors = (rules.get("name_selector") or DEFAULT_RULES["name_selector"]).split(",")
    price_selectors = (rules.get("price_selector") or DEFAULT_RULES["price_selector"]).split(",")
    url_selectors = (rules.get("url_selector") or DEFAULT_RULES["url_selector"]).split(",")

    nodes = _validate_selector(parser, item_selector)
    if not nodes:
        raise ScraperError("No products found with provided selectors")

    products: List[ParsedProduct] = []
    for node in nodes:
        name = _get_first_text(node, name_selectors)
        if not name:
            continue
        price_text = _get_first_text(node, price_selectors)
        price_value = _parse_price(price_text)
        link = _find_link(node, url_selectors)
        full_url = urljoin(base_url, link) if link else base_url
        products.append(
            ParsedProduct(
                name=name,
                url=full_url,
                price=price_value,
                raw_price=price_text or None,
            )
        )

    if not products:
        raise ScraperError("Products could not be parsed with current rules")
    return products


def parse_categories(html: str, base_url: str, rules: Dict[str, str]) -> List[Category]:
    parser = HTMLParser(html)
    selector = rules.get("category_link") or DEFAULT_RULES["category_link"]
    links: Dict[str, str] = {}
    for rule in selector.split(","):
        candidates = _validate_selector(parser, rule.strip())
        for link in candidates:
            href = link.attributes.get("href") or ""
            name = link.text().strip()
            if not href or len(name) < 3:
                continue
            full_url = urljoin(base_url, href)
            links[full_url] = name
        if links:
            break

    return [Category(name=value, url=key) for key, value in links.items()]


async def scrape_products(url: str, rules: Dict[str, str]) -> List[ParsedProduct]:
    html = await fetch_html(url)
    return parse_products(html, url, rules)


async def scrape_categories(url: str, rules: Dict[str, str]) -> List[Category]:
    html = await fetch_html(url)
    categories = parse_categories(html, url, rules)
    return categories


async def scrape_multiple_categories(category_urls: List[str], rules: Dict[str, str]) -> Dict[str, List[ParsedProduct]]:
    async def _scrape(url: str) -> tuple[str, List[ParsedProduct]]:
        try:
            items = await scrape_products(url, rules)
            return url, items
        except ScraperError:
            return url, []

    tasks = [_scrape(url) for url in category_urls]
    results = await asyncio.gather(*tasks)
    return {url: items for url, items in results}
