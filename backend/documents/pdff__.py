import os
import cv2
import pytesseract
from pdf2image import convert_from_path
import numpy as np
import pandas as pd
import re
import openpyxl
from pathlib import Path

from sqlalchemy import create_engine, Column, Integer, Float, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from env import DATABASE_URL

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

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
    # ── НОВЫЕ КОЛОНКИ: координаты bbox на странице PDF ──
    bbox_x           = Column(Float, nullable=True)  # px от левого края
    bbox_y           = Column(Float, nullable=True)  # px от верхнего края
    bbox_w           = Column(Float, nullable=True)  # ширина в px
    bbox_h           = Column(Float, nullable=True)  # высота в px
    bbox_page        = Column(Integer, nullable=True) # номер страницы (1-based)
    pdf_page_w       = Column(Float, nullable=True)  # ширина страницы в px (при DPI=300)
    pdf_page_h       = Column(Float, nullable=True)  # высота страницы в px (при DPI=300)


COL_NAME       = 10
COL_STEEL_KG   = 121
COL_BETON_M3   = 161
DATA_ROW_START = 29
DATA_ROW_END   = 225
BETON_CLASS_FULL = "B30 F200 W6"
PDF_DPI        = 300   # должно совпадать с dpi в pdf_page_to_image


def pdf_page_to_image(pdf_path: str, page_number: int = 6):
    pages = convert_from_path(
        pdf_path,
        dpi=PDF_DPI,
        first_page=page_number,
        last_page=page_number,
        poppler_path=r"C:\poppler\poppler-25.12.0\Library\bin",
    )
    if not pages:
        raise ValueError(f"Страница {page_number} не найдена в файле {pdf_path}")
    return pages[0]


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


def map_to_excel(cells, scale=25):
    mapped = []
    for (x, y, w, h, cell_img) in cells:
        text = ocr_cell(cell_img)
        col = int(x / scale)
        row = int(y / scale)
        mapped.append((row, col, text))
    return mapped


def build_excel(mapped_cells, output_file):
    max_row = max([r for r, c, t in mapped_cells]) + 5
    max_col = max([c for r, c, t in mapped_cells]) + 5
    sheet = [["" for _ in range(max_col)] for _ in range(max_row)]
    for r, c, text in mapped_cells:
        sheet[r][c] = text
    df = pd.DataFrame(sheet)
    df.to_excel(output_file, index=False, header=False)


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
    if raw is None:
        return None
    s = str(raw).strip().replace("\xa0", "")
    if s.lower() in _ZERO_STUBS:
        return 0.0
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


# ── НОВАЯ ФУНКЦИЯ: строим индекс ячеек по (excel_row, excel_col) → (px_x, px_y, px_w, px_h)
def build_cell_coord_index(cells, scale=25) -> dict:
    """
    Возвращает словарь { (excel_row, excel_col): (px_x, px_y, px_w, px_h) }
    Используется для сопоставления ячейки Excel с координатами в PDF.
    """
    index = {}
    for (x, y, w, h, _cell_img) in cells:
        col = int(x / scale)
        row = int(y / scale)
        # Если несколько контуров попали в одну клетку — берём наибольший
        if (row, col) not in index or (w * h) > (index[(row, col)][2] * index[(row, col)][3]):
            index[(row, col)] = (x, y, w, h)
    return index


# ── Чтение Excel + координаты ячеек ──────────────────────────────────────────
def extract_rows_with_coords(
    excel_path: str,
    cell_coord_index: dict,
    page_number: int,
    img_w: int,
    img_h: int,
    scale: int = 25,
) -> list[Element]:
    """
    Читает Excel и для каждой строки данных ищет bbox ячейки с именем элемента.
    Координаты нормализуются в диапазон [0..1] относительно размера изображения —
    это делает их независимыми от DPI и позволяет легко перевести в координаты PDF.
    """
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

        steel = _parse_number(row[COL_STEEL_KG - 1], divide_by_100=True)
        beton = _parse_number(row[COL_BETON_M3 - 1], divide_by_100=True)
        coef_a = round(steel / beton, 4) if steel and beton and beton > 0 else None

        # Ищем координаты ячейки с именем в нашем индексе
        # excel_row в нашем маппинге = int(px_y / scale), поэтому ищем по диапазону
        # Колонка имени: COL_NAME = 10 → excel_col близко к этому значению
        bbox_x = bbox_y = bbox_w = bbox_h = None
        best_match = _find_cell_by_excel_row(cell_coord_index, row_idx, COL_NAME, scale)
        if best_match:
            px_x, px_y, px_w, px_h = best_match
            # Нормализуем координаты → [0..1]
            bbox_x = round(px_x / img_w, 6)
            bbox_y = round(px_y / img_h, 6)
            bbox_w = round(px_w / img_w, 6)
            bbox_h = round(px_h / img_h, 6)

        objects.append(Element(
            tmarka_elementa=name,
            tclass_betona=BETON_CLASS_FULL,
            tthickness=None,
            tbeton_m3=beton,
            tstal_kg=steel,
            tcoef_a=coef_a,
            bbox_x=bbox_x,
            bbox_y=bbox_y,
            bbox_w=bbox_w,
            bbox_h=bbox_h,
            bbox_page=page_number,
            pdf_page_w=float(img_w),
            pdf_page_h=float(img_h),
        ))

    return objects


def _find_cell_by_excel_row(
    cell_coord_index: dict,
    excel_data_row: int,   # номер строки в Excel (DATA_ROW_START..DATA_ROW_END)
    target_col: int,       # COL_NAME = 10
    scale: int = 25,
) -> tuple | None:
    """
    Находит ячейку в индексе, чья excel-строка ближайшая к excel_data_row,
    а excel-колонка ближайшая к target_col.
    Допуск: ±3 строки, ±5 колонок.
    """
    best = None
    best_dist = float("inf")
    for (r, c), coords in cell_coord_index.items():
        dr = abs(r - excel_data_row)
        dc = abs(c - target_col)
        if dr <= 3 and dc <= 5:
            dist = dr * 10 + dc   # строки важнее колонок
            if dist < best_dist:
                best_dist = dist
                best = coords
    return best


# ── Запись в PostgreSQL ───────────────────────────────────────────────────────
from sqlalchemy import text

def load_to_db(objects: list) -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        session.execute(text("TRUNCATE TABLE elements RESTART IDENTITY"))
        session.add_all(objects)
        session.commit()
        print(f"✅ Записано {len(objects)} строк в таблицу '{Element.__tablename__}'")


# ── ОСНОВНАЯ ФУНКЦИЯ ──────────────────────────────────────────────────────────
def parse_pdf_all(pdf_path: str) -> dict:
    filename = os.path.basename(pdf_path)
    PAGE_NUMBER = 6
    SCALE = 25

    # Шаг 1: PDF → изображение
    try:
        pil_image = pdf_page_to_image(pdf_path, page_number=PAGE_NUMBER)
        img_w, img_h = pil_image.size   # PIL возвращает (width, height)
    except Exception as e:
        return {"function": "parse_pdf_all", "file": filename,
                "status": "error", "step": "pdf_to_image", "message": str(e)}

    # Шаг 2: OCR → Excel + строим индекс координат
    excel_output = f"layout_page6_{Path(pdf_path).stem}.xlsx"
    try:
        processed = preprocess_image(pil_image)
        mask = detect_table_structure(processed)
        cells = extract_cells(processed, mask)

        if not cells:
            return {"function": "parse_pdf_all", "file": filename,
                    "status": "error", "step": "ocr",
                    "message": "Не найдено ни одной ячейки таблицы на странице 6."}

        # Строим индекс ДО build_excel, пока cells ещё содержит координаты
        cell_coord_index = build_cell_coord_index(cells, scale=SCALE)

        mapped = map_to_excel(cells, scale=SCALE)
        build_excel(mapped, excel_output)
    except Exception as e:
        return {"function": "parse_pdf_all", "file": filename,
                "status": "error", "step": "ocr_to_excel", "message": str(e)}

    # Шаг 3: парсинг Excel с координатами
    try:
        rows = extract_rows_with_coords(
            excel_output,
            cell_coord_index,
            page_number=PAGE_NUMBER,
            img_w=img_w,
            img_h=img_h,
            scale=SCALE,
        )
    except Exception as e:
        return {"function": "parse_pdf_all", "file": filename,
                "status": "error", "step": "parse_excel", "message": str(e)}

    if not rows:
        return {"function": "parse_pdf_all", "file": filename,
                "status": "warning", "step": "parse_excel",
                "message": "Excel создан, но данных для записи не найдено.", "rows_found": 0}

    # Шаг 4: запись в БД
    try:
        load_to_db(rows)
    except Exception as e:
        return {"function": "parse_pdf_all", "file": filename,
                "status": "error", "step": "load_to_db", "message": str(e)}

    try:
        os.remove(excel_output)
    except OSError:
        pass

    rows_with_bbox = sum(1 for r in rows if r.bbox_x is not None)
    return {
        "function": "parse_pdf_all",
        "file": filename,
        "status": "ok",
        "message": f"Готово: {filename}",
        "rows_saved": len(rows),
        "rows_with_bbox": rows_with_bbox,
        "excel_used": excel_output,
    }