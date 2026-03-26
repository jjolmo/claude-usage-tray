#!/usr/bin/env python3
"""Claude Usage Tray — cross-platform system tray app showing Claude subscription usage.

Uses rumps on macOS (native menu bar text), PyQt6 QSystemTrayIcon on Linux (KDE/GNOME).
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

            self._needs_setup = not is_configured()
            if is_configured():
                threading.Thread(target=self._refresh, daemon=True).start()

        @rumps.timer(1)
        def _tick(self, timer):
            if self._needs_setup:
                self._needs_setup = False
                self.open_settings(None)
            timer.interval = self.config.get("refresh_interval", 5) * 60
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

            self.config["session_cookie"] = cookie
            save_config(self.config)
            self.title = "..."
            self.session_item.title = "Connecting..."

            def _detect_and_refresh():
                try:
                    self.config["org_id"] = fetch_org_id(cookie)
                    save_config(self.config)
                except Exception:
                    pass
                self._refresh()

            threading.Thread(target=_detect_and_refresh, daemon=True).start()

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
# Linux backend (PyQt6 QSystemTrayIcon — native KDE/GNOME)
# ---------------------------------------------------------------------------

def run_qt():
    from PyQt6.QtWidgets import (
        QApplication, QSystemTrayIcon, QMenu, QDialog,
        QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
        QSpinBox, QPushButton, QGroupBox, QCheckBox,
        QMessageBox,
    )
    from PyQt6.QtGui import QIcon, QImage, QPainter, QColor, QFont, QPixmap, QAction
    from PyQt6.QtCore import QTimer, Qt, QSize, QObject, pyqtSignal

    app = QApplication(sys.argv)
    app.setApplicationName("Claude Usage Tray")
    app.setQuitOnLastWindowClosed(False)

    # Bridge to emit signals from background threads to the main Qt thread
    class RefreshSignal(QObject):
        finished = pyqtSignal()

    refresh_signal = RefreshSignal()

    config = load_config()
    usage_data = {"usage": None, "error": None, "updated": None}

    def create_icon_pixmap(top_text, bottom_text=None, size=128):
        """Create a two-line text icon as QPixmap.

        top_text: session %, bottom_text: weekly %.
        If bottom_text is None, shows top_text centered (for "..." or "ERR").
        """
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))

        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Rounded rect background
        painter.setBrush(QColor(45, 45, 45))
        painter.setPen(Qt.PenStyle.NoPen)
        r = size // 8
        painter.drawRoundedRect(0, 0, size, size, r, r)

        painter.setPen(QColor(255, 255, 255))

        if bottom_text is None:
            # Single centered text
            font = QFont("DejaVu Sans", size // 3, QFont.Weight.Bold)
            painter.setFont(font)
            painter.drawText(0, 0, size, size, Qt.AlignmentFlag.AlignCenter, top_text)
        else:
            # Two lines — big numbers filling the icon
            half = size // 2
            font_size = size * 2 // 5
            font = QFont("DejaVu Sans", font_size, QFont.Weight.Bold)
            painter.setFont(font)

            # Shrink if needed
            for text in (top_text, bottom_text):
                rect = painter.boundingRect(0, 0, size, half, Qt.AlignmentFlag.AlignCenter, text)
                while rect.width() > size - 4 and font_size > 10:
                    font_size -= 2
                    font.setPointSize(font_size)
                    painter.setFont(font)
                    rect = painter.boundingRect(0, 0, size, half, Qt.AlignmentFlag.AlignCenter, text)

            # Top line (session) — cyan-ish
            painter.setPen(QColor(130, 210, 255))
            painter.drawText(0, 2, size, half, Qt.AlignmentFlag.AlignCenter, top_text)
            # Bottom line (weekly) — orange-ish
            painter.setPen(QColor(255, 180, 80))
            painter.drawText(0, half - 2, size, half, Qt.AlignmentFlag.AlignCenter, bottom_text)

        painter.end()
        return QPixmap.fromImage(img)

    # --- Settings Dialog ---
    class SettingsDialog(QDialog):
        def __init__(self, cfg, first_run=False, parent=None):
            super().__init__(parent)
            self.cfg = cfg
            self.result_config = None
            self.setWindowTitle("Claude Usage Tray — Setup" if first_run else "Claude Usage Tray — Settings")
            self.setMinimumWidth(500)

            layout = QVBoxLayout(self)

            if first_run:
                welcome = QLabel("Welcome! Paste your Claude session cookie to get started.")
                welcome.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px;")
                welcome.setWordWrap(True)
                layout.addWidget(welcome)

            # Auth section
            auth_group = QGroupBox("Authentication")
            auth_layout = QVBoxLayout(auth_group)

            instructions = QLabel(
                "How to get your session cookie:\n"
                "1. Open claude.ai in your browser and sign in\n"
                "2. Open DevTools (F12 or Ctrl+Shift+I)\n"
                "3. Go to Application > Cookies > https://claude.ai\n"
                "4. Find 'sessionKey' and copy its value"
            )
            instructions.setStyleSheet("color: #888; padding: 4px;")
            auth_layout.addWidget(instructions)

            auth_layout.addWidget(QLabel("Session Cookie:"))
            self.cookie_input = QLineEdit(cfg.get("session_cookie", ""))
            self.cookie_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.cookie_input.setPlaceholderText("Paste your sessionKey here...")
            auth_layout.addWidget(self.cookie_input)

            self.show_cookie = QCheckBox("Show cookie")
            self.show_cookie.toggled.connect(
                lambda checked: self.cookie_input.setEchoMode(
                    QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
                )
            )
            auth_layout.addWidget(self.show_cookie)

            auto_label = QLabel("Organization ID is detected automatically.")
            auto_label.setStyleSheet("color: #888; font-style: italic;")
            auth_layout.addWidget(auto_label)

            layout.addWidget(auth_group)

            # Preferences section
            pref_group = QGroupBox("Preferences")
            pref_layout = QHBoxLayout(pref_group)
            pref_layout.addWidget(QLabel("Refresh interval (minutes):"))
            self.interval_spin = QSpinBox()
            self.interval_spin.setRange(1, 60)
            self.interval_spin.setValue(cfg.get("refresh_interval", 5))
            pref_layout.addWidget(self.interval_spin)
            pref_layout.addStretch()
            layout.addWidget(pref_group)

            # Buttons
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            cancel_btn = QPushButton("Quit" if first_run else "Cancel")
            cancel_btn.clicked.connect(self.reject)
            btn_layout.addWidget(cancel_btn)
            save_btn = QPushButton("Save")
            save_btn.setDefault(True)
            save_btn.clicked.connect(self._on_save)
            btn_layout.addWidget(save_btn)
            layout.addLayout(btn_layout)

        def _on_save(self):
            cookie = self.cookie_input.text().strip()
            if not cookie:
                QMessageBox.warning(self, "Missing", "Please enter your session cookie.")
                return
            self.result_config = {
                "session_cookie": cookie,
                "refresh_interval": self.interval_spin.value(),
            }
            self.accept()

    # --- Tray Icon ---
    tray = QSystemTrayIcon()
    tray.setIcon(QIcon(create_icon_pixmap("...")))
    tray.setToolTip("Claude Usage Tray")

    def update_menu():
        menu = QMenu()
        u = usage_data["usage"]
        err = usage_data["error"]

        if u:
            session_action = menu.addAction(f"Session (5h):  {u['session_pct']}%  resets {u['session_reset']}")
            session_action.setEnabled(False)
            weekly_action = menu.addAction(f"Weekly (7d):   {u['weekly_pct']}%  resets {u['weekly_reset']}")
            weekly_action.setEnabled(False)
            if u.get("sonnet_pct") is not None:
                sonnet_action = menu.addAction(f"Sonnet only:   {u['sonnet_pct']}%  resets {u['sonnet_reset']}")
                sonnet_action.setEnabled(False)
        elif err:
            err_action = menu.addAction(f"Error: {err}")
            err_action.setEnabled(False)
        else:
            loading_action = menu.addAction("Loading...")
            loading_action.setEnabled(False)

        menu.addSeparator()
        if usage_data["updated"]:
            updated_action = menu.addAction(f"Updated {usage_data['updated']}")
            updated_action.setEnabled(False)
            menu.addSeparator()

        menu.addAction("Refresh Now", do_refresh)
        menu.addAction("Open claude.ai usage", lambda: webbrowser.open(CLAUDE_SETTINGS_URL))
        menu.addAction("Settings...", show_settings)
        menu.addSeparator()
        menu.addAction("Quit", app.quit)

        tray.setContextMenu(menu)

    RETRY_INTERVAL_MS = 60 * 1000  # 1 minute when in error state
    timer = QTimer()

    def update_icon():
        u = usage_data["usage"]
        if u:
            tray.setIcon(QIcon(create_icon_pixmap(f"{u['session_pct']}%", f"{u['weekly_pct']}%")))
            tray.setToolTip(
                f"Session (5h): {u['session_pct']}% resets {u['session_reset']}\n"
                f"Weekly (7d): {u['weekly_pct']}% resets {u['weekly_reset']}"
            )
            # Recovered — restore normal interval
            normal_ms = config.get("refresh_interval", 5) * 60 * 1000
            if timer.interval() != normal_ms:
                timer.start(normal_ms)
        elif usage_data["error"]:
            tray.setIcon(QIcon(create_icon_pixmap("ERR")))
            tray.setToolTip(f"Error: {usage_data['error']}")
            # Error — retry faster
            if timer.interval() != RETRY_INTERVAL_MS:
                timer.start(RETRY_INTERVAL_MS)
        else:
            tray.setIcon(QIcon(create_icon_pixmap("...")))
            tray.setToolTip("Claude Usage Tray — loading...")
        update_menu()

    def poll_once():
        if not config.get("session_cookie"):
            usage_data["error"] = "Not configured"
            return
        try:
            if not config.get("org_id"):
                config["org_id"] = fetch_org_id(config["session_cookie"])
                save_config(config)
            data = fetch_usage(config["session_cookie"], config["org_id"])
            usage_data["usage"] = parse_usage(data)
            usage_data["error"] = None
            usage_data["updated"] = datetime.now().strftime("%H:%M")
        except AuthError as e:
            usage_data["usage"] = None
            usage_data["error"] = str(e)
        except Exception as e:
            usage_data["error"] = str(e)

    # Connect signal to UI update on main thread
    refresh_signal.finished.connect(update_icon)

    def do_refresh():
        def _run():
            poll_once()
            # Signal the main thread to update the UI
            refresh_signal.finished.emit()
        threading.Thread(target=_run, daemon=True).start()

    def show_settings():
        dlg = SettingsDialog(config)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_config:
            config.update(dlg.result_config)
            # Auto-detect org_id
            try:
                config["org_id"] = fetch_org_id(config["session_cookie"])
            except Exception:
                pass
            save_config(config)
            do_refresh()

    # First-run setup
    if not is_configured():
        dlg = SettingsDialog(config, first_run=True)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_config:
            sys.exit(0)
        config.update(dlg.result_config)
        try:
            config["org_id"] = fetch_org_id(config["session_cookie"])
        except Exception:
            pass
        save_config(config)

    update_menu()
    tray.show()

    # Initial refresh
    do_refresh()

    # Auto-refresh timer
    timer.timeout.connect(do_refresh)
    timer.start(config.get("refresh_interval", 5) * 60 * 1000)

    sys.exit(app.exec())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if sys.platform == "darwin":
        run_macos()
    else:
        run_qt()


if __name__ == "__main__":
    main()
