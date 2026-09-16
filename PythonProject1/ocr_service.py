"""Invoice text extraction and field parsing.

Text PDFs are handled locally with pypdf. Image/scanned PDFs can use the optional
pytesseract/Pillow path when those packages and the Tesseract executable exist.
"""
from datetime import date
from io import BytesIO
import os
from pathlib import Path
import re
import subprocess
import tempfile


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_TESSERACT = Path(r'C:\Program Files\Tesseract-OCR\tesseract.exe')
DEFAULT_TESSDATA = Path(os.getenv('LOCALAPPDATA', str(BASE_DIR / 'ocr_assets'))) / 'TesseractData'
TESSDATA_DIR = Path(os.getenv('TESSDATA_DIR', str(DEFAULT_TESSDATA)))


def _text_from_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    except Exception:
        return ""


def _ocr_image(image) -> str:
    """Run the Windows binary directly to handle its GB18030 OCR output."""
    command = Path(os.getenv('TESSERACT_CMD', DEFAULT_TESSERACT))
    if not command.is_file() or not TESSDATA_DIR.is_dir():
        return ''
    handle = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    temporary = Path(handle.name)
    handle.close()
    try:
        image.convert('RGB').save(temporary)
        result = subprocess.run(
            [str(command), str(temporary), 'stdout', '-l', 'chi_sim+eng', '--tessdata-dir', str(TESSDATA_DIR)],
            capture_output=True, timeout=90, check=False,
        )
        if result.returncode:
            return ''
        for encoding in ('utf-8', 'gb18030'):
            try:
                return result.stdout.decode(encoding)
            except UnicodeDecodeError:
                continue
        return result.stdout.decode('utf-8', errors='replace')
    finally:
        temporary.unlink(missing_ok=True)


def extract_text(path: Path) -> tuple[str, str]:
    text = _text_from_pdf(path) if path.suffix.lower() == ".pdf" else ""
    # Some Chinese electronic invoices expose garbled glyphs to PDF text
    # extraction. Treat that as an OCR fallback case instead of guessing fields.
    parsed = extract_fields(text, path.name) if text.strip() else {}
    usable = (
        bool(re.fullmatch(r'[0-9A-Z-]{6,}', str(parsed.get('invoice_no') or ''))),
        parsed.get('amount') is not None,
        bool(re.fullmatch(r'\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?', str(parsed.get('issue_date') or ''))),
        bool(parsed.get('buyer_name')) and '\ufffd' not in str(parsed.get('buyer_name')),
    )
    if text.strip() and (path.suffix.lower() != '.pdf' or (usable[0] and sum(usable) >= 3)):
        return text, "pdf_text"
    try:
        from PIL import Image
        if path.suffix.lower() != ".pdf":
            return _ocr_image(Image.open(path)), "tesseract"
        import pymupdf
        pages = []
        with pymupdf.open(path) as document:
            for page in list(document)[:3]:
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                image = Image.open(BytesIO(pixmap.tobytes('png')))
                pages.append(_ocr_image(image))
        return "\n".join(pages), "tesseract_pdf"
    except Exception:
        pass
    return "", "unavailable"


def _first(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.M)
        if match:
            return match.group(1).strip()
    return None


def extract_fields(text: str, filename: str) -> dict:
    invoice_no = _first([r"(?:发票号码|票号|Invoice\s*(?:No|Number))\s*[:：]?\s*([0-9A-Z-]{6,})"], text)
    issue_date = _first([r"(?:开票日期|日期|Date)\s*[:：]?\s*(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)", r"(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)"], text)
    buyer_name = _first([r"(?:购买方|购方名称|购方|Buyer)\s*[:：]?\s*(.+)", r"名称\s*[:：]?\s*(.+)"], text)
    if buyer_name:
        buyer_name = re.split(r'\s{2,}|[|｜]', buyer_name, maxsplit=1)[0].strip()
    amount_text = _first([r"(?:价税合计|合计金额|小写|Total)\s*[:：]?\s*[¥￥]?\s*([\d,]+(?:\.\d{1,2})?)", r"[¥￥]\s*([\d,]+(?:\.\d{1,2})?)"], text)
    amount = float(amount_text.replace(",", "")) if amount_text else None
    return {"invoice_no": invoice_no, "amount": amount, "issue_date": issue_date, "buyer_name": buyer_name, "source_filename": filename, "raw_text_length": len(text)}


def recognize_invoice(path: Path, filename: str) -> dict:
    text, method = extract_text(path)
    fields = extract_fields(text, filename)
    fields.update({"ocr_method": method, "recognized": bool(text.strip()), "recognized_at": date.today().isoformat()})
    return fields
