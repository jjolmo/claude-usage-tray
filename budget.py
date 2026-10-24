"""Daily budget shown in the tray, and the settings of the guard that enforces it.

The pace math lives in the Claude Code usage-guard hook; the tray only runs its
`--status` and edits its config file, so both always agree.
"""

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from usage_api import _format_reset

GUARD_SCRIPT = Path.home() / ".claude" / "hooks" / "usage-guard.py"
GUARD_CONFIG = Path.home() / ".config" / "claude-usage-guard.json"

GUARD_DEFAULTS = {
    "enabled": True,
    "mode": "block",
    "target_pct": 98,
    "accounts": 2,
    "day_start_hour": 0,
    "warn_margin": 5,
}


def available() -> bool:
    return GUARD_SCRIPT.exists()


def status() -> dict | None:
    if not available():
        return None
    python = shutil.which("python3") or sys.executable
    try:
        out = subprocess.run([python, str(GUARD_SCRIPT), "--status"],
                             capture_output=True, text=True, timeout=10)
        data = json.loads(out.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    return data if data.get("ok") else None


def load_guard_config() -> dict:
    cfg = dict(GUARD_DEFAULTS)
    try:
        cfg.update(json.loads(GUARD_CONFIG.read_text()))
    except (OSError, json.JSONDecodeError):
        pass
    return cfg


def save_guard_config(values: dict) -> None:
    """Merge `values` into the guard config, keeping keys the tray doesn't edit."""
    try:
        cfg = json.loads(GUARD_CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        cfg = {}
    cfg.update(values)
    GUARD_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    GUARD_CONFIG.write_text(json.dumps(cfg, indent=2) + "\n")


DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
BAR_CELLS = 12
PARTIAL = " ▏▎▍▌▋▊▉"


def bar(pct: float) -> str:
    """Text progress bar in eighths of a cell; the tray tooltip is plain text."""
    eighths = round(max(0.0, min(100.0, pct)) / 100 * BAR_CELLS * 8)
    full, rest = divmod(eighths, 8)
    text = "█" * full + (PARTIAL[rest] if rest else "")
    return text + "░" * (BAR_CELLS - len(text))


def _day_time(iso: str) -> str:
    # Resets land at hh:59:59.9; round so they read as the hour they mean.
    t = (datetime.fromisoformat(iso) + timedelta(seconds=30)).astimezone()
    return f"{DAYS[t.weekday()]} {t:%H:%M}"


def _today(st: dict) -> tuple[float, str]:
    if not st.get("enabled", True):
        return 0, "Today   guard off"
    if st["override"]:
        return 0, "Today   limit skipped until tomorrow"
    if st["over"]:
        resume = _day_time(st["resume"]) if st["resume"] else "weekly reset"
        return 100, f"Today   STOP · resume {resume}"
    spent = st["today"] or 0
    total = spent + max(0, st["slack"])
    return (100 * spent / total if total else 0), f"Today   {max(0, st['slack']):.0f}% left of {total:.0f}%"


def _activity(active: dict | None) -> str:
    if not active:
        return ""
    parts = []
    if active.get("sessions"):
        parts.append(f"{active['sessions']} session{'s' if active['sessions'] != 1 else ''}")
    if active.get("desktop"):
        parts.append("Desktop")
    return "   ● " + " · ".join(parts) if parts else ""


def summary_lines(st: dict | None) -> list[str]:
    """Bars for the tooltip and menu: today's shared budget, then each account."""
    if not st:
        return []
    pct, text = _today(st)
    lines = [f"{bar(pct)}  {text}"]
    for a in st["accounts"]:
        lines += ["", a["label"] + _activity(a.get("active"))]
        if a["session"] is not None:
            reset = _format_reset(a["session_reset"]) if a["session_reset"] else "?"
            lines.append(f"{bar(a['session'])}  5h      {a['session']:.0f}% · {reset}")
        lines.append(f"{bar(a['weekly'])}  Week   {a['weekly']:.0f}% · {_day_time(a['reset'])}")
    labels = st.get("missing_labels") or []
    for i in range(st["missing"]):
        name = labels[i] if i < len(labels) else "Other account"
        lines += ["", f"{name}: no data (log in on a Claude Desktop profile)"]
    return lines
