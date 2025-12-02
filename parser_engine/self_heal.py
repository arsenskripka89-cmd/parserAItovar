from __future__ import annotations

from typing import Dict, List, Tuple

from parser_engine import rule_detector_ai
from parser_engine.scraper import ParsedProduct, ScraperError, fetch_html, parse_products, scrape_products


async def try_scrape(category_url: str, rules: Dict[str, str]) -> Tuple[List[ParsedProduct], Dict[str, str]]:
    """Try classical scraper first; if it fails, repair rules via AI and retry."""
    try:
        items = await scrape_products(category_url, rules)
        return items, rules
    except ScraperError:
        html = await fetch_html(category_url)
        new_rules = rule_detector_ai.fix_rules(html, rules)
        fixed_items = parse_products(html, category_url, new_rules)
        return fixed_items, new_rules
