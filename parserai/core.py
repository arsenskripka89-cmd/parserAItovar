"""Core utilities for self-healing product parsers.

The module is intentionally dependency-free so it can run in minimal
sandboxes. It implements lightweight HTML traversal, heuristic selector
analysis, and utilities to create parsing code snippets.
"""

from __future__ import annotations

import dataclasses
import json
import re
import string
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional


# --------------------------- HTML tree utilities ---------------------------


@dataclass
class Node:
    tag: str
    attrs: Dict[str, str]
    children: List["Node"]
    text: str = ""
    parent: Optional["Node"] = None

    def all_text(self) -> str:
        parts = [self.text]
        for child in self.children:
            parts.append(child.all_text())
        return "".join(parts)


class SimpleHTMLParser(HTMLParser):
    """Convert HTML into a navigable tree of :class:`Node` objects."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node(tag="document", attrs={}, children=[])
        self.current = self.root

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]):
        attrs_dict = {name: (value or "") for name, value in attrs}
        node = Node(tag=tag, attrs=attrs_dict, children=[], text="", parent=self.current)
        self.current.children.append(node)
        self.current = node

    def handle_endtag(self, tag: str):
        if self.current.parent is not None:
            self.current = self.current.parent

    def handle_data(self, data: str):
        if data.strip():
            self.current.text += data


def parse_html(html: str) -> Node:
    parser = SimpleHTMLParser()
    parser.feed(html)
    return parser.root


# --------------------------- Selector matching ----------------------------


def _parse_selector_token(token: str) -> Dict[str, Any]:
    tag = None
    classes: List[str] = []
    element_id = None
    attrs: Dict[str, str] = {}

    attr_match = re.findall(r"\[([^=\]]+)=\"?([^\]]+)\"?\]", token)
    if attr_match:
        for name, value in attr_match:
            attrs[name] = value
        token = re.sub(r"\[[^\]]+\]", "", token)

    while token.startswith("."):
        classes.append(token[1:])
        token = ""

    if token.startswith("#"):
        element_id = token[1:]
        token = ""

    if "." in token:
        parts = token.split(".")
        tag = parts[0]
        classes.extend(parts[1:])
    elif token:
        tag = token

    return {"tag": tag, "classes": classes, "id": element_id, "attrs": attrs}


def _matches_token(node: Node, token: str) -> bool:
    if node.tag == "document":
        return False
    spec = _parse_selector_token(token)
    if spec["tag"] and node.tag != spec["tag"]:
        return False
    if spec["id"] and node.attrs.get("id") != spec["id"]:
        return False
    for cls in spec["classes"]:
        class_attr = node.attrs.get("class", "")
        if cls not in class_attr.split():
            return False
    for attr, value in spec["attrs"].items():
        if node.attrs.get(attr) != value:
            return False
    return True


def _descendant_matches(node: Node, tokens: List[str], index: int) -> Optional[Node]:
    if index >= len(tokens):
        return None
    matches: List[Node] = []
    for child in node.children:
        if _matches_token(child, tokens[index]):
            if index == len(tokens) - 1:
                return child
            deeper = _descendant_matches(child, tokens, index + 1)
            if deeper:
                return deeper
        nested = _descendant_matches(child, tokens, index)
        if nested:
            matches.append(nested)
    return matches[0] if matches else None


def select_first(root: Node, selector: str) -> Optional[Node]:
    selector = selector.strip()
    if not selector:
        return None
    tokens = [t for t in selector.split() if t]
    return _descendant_matches(root, tokens, 0)


# ----------------------- Heuristic selector analysis ----------------------


@dataclass
class ParsingRules:
    price_clean: str = "strip non-digit characters and convert to float"
    image_fix: str = "urljoin with page origin for relative URLs"


@dataclass
class ParsingAlgorithm:
    selectors: Dict[str, str]
    rules: ParsingRules
    meta: Dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {
                "selectors": self.selectors,
                "rules": dataclasses.asdict(self.rules),
                "meta": self.meta,
            },
            ensure_ascii=False,
        )


KEYWORDS = {
    "title": ["title", "name", "product-title", "product_name", "product-name"],
    "price": ["price", "amount", "cost", "value"],
    "description": ["description", "details", "product-description"],
    "images": ["image", "photo", "gallery", "product-image"],
    "attributes": ["spec", "feature", "detail", "attribute", "info"],
}


def _score_node(node: Node, keywords: List[str]) -> int:
    class_attr = node.attrs.get("class", "")
    score = 0
    for kw in keywords:
        if kw in class_attr:
            score += 3
        if kw in node.tag:
            score += 2
        if kw in node.attrs.get("id", ""):
            score += 4
    if node.tag.startswith("h") and node.tag[1:].isdigit():
        score += 1
    return score


def _find_best_selector(root: Node, field: str) -> str:
    best: Optional[tuple[int, str]] = None
    keywords = KEYWORDS.get(field, [])

    def visit(node: Node, path: List[str]):
        nonlocal best
        if node.tag == "document":
            for child in node.children:
                visit(child, [])
            return
        token = node.tag
        node_classes = node.attrs.get("class", "").split()
        if node_classes:
            token = f"{token}.{' .'.join(node_classes)}" if False else f"{token}.{'.'.join(node_classes)}"
        if node.attrs.get("id"):
            token = f"#{node.attrs['id']}"
        score = _score_node(node, keywords)
        if field == "price" and re.search(r"[0-9]+", node.all_text()):
            score += 2
        if field == "images" and node.tag == "img" and node.attrs.get("src"):
            score += 4
        if best is None or score > best[0]:
            best = (score, token)
        for child in node.children:
            visit(child, path + [token])

    visit(root, [])
    return best[1] if best else ""


DEFAULT_META = {"confidence": 0.6, "warnings": []}


def analyze_html(html: str) -> ParsingAlgorithm:
    root = parse_html(html)
    selectors = {
        "title": _find_best_selector(root, "title"),
        "price": _find_best_selector(root, "price"),
        "description": _find_best_selector(root, "description"),
        "images": _find_best_selector(root, "images"),
        "attributes": _find_best_selector(root, "attributes"),
    }
    meta = dict(DEFAULT_META)
    meta["warnings"] = [key for key, val in selectors.items() if not val]
    return ParsingAlgorithm(selectors=selectors, rules=ParsingRules(), meta=meta)


# -------------------------- Parsing with algorithm ------------------------


def _extract_text(node: Optional[Node]) -> str:
    return node.all_text().strip() if node else ""


def _extract_image_sources(node: Optional[Node]) -> List[str]:
    if not node:
        return []
    sources: List[str] = []
    if node.tag == "img" and node.attrs.get("src"):
        sources.append(node.attrs["src"])
    for child in node.children:
        sources.extend(_extract_image_sources(child))
    return sources


def parse_with_algorithm(html: str, algo: ParsingAlgorithm) -> Dict[str, Any]:
    root = parse_html(html)
    selectors = algo.selectors
    data = {
        "title": _extract_text(select_first(root, selectors.get("title", ""))),
        "price": _extract_text(select_first(root, selectors.get("price", ""))),
        "description": _extract_text(select_first(root, selectors.get("description", ""))),
        "images": _extract_image_sources(select_first(root, selectors.get("images", ""))),
        "attributes": _extract_text(select_first(root, selectors.get("attributes", ""))),
    }
    return data


# -------------------------- Self-healing selectors ------------------------


def self_heal_algorithm(error_html: str, previous_algo: ParsingAlgorithm) -> ParsingAlgorithm:
    root = parse_html(error_html)
    updated_selectors = dict(previous_algo.selectors)
    for key, selector in previous_algo.selectors.items():
        node = select_first(root, selector)
        if node is None:
            updated_selectors[key] = _find_best_selector(root, key)
    meta = dict(previous_algo.meta)
    meta["warnings"] = [key for key, sel in updated_selectors.items() if not sel]
    meta["confidence"] = max(0.3, min(1.0, meta.get("confidence", 0.6) - 0.05 + 0.1 * len(meta["warnings"])) )
    return ParsingAlgorithm(selectors=updated_selectors, rules=previous_algo.rules, meta=meta)


# --------------------------- Code generation ------------------------------


PYTHON_TEMPLATE = string.Template(
    """import json
import re
import requests
from bs4 import BeautifulSoup


def clean_price(value: str) -> float:
    digits = re.sub(r"[^0-9.,]", "", value)
    digits = digits.replace(",", ".")
    try:
        return float(digits)
    except ValueError:
        return 0.0


def absolute_url(base: str, url: str) -> str:
    if url.startswith("http"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return base.rstrip("/") + url
    return base.rstrip("/") + "/" + url


def parse(url: str):
    html = requests.get(url, timeout=10).text
    soup = BeautifulSoup(html, "html.parser")

    def first(sel: str):
        return soup.select_one(sel) if sel else None

    data = {
        "title": first("$title").get_text(strip=True) if first("$title") else "",
        "price": clean_price(first("$price").get_text()) if first("$price") else 0.0,
        "description": first("$description").get_text("\n", strip=True) if first("$description") else "",
        "images": [absolute_url(url, img["src"]) for img in soup.select("$images img, $images") if img.get("src")],
        "attributes": first("$attributes").get_text("\n", strip=True) if first("$attributes") else "",
    }
    print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    parse("https://example.com/product")
"""
)

NODE_TEMPLATE = string.Template(
    """const axios = require('axios');
const cheerio = require('cheerio');

function cleanPrice(value) {
  const digits = value.replace(/[^0-9.,]/g, '').replace(',', '.');
  return parseFloat(digits) || 0;
}

function absoluteUrl(base, url) {
  if (url.startsWith('http')) return url;
  if (url.startsWith('//')) return `https:${url}`;
  if (url.startsWith('/')) return `${base.replace(/\\/$/, '')}${url}`;
  return `${base.replace(/\\/$/, '')}/${url}`;
}

async function parse(url) {
  const html = (await axios.get(url, { timeout: 10000 })).data;
  const $ = cheerio.load(html);

  const pick = (sel) => sel ? $(sel).first() : null;

  const imageNodes = "$images" ? $(`$images img, $images`) : [];
  const images = [];
  imageNodes.each((_, el) => {
    const src = $(el).attr('src');
    if (src) images.push(absoluteUrl(url, src));
  });

  const data = {
    title: pick("$title") ? pick("$title").text().trim() : "",
    price: pick("$price") ? cleanPrice(pick("$price").text()) : 0,
    description: pick("$description") ? pick("$description").text().trim() : "",
    images,
    attributes: pick("$attributes") ? pick("$attributes").text().trim() : "",
  };
  console.log(JSON.stringify(data));
}

parse('https://example.com/product');
"""
)


def generate_parser_code(algo: ParsingAlgorithm, language: str = "python") -> str:
    selectors = algo.selectors
    if language.lower() == "python":
        return PYTHON_TEMPLATE.safe_substitute(**selectors)
    if language.lower() == "node":
        return NODE_TEMPLATE.safe_substitute(**selectors)
    raise ValueError("language must be 'python' or 'node'")


# --------------------------- Product matching -----------------------------


def _tokenize(text: str) -> Counter:
    tokens = re.findall(r"[\w-]+", text.lower())
    return Counter(tokens)


def _similarity(a: str, b: str) -> float:
    ca, cb = _tokenize(a), _tokenize(b)
    if not ca or not cb:
        return 0.0
    intersection = sum((ca & cb).values())
    union = sum((ca | cb).values())
    return intersection / union if union else 0.0


def match_competitor_product(competitor_title: str, our_catalog: Dict[int, str]) -> Dict[str, Any]:
    best_id = None
    best_score = 0.0
    for pid, title in our_catalog.items():
        score = _similarity(competitor_title, title)
        if score > best_score:
            best_score = score
            best_id = pid
    reason = "matched by token similarity" if best_score else "no sufficient similarity"
    return {
        "competitor_title": competitor_title,
        "our_id": best_id,
        "match_confidence": round(best_score, 3),
        "reason": reason,
    }


# --------------------------- Error analysis -------------------------------


def analyze_parser_error(error_message: str, snippet: str) -> Dict[str, str]:
    reason = "unknown"
    fix = snippet
    if "timeout" in error_message.lower():
        reason = "request timed out"
        fix = snippet + "\n# Suggestion: increase timeout or add retries"
    elif "selector" in error_message.lower():
        reason = "selector not found"
        fix = snippet + "\n# Suggestion: verify selectors or run self_heal_algorithm"
    elif "json" in error_message.lower():
        reason = "JSON parsing issue"
        fix = snippet + "\n# Suggestion: validate JSON formatting"
    return {"error_reason": reason, "fixed_code": fix}


__all__ = [
    "ParsingAlgorithm",
    "ParsingRules",
    "analyze_html",
    "parse_with_algorithm",
    "self_heal_algorithm",
    "generate_parser_code",
    "match_competitor_product",
    "analyze_parser_error",
]
