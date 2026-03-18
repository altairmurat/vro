"""
router_raschet.py — FastAPI роутер для страницы raschet.html

Подключить в main.py:
    from backend.router_raschet import router as raschet_router
    app.include_router(raschet_router)
"""

import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text

from env import DATABASE_URL
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# router_raschet.py — вверху файла убрать tempfile, добавить параметр
import os

# Папка загрузок — устанавливается из main.py при подключении роутера
UPLOAD_DIR: str = ""

def set_upload_dir(path: str):
    global UPLOAD_DIR
    UPLOAD_DIR = path

# ── DB setup ──────────────────────────────────────────────
engine       = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

router = APIRouter(prefix="/api")

# ── Pydantic schemas ──────────────────────────────────────

class ElementOut(BaseModel):
    id:               int
    tmarka_elementa:  Optional[str]   = None
    tclass_betona:    Optional[str]   = None
    tthickness:       Optional[float] = None
    tbeton_m3:        Optional[float] = None
    tstal_kg:         Optional[float] = None
    tcoef_a:          Optional[float] = None
    pdf_page:         Optional[int]   = None
    pdf_x:            Optional[float] = None
    pdf_y:            Optional[float] = None

    class Config:
        from_attributes = True


class ElementIn(BaseModel):
    id:               int
    tmarka_elementa:  Optional[str]   = None
    tclass_betona:    Optional[str]   = None
    tthickness:       Optional[float] = None
    tbeton_m3:        Optional[float] = None
    tstal_kg:         Optional[float] = None
    tcoef_a:          Optional[float] = None


class CoordsIn(BaseModel):
    id:       int
    pdf_page: int
    pdf_x:    float
    pdf_y:    float


# ── Migration helper: add PDF coordinate columns if missing ──
def ensure_pdf_columns():
    """
    Добавляет колонки pdf_page / pdf_x / pdf_y в таблицу elements,
    если их ещё нет. Вызывается при старте приложения.
    """
    with engine.connect() as conn:
        existing = [
            row[0]
            for row in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name='elements'")
            )
        ]
        migrations = {
            "pdf_page": "INTEGER",
            "pdf_x":    "DOUBLE PRECISION",
            "pdf_y":    "DOUBLE PRECISION",
        }
        for col, dtype in migrations.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE elements ADD COLUMN {col} {dtype}"))
        conn.commit()


# ── Run migration on import ───────────────────────────────
try:
    ensure_pdf_columns()
except Exception as e:
    print(f"[raschet] Migration warning: {e}")


# ── GET /api/elements ─────────────────────────────────────
@router.get("/elements", response_model=list[ElementOut])
def get_elements():
    """Вернуть все строки таблицы elements."""
    with SessionLocal() as db:
        rows = db.execute(
            text("""
                SELECT id, tmarka_elementa, tclass_betona, tthickness,
                       tbeton_m3, tstal_kg, tcoef_a,
                       pdf_page, pdf_x, pdf_y, bbox_x, bbox_y, bbox_w, bbox_h, pdf_page_w, pdf_page_h
                FROM elements
                ORDER BY id
            """)
        ).mappings().all()

    return [dict(r) for r in rows]


# ── PUT /api/elements/bulk ────────────────────────────────
@router.put("/elements/bulk")
def update_elements(items: list[ElementIn]):
    """
    Принять массив изменённых строк и обновить в БД.
    Обновляются только поля tmarka_elementa, tclass_betona,
    tthickness, tbeton_m3, tstal_kg, tcoef_a.
    """
    if not items:
        return {"updated": 0}

    with SessionLocal() as db:
        updated = 0
        for item in items:
            result = db.execute(
                text("""
                    UPDATE elements SET
                        tmarka_elementa = :tmarka_elementa,
                        tclass_betona   = :tclass_betona,
                        tthickness      = :tthickness,
                        tbeton_m3       = :tbeton_m3,
                        tstal_kg        = :tstal_kg,
                        tcoef_a         = :tcoef_a
                    WHERE id = :id
                """),
                {
                    "id":               item.id,
                    "tmarka_elementa":  item.tmarka_elementa,
                    "tclass_betona":    item.tclass_betona,
                    "tthickness":       item.tthickness,
                    "tbeton_m3":        item.tbeton_m3,
                    "tstal_kg":         item.tstal_kg,
                    "tcoef_a":          item.tcoef_a,
                },
            )
            updated += result.rowcount
        db.commit()

    return {"updated": updated}


# ── PATCH /api/elements/coords ────────────────────────────
@router.patch("/elements/coords")
def save_coords(data: CoordsIn):
    """
    Сохранить PDF-координаты для одной строки.
    Вызывается автоматически после первого клика по строке в таблице.
    """
    with SessionLocal() as db:
        result = db.execute(
            text("""
                UPDATE elements
                SET pdf_page = :pdf_page,
                    pdf_x    = :pdf_x,
                    pdf_y    = :pdf_y
                WHERE id = :id
            """),
            {"id": data.id, "pdf_page": data.pdf_page,
             "pdf_x": data.pdf_x, "pdf_y": data.pdf_y},
        )
        db.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Element {data.id} not found")

    return {"ok": True}


# ── GET /api/pdf/file ─────────────────────────────────────
@router.get("/pdf/file")
def serve_pdf(name: str):
    if not name.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files allowed")

    safe_name = Path(name).name
    file_path = Path(UPLOAD_DIR) / safe_name

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{safe_name}' not found")

    # RFC 5987 — кириллица в заголовке через UTF-8 encoding
    from urllib.parse import quote
    encoded_name = quote(safe_name, encoding='utf-8')

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_name}"
        },
    )