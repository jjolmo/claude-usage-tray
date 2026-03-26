#!/usr/bin/env python3
"""Claude Usage Tray — cross-platform system tray app showing Claude subscription usage.

Works on macOS, Linux (KDE/GNOME), and Windows.
"""

import sys
import threading
import time
import webbrowser
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont
import pystray

from config import load_config, save_config, is_configured
from usage_api import fetch_usage, parse_usage, AuthError, APIError
from settings_dialog import show_settings


CLAUDE_SETTINGS_URL = "https://claude.ai/settings/usage"


# --- Icon rendering ---

def _get_font(size: int):
    """Try to load a system font, fall back to default."""
    paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFCompact.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def create_text_icon(text: str, size: int = 64) -> Image.Image:
    """Render text onto a tray icon image."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_size = size // 2
    font = _get_font(font_size)

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    # Shrink if text is too wide
    while tw > size - 4 and font_size > 8:
        font_size -= 2
        font = _get_font(font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1]

    # Dark outline for visibility on any background
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                draw.text((x + dx, y + dy), text, fill=(0, 0, 0, 200), font=font)
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)

    return img


# --- App ---

class ClaudeUsageTray:
    def __init__(self):
        self.config = load_config()
        self.usage = None
        self.last_error = None
        self.last_updated = None
        self._stop_event = threading.Event()
        self._quit = False
        self.icon = None

    def _build_menu(self):
        items = []

        if self.usage:
            u = self.usage
            items.append(pystray.MenuItem(
                f"Session (5h):  {u['session_pct']}%  resets {u['session_reset']}",
                None, enabled=False
            ))
            items.append(pystray.MenuItem(
                f"Weekly (7d):   {u['weekly_pct']}%  resets {u['weekly_reset']}",
                None, enabled=False
            ))
            if u.get("sonnet_pct") is not None:
                items.append(pystray.MenuItem(
                    f"Sonnet only:   {u['sonnet_pct']}%  resets {u['sonnet_reset']}",
                    None, enabled=False
                ))
        elif self.last_error:
            items.append(pystray.MenuItem(f"Error: {self.last_error}", None, enabled=False))
        else:
            items.append(pystray.MenuItem("Loading...", None, enabled=False))

        items.append(pystray.Menu.SEPARATOR)

        if self.last_updated:
            items.append(pystray.MenuItem(
                f"Updated {self.last_updated}", None, enabled=False
            ))
            items.append(pystray.Menu.SEPARATOR)

        items.append(pystray.MenuItem("Refresh Now", self._on_refresh))
        items.append(pystray.MenuItem("Open claude.ai usage", self._on_open_web))
        items.append(pystray.MenuItem("Settings...", self._on_settings))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Quit", self._on_quit))

        return pystray.Menu(*items)

    def _update_icon(self):
        if self.usage:
            text = f"{self.usage['session_pct']}/{self.usage['weekly_pct']}%"
        elif self.last_error:
            text = "ERR"
        else:
            text = "..."

        if self.icon:
            self.icon.icon = create_text_icon(text)
            self.icon.title = self._tooltip()
            self.icon.menu = self._build_menu()

    def _tooltip(self) -> str:
        if self.usage:
            u = self.usage
            lines = [
                f"Session: {u['session_pct']}% (resets {u['session_reset']})",
                f"Weekly: {u['weekly_pct']}% (resets {u['weekly_reset']})",
            ]
            if u.get("sonnet_pct") is not None:
                lines.append(f"Sonnet: {u['sonnet_pct']}% (resets {u['sonnet_reset']})")
            return "\n".join(lines)
        if self.last_error:
            return f"Error: {self.last_error}"
        return "Claude Usage Tray"

    def _poll_once(self):
        try:
            data = fetch_usage(self.config["session_cookie"], self.config["org_id"])
            self.usage = parse_usage(data)
            self.last_error = None
            self.last_updated = datetime.now().strftime("%H:%M")
        except AuthError as e:
            self.usage = None
            self.last_error = str(e)
        except APIError as e:
            self.last_error = str(e)
        except Exception as e:
            self.last_error = str(e)

        self._update_icon()

    def _poll_loop(self):
        while not self._stop_event.is_set():
            self._poll_once()
            interval = self.config.get("refresh_interval", 5) * 60
            self._stop_event.wait(interval)

    def _on_refresh(self, icon=None, item=None):
        threading.Thread(target=self._poll_once, daemon=True).start()

    def _on_open_web(self, icon=None, item=None):
        webbrowser.open(CLAUDE_SETTINGS_URL)

    def _on_settings(self, icon=None, item=None):
        self._stop_event.set()
        if self.icon:
            self.icon.stop()

    def _on_quit(self, icon=None, item=None):
        self._quit = True
        self._stop_event.set()
        if self.icon:
            self.icon.stop()

    def run(self):
        # First-run setup
        if not is_configured():
            new_config = show_settings(self.config, first_run=True)
            if new_config is None:
                print("Setup cancelled. Exiting.")
                sys.exit(0)
            self.config.update(new_config)
            save_config(self.config)

        while True:
            self._stop_event.clear()

            self.icon = pystray.Icon(
                "claude-usage-tray",
                icon=create_text_icon("..."),
                title="Claude Usage Tray",
                menu=self._build_menu(),
            )

            poll_thread = threading.Thread(target=self._poll_loop, daemon=True)

            def on_setup(icon):
                poll_thread.start()

            self.icon.run(setup=on_setup)

            # If we get here, icon.run() returned
            if self._quit:
                break

            # Settings was clicked — show dialog then restart tray
            new_config = show_settings(self.config)
            if new_config:
                self.config.update(new_config)
                save_config(self.config)


def main():
    app = ClaudeUsageTray()
    app.run()


if __name__ == "__main__":
    main()
