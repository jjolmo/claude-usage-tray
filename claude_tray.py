#!/usr/bin/env python3
"""Claude Usage Tray — cross-platform system tray app showing Claude subscription usage.

Uses rumps on macOS (native menu bar text), pystray+Pillow on Linux/Windows.
"""

import sys
import threading
import webbrowser
from datetime import datetime

from config import load_config, save_config, is_configured
from usage_api import fetch_usage, fetch_org_id, parse_usage, AuthError, APIError

CLAUDE_SETTINGS_URL = "https://claude.ai/settings/usage"


# ---------------------------------------------------------------------------
# macOS backend (rumps)
# ---------------------------------------------------------------------------

def run_macos():
    import rumps

    class ClaudeUsageApp(rumps.App):
        def __init__(self):
            super().__init__("Claude", title="...")
            self.config = load_config()
            self.usage = None
            self.last_error = None

            self.session_item = rumps.MenuItem("Session: loading...", callback=None)
            self.weekly_item = rumps.MenuItem("Weekly: loading...", callback=None)
            self.sonnet_item = rumps.MenuItem("", callback=None)
            self.updated_item = rumps.MenuItem("", callback=None)

            self.menu = [
                self.session_item,
                self.weekly_item,
                self.sonnet_item,
                None,
                self.updated_item,
                None,
                rumps.MenuItem("Open claude.ai usage", callback=self.open_usage),
                rumps.MenuItem("Refresh now", callback=self.manual_refresh),
                rumps.MenuItem("Set refresh interval...", callback=self.set_interval),
                rumps.MenuItem("Update session cookie...", callback=self.open_settings),
            ]

            if not is_configured():
                # Show settings dialog on first launch after a short delay
                threading.Timer(1.0, lambda: self.open_settings(None)).start()
            else:
                threading.Thread(target=self._refresh, daemon=True).start()

        @rumps.timer(300)
        def auto_refresh(self, _):
            if not self.config.get("session_cookie"):
                return
            threading.Thread(target=self._refresh, daemon=True).start()

        def manual_refresh(self, _):
            threading.Thread(target=self._refresh, daemon=True).start()

        def open_usage(self, _):
            webbrowser.open(CLAUDE_SETTINGS_URL)

        def open_settings(self, _):
            w = rumps.Window(
                message=(
                    "How to get your session cookie:\n\n"
                    "1. Open claude.ai in Chrome/Safari and sign in\n"
                    "2. Open DevTools (F12 or Cmd+Opt+I)\n"
                    "3. Go to Application tab > Cookies > claude.ai\n"
                    "4. Find 'sessionKey' and copy its Value\n\n"
                    "Paste your sessionKey below and click Save.\n"
                    "The Organization ID will be detected automatically."
                ),
                title="Claude Usage Tray — Settings",
                default_text=self.config.get("session_cookie", ""),
                ok="Save",
                cancel="Cancel",
                dimensions=(400, 100),
            )
            r = w.run()
            if not r.clicked:
                return
            cookie = r.text.strip()
            if not cookie:
                rumps.alert("No cookie entered. Settings not saved.")
                return

            # Auto-detect org ID
            org_id = self.config.get("org_id", "")
            try:
                org_id = fetch_org_id(cookie)
            except Exception as e:
                if not org_id:
                    rumps.alert(f"Could not detect org ID: {e}")
                    return

            self.config["session_cookie"] = cookie
            self.config["org_id"] = org_id
            save_config(self.config)
            rumps.notification("Claude Usage Tray", "Settings saved", "Refreshing now...")
            threading.Thread(target=self._refresh, daemon=True).start()

        def set_interval(self, _):
            w = rumps.Window(
                message="Refresh interval in minutes (1-60):",
                title="Refresh Interval",
                default_text=str(self.config.get("refresh_interval", 5)),
                ok="Save",
                cancel="Cancel",
                dimensions=(100, 24),
            )
            r = w.run()
            if not r.clicked:
                return
            try:
                interval = max(1, min(60, int(r.text.strip())))
            except ValueError:
                return
            self.config["refresh_interval"] = interval
            save_config(self.config)
            rumps.notification("Claude Usage Tray", "Interval updated", f"Refreshing every {interval} min")

        def _refresh(self):
            if not self.config.get("session_cookie"):
                self.title = "Setup"
                self.session_item.title = "Click Settings to configure"
                return

            # Auto-detect org_id if missing
            if not self.config.get("org_id"):
                try:
                    self.config["org_id"] = fetch_org_id(self.config["session_cookie"])
                    save_config(self.config)
                except Exception:
                    self.title = "Setup"
                    self.session_item.title = "Click Settings to configure"
                    return

            try:
                data = fetch_usage(self.config["session_cookie"], self.config["org_id"])
                self.usage = parse_usage(data)
                self.last_error = None
            except AuthError as e:
                self.usage = None
                self.last_error = str(e)
            except (APIError, Exception) as e:
                self.last_error = str(e)

            if self.usage:
                u = self.usage
                self.title = f"{u['session_pct']}/{u['weekly_pct']}%"
                self.session_item.title = f"Session (5h):  {u['session_pct']}%  resets {u['session_reset']}"
                self.weekly_item.title = f"Weekly (7d):   {u['weekly_pct']}%  resets {u['weekly_reset']}"
                if u.get("sonnet_pct") is not None:
                    self.sonnet_item.title = f"Sonnet only:   {u['sonnet_pct']}%  resets {u['sonnet_reset']}"
                else:
                    self.sonnet_item.title = ""
                self.updated_item.title = f"Updated {datetime.now().strftime('%H:%M')}"
            elif self.last_error:
                self.title = "ERR"
                self.session_item.title = f"Error: {self.last_error}"

    ClaudeUsageApp().run()


# ---------------------------------------------------------------------------
# Linux / Windows backend (pystray + Pillow)
# ---------------------------------------------------------------------------

def run_pystray():
    from PIL import Image, ImageDraw, ImageFont
    import pystray
    from settings_dialog import show_settings

    def _get_font(size):
        paths = [
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

    def create_text_icon(text, size=64):
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font_size = size // 2
        font = _get_font(font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        while tw > size - 4 and font_size > 8:
            font_size -= 2
            font = _get_font(font_size)
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (size - tw) // 2 - bbox[0]
        y = (size - th) // 2 - bbox[1]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    draw.text((x + dx, y + dy), text, fill=(0, 0, 0, 200), font=font)
        draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
        return img

    config = load_config()
    usage = [None]
    last_error = [None]
    last_updated = [None]
    stop_event = threading.Event()
    quit_flag = [False]
    icon_ref = [None]

    def build_menu():
        items = []
        if usage[0]:
            u = usage[0]
            items.append(pystray.MenuItem(f"Session (5h):  {u['session_pct']}%  resets {u['session_reset']}", None, enabled=False))
            items.append(pystray.MenuItem(f"Weekly (7d):   {u['weekly_pct']}%  resets {u['weekly_reset']}", None, enabled=False))
            if u.get("sonnet_pct") is not None:
                items.append(pystray.MenuItem(f"Sonnet only:   {u['sonnet_pct']}%  resets {u['sonnet_reset']}", None, enabled=False))
        elif last_error[0]:
            items.append(pystray.MenuItem(f"Error: {last_error[0]}", None, enabled=False))
        else:
            items.append(pystray.MenuItem("Loading...", None, enabled=False))
        items.append(pystray.Menu.SEPARATOR)
        if last_updated[0]:
            items.append(pystray.MenuItem(f"Updated {last_updated[0]}", None, enabled=False))
            items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Refresh Now", lambda: threading.Thread(target=poll_once, daemon=True).start()))
        items.append(pystray.MenuItem("Open claude.ai usage", lambda: webbrowser.open(CLAUDE_SETTINGS_URL)))
        items.append(pystray.MenuItem("Settings...", on_settings))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Quit", on_quit))
        return pystray.Menu(*items)

    def update_icon():
        if usage[0]:
            text = f"{usage[0]['session_pct']}/{usage[0]['weekly_pct']}%"
        elif last_error[0]:
            text = "ERR"
        else:
            text = "..."
        if icon_ref[0]:
            icon_ref[0].icon = create_text_icon(text)
            icon_ref[0].menu = build_menu()

    def poll_once():
        try:
            # Auto-detect org_id if missing
            if not config.get("org_id"):
                config["org_id"] = fetch_org_id(config["session_cookie"])
                save_config(config)
            data = fetch_usage(config["session_cookie"], config["org_id"])
            usage[0] = parse_usage(data)
            last_error[0] = None
            last_updated[0] = datetime.now().strftime("%H:%M")
        except AuthError as e:
            usage[0] = None
            last_error[0] = str(e)
        except Exception as e:
            last_error[0] = str(e)
        update_icon()

    def poll_loop():
        while not stop_event.is_set():
            poll_once()
            stop_event.wait(config.get("refresh_interval", 5) * 60)

    def on_settings(*args):
        stop_event.set()
        if icon_ref[0]:
            icon_ref[0].stop()

    def on_quit(*args):
        quit_flag[0] = True
        stop_event.set()
        if icon_ref[0]:
            icon_ref[0].stop()

    # First-run setup
    if not is_configured():
        new_config = show_settings(config, first_run=True)
        if new_config is None:
            sys.exit(0)
        config.update(new_config)
        save_config(config)

    while True:
        stop_event.clear()
        icon = pystray.Icon("claude-usage-tray", icon=create_text_icon("..."), title="Claude Usage Tray", menu=build_menu())
        icon_ref[0] = icon
        poll_thread = threading.Thread(target=poll_loop, daemon=True)
        icon.run(setup=lambda ic: poll_thread.start())
        if quit_flag[0]:
            break
        new_config = show_settings(config)
        if new_config:
            config.update(new_config)
            save_config(config)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if sys.platform == "darwin":
        run_macos()
    else:
        run_pystray()


if __name__ == "__main__":
    main()
