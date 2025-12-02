from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import pandas as pd
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from parser_engine.matcher_ai import match_products_with_competitors
from parser_engine.rule_detector_ai import DEFAULT_RULES, detect_rules_for_url
from parser_engine.scraper import Category, discover_categories, scrape_category

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
TEMPLATES_DIR = BASE_DIR / "templates"

PRODUCTS_FILE = STORAGE_DIR / "products.json"
COMPETITORS_FILE = STORAGE_DIR / "competitors.json"
MATCH_FILE = STORAGE_DIR / "match.json"
RULES_DIR = STORAGE_DIR / "competitor_rules"
PRODUCTS_DIR = STORAGE_DIR / "competitor_products"

app = FastAPI(title="Parser AI Tovar")
app.mount("/storage", StaticFiles(directory=STORAGE_DIR), name="storage")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def ensure_storage() -> None:
    STORAGE_DIR.mkdir(exist_ok=True)
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        return default


def save_json_file(path: Path, payload: Any) -> None:
    ensure_storage()
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


# --- Products helpers ---

def normalize_key(name: str) -> str:
    mapping = {
        "производитель": "brand",
        "бренд": "brand",
        "страна": "country",
        "мощность": "power_hp",
    }
    key = name.strip().lower()
    if key in mapping:
        return mapping[key]
    sanitized = re.sub(r"[^\w\-]+", "_", key, flags=re.UNICODE).strip("_")
    return sanitized


def convert_value(value: str) -> Any:
    value = value.strip()
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def parse_attributes(text: str | None) -> Dict[str, Any]:
    if not text:
        return {}

    attributes: Dict[str, Any] = {}
    pattern = re.compile(r"\s*([^:;]+):\s*[A-Z]\[(.*?)\]")
    for match in pattern.finditer(text):
        raw_name, raw_value = match.groups()
        key = normalize_key(raw_name)
        value = convert_value(raw_value)
        attributes[key] = value
    return attributes


def dataframe_to_products(df: pd.DataFrame) -> List[Dict[str, Any]]:
    required_columns = {"name", "code", "attributes_raw"}
    missing = required_columns - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns: {', '.join(sorted(missing))}",
        )

    # Налаштування довжини коду товару з конфігурації
    config = load_json_file(BASE_DIR / "config.json", {})
    try:
        length = int(config.get("code_length", 6))
        if length < 1:
            length = 6
    except Exception:
        length = 6

    products: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        raw_code_value = row.get("code", "")
        raw_code = "" if pd.isna(raw_code_value) else str(raw_code_value).strip()
        raw_code = raw_code.split(".")[0]
        # Якщо код має не тільки цифри — не застосовувати zfill
        if raw_code.isdigit():
            code = raw_code.zfill(length)
        else:
            code = raw_code
        raw_value = row.get("attributes_raw")
        attributes_raw = "" if pd.isna(raw_value) else str(raw_value).strip()
        attributes_parsed = parse_attributes(attributes_raw)

        products.append(
            {
                "name": name,
                "code": code,
                "attributes_raw": attributes_raw,
                "attributes_parsed": attributes_parsed,
            }
        )
    return products


# --- Competitors helpers ---

def list_competitors() -> List[Dict[str, Any]]:
    return load_json_file(COMPETITORS_FILE, [])


def save_competitors(data: List[Dict[str, Any]]) -> None:
    save_json_file(COMPETITORS_FILE, data)


def get_competitor(competitor_id: str) -> Dict[str, Any]:
    for item in list_competitors():
        if str(item.get("id")) == str(competitor_id):
            return item
    raise HTTPException(status_code=404, detail="Конкурента не знайдено")


def get_rules_path(competitor_id: str) -> Path:
    return RULES_DIR / f"{competitor_id}.json"


def get_products_path(competitor_id: str) -> Path:
    return PRODUCTS_DIR / f"{competitor_id}.json"


def load_competitor_rules(competitor_id: str) -> Dict[str, Any]:
    return load_json_file(get_rules_path(competitor_id), DEFAULT_RULES)


def load_competitor_products(competitor_id: str) -> Dict[str, Any]:
    return load_json_file(get_products_path(competitor_id), {"categories": []})


# --- Category helpers ---


def _find_or_create(nodes: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    for node in nodes:
        if node.get("name") == name:
            return node
    new_node = {"name": name, "url": None, "children": []}
    nodes.append(new_node)
    return new_node


def build_category_tree(categories: List[Category]) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}

    for cat in categories:
        parsed = urlparse(cat.url)
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
            current_level = current_node.setdefault("children", [])

        current_level.append({"name": cat.name, "url": cat.url, "children": []})

    return list(groups.values())


# --- Routes ---


@app.get("/", response_class=HTMLResponse)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/competitors", status_code=303)


@app.get("/competitors", response_class=HTMLResponse)
async def competitors_page(request: Request, edit: str | None = None) -> HTMLResponse:
    competitors = list_competitors()
    edit_competitor = None
    if edit:
        for comp in competitors:
            if str(comp.get("id")) == edit:
                edit_competitor = comp
                break
    return templates.TemplateResponse(
        "competitors.html",
        {
            "request": request,
            "competitors": competitors,
            "edit_competitor": edit_competitor,
            "active_tab": "competitors",
            "title": "Конкуренти",
        },
    )


@app.post("/competitors")
async def create_competitor(
    name: str = Form(...),
    root_url: str = Form(...),
    competitor_id: str | None = Form(None),
) -> RedirectResponse:
    normalized_url = root_url.strip()
    if not normalized_url:
        raise HTTPException(status_code=400, detail="URL не може бути порожнім")

    competitors = list_competitors()
    if competitor_id:
        updated = False
        for item in competitors:
            if str(item.get("id")) == competitor_id:
                item["name"] = name.strip() or "Конкурент"
                item["root_url"] = normalized_url
                updated = True
                break
        if not updated:
            raise HTTPException(status_code=404, detail="Конкурента не знайдено")
    else:
        competitors.append({"id": str(uuid.uuid4()), "name": name.strip() or "Конкурент", "root_url": normalized_url})

    save_competitors(competitors)
    return RedirectResponse(url="/competitors", status_code=303)


@app.get("/competitor/{competitor_id}/rules", response_class=HTMLResponse)
async def competitor_rules_page(request: Request, competitor_id: str) -> HTMLResponse:
    competitor = get_competitor(competitor_id)
    rules = load_competitor_rules(competitor_id)
    return templates.TemplateResponse(
        "competitor_rules.html",
        {
            "request": request,
            "competitor": competitor,
            "rules": json.dumps(rules, ensure_ascii=False, indent=2),
            "active_tab": "competitors",
            "title": "Правила парсингу",
        },
    )


@app.post("/competitor/{competitor_id}/rules/detect")
async def detect_rules(competitor_id: str) -> RedirectResponse:
    competitor = get_competitor(competitor_id)
    rules = await detect_rules_for_url(competitor.get("root_url", ""))
    save_json_file(get_rules_path(competitor_id), rules)
    return RedirectResponse(url=f"/competitor/{competitor_id}/rules?detected=1", status_code=303)


@app.post("/competitor/{competitor_id}/rules")
async def save_rules(competitor_id: str, rules_body: str = Form(...)) -> RedirectResponse:
    try:
        parsed = json.loads(rules_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Помилка JSON: {exc}") from exc

    save_json_file(get_rules_path(competitor_id), parsed)
    return RedirectResponse(url=f"/competitor/{competitor_id}/rules?saved=1", status_code=303)


@app.get("/competitor/{competitor_id}/parsing", response_class=HTMLResponse)
async def competitor_parsing_page(request: Request, competitor_id: str, message: str | None = None) -> HTMLResponse:
    competitor = get_competitor(competitor_id)
    rules = load_competitor_rules(competitor_id)
    try:
        categories = await discover_categories(competitor.get("root_url", ""), rules)
    except Exception:
        categories = []
    category_tree = build_category_tree(categories) if categories else []
    existing = load_competitor_products(competitor_id)
    return templates.TemplateResponse(
        "competitor_parsing.html",
        {
            "request": request,
            "competitor": competitor,
            "rules": rules,
            "category_tree": category_tree,
            "existing": existing,
            "message": message,
            "active_tab": "competitors",
            "title": "Парсинг конкурента",
        },
    )


@app.post("/competitor/{competitor_id}/parsing")
async def run_parsing(competitor_id: str, category_urls: List[str] | str = Form(...)) -> RedirectResponse:
    rules = load_competitor_rules(competitor_id)
    urls = category_urls if isinstance(category_urls, list) else [category_urls]
    if not urls:
        raise HTTPException(status_code=400, detail="Оберіть хоча б одну категорію")

    products_by_category = {}
    for url in urls:
        items = await scrape_category(url, rules)
        products_by_category[url] = [item.__dict__ for item in items]

    payload = {
        "categories": [
            {"url": url, "items": products_by_category[url]} for url in urls
        ],
        "scraped_at": datetime.utcnow().isoformat() + "Z",
    }
    save_json_file(get_products_path(competitor_id), payload)
    return RedirectResponse(url=f"/competitor/{competitor_id}/parsing?message=parsed", status_code=303)


@app.get("/products", response_class=HTMLResponse)
async def products_page(request: Request) -> HTMLResponse:
    products = load_json_file(PRODUCTS_FILE, [])
    return templates.TemplateResponse(
        "products.html",
        {
            "request": request,
            "products": products,
            "active_tab": "products",
            "title": "Наші товари",
        },
    )


@app.post("/products/upload")
async def upload_products(file: UploadFile) -> RedirectResponse:
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=400, detail="Підтримуються лише .csv або .xlsx")

    if suffix == ".csv":
        df = pd.read_csv(file.file, dtype=str)
    else:
        df = pd.read_excel(file.file, dtype=str)

    products = dataframe_to_products(df)
    save_json_file(PRODUCTS_FILE, products)
    return RedirectResponse(url="/products?uploaded=1", status_code=303)


@app.get("/matching", response_class=HTMLResponse)
async def matching_page(request: Request) -> HTMLResponse:
    competitors = list_competitors()
    matches = load_json_file(MATCH_FILE, [])
    products = load_json_file(PRODUCTS_FILE, [])
    parsed_state: Dict[str, bool] = {}
    for comp in competitors:
        data = load_competitor_products(str(comp.get("id")))
        parsed_state[str(comp.get("id"))] = len(data.get("categories", [])) > 0
    return templates.TemplateResponse(
        "matching.html",
        {
            "request": request,
            "competitors": competitors,
            "matches": matches,
            "product_count": len(products),
            "parsed_state": parsed_state,
            "active_tab": "matching",
            "title": "Матчинг товарів",
        },
    )


@app.post("/matching")
async def run_matching(competitor_ids: List[str] | str = Form(...)) -> RedirectResponse:
    products = load_json_file(PRODUCTS_FILE, [])
    if not products:
        raise HTTPException(status_code=400, detail="Спочатку завантажте товари")

    ids = competitor_ids if isinstance(competitor_ids, list) else [competitor_ids]
    competitors = [get_competitor(cid) for cid in ids]
    products_by_competitor: Dict[str, List[Dict[str, Any]]] = {}
    for competitor in competitors:
        data = load_competitor_products(competitor["id"])
        parsed_state = len(data.get("categories", [])) > 0
        if not parsed_state:
            raise HTTPException(
                status_code=400,
                detail=f"Конкурента '{competitor['name']}' не розпарсено — спочатку запустіть парсинг у вкладці Конкуренти."
            )
        aggregated: List[Dict[str, Any]] = []
        for category in data.get("categories", []):
            aggregated.extend(category.get("items", []))
        products_by_competitor[str(competitor["id"])] = aggregated

    matches = match_products_with_competitors(products, competitors, products_by_competitor)
    save_json_file(MATCH_FILE, matches)
    return RedirectResponse(url="/matching?ready=1", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    config = load_json_file(BASE_DIR / "config.json", {})
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "openai_keys": config.get("openai_keys", []),
            "code_length": config.get("code_length", 6),
            "active_tab": "settings",
            "title": "Налаштування",
        },
    )


@app.post("/settings")
async def save_settings(
    operation: str = Form("save"),
    code_length: str | None = Form(None),
    key_name: str = Form(""),
    api_key: str = Form(""),
    key_id: str = Form(""),
) -> RedirectResponse:
    config = load_json_file(BASE_DIR / "config.json", {"openai_keys": [], "code_length": 6})
    openai_keys = config.get("openai_keys", [])

    if operation == "add_key":
        cleaned_key = api_key.strip()
        if cleaned_key:
            openai_keys.append(
                {
                    "id": str(uuid.uuid4()),
                    "name": key_name.strip() or "OpenAI ключ",
                    "api_key": cleaned_key,
                }
            )
    elif operation == "delete_key":
        openai_keys = [k for k in openai_keys if str(k.get("id")) != key_id]

    try:
        code_length_value = int(code_length) if code_length is not None else int(config.get("code_length", 6))
    except Exception:
        code_length_value = int(config.get("code_length", 6))

    if code_length_value < 1:
        code_length_value = 1

    payload = {"openai_keys": openai_keys, "code_length": code_length_value}
    save_json_file(BASE_DIR / "config.json", payload)
    return RedirectResponse(url="/settings?saved=1", status_code=303)


ensure_storage()
