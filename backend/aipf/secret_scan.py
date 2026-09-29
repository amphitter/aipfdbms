"""Fail if the repository contains a committed credential.

Patterns are assembled so this file does not itself contain a secret.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {
    ".git",
    "node_modules",
    "dist",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".pdf",
    ".db",
    ".pyc",
    ".woff",
    ".woff2",
    ".zip",
}
INSTALL_ROLES = ("director", "reception", "doctor", "pharmacy", "billing", "nurse", "lab")
URL_WITH_PASSWORD = re.compile(r"postgres(?:ql)?://[^/\s:]+:[^@\s]+@")
ASSIGNED_SECRET = re.compile(
    r"""(?i)(?:password|passwd|secret|api_key|token)\s*[:=]\s*['\"][^'\"]{6,}['\"]"""
)
PLACEHOLDERS = {"password", "secret", "changeme", "your-password", "username", "token"}


def findings(root: Path = ROOT) -> list[str]:
    hits: list[str] = []
    install = tuple("aipf-" + role for role in INSTALL_ROLES)
    dev_pw = "aipf_" + "dev"
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root)
        for needle in install:
            if needle in text:
                hits.append(f"{rel}: committed install password")
                break
        if dev_pw in text:
            hits.append(f"{rel}: committed database password")
        if URL_WITH_PASSWORD.search(text):
            hits.append(f"{rel}: database URL contains a password")
        for match in ASSIGNED_SECRET.finditer(text):
            value = match.group(0).split("=", 1)[-1].split(":", 1)[-1].strip().strip("\"'")
            if value.lower() in PLACEHOLDERS:
                continue
            if value.startswith("$") or value.startswith("os.environ"):
                continue
            hits.append(f"{rel}: assigned secret literal")
            break
    return hits


def main() -> int:
    found = findings()
    if found:
        print("secret scan failed:")
        for item in found:
            print(f"  {item}")
        return 1
    print("secret scan passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
