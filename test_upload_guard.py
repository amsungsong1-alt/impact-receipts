"""
test_upload_guard.py — golden tests for utils/upload_guard.py (Laudon Ch.8,
C1 input controls on the upload path: extension allowlist, size cap,
content-type/magic-byte verification, and outright rejection -- never
sanitization -- of macro-bearing Office documents).

No pytest, no network calls, no real files on disk: fixtures are built
in-memory (a genuine minimal zip for the OOXML cases via zipfile, raw bytes
for PDF/OLE2 signatures). Run with: python test_upload_guard.py
"""
import io
import zipfile

import utils.upload_guard as guard


def _build_ooxml_zip(extra_names=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")
        for name in extra_names:
            zf.writestr(name, b"dummy")
    return buf.getvalue()


def run_accepts_genuine_pdf():
    raw = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj\n%%EOF"
    ok, reason = guard.validate_upload("report.pdf", raw)
    assert ok, reason
    print("PASS: run_accepts_genuine_pdf")


def run_accepts_genuine_docx():
    raw = _build_ooxml_zip()
    ok, reason = guard.validate_upload("report.docx", raw)
    assert ok, reason
    print("PASS: run_accepts_genuine_docx")


def run_accepts_genuine_xlsx_and_pptx():
    raw = _build_ooxml_zip()
    ok, reason = guard.validate_upload("data.xlsx", raw)
    assert ok, reason
    ok, reason = guard.validate_upload("slides.pptx", raw)
    assert ok, reason
    print("PASS: run_accepts_genuine_xlsx_and_pptx")


def run_accepts_genuine_legacy_xls():
    raw = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1" + b"\x00" * 32
    ok, reason = guard.validate_upload("legacy.xls", raw)
    assert ok, reason
    print("PASS: run_accepts_genuine_legacy_xls")


def run_accepts_txt_csv_and_valid_json():
    ok, _ = guard.validate_upload("notes.txt", b"plain text content")
    assert ok
    ok, _ = guard.validate_upload("data.csv", b"a,b,c\n1,2,3")
    assert ok
    ok, reason = guard.validate_upload("draft.json", b'{"result_statement": "x"}')
    assert ok, reason
    print("PASS: run_accepts_txt_csv_and_valid_json")


def run_rejects_invalid_json():
    ok, reason = guard.validate_upload("draft.json", b"{not valid json")
    assert not ok
    assert "json" in reason.lower()
    print("PASS: run_rejects_invalid_json")


def run_rejects_empty_file():
    ok, reason = guard.validate_upload("report.pdf", b"")
    assert not ok
    assert "empty" in reason.lower()
    print("PASS: run_rejects_empty_file")


def run_rejects_oversized_file():
    raw = b"%PDF-1.4\n" + b"0" * (guard.MAX_UPLOAD_BYTES + 1)
    ok, reason = guard.validate_upload("huge.pdf", raw, max_bytes=guard.MAX_UPLOAD_BYTES)
    assert not ok
    assert "too large" in reason.lower()
    print("PASS: run_rejects_oversized_file")


def run_rejects_unsupported_extension():
    ok, reason = guard.validate_upload("script.exe", b"MZ\x90\x00")
    assert not ok
    assert "exe" in reason.lower()
    print("PASS: run_rejects_unsupported_extension")


def run_rejects_content_type_mismatch():
    """A .docx-named file that is actually a PDF (or vice versa) must be
    rejected by content, not silently accepted because the name looked
    right -- this is the "content-type verification, not extension trust"
    control the prompt specifically calls for."""
    pdf_bytes = b"%PDF-1.4\n%%EOF"
    ok, reason = guard.validate_upload("fake.docx", pdf_bytes)
    assert not ok
    assert "content" in reason.lower()

    docx_bytes = _build_ooxml_zip()
    ok, reason = guard.validate_upload("fake.pdf", docx_bytes)
    assert not ok
    print("PASS: run_rejects_content_type_mismatch")


def run_rejects_macro_extension_outright():
    """Macro-bearing extensions are rejected by name alone, before any
    content is even inspected -- this app has never intended to support
    them, matching "reject rather than sanitise.\""""
    raw = _build_ooxml_zip()
    for ext in ("docm", "xlsm", "pptm", "xlsb"):
        ok, reason = guard.validate_upload(f"file.{ext}", raw)
        assert not ok, f".{ext} should always be rejected"
        assert "macro" in reason.lower()
    print("PASS: run_rejects_macro_extension_outright")


def run_rejects_macro_content_disguised_as_docx():
    """The actual attack this control exists for: a file renamed to .docx
    (passing any naive extension allowlist) that still contains a
    vbaProject.bin macro part internally."""
    raw = _build_ooxml_zip(extra_names=["word/vbaProject.bin"])
    ok, reason = guard.validate_upload("looks_safe.docx", raw)
    assert not ok
    assert "macro" in reason.lower()
    print("PASS: run_rejects_macro_content_disguised_as_docx")


def run_rejects_no_filename_or_none_content():
    ok, _ = guard.validate_upload("", b"data")
    assert not ok
    ok, _ = guard.validate_upload("report.pdf", None)
    assert not ok
    print("PASS: run_rejects_no_filename_or_none_content")


if __name__ == "__main__":
    run_accepts_genuine_pdf()
    run_accepts_genuine_docx()
    run_accepts_genuine_xlsx_and_pptx()
    run_accepts_genuine_legacy_xls()
    run_accepts_txt_csv_and_valid_json()
    run_rejects_invalid_json()
    run_rejects_empty_file()
    run_rejects_oversized_file()
    run_rejects_unsupported_extension()
    run_rejects_content_type_mismatch()
    run_rejects_macro_extension_outright()
    run_rejects_macro_content_disguised_as_docx()
    run_rejects_no_filename_or_none_content()
    print("\nAll test_upload_guard.py tests passed.")
