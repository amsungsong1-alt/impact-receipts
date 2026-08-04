"""
utils/upload_guard.py — input controls for the document-upload path (Laudon
Ch.8, C1). Trusts nothing about a claimed filename: checks the actual bytes
against a magic-byte signature for the declared type, rejects (never
sanitizes) macro-bearing OOXML content, and enforces a size cap before any
parser (pdfplumber/python-docx/python-pptx/pandas+openpyxl) ever touches the
file. Every one of those parsers is a document-parsing library, not a
scripting engine, so this module's job isn't "detect malware" -- it's
closing the specific, checkable gaps the app had: extension-only trust, no
size cap, and no rejection of a format class (macro-enabled Office files)
this app has never intended to support.

validate_upload() is called BEFORE bytes are handed to any parser. A
rejection here must always fail closed (reject), never attempt to strip/
sanitize the offending content and continue -- see the prompt's own
instruction: "reject rather than sanitise."
"""
from __future__ import annotations
import io
import zipfile

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB -- generous for a text-bearing
                                      # report, small enough to bound parse
                                      # time/memory for an in-memory-only
                                      # pipeline (see app.py's
                                      # _extract_text_from_file)

# Extension -> the family of magic-byte signatures a genuine file of that
# type must start with. Checked BEFORE any parser runs -- a mismatch means
# the content doesn't match the claimed type, regardless of what Streamlit's
# UI-level `type=` filter (an <input accept> hint, not a hard guarantee)
# allowed through.
_PDF_MAGIC = (b"%PDF-",)
_OOXML_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE2_MAGIC = (b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1",)

_ALLOWED_EXTENSIONS = {
    "pdf": _PDF_MAGIC,
    "docx": _OOXML_ZIP_MAGIC,
    "pptx": _OOXML_ZIP_MAGIC,
    "xlsx": _OOXML_ZIP_MAGIC,
    "xls": _OLE2_MAGIC,
    "txt": None,   # plain text has no reliable magic-byte signature
    "csv": None,
    "json": None,  # validated structurally instead, see _looks_like_json
}

# Macro-enabled Office formats are never in _ALLOWED_EXTENSIONS above (this
# app has never intended to accept them), but OOXML doesn't require a file's
# extension to match its actual content -- a file named "report.docx" can
# still be a macro-enabled document internally. Reject by inspecting the zip
# for a macro project part, not just by extension string-matching.
_MACRO_EXTENSIONS = {"docm", "xlsm", "pptm", "xlsb", "xlam", "dotm", "potm", "ppam", "ppsm"}


def _extension_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _looks_like_json(raw: bytes) -> bool:
    import json
    try:
        json.loads(raw.decode("utf-8"))
        return True
    except Exception:
        return False


def _contains_macro_project(raw: bytes) -> bool:
    """True if the zip contains a VBA macro project part
    (word|xl|ppt/vbaProject.bin) -- the actual, content-based signal that a
    file is macro-enabled, independent of its claimed extension."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            return any("vbaproject" in name.lower() for name in zf.namelist())
    except Exception:
        # Not a valid zip at all -- _matches_magic_bytes() will already have
        # rejected this before _contains_macro_project is ever reached for a
        # claimed-OOXML file, so this branch is defensive, not load-bearing.
        return False


def _matches_magic_bytes(raw: bytes, signatures) -> bool:
    if signatures is None:
        return True  # no reliable signature for this type (txt/csv/json)
    return any(raw.startswith(sig) for sig in signatures)


def validate_upload(filename: str, raw: bytes, max_bytes: int = MAX_UPLOAD_BYTES) -> tuple[bool, str]:
    """Validate an uploaded file's name + actual bytes before any parser
    touches it. Returns (True, "") if the file may proceed, or (False,
    reason) if it must be rejected outright -- callers must never attempt to
    strip/sanitize and continue on a rejection, only reject.
    """
    if not filename:
        return False, "No filename provided."
    if raw is None:
        return False, "No file content received."
    if len(raw) == 0:
        return False, "The uploaded file is empty."
    if len(raw) > max_bytes:
        return False, (
            f"File is too large ({len(raw) / (1024*1024):.1f} MB). "
            f"The maximum is {max_bytes / (1024*1024):.0f} MB."
        )

    ext = _extension_of(filename)

    if ext in _MACRO_EXTENSIONS:
        return False, (
            f"'.{ext}' files (macro-enabled Office documents) aren't accepted. "
            f"Please save/export as a standard .{'docx' if 'doc' in ext else 'xlsx' if 'xl' in ext else 'pptx'} "
            f"file without macros and re-upload."
        )

    if ext not in _ALLOWED_EXTENSIONS:
        return False, (
            f"'.{ext}' files aren't accepted. Supported types: "
            + ", ".join(sorted(k for k in _ALLOWED_EXTENSIONS if k != "json"))
        )

    if ext == "json":
        if not _looks_like_json(raw):
            return False, "This .json file isn't valid JSON."
        return True, ""

    signatures = _ALLOWED_EXTENSIONS[ext]
    if not _matches_magic_bytes(raw, signatures):
        return False, (
            f"This file's content doesn't match a genuine .{ext} file "
            f"(failed a content check, not just a filename check). It may be "
            f"mislabeled, corrupted, or a different file type renamed to .{ext}."
        )

    if ext in ("docx", "pptx", "xlsx") and _contains_macro_project(raw):
        return False, (
            f"This .{ext} file contains an embedded macro project, which "
            f"isn't accepted regardless of its extension. Please remove any "
            f"macros (Save As without macro-enabled format) and re-upload."
        )

    return True, ""
