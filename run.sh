#!/usr/bin/env bash
# Launch Claude Usage Tray
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/claude_tray.py" "$@"
