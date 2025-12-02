from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import get_async_openai_client

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
TEMPLATES_DIR = BASE_DIR / "templates"
PRODUCTS_FILE = STORAGE_DIR / "products.json"
COMPETITOR_FILE = STORAGE_DIR / "competitor.json"
MATCH_FILE = STORAGE_DIR / "match.json"

app = FastAPI(title="Product Importer")
app.mount("/storage", StaticFiles(directory=STORAGE_DIR), name="storage")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        return default


def save_json_file(path: Path, payload: Any) -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def dataframe_to_products(df: pd.DataFrame) -> List[Dict[str, Any]]:
    required_columns = {"name", "code", "attributes_raw"}
    missing = required_columns - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns: {', '.join(sorted(missing))}",
        )

    products: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        code = str(row.get("code", "")).strip()
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


def save_products(products: List[Dict[str, Any]]) -> None:
    save_json_file(PRODUCTS_FILE, products)


def prepare_match_prompt(root_url: str, product: Dict[str, Any]) -> str:
    attributes = product.get("attributes_parsed") or {}
    attributes_text = json.dumps(attributes, ensure_ascii=False, indent=2)
    return (
        "Знайди на сайті конкурента {root_url} відповідний товар для:\n"
        "Назва: {name}\n"
        "Код: {code}\n"
        "Характеристики: {attributes}\n"
        "Поверни JSON з ключами competitor_url і confidence (0..1)."
    ).format(root_url=root_url, name=product.get("name", ""), code=product.get("code", ""), attributes=attributes_text)


def parse_match_response(content: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return {"competitor_url": "", "confidence": 0.0}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"competitor_url": "", "confidence": 0.0}

    try:
        competitor_url = str(parsed.get("competitor_url", "")).strip()
        confidence = float(parsed.get("confidence", 0))
        return {"competitor_url": competitor_url, "confidence": confidence}
    except (ValueError, TypeError):
        return {"competitor_url": "", "confidence": 0.0}


@app.get("/")
async def index(request: Request):
    products = load_json_file(PRODUCTS_FILE, [])
    return templates.TemplateResponse(
        "index.html", {"request": request, "products": products, "active_tab": "upload", "title": "Завантаження"}
    )


@app.get("/match")
async def match_page(request: Request):
    competitor = load_json_file(COMPETITOR_FILE, {})
    matches = load_json_file(MATCH_FILE, [])
    return templates.TemplateResponse(
        "match.html",
        {
            "request": request,
            "competitor_root_url": competitor.get("root_url", ""),
            "matches": matches,
            "active_tab": "match",
            "title": "Тест парсера",
        },
    )


@app.get("/competitor")
async def competitor_page(request: Request):
    competitor = load_json_file(COMPETITOR_FILE, {})
    return templates.TemplateResponse(
        "competitor.html",
        {
            "request": request,
            "root_url": competitor.get("root_url", ""),
            "active_tab": "competitor",
            "title": "Конкурент",
        },
    )


@app.post("/competitor")
async def save_competitor(competitor_root_url: str = Form(...)):
    normalized = competitor_root_url.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="URL конкурента не може бути порожнім")

    save_json_file(COMPETITOR_FILE, {"root_url": normalized})
    return RedirectResponse(url="/competitor?saved=1", status_code=303)


@app.get("/products", response_class=JSONResponse)
async def get_products() -> JSONResponse:
    data = load_json_file(PRODUCTS_FILE, [])
    return JSONResponse(content={"products": data})


@app.post("/upload", response_class=JSONResponse)
async def upload_file(file: UploadFile = File(...)) -> JSONResponse:
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()

    if suffix not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx files are supported")

    if suffix == ".csv":
        df = pd.read_csv(file.file)
    else:
        df = pd.read_excel(file.file)

    products = dataframe_to_products(df)
    save_products([])
    save_products(products)
    return JSONResponse(content={"products": products})


@app.post("/match", response_class=JSONResponse)
async def run_match() -> JSONResponse:
    products = load_json_file(PRODUCTS_FILE, [])
    if not products:
        raise HTTPException(status_code=400, detail="Спочатку завантажте товари")

    competitor = load_json_file(COMPETITOR_FILE, {})
    root_url = competitor.get("root_url", "").strip()
    if not root_url:
        raise HTTPException(status_code=400, detail="Спочатку збережіть URL конкурента")

    try:
        client = get_async_openai_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    matches: List[Dict[str, Any]] = []

    for product in products:
        prompt = prepare_match_prompt(root_url, product)
        try:
            completion = await client.chat.completions.create(
                model="gpt-4.1-mini",
                temperature=0.2,
                messages=[
                    {
                        "role": "system",
                        "content": "Ти допомагаєш знаходити відповідні товари на сайті конкурента. Відповідай у форматі JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            message_content = completion.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Помилка виклику моделі: {exc}") from exc

        parsed = parse_match_response(message_content)
        matches.append(
            {
                "our_code": product.get("code", ""),
                "our_name": product.get("name", ""),
                "competitor_url": parsed.get("competitor_url", ""),
                "confidence": parsed.get("confidence", 0.0),
            }
        )

    save_json_file(MATCH_FILE, matches)
    return JSONResponse(content={"matches": matches})


@app.get("/match/data", response_class=JSONResponse)
async def get_match_data() -> JSONResponse:
    matches = load_json_file(MATCH_FILE, [])
    return JSONResponse(content={"matches": matches})


@app.post("/match/update", response_class=JSONResponse)
async def update_match(our_code: str = Form(...), competitor_url: str = Form(...)) -> JSONResponse:
    matches = load_json_file(MATCH_FILE, [])
    updated = False
    for item in matches:
        if item.get("our_code") == our_code:
            item["competitor_url"] = competitor_url.strip()
            updated = True
            break

    if not updated:
        raise HTTPException(status_code=404, detail="Запис не знайдено")

    save_json_file(MATCH_FILE, matches)
    return JSONResponse(content={"matches": matches})
