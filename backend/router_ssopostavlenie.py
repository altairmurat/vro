"""
router_ssopostavlenie.py — эндпоинты для страницы сопоставления ССР

Подключить в main.py:
    from backend.router_ssopostavlenie import router as ssr_router
    app.include_router(ssr_router)
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import Depends

from database import SessionLocal
from documents.ccp import punkts_markas_list, receive_punkts_and_elements_ccp
from model.models import StructuralElement

router = APIRouter(prefix="/api/ssr")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Pydantic ──────────────────────────────────────────────────────────────────

class MappingItem(BaseModel):
    db_id:     int
    punkt:     str
    thickness: str | None = None


# ── Matching logic (same as match_titles in main.py) ──────────────────────────

def _match_titles(db_rows, list_of_dicts: list[dict]) -> list[dict]:
    result = []
    for row in db_rows:
        matched_title   = None
        confidence_score = 0

        for item in list_of_dicts:
            score = 0

            marka_elementa = item["marka"]
            
            if row.tmarka_elementa and item.get("marka"):
                if row.tmarka_elementa.lower()[:4] in item["marka"].split(" "):
                    score += 0.5

            if item.get("class") and row.tclass_betona:
                item_classes = set(item["class"].split(", "))
                row_classes  = set(row.tclass_betona.split(", "))
                if item_classes & row_classes:
                    score += 0.4

            thickness = item.get("thickness")
            if thickness is not None and row.tthickness is not None:
                if isinstance(thickness, int):
                    try:
                        if float(row.tthickness) == thickness:
                            score += 0.1
                    except (ValueError, TypeError):
                        pass
                else:
                    try:
                        low, high = map(int, str(thickness).split("-"))
                        if low <= float(row.tthickness) <= high:
                            score += 0.1
                    except (ValueError, TypeError):
                        pass

            if score > confidence_score:
                confidence_score = score
                matched_title    = marka_elementa

        result.append({
            "db_id":          row.id,
            "marka":          row.tmarka_elementa,
            "class":          row.tclass_betona,
            "thickness":      row.tthickness,
            "beton":          row.tbeton_m3,
            "stal":           row.tstal_kg,
            "coef":           row.tcoef_a,
            "assigned_punkt": matched_title,
            "confidence":     round(confidence_score, 4),
            "is_match":       confidence_score >= 0.5,
        })

    return result


# ── GET /api/ssr/match ────────────────────────────────────────────────────────
@router.get("/match")
def get_match(db: Session = Depends(get_db)):
    """
    Возвращает:
      - rows:   список элементов с автоматическим сопоставлением и % точности
      - titles: список всех пунктов ССР для дропдауна
    """
    db_rows      = db.query(StructuralElement).all()
    list_of_dicts = receive_punkts_and_elements_ccp()
    paras_list = punkts_markas_list()

    rows = _match_titles(db_rows, list_of_dicts)

    return JSONResponse({
        "rows":   rows,
        "titles": paras_list,   # список строк — пунктов ССР
    })


# ── POST /api/ssr/submit ──────────────────────────────────────────────────────
@router.post("/submit")
def submit_match(items: list[MappingItem], db: Session = Depends(get_db)):
    """
    Сохраняет сопоставления в таблицу processed_data.
    Перед вставкой очищает старые записи.
    """
    if not items:
        return JSONResponse({"status": "ok", "saved": 0})

    # Очищаем старые результаты
    db.execute(text("DELETE FROM processed_data"))

    from model.models import ProcessedData

    for item in items:
        original = db.query(StructuralElement).filter(
            StructuralElement.id == item.db_id
        ).first()

        if not original:
            continue

        new_row = ProcessedData(
            db_id     = item.db_id,
            punkt     = item.punkt,
            thickness = item.thickness,
            marka     = original.tmarka_elementa,
            beton     = original.tbeton_m3,
            stal      = original.tstal_kg,
            coef      = original.tcoef_a,
        )
        db.add(new_row)

    db.commit()

    return JSONResponse({"status": "ok", "saved": len(items)})