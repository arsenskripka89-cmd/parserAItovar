from __future__ import annotations

import json
from difflib import SequenceMatcher
from typing import Dict, List, Optional

from config import get_openai_client


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _heuristic_match(
    our_products: List[Dict[str, str]], competitor_products: List[Dict[str, str]], competitor_id: str
) -> List[Dict[str, str]]:
    matches: List[Dict[str, str]] = []
    for product in our_products:
        our_name = product.get("name", "")
        best_score = 0.0
        best_product: Dict[str, str] | None = None
        for item in competitor_products:
            score = _similarity(our_name, item.get("name", ""))
            if score > best_score:
                best_score = score
                best_product = item
        matches.append(
            {
                "competitor_id": competitor_id,
                "our_code": product.get("code", ""),
                "our_name": our_name,
                "competitor_name": (best_product or {}).get("name", ""),
                "competitor_url": (best_product or {}).get("url", ""),
                "competitor_price": (best_product or {}).get("price"),
                "confidence": round(best_score, 3),
            }
        )
    return matches


def _safe_parse_matches(raw: str) -> Optional[List[Dict[str, str]]]:
    """Безпечне парсення відповіді моделі в JSON."""

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    # Якщо відповідь моделі містить непотрібний текст, пробуємо знайти JSON масив
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, list):
                return parsed
        except Exception:
            return None
    return None


def _ai_match(
    our_products: List[Dict[str, str]], competitor_products: List[Dict[str, str]], competitor_name: str, competitor_id: str
) -> List[Dict[str, str]]:
    try:
        client = get_openai_client()
    except Exception:
        return _heuristic_match(our_products, competitor_products, competitor_id)

    top_competitor_products = competitor_products[:30]
    prompt = (
        "Зістав товари з нашого каталогу з товарами конкурента. Відповідай JSON масивом об'єктів "
        "{our_code, our_name, competitor_name, competitor_url, competitor_price, confidence}. "
        "Наші товари: " + json.dumps(our_products, ensure_ascii=False) + ". "
        "Топ-30 товарів конкурента: " + json.dumps(top_competitor_products, ensure_ascii=False)
    )

    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Ти асистент з матчінгу товарів."},
                {"role": "user", "content": prompt},
            ],
        )
        raw = completion.choices[0].message.content or "[]"
        parsed = _safe_parse_matches(raw)
        if parsed is None:
            return _heuristic_match(our_products, competitor_products, competitor_id)

        matches: List[Dict[str, str]] = []
        for item in parsed:
            matches.append(
                {
                    "competitor_id": competitor_id,
                    "our_code": item.get("our_code", ""),
                    "our_name": item.get("our_name", ""),
                    "competitor_name": item.get("competitor_name", competitor_name),
                    "competitor_url": item.get("competitor_url", ""),
                    "competitor_price": item.get("competitor_price"),
                    "confidence": float(item.get("confidence", 0)),
                }
            )
        if matches:
            return matches
    except Exception:
        return _heuristic_match(our_products, competitor_products, competitor_id)

    return _heuristic_match(our_products, competitor_products, competitor_id)


def match_products_with_competitors(
    our_products: List[Dict[str, str]],
    competitors: List[Dict[str, str]],
    products_by_competitor: Dict[str, List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    all_matches: List[Dict[str, str]] = []
    for competitor in competitors:
        competitor_id = competitor.get("id")
        if not competitor_id:
            continue
        competitor_name = competitor.get("name", "Конкурент")
        competitor_products = products_by_competitor.get(str(competitor_id), [])
        if not competitor_products:
            continue
        matches = _ai_match(our_products, competitor_products, competitor_name, str(competitor_id))
        all_matches.extend(matches)
    return all_matches
