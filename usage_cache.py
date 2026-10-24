"""Local cache of every tracked account's usage, so other tools never call claude.ai.

Accounts live in the tray config under "accounts": {org_id: {"label", "track",
"cookie"?}}. Accounts logged into a Claude Desktop profile are added on their
own; others can be added by org ID (with a cookie to fetch their usage, or
without one to count them in the budget until they show up in a profile).

The tray writes ~/.cache/claude-usage/accounts.json (latest per tracked account,
with what is using it right now) and history.jsonl (one line per poll and
account, last 14 days). The Claude Code usage guard hook reads these files and
nothing else.
"""

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from usage_api import fetch_org_id, fetch_usage
import activity
import desktop_cookies

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "claude-usage"
ACCOUNTS_FILE = CACHE_DIR / "accounts.json"
HISTORY_FILE = CACHE_DIR / "history.jsonl"
HISTORY_DAYS = 14

_org_by_cookie: dict[str, str] = {}


def _cookie_id(cookie: str) -> str:
    return hashlib.sha256(cookie.encode()).hexdigest()


def _window(data: dict, name: str) -> dict:
    w = data.get(name) or {}
    return {"pct": w.get("utilization"), "resets_at": w.get("resets_at")}


def load() -> dict:
    try:
        return json.loads(ACCOUNTS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"accounts": {}}


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def _append_history(entries: list[dict]) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).isoformat()
    lines = []
    if HISTORY_FILE.exists():
        for line in HISTORY_FILE.read_text().splitlines():
            try:
                if json.loads(line)["ts"] >= cutoff:
                    lines.append(line)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
    lines += [json.dumps(e) for e in entries]
    _write_atomic(HISTORY_FILE, "\n".join(lines) + "\n")


def _org_of(cookie: str) -> str:
    cid = _cookie_id(cookie)
    if cid not in _org_by_cookie:
        _org_by_cookie[cid] = fetch_org_id(cookie)
    return _org_by_cookie[cid]


def discover(config: dict) -> tuple[dict[str, list[tuple[str, str]]], dict[str, str], bool]:
    """Find every account with a usable cookie and add new ones to the config.

    Returns ({org: [(source, cookie), ...]}, {source: error}, config_changed).
    A source is a desktop profile name, or "manual" for a cookie in the config.
    """
    accounts = config.setdefault("accounts", {})
    found, errors, changed = {}, {}, False

    sources = [(profile, cookie) for profile, cookie in desktop_cookies.session_keys().items()]
    if config.get("session_cookie"):
        sources.append(("tray-config", config["session_cookie"]))
    sources += [("manual", a["cookie"]) for a in accounts.values() if a.get("cookie")]

    for source, cookie in sources:
        try:
            org = _org_of(cookie)
        except Exception as e:
            errors[source] = str(e)
            continue
        found.setdefault(org, []).append((source, cookie))
        if org not in accounts:
            label = source if source not in ("tray-config", "manual") else org[:8]
            accounts[org] = {"label": label, "track": True}
            changed = True
    return found, errors, changed


def refresh_all(config: dict) -> tuple[dict, bool]:
    """Fetch every tracked account once and rewrite the cache.

    Returns (cache, config_changed); the caller saves the config when it changed.
    """
    found, errors, changed = discover(config)
    accounts = config["accounts"]
    previous = load().get("accounts", {})
    now = datetime.now(timezone.utc).isoformat()
    cache_accounts, history = {}, []

    for org, acc in accounts.items():
        if not acc.get("track", True):
            continue
        sources = found.get(org, [])
        profiles = [s for s, _ in sources if s not in ("tray-config", "manual")]
        entry = {"label": acc.get("label") or org[:8], "profiles": profiles}
        data = None
        for source, cookie in sources:
            try:
                data = fetch_usage(cookie, org)
                break
            except Exception as e:
                errors[source] = str(e)
        if data is not None:
            entry.update(fetched_at=now, weekly=_window(data, "seven_day"), session=_window(data, "five_hour"))
            history.append({"ts": now, "org": org, "weekly_pct": entry["weekly"]["pct"]})
        elif org in previous and previous[org].get("fetched_at"):
            # Keep the last good reading; the guard decides whether it is too old.
            for key in ("fetched_at", "weekly", "session"):
                entry[key] = previous[org].get(key)
        cache_accounts[org] = entry

    cache = {"updated_at": now, "errors": errors, "accounts": cache_accounts}
    update_activity(cache)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _write_atomic(ACCOUNTS_FILE, json.dumps(cache, indent=2))
    if history:
        _append_history(history)
    return cache, changed


def update_activity(cache: dict | None = None) -> dict:
    """Refresh which accounts are in use now (cheap, no network) in the cache."""
    write = cache is None
    if cache is None:
        cache = load()
    accs = cache.get("accounts", {})
    act = activity.snapshot({org: a.get("profiles") or [] for org, a in accs.items()})
    for org, a in accs.items():
        a["active"] = act.get(org, {"desktop": False, "sessions": 0})
    cache["activity_at"] = datetime.now(timezone.utc).isoformat()
    if write and ACCOUNTS_FILE.exists():
        _write_atomic(ACCOUNTS_FILE, json.dumps(cache, indent=2))
    return cache
