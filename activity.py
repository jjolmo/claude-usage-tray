"""Which accounts are in use right now, from local processes only (Linux).

- Claude Desktop profiles that are open: the desktop app's main process, with
  --user-data-dir for the extra profiles and without it for ~/.config/Claude.
- Claude Code sessions per account: every `claude` process carries
  CLAUDE_CODE_ORGANIZATION_UUID and CLAUDE_CODE_SESSION_ID in its environment.
"""

import os
from collections import defaultdict
from pathlib import Path

DEFAULT_PROFILE = Path.home() / ".config" / "Claude"


def _procs():
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if len(argv) == 1:
            # Electron rewrites its cmdline as one space-joined string.
            argv = argv[0].split(" ")
        if argv:
            yield pid, argv


def open_profiles() -> set[str]:
    """Names of the Claude Desktop profiles running now (profile dir basenames)."""
    names = set()
    for _, argv in _procs():
        if not argv[0].endswith("/claude-desktop") or any(a.startswith("--type=") for a in argv):
            continue
        data_dir = next((a.split("=", 1)[1] for a in argv if a.startswith("--user-data-dir=")), None)
        names.add(Path(data_dir).name if data_dir else DEFAULT_PROFILE.name)
    return names


def code_sessions() -> dict[str, int]:
    """{org_id: number of distinct Claude Code sessions running on that account}."""
    sessions = defaultdict(set)
    for pid, argv in _procs():
        if os.path.basename(argv[0]) != "claude":
            continue
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = dict(e.split(b"=", 1) for e in f.read().split(b"\0") if b"=" in e)
        except OSError:
            continue
        org = env.get(b"CLAUDE_CODE_ORGANIZATION_UUID")
        if org:
            sessions[org.decode()].add(env.get(b"CLAUDE_CODE_SESSION_ID", pid.encode()))
    return {org: len(ids) for org, ids in sessions.items()}


def snapshot(profiles_by_org: dict[str, list[str]]) -> dict[str, dict]:
    """{org_id: {"desktop": bool, "sessions": int}} for every org seen in use."""
    running = open_profiles()
    out = {org: {"desktop": bool(running & set(profiles)), "sessions": 0}
           for org, profiles in profiles_by_org.items()}
    for org, n in code_sessions().items():
        out.setdefault(org, {"desktop": False, "sessions": 0})["sessions"] = n
    return out
