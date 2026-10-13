"""Look for leaked secrets in the project files and in Git history.

    python scripts/secret_scan.py              # files Git would commit (respects .gitignore)
    python scripts/secret_scan.py --history    # also every line ever added in any commit
    python scripts/secret_scan.py --out docs/secret-scan-report.md

Standard library only. Secrets found are shown redacted (first 4 characters), never in full.
Exit code 0 = nothing found, 1 = something found. It also checks that .env is ignored by Git.

Limits: it matches known key shapes and suspicious assignments. It cannot prove there are no
secrets; it is one check in docs/secrets-audit.md, not the whole audit.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PLACEHOLDER = re.compile(r"(your[-_ ]|example|placeholder|change|xxxx|<|\.\.\.|\$\{|\bpassword\b|\buser:pass)", re.I)

RULES = [
    ("Groq API key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}")),
    ("Langfuse key", re.compile(r"\b(?:pk|sk)-lf-[0-9a-fA-F-]{20,}")),
    ("Cohere API key", re.compile(r"COHERE_API_KEY\s*[=:]\s*[\"']?([A-Za-z0-9]{30,})")),
    ("Database URL with password", re.compile(r"postgres(?:ql)?://[^:\s/@]+:([^@\s]{4,})@")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Secret assignment", re.compile(
        r"\b[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|ACCESS_CODE)\s*[=:]\s*[\"']?([A-Za-z0-9_\-./+]{16,})")),
]
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".ico", ".woff", ".woff2", ".gz", ".pyc"}
SKIP_FILES = {"secret_scan.py", "test_secret_scan.py"}  # contain the patterns themselves


def redact(value: str) -> str:
    return value[:4] + "*" * 6


def scan_text(text: str) -> list[tuple[str, str, int]]:
    """Return (rule, redacted match, line number) for each suspected secret in text."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for name, pattern in RULES:
            match = pattern.search(line)
            if not match:
                continue
            value = match.group(1) if match.groups() else match.group(0)
            if PLACEHOLDER.search(value) or PLACEHOLDER.search(match.group(0)):
                continue
            found.append((name, redact(value), number))
            break
    return found


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def scan_files(root: Path) -> list[tuple[str, str, str, int]]:
    names = git("ls-files", "-co", "--exclude-standard", cwd=root).splitlines()
    results = []
    for name in names:
        path = root / name
        if path.suffix.lower() in SKIP_SUFFIX or path.name in SKIP_FILES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        results += [(name, rule, shown, line) for rule, shown, line in scan_text(text)]
    return results


def scan_history(root: Path) -> list[tuple[str, str, str, int]]:
    """Every line ever added in any commit. A secret removed later is still in history."""
    results, commit, seen = [], "", set()
    log = git("log", "--all", "-p", "--no-color", "--format=commit %h", cwd=root)
    for line in log.splitlines():
        if line.startswith("commit "):
            commit = line[7:]
        elif line.startswith("+") and not line.startswith("+++"):
            for rule, shown, _ in scan_text(line[1:]):
                key = (commit, rule, shown)
                if key not in seen:
                    seen.add(key)
                    results.append((f"commit {commit}", rule, shown, 0))
    return results


def env_file_ignored(root: Path) -> bool | None:
    """True if .env exists and Git ignores it, False if it exists and is NOT ignored, None if no .env."""
    if not (root / ".env").exists():
        return None
    return subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=root).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--history", action="store_true", help="also scan every commit")
    parser.add_argument("--out", help="write a Markdown report")
    parser.add_argument("--root", default=".", help="project folder (default: current)")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    findings = scan_files(root)
    if args.history:
        findings += scan_history(root)
    ignored = env_file_ignored(root)
    problems = len(findings) + (1 if ignored is False else 0)

    lines = ["# Secret scan report", "", f"Run at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. "
             f"History scanned: {'yes' if args.history else 'no'}.", ""]
    lines.append({True: "- `.env` exists and is ignored by Git: OK",
                  False: "- **`.env` exists and is NOT ignored by Git: add it to .gitignore now**",
                  None: "- No `.env` file found"}[ignored])
    if findings:
        lines += ["", "| Where | Rule | Match (redacted) | Line |", "|---|---|---|---|"]
        lines += [f"| {w} | {r} | `{s}` | {n or ''} |" for w, r, s, n in findings]
        lines += ["", "For each match: remove it, rotate the key at the provider, and note it in the audit log."]
    else:
        lines += ["", "No suspected secrets found."]
    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Saved {args.out}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
