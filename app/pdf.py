from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.config import Settings
from app.errors import AnalysisError
from app.models import SourcePage


def read_pdf(data: bytes, settings: Settings) -> list[SourcePage]:
    if not data:
        raise AnalysisError("empty_file", "This file is empty. Choose a PDF with selectable text.")
    if len(data) > settings.max_upload_bytes:
        raise AnalysisError("file_too_large", "Choose a PDF smaller than 10 MB.", 413)
    if not data.startswith(b"%PDF-"):
        raise AnalysisError(
            "invalid_pdf", "This file is not a PDF. Renaming a file does not convert it."
        )
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise AnalysisError(
                "encrypted_pdf", "This PDF is password-protected. Upload an unlocked copy."
            )
        if not reader.pages:
            raise AnalysisError("empty_pdf", "This PDF has no pages.")
        if len(reader.pages) > settings.max_pages:
            raise AnalysisError(
                "too_many_pages", f"Choose a PDF with at most {settings.max_pages} pages."
            )
        pages = []
        total = 0
        for i, page in enumerate(reader.pages, 1):
            # Refuse oversized uncompressed streams before text extraction where possible.
            contents = page.get_contents()
            if contents and len(contents.get_data()) > 5_000_000:
                raise AnalysisError(
                    "complex_pdf", "A PDF page is too complex. Split or simplify this file."
                )
            text = (page.extract_text() or "").strip()
            total += len(text)
            if total > settings.max_text_chars:
                raise AnalysisError(
                    "too_much_text", "This PDF exceeds the 120,000-character limit. Split it first."
                )
            pages.append(SourcePage(number=i, text=text))
    except AnalysisError:
        raise
    except (
        PdfReadError,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        NotImplementedError,
        RecursionError,
    ) as exc:
        raise AnalysisError(
            "unreadable_pdf", "This PDF could not be read. Try exporting a new PDF copy."
        ) from exc
    if sum(len(p.text.strip()) for p in pages) < 40:
        raise AnalysisError(
            "ocr_required", "No usable text layer was found. Scanned PDFs need OCR before upload."
        )
    return pages
