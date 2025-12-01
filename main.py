from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
PRODUCTS_FILE = STORAGE_DIR / "products.json"

app = FastAPI(title="Product Importer")
app.mount("/storage", StaticFiles(directory=STORAGE_DIR), name="storage")


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

    products: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        code = str(row.get("code", "")).strip()
        attributes_raw = "" if pd.isna(row.get("attributes_raw")) else str(row["attributes_raw"]).strip()
        attributes = parse_attributes(attributes_raw)

        products.append(
            {
                "name": name,
                "code": code,
                "attributes_raw": attributes_raw,
                "attributes": attributes,
            }
        )
    return products


def save_products(products: List[Dict[str, Any]]) -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    with PRODUCTS_FILE.open("w", encoding="utf-8") as file:
        json.dump(products, file, ensure_ascii=False, indent=2)


@app.get("/", response_class=FileResponse)
async def index() -> FileResponse:
    index_file = BASE_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_file)


@app.get("/products", response_class=JSONResponse)
async def get_products() -> JSONResponse:
    if not PRODUCTS_FILE.exists():
        return JSONResponse(content={"products": []})
    with PRODUCTS_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)
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
    save_products(products)
    return JSONResponse(content={"products": products})
