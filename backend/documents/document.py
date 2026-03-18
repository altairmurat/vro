#from main import get_pdf

#pdf_path = get_pdf()

from pypdf import PdfReader

def is_scan(pdf_path):
    try:
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            text = page.extract_text()
            if not text or len(text.strip()) < 50:
                if '/XObject' in page['/Resources']:
                    return True #текста нет, есть картинки, скан
        return False #текст можно извлечь, печатный
    except Exception as e:
        return f"Failed to read pdf: {e}"
    
import pandas as pd
def is_pdf_or_excell(file_path):
    file_path.split('.')[-1]
    
    
    
    
print(is_pdf_or_excell("./documents/pdf_vor/1590-Р-КЖ1.1.-1_стены_минус_1_башня_(24.12.2025).pdf"))