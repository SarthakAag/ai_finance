from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


SUPPORTED_TABULAR_EXTENSIONS = {".xlsx", ".xls", ".csv"}
SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf"}


class FileParseError(Exception):
    """Raised when an uploaded file cannot be parsed."""


def parse_tabular_file(file_path: str | Path) -> pd.DataFrame:
    """
    Parse CSV/XLS/XLSX files into a pandas DataFrame.

    The parser deliberately does not try to understand whether the file
    belongs to a bank, Razorpay, ledger, or invoice source. That responsibility
    belongs to the normalizer/source detector.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileParseError(f"File does not exist: {path}")

    extension = path.suffix.lower()

    try:
        if extension == ".csv":
            return pd.read_csv(path)

        if extension in {".xlsx", ".xls"}:
            return pd.read_excel(path)

    except Exception as exc:
        raise FileParseError(
            f"Could not parse tabular file '{path.name}': {exc}"
        ) from exc

    raise FileParseError(
        f"Unsupported tabular file type: '{extension}'. "
        f"Supported types: {sorted(SUPPORTED_TABULAR_EXTENSIONS)}"
    )


def parse_pdf_text(file_path: str | Path) -> str:
    """
    Extract text from a PDF.

    This is intended for payment-related documents such as:
    - Bank statement PDFs
    - Settlement reports
    - Payment confirmations
    - Invoices
    - Contracts

    PDF text extraction is intentionally kept separate from tabular parsing.
    Later, the document/RAG layer can process this text independently.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileParseError(f"File does not exist: {path}")

    if path.suffix.lower() != ".pdf":
        raise FileParseError(f"Expected a PDF file, received: {path.suffix}")

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))

        pages: list[str] = []

        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())

        return "\n\n".join(pages)

    except Exception as exc:
        raise FileParseError(
            f"Could not extract text from PDF '{path.name}': {exc}"
        ) from exc


def get_file_extension(file_path: str | Path) -> str:
    """Return the normalized lowercase extension."""
    return Path(file_path).suffix.lower()


def is_tabular_file(file_path: str | Path) -> bool:
    """Return True for CSV/XLS/XLSX files."""
    return get_file_extension(file_path) in SUPPORTED_TABULAR_EXTENSIONS


def is_document_file(file_path: str | Path) -> bool:
    """Return True for supported document files."""
    return get_file_extension(file_path) in SUPPORTED_DOCUMENT_EXTENSIONS


def dataframe_preview(
    dataframe: pd.DataFrame,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Convert a DataFrame preview into JSON-safe dictionaries.

    Useful for showing the user a preview of an uploaded spreadsheet
    before ingestion.
    """
    preview = dataframe.head(limit).copy()

    # Convert timestamps and other pandas-specific values to strings/None
    # so FastAPI can safely serialize the preview.
    preview = preview.astype(object).where(pd.notna(preview), None)

    records = preview.to_dict(orient="records")

    for record in records:
        for key, value in record.items():
            if hasattr(value, "isoformat"):
                record[key] = value.isoformat()

    return records