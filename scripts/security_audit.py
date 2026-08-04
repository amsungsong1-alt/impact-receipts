"""
scripts/security_audit.py

Laudon Ch.8 hardening, C9: internal information-systems audit. Examines the
firm's overall security environment and the controls governing individual
systems, and lists/ranks control weaknesses by probability and impact — the
exact format A3 describes for a risk assessment, applied here as a
recurring, automatable check rather than a one-time document.

Each check degrades gracefully and independently: a check that needs a live
Postgres connection (SUPABASE_DB_URL) or an external tool (gitleaks,
pip-audit) on PATH reports itself as SKIPPED rather than failing the whole
run, matching this codebase's existing degrade-gracefully convention
(utils/db.py, utils/audits.py). Run manually or on a schedule (cron, a
GitHub Actions scheduled workflow) -- this is a standalone script, not part
of the test_*.py suite, since it can take real time (network calls to OSV,
a live DB query) and isn't a pass/fail gate for a code change the way the
tests are.

Run with: python scripts/security_audit.py
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

# Allows `python scripts/security_audit.py` from any cwd to import utils.* --
# scripts/ is not a package with its own utils/, the repo root is.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class Weakness:
    check: str
    weakness: str
    probability: str  # Low | Medium | High
    impact: str        # Low | Medium | High | Very High
    remediation: str


@dataclass
class CheckResult:
    name: str
    status: str  # OK | WEAKNESS | SKIPPED
    weaknesses: list = field(default_factory=list)
    note: str = ""


_SEVERITY_RANK = {"Low": 0, "Medium": 1, "High": 2, "Very High": 3}


def _severity_score(w: Weakness) -> int:
    return _SEVERITY_RANK.get(w.probability, 0) + _SEVERITY_RANK.get(w.impact, 0)


# ---------------------------------------------------------------------------
# 1. RLS coverage -- always runs, no live DB needed (static migration parse).
# ---------------------------------------------------------------------------

def check_rls_coverage() -> CheckResult:
    from utils.rls_coverage import compute_rls_state, EXEMPT_TABLES
    tables, rls_state, policy_counts = compute_rls_state()
    weaknesses = []
    for t in sorted(tables):
        if t in EXEMPT_TABLES:
            continue
        if rls_state.get(t) != "enable":
            weaknesses.append(Weakness(
                "rls_coverage", f"Table '{t}' does not have RLS enabled.",
                "Medium", "Very High",
                f"Add 'alter table {t} enable row level security;' plus at least one policy, "
                f"or add {t!r} to utils/rls_coverage.py's EXEMPT_TABLES with a documented reason.",
            ))
        elif policy_counts.get(t, 0) == 0:
            weaknesses.append(Weakness(
                "rls_coverage", f"Table '{t}' has RLS enabled but zero policies (silent deny-all).",
                "Low", "Medium",
                f"Add at least one 'create policy ... on {t} ...' statement.",
            ))
    return CheckResult("RLS coverage", "OK" if not weaknesses else "WEAKNESS", weaknesses)


# ---------------------------------------------------------------------------
# 2. Unencrypted sensitive columns -- static check against known-sensitive
#    column names declared across the migrations.
# ---------------------------------------------------------------------------

_KNOWN_ENCRYPTED_COLUMNS = {
    ("audits", "submissions_json"), ("audits", "evaluations_json"),
    ("logframe_library_items", "indicator_name"),
    ("logframe_library_items", "logframe_indicator"),
    ("logframe_library_items", "logframe_baseline"),
    ("logframe_library_items", "logframe_target"),
    ("logframe_library_items", "logframe_achievement"),
    ("sessions", "auth_access_token"), ("sessions", "auth_refresh_token"),
    ("users", "totp_secret"),
}
# Column-name substrings that suggest free-text/sensitive content -- if a
# future migration adds one of these to a table NOT in the encrypted set
# above, that's worth a human looking at, not necessarily a real problem
# (many legitimate columns match, e.g. "sector" is a constrained dropdown,
# not free text -- this check is a prompt to review, not an automatic verdict).
_SENSITIVE_NAME_HINTS = ("narrative", "evidence_text", "indicator_name", "beneficiary")


def check_unencrypted_columns() -> CheckResult:
    import re
    from utils.rls_coverage import _MIGRATIONS_DIR
    weaknesses = []
    seen_columns = set()
    add_col_re = re.compile(
        r'alter\s+table\s+(?:if\s+exists\s+)?"?(\w+)"?\s+add\s+column\s+(?:if\s+not\s+exists\s+)?"?(\w+)"?',
        re.IGNORECASE,
    )
    for fname in sorted(os.listdir(_MIGRATIONS_DIR)):
        if not fname.endswith(".sql"):
            continue
        with open(os.path.join(_MIGRATIONS_DIR, fname), "r", encoding="utf-8") as fh:
            content = fh.read()
        for m in add_col_re.finditer(content):
            table, col = m.group(1).lower(), m.group(2).lower()
            seen_columns.add((table, col))
            if (table, col) not in _KNOWN_ENCRYPTED_COLUMNS and any(
                hint in col for hint in _SENSITIVE_NAME_HINTS
            ):
                weaknesses.append(Weakness(
                    "unencrypted_columns",
                    f"Column {table}.{col} looks like free-text/sensitive content "
                    f"and is not in the known-encrypted allowlist.",
                    "Low", "Medium",
                    f"Review whether {table}.{col} should be Fernet-encrypted "
                    f"(utils/crypto.py) like {sorted(_KNOWN_ENCRYPTED_COLUMNS)[:1]}, "
                    f"or add it to _KNOWN_ENCRYPTED_COLUMNS here if it's deliberately plaintext.",
                ))
    return CheckResult("Unencrypted sensitive columns", "OK" if not weaknesses else "WEAKNESS", weaknesses)


# ---------------------------------------------------------------------------
# 3. Secrets in the repo -- invokes gitleaks if it's on PATH; skips otherwise.
# ---------------------------------------------------------------------------

def check_secrets_in_repo() -> CheckResult:
    gitleaks = shutil.which("gitleaks")
    if not gitleaks:
        return CheckResult("Secrets in repo (gitleaks)", "SKIPPED",
                            note="gitleaks not found on PATH -- install it to enable this check "
                                 "(see .pre-commit-config.yaml for the version this repo expects).")
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        proc = subprocess.run(
            [gitleaks, "detect", "--source", repo_root, "--config",
             os.path.join(repo_root, ".gitleaks.toml"), "--log-opts=--all",
             "--no-banner", "--report-format", "json", "--report-path", "-"],
            capture_output=True, text=True, timeout=180,
        )
        # gitleaks exits 1 when leaks are found, 0 when clean -- both are a
        # successful run of the tool itself, not a script error.
        findings = json.loads(proc.stdout) if proc.stdout.strip() else []
    except Exception as exc:
        return CheckResult("Secrets in repo (gitleaks)", "SKIPPED",
                            note=f"gitleaks run failed: {type(exc).__name__}: {exc}")
    weaknesses = [
        Weakness("secrets_in_repo",
                 f"Possible secret found in git history: {f.get('File')}:{f.get('StartLine')} "
                 f"(rule {f.get('RuleID')}).",
                 "Medium", "High",
                 "Review the finding; if genuine, rotate the credential immediately and purge "
                 "it from history. If a false positive, add it to .gitleaks.toml's allowlist "
                 "with a dated comment, matching the two existing entries there.")
        for f in findings
    ]
    return CheckResult("Secrets in repo (gitleaks)", "OK" if not weaknesses else "WEAKNESS", weaknesses)


# ---------------------------------------------------------------------------
# 4. Dependency CVEs -- invokes pip-audit against requirements.txt.
# ---------------------------------------------------------------------------

def check_dependency_cves() -> CheckResult:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    req_path = os.path.join(repo_root, "requirements.txt")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip_audit", "-r", req_path, "--format", "json"],
            capture_output=True, text=True, timeout=300,
        )
    except FileNotFoundError:
        return CheckResult("Dependency CVEs (pip-audit)", "SKIPPED",
                            note="pip-audit not installed -- `pip install pip-audit` to enable this check.")
    except Exception as exc:
        return CheckResult("Dependency CVEs (pip-audit)", "SKIPPED",
                            note=f"pip-audit run failed: {type(exc).__name__}: {exc}")
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return CheckResult("Dependency CVEs (pip-audit)", "SKIPPED",
                            note=f"Could not parse pip-audit output: {proc.stdout[:200]}")
    weaknesses = []
    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            weaknesses.append(Weakness(
                "dependency_cve",
                f"{dep.get('name')}=={dep.get('version')} has known vulnerability {vuln.get('id')}.",
                "Medium", "High",
                f"Upgrade {dep.get('name')} to a fixed version "
                f"({vuln.get('fix_versions') or 'see advisory'}) in requirements.txt, "
                f"then run the full test suite before committing the bump.",
            ))
    return CheckResult("Dependency CVEs (pip-audit)", "OK" if not weaknesses else "WEAKNESS", weaknesses)


# ---------------------------------------------------------------------------
# 5. Retention-policy violations -- needs a live DB; skips otherwise.
# ---------------------------------------------------------------------------

def check_retention_violations(days_threshold: int = 730) -> CheckResult:
    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        return CheckResult("Retention policy violations", "SKIPPED",
                            note="SUPABASE_DB_URL not set -- cannot query live audits table. "
                                 "Also note: ImpactProof has no automatic retention/expiry policy "
                                 "today (docs/compliance/records_of_processing.md, open item #13) -- "
                                 "this check can only flag OLD records against an illustrative "
                                 "threshold, it cannot enforce a policy that doesn't exist yet.")
    try:
        from sqlalchemy import create_engine, text
        from datetime import datetime, timedelta, timezone
        engine = create_engine(db_url, pool_pre_ping=True)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)
        with engine.connect() as conn:
            count = conn.execute(
                text("select count(*) from audits where created_at < :cutoff"),
                {"cutoff": cutoff},
            ).scalar()
    except Exception as exc:
        return CheckResult("Retention policy violations", "SKIPPED",
                            note=f"Could not query live database: {type(exc).__name__}: {exc}")
    if not count:
        return CheckResult("Retention policy violations", "OK", [])
    return CheckResult("Retention policy violations", "WEAKNESS", [Weakness(
        "retention_violation",
        f"{count} saved audit(s) are older than {days_threshold} days with no retention policy "
        f"to act on them (no auto-delete exists today).",
        "High", "Medium",
        "Decide and implement a retention window (docs/compliance/records_of_processing.md, "
        "open item #13), then re-run this check to confirm it drops to zero going forward.",
    )])


# ---------------------------------------------------------------------------
# 6. Expiring TLS certificates -- only meaningful on the VPS/Docker path.
# ---------------------------------------------------------------------------

def check_expiring_certificates(warn_within_days: int = 21) -> CheckResult:
    cert_glob_dir = "/etc/letsencrypt/live"
    if not os.path.isdir(cert_glob_dir):
        return CheckResult("Expiring TLS certificates", "SKIPPED",
                            note="No /etc/letsencrypt/live directory found -- not running on the "
                                 "VPS/Docker deployment path, or certbot hasn't issued a cert here yet.")
    import glob
    import ssl
    from datetime import datetime, timezone
    weaknesses = []
    for cert_path in glob.glob(os.path.join(cert_glob_dir, "*", "fullchain.pem")):
        try:
            cert_dict = ssl._ssl._test_decode_cert(cert_path)
            expires = datetime.strptime(cert_dict["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days_left = (expires - datetime.now(timezone.utc)).days
            if days_left < warn_within_days:
                weaknesses.append(Weakness(
                    "expiring_certificate", f"Certificate at {cert_path} expires in {days_left} day(s).",
                    "High" if days_left < 7 else "Medium", "High",
                    "Confirm the host-crontab certbot renewal job is running "
                    "(docker-compose's restart:unless-stopped does NOT renew certs on its own -- "
                    "see nginx/conf.d/impactproof.conf's header comment).",
                ))
        except Exception as exc:
            weaknesses.append(Weakness(
                "expiring_certificate", f"Could not read certificate at {cert_path}: {exc}",
                "Low", "Medium", "Investigate manually.",
            ))
    return CheckResult("Expiring TLS certificates", "OK" if not weaknesses else "WEAKNESS", weaknesses)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def run_all_checks() -> list[CheckResult]:
    return [
        check_rls_coverage(),
        check_unencrypted_columns(),
        check_secrets_in_repo(),
        check_dependency_cves(),
        check_retention_violations(),
        check_expiring_certificates(),
    ]


def print_report(results: list[CheckResult]) -> int:
    all_weaknesses = [w for r in results for w in r.weaknesses]
    all_weaknesses.sort(key=_severity_score, reverse=True)

    print("=" * 70)
    print("ImpactProof internal security audit (Laudon Ch.8, C9)")
    print("=" * 70)
    for r in results:
        marker = {"OK": "[OK]     ", "WEAKNESS": "[WEAKNESS]", "SKIPPED": "[SKIPPED]"}[r.status]
        print(f"{marker} {r.name}" + (f" -- {r.note}" if r.note else ""))
    print()

    if not all_weaknesses:
        print("No weaknesses found by any check that actually ran.")
        return 0

    print(f"{len(all_weaknesses)} weakness(es), ranked most severe first:\n")
    for i, w in enumerate(all_weaknesses, 1):
        print(f"{i}. [{w.probability} probability / {w.impact} impact] ({w.check}) {w.weakness}")
        print(f"   Remediation: {w.remediation}\n")
    return 1


def main() -> None:
    results = run_all_checks()
    sys.exit(print_report(results))


if __name__ == "__main__":
    main()
