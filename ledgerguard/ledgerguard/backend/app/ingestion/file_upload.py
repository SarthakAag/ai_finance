from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from app.ingestion.normalizer import (
    detect_source,
    normalize_dataframe,
)
from app.ingestion.parser import (
    FileParseError,
    is_document_file,
    is_tabular_file,
    parse_pdf_text,
    parse_tabular_file,
)
from app.ingestion.validators import validate_transactions


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]

UPLOAD_DIR = BASE_DIR / "uploads"

SOURCE_DIRECTORIES = {
    "bank": UPLOAD_DIR / "bank",
    "razorpay": UPLOAD_DIR / "razorpay",
    "ledger": UPLOAD_DIR / "ledger",
    "invoice": UPLOAD_DIR / "invoices",
    "unknown": UPLOAD_DIR / "documents",
}

ALLOWED_EXTENSIONS = {
    ".xlsx",
    ".xls",
    ".csv",
    ".pdf",
}

MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB


class UploadValidationError(Exception):
    """Raised when an uploaded file is invalid."""


# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------

def ensure_upload_directories() -> None:
    """Create all upload directories if they don't already exist."""

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    for directory in SOURCE_DIRECTORIES.values():
        directory.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# File validation
# ---------------------------------------------------------------------------

def validate_filename(filename: str | None) -> str:
    """
    Validate and sanitize an uploaded filename.

    We never trust the original filename as a filesystem path.
    """

    if not filename:
        raise UploadValidationError("Uploaded file has no filename.")

    filename = Path(filename).name

    if filename in {"", ".", ".."}:
        raise UploadValidationError("Invalid filename.")

    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            f"Unsupported file type '{extension}'. "
            f"Allowed types: {sorted(ALLOWED_EXTENSIONS)}"
        )

    return filename


def validate_file_size(file_path: Path) -> int:
    """Validate the saved file size."""

    size = file_path.stat().st_size

    if size == 0:
        raise UploadValidationError("Uploaded file is empty.")

    if size > MAX_FILE_SIZE:
        raise UploadValidationError(
            f"File is too large. Maximum allowed size is "
            f"{MAX_FILE_SIZE // (1024 * 1024)} MB."
        )

    return size


# ---------------------------------------------------------------------------
# Saving uploaded files
# ---------------------------------------------------------------------------

async def save_upload(
    upload_file: UploadFile,
) -> dict[str, Any]:
    """
    Save an uploaded file safely.

    The file is first stored in the temporary 'unknown' directory.
    Once the source is detected, it can be moved into the appropriate
    source directory.
    """

    ensure_upload_directories()

    filename = validate_filename(upload_file.filename)

    unique_id = uuid.uuid4().hex

    extension = Path(filename).suffix.lower()

    safe_filename = f"{unique_id}{extension}"

    temporary_directory = SOURCE_DIRECTORIES["unknown"]

    destination = temporary_directory / safe_filename

    try:
        with destination.open("wb") as output_file:
            shutil.copyfileobj(
                upload_file.file,
                output_file,
            )

    except Exception as exc:
        if destination.exists():
            destination.unlink()

        raise UploadValidationError(
            f"Could not save uploaded file: {exc}"
        ) from exc

    size = validate_file_size(destination)

    return {
        "original_filename": filename,
        "stored_filename": safe_filename,
        "path": str(destination),
        "size": size,
        "extension": extension,
    }


# ---------------------------------------------------------------------------
# Source-specific storage
# ---------------------------------------------------------------------------

def move_to_source_directory(
    file_path: str | Path,
    source: str,
) -> Path:
    """
    Move a temporarily uploaded file into the directory corresponding
    to its detected source.
    """

    source = source if source in SOURCE_DIRECTORIES else "unknown"

    destination_directory = SOURCE_DIRECTORIES[source]

    destination_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    current_path = Path(file_path)

    destination = destination_directory / current_path.name

    if current_path.resolve() != destination.resolve():
        shutil.move(
            str(current_path),
            str(destination),
        )

    return destination


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------

def process_tabular_upload(
    file_path: str | Path,
    original_filename: str,
    source_override: str | None = None,
) -> dict[str, Any]:
    """
    Parse, detect, normalize and validate a CSV/XLS/XLSX upload.
    """

    try:
        dataframe = parse_tabular_file(file_path)
    except FileParseError:
        raise
    except Exception as exc:
        raise UploadValidationError(
            f"Unable to read spreadsheet: {exc}"
        ) from exc

    if dataframe.empty:
        raise UploadValidationError(
            "The uploaded spreadsheet contains no data."
        )

    detected_source = (
        source_override
        if source_override
        else detect_source(
            dataframe,
            original_filename,
        )
    )

    if detected_source == "unknown":
        raise UploadValidationError(
            "Could not identify the payment source automatically. "
            "Please select Bank, Razorpay, Ledger, or Invoice."
        )

    transactions = normalize_dataframe(
        dataframe=dataframe,
        source=detected_source,
        filename=original_filename,
    )

    validation_report = validate_transactions(
        transactions
    )

    return {
        "type": "tabular",
        "source": detected_source,
        "filename": original_filename,
        "rows_read": len(dataframe),
        "transactions_created": len(transactions),
        "columns": [
            str(column)
            for column in dataframe.columns
        ],
        "transactions": [
            transaction.to_dict()
            for transaction in transactions
        ],
        "validation": validation_report,
    }


def process_document_upload(
    file_path: str | Path,
    original_filename: str,
) -> dict[str, Any]:
    """
    Process a PDF payment-related document.

    The extracted text is returned for the document/RAG pipeline.
    """

    try:
        text = parse_pdf_text(file_path)
    except FileParseError:
        raise
    except Exception as exc:
        raise UploadValidationError(
            f"Unable to read PDF: {exc}"
        ) from exc

    if not text.strip():
        return {
            "type": "document",
            "source": "unknown",
            "filename": original_filename,
            "text": "",
            "text_length": 0,
            "warning": (
                "No text could be extracted from the PDF. "
                "It may be a scanned/image-only document."
            ),
        }

    return {
        "type": "document",
        "source": "unknown",
        "filename": original_filename,
        "text": text,
        "text_length": len(text),
    }


# ---------------------------------------------------------------------------
# Main upload processor
# ---------------------------------------------------------------------------

async def process_upload(
    upload_file: UploadFile,
    source_override: str | None = None,
) -> dict[str, Any]:
    """
    Complete LedgerGuard upload pipeline.

    Flow:

        Frontend
            ↓
        UploadFile
            ↓
        Validate
            ↓
        Save
            ↓
        Detect source
            ↓
        Parse
            ↓
        Normalize
            ↓
        Validate records
            ↓
        Return structured result
    """

    saved_file = await save_upload(
        upload_file
    )

    original_filename = saved_file["original_filename"]

    file_path = Path(
        saved_file["path"]
    )

    try:
        if is_tabular_file(file_path):

            result = process_tabular_upload(
                file_path=file_path,
                original_filename=original_filename,
                source_override=source_override,
            )

            detected_source = result["source"]

            final_path = move_to_source_directory(
                file_path=file_path,
                source=detected_source,
            )

            result["stored_path"] = str(
                final_path
            )

            result["stored_filename"] = (
                final_path.name
            )

            return result

        if is_document_file(file_path):

            result = process_document_upload(
                file_path=file_path,
                original_filename=original_filename,
            )

            result["stored_path"] = str(
                file_path
            )

            result["stored_filename"] = (
                file_path.name
            )

            return result

        raise UploadValidationError(
            "Unsupported file format."
        )

    except Exception:
        # Keep the uploaded file for debugging/audit only if processing
        # reached the save stage. Do not silently delete user data.
        raise