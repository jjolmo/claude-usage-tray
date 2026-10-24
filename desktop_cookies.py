"""Read claude.ai session cookies from Claude Desktop profiles (Linux only).

Every Claude Desktop profile is a Chromium profile: the default one lives in
~/.config/Claude and the extra ones in ~/.claude_spaces/<slug>. Each keeps its
own claude.ai `sessionKey`, so the tray can follow every logged-in account
without the user pasting cookies, and the keys stay fresh because the desktop
app renews them.
"""

import hashlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

PROFILE_ROOTS = [Path.home() / ".config" / "Claude"]
SPACES_DIR = Path.home() / ".claude_spaces"
WALLET_ENTRY = ("Claude Safe Storage", "Claude Keys", "kdewallet")


def profile_dirs() -> list[Path]:
    dirs = [p for p in PROFILE_ROOTS if p.is_dir()]
    if SPACES_DIR.is_dir():
        dirs += sorted(p for p in SPACES_DIR.iterdir() if p.is_dir())
    return dirs


def _safe_storage_password() -> bytes | None:
    name, folder, wallet = WALLET_ENTRY
    try:
        out = subprocess.run(
            ["kwallet-query", "-r", name, "-f", folder, wallet],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    pw = out.stdout.strip()
    if out.returncode != 0 or not pw or "does not exist" in pw:
        return None
    return pw.encode()


def _decrypt(value: bytes, host: str, key: bytes) -> str | None:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if value[:3] not in (b"v10", b"v11"):
        return None
    dec = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    raw = dec.update(value[3:]) + dec.finalize()
    raw = raw[: -raw[-1]]
    # Chromium 130+ prefixes the plaintext with sha256(host_key).
    digest = hashlib.sha256(host.encode()).digest()
    if raw.startswith(digest):
        raw = raw[32:]
    try:
        return raw.decode()
    except UnicodeDecodeError:
        return None


def session_keys() -> dict[str, str]:
    """Return {profile_name: sessionKey} for every logged-in desktop profile."""
    if not sys.platform.startswith("linux"):
        return {}
    password = _safe_storage_password()
    if not password:
        return {}
    key = hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1, 16)

    found = {}
    with tempfile.TemporaryDirectory() as tmp:
        for profile in profile_dirs():
            db = profile / "Cookies"
            if not db.exists():
                continue
            copy = Path(tmp) / f"{profile.name}.db"
            shutil.copy(db, copy)
            try:
                rows = sqlite3.connect(copy).execute(
                    "SELECT host_key, encrypted_value FROM cookies "
                    "WHERE name = 'sessionKey' AND host_key LIKE '%claude.ai'"
                ).fetchall()
            except sqlite3.Error:
                continue
            for host, value in rows:
                cookie = _decrypt(value, host, key)
                if cookie and cookie.startswith("sk-ant-"):
                    found[profile.name] = cookie
                    break
    return found
