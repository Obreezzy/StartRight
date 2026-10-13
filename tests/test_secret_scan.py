"""Tests for scripts/secret_scan.py."""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("secret_scan", Path(__file__).parent.parent / "scripts" / "secret_scan.py")
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)

GROQ = "gsk_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3"
NEON = "postgresql://neon_owner:" + "Xy7pQ2mN9vK4" + "@ep-cool-123.us-east-1.aws.neon.tech/neondb?sslmode=require"


def test_known_key_shapes_are_found_and_redacted():
    found = scan.scan_text(f"GROQ_API_KEY={GROQ}")
    assert found and found[0][0] in ("Groq API key", "Secret assignment")
    assert GROQ not in str(found)  # only a redacted piece is returned
    assert scan.scan_text(f'DATABASE_URL="{NEON}"')[0][0] == "Database URL with password"
    assert scan.scan_text("COHERE_API_KEY=" + "a" * 8 + "B" * 8 + "c" * 8 + "D" * 8)[0][0] == "Cohere API key"


def test_placeholders_and_ordinary_code_are_not_flagged():
    for line in [
        "GROQ_API_KEY=your-groq-key",
        "DATABASE_URL=postgresql://user:password@localhost:5432/db",
        "postgresql://...neon.tech/neondb?sslmode=require",
        "token = get_token()",
        'os.getenv("COHERE_API_KEY", "")',
        "ACCESS_CODE=change-this-to-a-long-random-code",
        "ACCESS_CODE: optional, a code visitors must type",
    ]:
        assert scan.scan_text(line) == [], line


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def run(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@needs_git
def test_history_finds_a_secret_that_was_deleted_later(tmp_path):
    run("init", cwd=tmp_path)
    run("config", "user.email", "t@example.com", cwd=tmp_path)
    run("config", "user.name", "t", cwd=tmp_path)
    (tmp_path / "config.txt").write_text(f"KEY={GROQ}\n")
    run("add", ".", cwd=tmp_path)
    run("commit", "-m", "oops", cwd=tmp_path)
    (tmp_path / "config.txt").write_text("KEY=removed\n")
    run("add", ".", cwd=tmp_path)
    run("commit", "-m", "remove", cwd=tmp_path)
    assert scan.scan_files(tmp_path) == []          # the current files are clean
    assert len(scan.scan_history(tmp_path)) >= 1    # but history still has it


@needs_git
def test_env_file_must_be_ignored(tmp_path):
    run("init", cwd=tmp_path)
    (tmp_path / ".env").write_text(f"GROQ_API_KEY={GROQ}\n")
    assert scan.env_file_ignored(tmp_path) is False
    (tmp_path / ".gitignore").write_text(".env\n")
    assert scan.env_file_ignored(tmp_path) is True
    assert scan.scan_files(tmp_path) == []          # an ignored .env is not scanned or committed
