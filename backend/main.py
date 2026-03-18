from fastapi import FastAPI, status, HTTPException, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Annotated
import pandas as pd
import shutil, os, tempfile
from typing import List, Optional

from database import SessionLocal, engine
from model import models
from env import API_FRONT

app = FastAPI()
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

UPLOAD_DIR = tempfile.mkdtemp()
from router_raschet import router as raschet_router, set_upload_dir
app.include_router(raschet_router)
set_upload_dir(UPLOAD_DIR)

from router_ssopostavlenie import router as ssr_router
app.include_router(ssr_router)

origins = [API_FRONT]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

models.Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


db_dependency = Annotated[Session, Depends(get_db)]


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health-check", status_code=status.HTTP_200_OK)
async def health_check():
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# CCP parsing
# ---------------------------------------------------------------------------

def match_titles(db_rows, list_of_dicts):
    result = []

    for row in db_rows:
        matched_title = None
        confidence_score = 0

        for item in list_of_dicts:
            score = 0

            # marka
            if row.tmarka_elementa.lower()[:4] in item["marka"].split(" "): #стен в листе
                score += 0.5

            # class в пункте может быть B30 B30 F200 W6, а в базе просто B30 F200 W6, поэтому проверяем по частям
            if item["class"]:
                item_classes = set(item["class"].split(", "))
                row_classes = set(row.tclass_betona.split(", ")) if row.tclass_betona else set()
                if item_classes.intersection(row_classes):
                    score += 0.4

            # thickness
            if isinstance(item["thickness"], int):
                if row.tthickness == item["thickness"]:
                    score += 0.1
            else:
                try:
                    low, high = map(int, item["thickness"].split("-"))
                    if low <= row.tthickness <= high:
                        score += 0.1
                except:
                    pass

            # выбираем лучший матч
            if score > confidence_score:
                confidence_score = score
                matched_title = item["punkt"]

        result.append({
            "db_id": row.id,
            "marka": row.tmarka_elementa,
            "class": row.tclass_betona,
            "thickness": row.tthickness,
            "beton": row.tbeton_m3,
            "stal": row.tstal_kg,
            "coef": row.tcoef_a,
            "assigned_punkt": matched_title,
            "confidence": confidence_score,
            "is_match": confidence_score > 0.5  # 🔴 критерий совпадения
        })

    return result

from documents.ccp import punkts_markas_list, receive_punkts_and_elements_ccp
from model.models import StructuralElement

@app.get("/data")
def get_data(db: Session = Depends(get_db)):
    db_rows = db.query(StructuralElement).all()
    
    markas_list = punkts_markas_list()
    list_of_dicts = receive_punkts_and_elements_ccp()

    matched = match_titles(db_rows, list_of_dicts)

    return {
        "rows": matched,
        "titles": markas_list
    }
    
from pydantic import BaseModel

class MappingItem(BaseModel):
    db_id: int
    punkt: str
    thickness: int

from model.models import ProcessedData
@app.post("/submit")
def submit_mapping(data: list[MappingItem], db: Session = Depends(get_db)):

    for item in data:
        original = db.query(StructuralElement).filter(StructuralElement.id == item.db_id).first()

        new_row = ProcessedData(
            db_id=item.db_id,
            punkt=item.punkt,
            thickness=item.thickness,
            marka=original.tmarka_elementa,
            beton=original.tbeton_m3,
            stal=original.tstal_kg,
            coef=original.tcoef_a
        )

        db.add(new_row)

    db.commit()

    return {"status": "saved"}

import re
def extract_info(text):
    unit = None
    cls = None

    if "кг" in text:
        unit = "кг"
    elif "м3" in text:
        unit = "м3"
    elif "%" in text:
        unit = "%"

    match = re.search(r"\((.*?)\)", text)
    if match:
        inside = match.group(1)
        if "B" in inside or "В" in inside:
            cls = inside #what is it:

    return unit, cls

@app.get("/api/aggregation")
def get_aggregation():
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT db_id, punkt, thickness, marka, beton, stal, coef FROM processed_data ORDER BY punkt"
        )).fetchall()
 
        result = []
        groups = {
            "выравнивание": [],
            "фундамент": [],
            "монолит": [],
        }
 
        for row in rows:
            item = {
                "db_id": row.db_id,
                "punkt": row.punkt,
                "thickness": row.thickness,
                "marka": row.marka,
                "beton": row.beton,
                "stal": row.stal,
                "coef": row.coef,
            }
            punkt_lower = (row.punkt or "").lower()
            if "выравнив" in punkt_lower:
                groups["выравнивание"].append(item)
            elif "фундамент" in punkt_lower or "плит" in punkt_lower:
                groups["фундамент"].append(item)
            else:
                groups["монолит"].append(item)
 
        def build_subitem(item):
            return {
                "label": item["punkt"],
                "thickness": item["thickness"],
                "marka": item["marka"],
                "children": [
                    {
                        "label": "Армирование",
                        "value": f"{item['stal']} кг" if item["stal"] else "—",
                        "children": []
                    },
                    {
                        "label": "Бетонирование",
                        "value": f"{item['beton']} м³" if item["beton"] else "—",
                        "children": [
                            {
                                "label": "Класс бетона",
                                "value": item["marka"] or "—",
                                "children": []
                            },
                            {
                                "label": "Коэф. армирования",
                                "value": f"{item['coef']}%" if item["coef"] else "—",
                                "children": []
                            }
                        ]
                    }
                ]
            }
 
        tree = [
            {
                "group": 1,
                "label": "Выравнивание конструкции подземной части",
                "children": [build_subitem(i) for i in groups["выравнивание"]]
            },
            {
                "group": 2,
                "label": "Устройство фундаментной плиты",
                "children": [build_subitem(i) for i in groups["фундамент"]]
            },
            {
                "group": 3,
                "label": "Монолитные работы ниже отм. 0.00",
                "children": [build_subitem(i) for i in groups["монолит"]]
            }
        ]
 
        return {"tree": tree}
    finally:
        db.close()
 
    
import pandas as pd

@app.get("/export")
def export_excel(db: Session = Depends(get_db)):
    rows = db.query(ProcessedData).all()

    df = pd.DataFrame([{
        "punkt": r.punkt,
        "beton": r.beton,
        "stal": r.stal
    } for r in rows])

    file_path = "output.xlsx"
    df.to_excel(file_path, index=False)

    return {"file": file_path}

# ---------------------------------------------------------------------------
# Excel parsing helpers
# ---------------------------------------------------------------------------

CONCRETE_COL_NAME   = 0
CONCRETE_COL_B30W6  = 2
CONCRETE_COL_B30W8  = 3
CONCRETE_COL_B10    = 4
CONCRETE_COL_TOTAL  = 5

STEEL_COL_ARMATURU  = 22

# Row where actual data begins (0-based). Rows 0-5 are merged headers.
DATA_START_ROW = 6

#check whether data is here
def _val(v):
    """Return 0 if NaN, otherwise the value."""
    return 0 if pd.isna(v) else v

#check whether it is concrete or steel
def detect_file_type(df_raw: pd.DataFrame) -> str:
    """
    Returns 'concrete' or 'steel' based on the first cell of the file.
    """
    first_cell = str(df_raw.iloc[0, 0]) if not pd.isna(df_raw.iloc[0, 0]) else ""
    if "бетон" in first_cell.lower():
        return "concrete"
    if "стал" in first_cell.lower():
        return "steel"
    raise ValueError(f"Cannot determine file type from header: '{first_cell}'")

#returns list of dictionaries with all information
def parse_excel_pair(concrete_path: str, steel_path: str) -> list[dict]:
    """
    Merge both Excel files row-by-row into a list of clean records.

    Rules:
    - Only store the кlass_betona class(es) whose value != 0.
    - All other fields come from the non-zero columns.
    - Skip the last "Итого" summary row.
    """
    df_c = pd.read_excel(concrete_path, engine="openpyxl", header=None)
    df_s = pd.read_excel(steel_path,   engine="openpyxl", header=None)

    records = []
    for i in range(DATA_START_ROW, len(df_c)):
        name = _val(df_c.iloc[i, CONCRETE_COL_NAME])

        # Skip empty rows and the summary row
        if not name or str(name).strip().lower() == "итого":
            continue
        
        # to include only Stena elements
        if name.split(' ')[0] != "Стена":
            return records

        #beton
        b30_w6   = _val(df_c.iloc[i, CONCRETE_COL_B30W6])
        b30_w8   = _val(df_c.iloc[i, CONCRETE_COL_B30W8])
        b10      = _val(df_c.iloc[i, CONCRETE_COL_B10])
        total_m3 = _val(df_c.iloc[i, CONCRETE_COL_TOTAL])

        # Only include concrete classes where the value is non-zero
        classes = []
        if b30_w6 != 0:
            classes.append("В30 F200 W6")
        if b30_w8 != 0:
            classes.append("В30 F200 W8")
        if b10 != 0:
            classes.append("В10")
        klass_betona = ", ".join(classes) if classes else None
        
        # Арматуру from the steel file (same row index)
        armaturu = _val(df_s.iloc[i, STEEL_COL_ARMATURU]) if i < len(df_s) else 0

        # Коэффициент арматуризации = armaturu_kg / (concrete_m3 * 7850 кг/м3)
        koeff = round(armaturu * 100 / (total_m3 * 7850), 4) if total_m3 else 0

        import random
        from documents.ccp import list_of_thicknesses
        thicknesses_list = list_of_thicknesses()
        records.append({
            "marka_elementa":        str(name).strip(),
            "class_betona":        klass_betona,
            "thickness": random.choice(thicknesses_list),
            "beton_m3":                  float(total_m3),
            "stal_kg":            round(float(armaturu),4),
            "coef_a": koeff,
        })

    return records

#create necessary table
def ensure_table(table_name: str, db: Session):
    """Create the target table if it does not yet exist."""
    db.execute(text(f"""
        DROP TABLE "{table_name}";
        
        CREATE TABLE IF NOT EXISTS "{table_name}" (
            id                   SERIAL PRIMARY KEY,
            tmarka_elementa         TEXT,
            tclass_betona         TEXT,
            tthickness TEXT,
            tbeton_m3                   NUMERIC,
            tstal_kg             NUMERIC,
            tcoef_a  NUMERIC
        )
    """))
    db.commit()

#insert records into table
def insert_records(table_name: str, records: list[dict], db: Session):
    """Bulk-insert all parsed records into the table."""
    if not records:
        return
    db.execute(
        text(f"""
            INSERT INTO "{table_name}"
                (tmarka_elementa, tclass_betona, tthickness, tbeton_m3, tstal_kg, tcoef_a)
            VALUES
                (:marka_elementa, :class_betona, :thickness, :beton_m3, :stal_kg, :coef_a)
        """),
        records,
    )
    db.commit()

#remake the table name
def sanitize_table_name(filename: str) -> str:
    """Turn a filename into a valid PostgreSQL table name."""
    import re
    name = os.path.splitext(filename)[0].lower()
    name = re.sub(r"[^\w]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if name and name[0].isdigit():
        name = "t_" + name
    #return name or "imported_data"
    return "structural_elements"

# ---------------------------------------------------------------------------
# Upload endpoint — two named xlsx uploads: `beton` and `stal`
# ---------------------------------------------------------------------------

@app.post("/upload-excel", status_code=status.HTTP_201_CREATED)
async def upload_excel(
    db: db_dependency,
    beton: UploadFile = File(..., description="Ведомость расхода бетона (.xlsx)"),
    stal:  UploadFile = File(..., description="Ведомость расхода стали  (.xlsx)"),
):
    """
    Upload two Excel files:
      - field `beton` — concrete sheet (Ведомость расхода бетона)
      - field `stal`  — steel sheet    (Ведомость расхода стали)

    Both must be .xlsx. The endpoint merges them row-by-row, filters
    zero-value concrete class columns, and inserts into PostgreSQL.
    """
    tmp_paths = {}
    try:
        # ── 1. Validate extensions ───────────────────────────────────────────
        for name, upload in (("beton", beton), ("stal", stal)):
            if not upload.filename.lower().endswith(".xlsx"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Field '{name}': only .xlsx files are accepted, "
                           f"got '{upload.filename}'.",
                )

        # ── 2. Save to temp files ────────────────────────────────────────────
        for name, upload in (("beton", beton), ("stal", stal)):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                tmp.write(await upload.read())
                tmp_paths[name] = (tmp.name, upload.filename)

        concrete_path, concrete_fname = tmp_paths["beton"]
        steel_path,    _              = tmp_paths["stal"]

        # ── 3. Parse & merge ─────────────────────────────────────────────────
        records = parse_excel_pair(concrete_path, steel_path)
        if not records:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No data rows found after parsing.",
            )

        # ── 4. Persist to PostgreSQL ─────────────────────────────────────────
        table_name = sanitize_table_name(concrete_fname)
        ensure_table(table_name, db)
        insert_records(table_name, records, db)

        return {
            "status":        "ok",
            "table":         table_name,
            "rows_inserted": len(records),
            "columns": [
                "tmarka_elementa", "class_betona", "thickness",
                "beton_m3", "stal_kg", "coef_a",
            ],
            "preview": records[:3],
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    finally:
        for path, _ in tmp_paths.values():
            try:
                os.unlink(path)
            except OSError:
                pass
            
            
# ---------------------------------------------------------------------------
# ПДФ parsing helpers
# ---------------------------------------------------------------------------



# ─── Stub functions ────────────────────────────────────────────────────────────
from documents.pdff import *
def parse_pdf_all(pdf_path: str) -> dict:
    """
    Полный пайплайн:
      1. Извлекает 6-ю страницу PDF
      2. OCR → Excel-файл
      3. Парсит Excel
      4. Записывает данные в PostgreSQL

    Принимает путь к PDF-файлу, загруженному с фронта.
    Возвращает dict со статусом выполнения.
    """
    filename = os.path.basename(pdf_path)

    # Шаг 1: конвертация 6-й страницы в изображение
    try:
        pil_image = pdf_page_to_image(pdf_path, page_number=6)
    except Exception as e:
        return {
            "function": "parse_pdf_all",
            "file": filename,
            "status": "error",
            "step": "pdf_to_image",
            "message": f"Ошибка при извлечении страницы 6: {e}",
        }

    # Шаг 2: OCR и сохранение в Excel
    excel_output = f"layout_page6_{Path(pdf_path).stem}.xlsx"
    try:
        processed = preprocess_image(pil_image)
        mask = detect_table_structure(processed)
        cells = extract_cells(processed, mask)

        if not cells:
            return {
                "function": "parse_pdf_all",
                "file": filename,
                "status": "error",
                "step": "ocr",
                "message": "Не найдено ни одной ячейки таблицы на странице 6.",
            }

        mapped = map_to_excel(cells, scale=25)
        build_excel(mapped, excel_output)
    except Exception as e:
        return {
            "function": "parse_pdf_all",
            "file": filename,
            "status": "error",
            "step": "ocr_to_excel",
            "message": f"Ошибка при OCR/Excel: {e}",
        }

    # Шаг 3: парсинг Excel
    try:
        rows = extract_rows(excel_output)
    except Exception as e:
        return {
            "function": "parse_pdf_all",
            "file": filename,
            "status": "error",
            "step": "parse_excel",
            "message": f"Ошибка при парсинге Excel: {e}",
        }

    if not rows:
        return {
            "function": "parse_pdf_all",
            "file": filename,
            "status": "warning",
            "step": "parse_excel",
            "message": "Excel создан, но данных для записи не найдено (проверьте диапазон строк).",
            "rows_found": 0,
        }

    # Шаг 4: запись в PostgreSQL
    try:
        load_to_db(rows)
    except Exception as e:
        return {
            "function": "parse_pdf_all",
            "file": filename,
            "status": "error",
            "step": "load_to_db",
            "message": f"Ошибка при записи в БД: {e}",
        }

    # Удаляем временный Excel после успешной загрузки
    try:
        os.remove(excel_output)
    except OSError:
        pass

    return {
        "function": "parse_pdf_all",
        "file": filename,
        "status": "ok",
        "message": f"Полный разбор PDF завершён: {filename}",
        "rows_saved": len(rows),
        "excel_used": excel_output,
    }


def parse_pdf_thicknessonly(pdf_path: str) -> dict:
    """Process one PDF — thickness only. Replace with your real implementation."""
    return {
        "function": "parse_pdf_thicknessonly",
        "file": os.path.basename(pdf_path),
        "status": "ok",
        "message": f"Разбор толщины из PDF завершён: {os.path.basename(pdf_path)}",
    }


import openpyxl

def _detect_excel_type(path: str) -> str:
    """
    Открывает Excel и ищет 'бетон' или 'сталь' в первых 5 строках.
    Возвращает 'beton', 'stal' или бросает ValueError.
    """
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    for row in ws.iter_rows(min_row=1, max_row=5, values_only=True):
        for cell in row:
            if cell is None:
                continue
            val = str(cell).lower()
            if "бетон" in val:
                wb.close()
                return "beton"
            if "сталь" in val or "стал" in val:
                wb.close()
                return "stal"
    wb.close()
    raise ValueError(
        f"Не удалось определить тип файла '{os.path.basename(path)}': "
        "не найдено слово 'бетон' или 'сталь' в первых 5 строках."
    )


def parse_excel(excel_path_1: str, excel_path_2: str, db: Session) -> dict:
    """
    Принимает два уже сохранённых пути к .xlsx файлам.
    Автоматически определяет, какой из них бетон, а какой сталь,
    по наличию слов 'бетон'/'сталь' в заголовках.
    """
    try:
        # ── 1. Определить типы файлов ────────────────────────────────────────
        types = {}
        for path in (excel_path_1, excel_path_2):
            kind = _detect_excel_type(path)
            if kind in types:
                raise ValueError(
                    f"Оба файла определены как '{kind}'. "
                    "Загрузите один файл с бетоном и один со сталью."
                )
            types[kind] = path

        if "beton" not in types or "stal" not in types:
            raise ValueError("Не найден файл для бетона или стали.")

        concrete_path = types["beton"]
        steel_path    = types["stal"]
        concrete_fname = os.path.basename(concrete_path)

        # ── 2. Parse & merge ─────────────────────────────────────────────────
        records = parse_excel_pair(concrete_path, steel_path)
        if not records:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No data rows found after parsing.",
            )

        # ── 3. Persist to PostgreSQL ─────────────────────────────────────────
        table_name = sanitize_table_name(concrete_fname)
        ensure_table(table_name, db)
        insert_records(table_name, records, db)

        return {
            "status":        "ok",
            "function":       "parse_excel",
            "table":         table_name,
            "rows_inserted": len(records),
            "beton_file":    os.path.basename(concrete_path),
            "stal_file":     os.path.basename(steel_path),
            "columns": [
                "tmarka_elementa", "class_betona", "thickness",
                "beton_m3", "stal_kg", "coef_a",
            ],
            "preview": records[:3],
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    
    return {
        "function": "parse_excel",
        "files": [os.path.basename(excel_path_1), os.path.basename(excel_path_2)],
        "status": "ok",
        "message": f"Excel обработан: {os.path.basename(excel_path_1)}, {os.path.basename(excel_path_2)}",
    }


# ─── Helpers ───────────────────────────────────────────────────────────────────

def save_upload(upload: UploadFile) -> str:
    dest = os.path.join(UPLOAD_DIR, upload.filename)
    with open(dest, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest


# ─── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("../frontend/index.html", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.post("/upload/pdf-only")
async def upload_pdf_only(pdf: UploadFile = File(...)):
    """One PDF → parse_pdf_all"""
    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Ожидается PDF-файл")
    path = save_upload(pdf)
    result = parse_pdf_all(path)
    return JSONResponse(result)


@app.post("/upload/pdf-excel")
async def upload_pdf_excel(
    pdf: UploadFile = File(...),
    excel1: UploadFile = File(...),
    excel2: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """One PDF + two Excel → parse_excel + parse_pdf_thicknessonly"""
    if not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Первый файл должен быть PDF")
    for xl in (excel1, excel2):
        if not xl.filename.lower().endswith((".xlsx", ".xls", ".xlsm")):
            raise HTTPException(400, f"Ожидается Excel-файл, получен: {xl.filename}")

    pdf_path = save_upload(pdf)
    xl1_path = save_upload(excel1)
    xl2_path = save_upload(excel2)

    r1 = parse_excel(xl1_path, xl2_path, db)
    r2 = parse_pdf_thicknessonly(pdf_path)
    return JSONResponse({"results": [r1, r2]})


@app.post("/upload/multi-pdf")
async def upload_multi_pdf(pdfs: List[UploadFile] = File(...)):
    """Multiple PDFs → parse_pdf_all for each"""
    for f in pdfs:
        if not f.filename.lower().endswith(".pdf"):
            raise HTTPException(400, f"Ожидается PDF-файл: {f.filename}")

    results = []
    for pdf in pdfs:
        path = save_upload(pdf)
        results.append(parse_pdf_all(path))
    return JSONResponse({"results": results})
    