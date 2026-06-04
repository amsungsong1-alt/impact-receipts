"""
Strip PII from field values before storing as training examples.
Removes emails, phone numbers, URLs. Truncates at 200 chars.
Returns None if result is too short to be useful.
"""
import re

_PATTERNS = [
    re.compile(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}'),   # email
    re.compile(r'[\+\d][\d\s\-\(\)]{7,}'),             # phone
    re.compile(r'https?://\S+'),                        # URL
]

def anonymize(text: str) -> str | None:
    if not text or not isinstance(text, str):
        return None
    cleaned = text.strip()
    for pat in _PATTERNS:
        cleaned = pat.sub('[REDACTED]', cleaned)
    cleaned = cleaned[:200].strip()
    return cleaned if len(cleaned) >= 10 else None
