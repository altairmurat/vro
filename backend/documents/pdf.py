import cv2
import pytesseract
from pdf2image import convert_from_path
import numpy as np
import pandas as pd

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# --- READ PDF TABLES ONLY (WITHOUT THICKNESS) ---
def pdf_to_images(pdf_path):
    return convert_from_path(pdf_path, dpi=300, poppler_path=r"C:\poppler\poppler-25.12.0\Library\bin")


def preprocess_image(pil_image):
    img = np.array(pil_image)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
    return thresh


def detect_table_structure(img):
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    horizontal = cv2.morphologyEx(img, cv2.MORPH_OPEN, horizontal_kernel)

    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
    vertical = cv2.morphologyEx(img, cv2.MORPH_OPEN, vertical_kernel)

    return cv2.add(horizontal, vertical)


def extract_cells(img, mask):
    contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    cells = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w > 40 and h > 20:
            cell_img = img[y:y+h, x:x+w]
            cells.append((x, y, w, h, cell_img))

    return cells


def ocr_cell(cell_img):
    return pytesseract.image_to_string(cell_img, config='--psm 6').strip()


def map_to_excel(cells, scale=20):
    """
    Преобразуем координаты изображения в сетку Excel
    scale — чем меньше, тем точнее, но больше файл
    """
    mapped = []

    for (x, y, w, h, cell_img) in cells:
        text = ocr_cell(cell_img)

        col = int(x / scale)
        row = int(y / scale)

        mapped.append((row, col, text))

    return mapped


def build_excel(mapped_cells, output_file):
    # определяем размер таблицы
    max_row = max([r for r, c, t in mapped_cells]) + 5
    max_col = max([c for r, c, t in mapped_cells]) + 5

    sheet = [["" for _ in range(max_col)] for _ in range(max_row)]

    for r, c, text in mapped_cells:
        sheet[r][c] = text

    df = pd.DataFrame(sheet)
    df.to_excel(output_file, index=False, header=False)


def extract_layout_pdf(pdf_path):
    images = pdf_to_images(pdf_path)

    for i, img in enumerate(images):
        processed = preprocess_image(img)
        mask = detect_table_structure(processed)
        cells = extract_cells(processed, mask)

        mapped = map_to_excel(cells, scale=25)

        build_excel(mapped, f"layout_pagee_{i}.xlsx")
        print(f"Page {i} done")
        return f"layout_pagee_{i}.xlsx"

def parse_pdf(pdf_path):
    extract_layout_pdf(pdf_path)
    
# --- END OF PDF TABLES ONLY ---

# --- PARSE PDF-EXCEL TABLES ---

"""
Парсер OCR-сканированного Excel-файла → PostgreSQL через SQLAlchemy.

Таблица: elements
  tmarka_elementa  TEXT  — марка элемента
  tclass_betona    TEXT  — класс бетона (B30 F200 W6)
  tthickness       REAL  — толщина, мм (не используется на этом листе)
  tbeton_m3        REAL  — расход бетона, м³  (col 161, правая таблица)
  tstal_kg         REAL  — расход стали, кг   (col 121, Всего левой таблицы)
  tcoef_a          REAL  — коэффициент армирования

Важно:
  col 121 (сталь):  OCR теряет запятую → «361,24» → «36124» → делим на 100
  col 161 (бетон):  OCR частично читает значения уже с разделителем («10.03»),
                    частично теряет ведущие цифры («1409» → «409»).
                    Значения без точки — тоже делим на 100 (целые = потеряли запятую).
                    Значения уже с точкой — используем как есть.
"""

import re
import openpyxl
from pathlib import Path

from sqlalchemy import create_engine, Column, Integer, Float, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from backend.env import DATABASE_URL


# ── SQLAlchemy setup ──────────────────────────────────────────────────────────
engine       = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
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
EXCEL_PATH = extract_layout_pdf("betonstal.pdf")

COL_NAME     = 10   # Марка элемента
COL_STEEL_KG = 121  # Всего сталь кг — правый край левой таблицы
COL_BETON_M3 = 161  # Бетон м³ — правая таблица (под заголовком F200 W6)

DATA_ROW_START = 29
DATA_ROW_END   = 225

BETON_CLASS_FULL = "B30 F200 W6"

# ── OCR-очистка ───────────────────────────────────────────────────────────────
_ZERO_STUBS = {"oo", "po", "o", "0", "-", "a", "oa", "oe", "ao"}

def _ocr_letter_fix(s: str) -> str:
    s = s.replace(" ", "")
    s = re.sub(r"^[Bb](\d)", r"8\1", s)
    s = re.sub(r"^[Ll](\d)", r"1\1", s)
    s = re.sub(r"(?<=\d)[IiLl]", "1", s)
    s = re.sub(r"[IiLl](?=\d)", "1", s)
    s = re.sub(r"^K(\d)", r"6\1", s)
    return s

def _parse_number(raw, divide_by_100: bool) -> float | None:
    """
    Парсит OCR-число.
    divide_by_100=True  — для значений без десятичного разделителя (сталь, часть бетона)
    divide_by_100=False — для значений уже с точкой (часть бетона читается правильно)
    """
    if raw is None:
        return None
    s = str(raw).strip().replace("\xa0", "")
    if s.lower() in _ZERO_STUBS:
        return 0.0

    # Если уже есть точка или запятая — число прочитано с разделителем, не делим
    has_separator = "." in s or "," in s
    s = s.replace(",", ".")
    s = _ocr_letter_fix(s)

    m = re.search(r"\d+\.?\d*", s)
    if not m:
        return None
    try:
        value = float(m.group())
        if divide_by_100 and not has_separator:
            return round(value / 100, 4)
        return round(value, 4)
    except ValueError:
        return None


# ── Нормализация имени элемента ───────────────────────────────────────────────
def _normalize_name(raw: str) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()

    if re.match(r"^[Mm](mozo|nozo|mnozo)", s, re.I):
        return None

    if re.match(r"^\(?[CcGg][mM][eEnN][wWxXaAvV]|^\([mMnN][eEnN]", s):
        elem_type = "Стена"
        sec = re.search(r"(\d{1,2})[-–](\d{1,2})", s)
        section = f" (разрез {sec.group(1)}-{sec.group(2)})" if sec else ""

    elif re.match(r"^[Kk][oO0][nNhH][oO0]", s):
        elem_type = "Колонна монолитная"
        km = re.search(r"[Kk][Mm]\(?(\w+)", s)
        if km:
            mark = re.sub(r"[^A-Z0-9]", "", km.group(1).upper())
            section = f" КМ{mark}"
        else:
            section = ""

    elif re.match(r"^[Mm][oO0][nNhH][wW]", s):
        elem_type = "Монолитная плита"
        section = ""

    else:
        elem_type = "Элемент"
        section = ""

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

        # Сталь: всегда делим на 100 (OCR теряет запятую → 361,24 → 36124)
        steel = _parse_number(row[COL_STEEL_KG - 1], divide_by_100=True)
        # Бетон: делим на 100 только если нет разделителя в строке
        beton = _parse_number(row[COL_BETON_M3 - 1], divide_by_100=True)

        coef_a = round(steel / beton, 4) if steel and beton and beton > 0 else None

        objects.append(Element(
            tmarka_elementa = name,
            tclass_betona   = BETON_CLASS_FULL,
            tthickness      = None,
            tbeton_m3       = beton,
            tstal_kg        = steel,
            tcoef_a         = coef_a,
        ))

    return objects


# ── Запись в PostgreSQL ───────────────────────────────────────────────────────
def load_to_db(objects: list[Element]) -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
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

    print(f"\n{'tmarka_elementa':<50} {'tstal_kg':>10} {'tbeton_m3':>10} {'tcoef_a':>10}")
    print("-" * 85)
    for e in rows[:10]:
        s = f"{e.tstal_kg:.2f}"  if e.tstal_kg  is not None else "—"
        b = f"{e.tbeton_m3:.2f}" if e.tbeton_m3 is not None else "—"
        c = f"{e.tcoef_a:.4f}"   if e.tcoef_a   is not None else "—"
        print(f"{(e.tmarka_elementa or ''):<50} {s:>10} {b:>10} {c:>10}")

    print(f"\n💾 Записываем в PostgreSQL...")
    load_to_db(rows)

# --- END OF PARSE PDF-EXCEL TABLES ---