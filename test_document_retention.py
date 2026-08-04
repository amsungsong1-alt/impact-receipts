"""
test_document_retention.py — regression test locking in ImpactProof's
single highest-value security control (Laudon Ch.8, C2): uploaded document
bytes are processed in-memory only and never persisted to disk or Supabase
Storage. What has never been written down cannot leak.

No pytest, no network calls: this statically inspects the source of every
function that actually reads uploaded file bytes (confirmed via prior audit
to be exactly these five -- app.py's shared parser and its four callers) for
disk-write or Storage-upload calls, and separately confirms no
`storage.from_(...)` call exists anywhere in the codebase at all. A future
change that starts writing uploaded bytes to disk or Storage inside one of
these functions will fail this test; a change to an unrelated function
(e.g. generating a downloadable report into an io.BytesIO buffer, which is
not a retention concern) will not.

Run with: python test_document_retention.py
"""
import inspect
import os
import re

import app

_DISK_OR_STORAGE_PATTERNS = [
    re.compile(r'open\([^)]*["\']\s*w\s*b'),   # open(..., "wb") / 'wb'
    re.compile(r'\bNamedTemporaryFile\b'),
    re.compile(r'\btempfile\.'),
    re.compile(r'\.storage\.from_\('),
    re.compile(r'\.storage\.\w+\('),
]

# Every function in app.py that actually reads bytes from an uploaded file
# (confirmed via audit of every st.file_uploader call site -- the other two
# upload widgets, "Attach supporting documents" and the Governance DPP
# upload, never call .read()/.getvalue() on the file at all, only .name).
_UPLOAD_HANDLING_FUNCTIONS = [
    "_extract_text_from_file",
    "_extract_report_fields",
    "_irc_extract_combined",
    "_extract_all_results_from_document",
    "_score_report_from_document",
]


def run_upload_handling_functions_never_persist_bytes():
    failures = []
    for fname in _UPLOAD_HANDLING_FUNCTIONS:
        fn = getattr(app, fname, None)
        assert fn is not None, f"app.{fname} not found -- has it been renamed? Update this test's list."
        source = inspect.getsource(fn)
        for pattern in _DISK_OR_STORAGE_PATTERNS:
            if pattern.search(source):
                failures.append(
                    f"app.{fname} matches disk/Storage-persistence pattern {pattern.pattern!r} -- "
                    f"uploaded document bytes must stay in-memory only."
                )
    assert not failures, "\n".join(failures)
    print(f"PASS: run_upload_handling_functions_never_persist_bytes "
          f"({len(_UPLOAD_HANDLING_FUNCTIONS)} functions checked)")


def run_no_supabase_storage_usage_anywhere():
    """A second, whole-repo-scoped check: this app has never had a
    Supabase Storage bucket wired up at all (uploaded content is discarded
    after extraction, not archived) -- if that ever changes, it must be a
    deliberate, reviewed decision, not something that silently appears
    inside an unrelated code path this test's function-level check above
    doesn't happen to cover."""
    root = os.path.dirname(os.path.abspath(__file__))
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (
            ".git", "venv", "__pycache__", "node_modules", "impact-receipts"
        )]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            if fname.startswith("test_"):
                continue  # this file and its siblings may legitimately mention the pattern in comments
            path = os.path.join(dirpath, fname)
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            if re.search(r'\.storage\.from_\(', content):
                hits.append(path)
    assert not hits, f"Supabase Storage usage found (expected none): {hits}"
    print("PASS: run_no_supabase_storage_usage_anywhere")


if __name__ == "__main__":
    run_upload_handling_functions_never_persist_bytes()
    run_no_supabase_storage_usage_anywhere()
    print("\nAll test_document_retention.py tests passed.")
