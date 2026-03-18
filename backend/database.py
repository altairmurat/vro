"""
Парсер OCR-сканированного Excel-файла → PostgreSQL через SQLAlchemy.

Таблица: elements
  tmarka_elementa  TEXT   — марка элемента (Стена разрез X-X на отм. +XXXXX)
  tclass_betona    TEXT   — класс бетона (B30 F200 W6)
  tthickness       REAL   — толщина, мм (если есть в таблице)
  tbeton_m3        REAL   — расход бетона, м³
  tstal_kg         REAL   — расход стали, кг
  tcoef_a          REAL   — коэффициент армирования (tstal_kg / tbeton_m3 / 100)
"""

import re
import openpyxl
from pathlib import Path

from sqlalchemy import create_engine, Column, Integer, Float, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from env import DATABASE_URL


# ── SQLAlchemy setup ──────────────────────────────────────────────────────────
engine       = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base         = declarative_base()


class Element(Base):
    __tablename__ = "elements"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    tmarka_elementa  = Column(Text)
    tclass_betona    = Column(Text)
    tthickness       = Column(Float, nullable=True)
    tbeton_m3        = Column(Float, nullable=True)
    tstal_kg         = Column(Float, nullable=True)
    tcoef_a          = Column(Float, nullable=True)


# ── настройки Excel ───────────────────────────────────────────────────────────
EXCEL_PATH = "layout_page_0.xlsx"

# Колонки (1-based), определены по анализу структуры файла
COL_NAME      = 10   # Марка элемента
COL_STEEL_KG  = 114  # Итого сталь, кг
COL_BETON_M3  = 121  # Итого бетон, м³
COL_THICKNESS = 161  # Толщина, мм

DATA_ROW_START = 29
DATA_ROW_END   = 225  # до строки «Итого»

BETON_CLASS_FULL = "B30 F200 W6"  # из заголовков листа (строки 14 и 26)


# ── OCR-очистка ───────────────────────────────────────────────────────────────
_ZERO_STUBS = {"oo", "po", "o", "0", "-", "a", "oa", "oe", "ao"}

def _clean_ocr_number(raw) -> float | None:
    """Распознаёт OCR-искажённое число → float или None."""
    if raw is None:
        return None
    s = str(raw).strip().replace("\xa0", "")

    if s.lower() in _ZERO_STUBS:
        return 0.0

    s = s.replace(",", ".").replace(" ", "")

    s = re.sub(r"^[Bb](\d)", r"8\1", s)   # B36 → 836
    s = re.sub(r"^[Ll](\d)", r"1\1", s)   # L45 → 145
    s = re.sub(r"(?<=\d)[IiLl]", "1", s)  # 5L8 → 518
    s = re.sub(r"[IiLl](?=\d)", "1", s)   # I5  → 15
    s = re.sub(r"^K(\d)", r"6\1", s)      # K7  → 67

    m = re.search(r"\d+\.?\d*", s)
    if m:
        try:
            return float(m.group())
        except ValueError:
            pass
    return None


# ── Нормализация имени элемента ───────────────────────────────────────────────
def _normalize_name(raw: str) -> str | None:
    """Преобразует OCR-искажённое имя в нормальный читаемый вид."""
    if raw is None:
        return None
    s = str(raw).strip()

    if re.match(r"^[Mm](mozo|nozo|mnozo)", s, re.I):
        return None  # строка «Итого»

    # Стена (OCR варианты: Cmexa, (mena, Cmeva, Gena ...)
    if re.match(r"^\(?[CcGg][mM][eEnN][wWxXaAvV]|^\([mMnN][eEnN]", s):
        elem_type = "Стена"
        sec = re.search(r"(\d{1,2})[-–](\d{1,2})", s)
        section = f" (разрез {sec.group(1)}-{sec.group(2)})" if sec else ""

    # Колонна монолитная (OCR: Kononna, Konoxna, Kononwa ...)
    elif re.match(r"^[Kk][oO0][nNhH][oO0]", s):
        elem_type = "Колонна монолитная"
        km = re.search(r"[Kk][Mm]\(?(\w+)", s)
        if km:
            mark = re.sub(r"[^A-Z0-9]", "", km.group(1).upper())
            section = f" КМ{mark}"
        else:
            section = ""

    # Монолитная плита (OCR: Monwezaujuma ...)
    elif re.match(r"^[Mm][oO0][nNhH][wW]", s):
        elem_type = "Монолитная плита"
        section = ""

    else:
        elem_type = "Элемент"
        section = ""

    # Отметка: +5350, -5500 и т.п.
    elev = re.search(r"([+\-])\s*(\d[\d,\.\s]*)", s)
    if elev:
        elevation = elev.group(1) + re.sub(r"[\s,\.]", "", elev.group(2))
    else:
        elevation = "?"

    return f"{elem_type}{section} на отм. {elevation}"


# ── Чтение Excel ──────────────────────────────────────────────────────────────
def extract_rows(excel_path: str) -> list[Element]:
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws = wb.active

    objects = []

    for row_idx in range(DATA_ROW_START, DATA_ROW_END + 1):
        row = [cell.value for cell in ws[row_idx]]

        raw_name = row[COL_NAME - 1]
        if raw_name is None:
            continue

        name = _normalize_name(raw_name)
        if name is None:
            continue

        steel = _clean_ocr_number(row[COL_STEEL_KG - 1])
        beton = _clean_ocr_number(row[COL_BETON_M3 - 1])
        thick = _clean_ocr_number(row[COL_THICKNESS - 1])

        coef_a = round(steel / beton / 100, 4) if steel and beton and beton > 0 else None

        objects.append(Element(
            tmarka_elementa = name,
            tclass_betona   = BETON_CLASS_FULL,
            tthickness      = thick if thick and thick > 0 else None,
            tbeton_m3       = beton,
            tstal_kg        = steel,
            tcoef_a         = coef_a,
        ))

    return objects


# ── Запись в PostgreSQL ───────────────────────────────────────────────────────
def load_to_db(objects: list[Element]) -> None:
    Base.metadata.create_all(engine)  # создаёт таблицу если не существует

    with SessionLocal() as session:
        session.add_all(objects)
        session.commit()
        print(f"✅ Записано {len(objects)} строк в таблицу '{Element.__tablename__}'")


if __name__ == "__main__":
    excel_file = Path(EXCEL_PATH)
    if not excel_file.exists():
        print(f"❌ Файл не найден: {EXCEL_PATH}")
        raise SystemExit(1)

    print(f"📂 Читаем: {EXCEL_PATH}")
    rows = extract_rows(str(excel_file))
    print(f"   Извлечено строк: {len(rows)}")

    print(f"💾 Подключаемся к PostgreSQL и записываем...")
    load_to_db(rows)