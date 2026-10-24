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
import usage_cache
import budget

CLAUDE_SETTINGS_URL = "https://claude.ai/settings/usage"


# ---------------------------------------------------------------------------
# macOS backend (rumps)
# ---------------------------------------------------------------------------

def run_macos():
    import rumps

    # The bundled .app hides the Dock icon via LSUIElement in Info.plist, but
    # running from source shows a Python icon in the Dock; hide it by making
    # the process an accessory (menu-bar-only) app.
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass

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
                return  # open_settings already started a background refresh
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
                except Exception as e:
                    # Surface the real failure instead of silently falling
                    # back to "Setup" — the cookie may be saved and valid.
                    self.usage = None
                    self.last_error = str(e)
                    from PyObjCTools import AppHelper
                    AppHelper.callAfter(self._apply_ui)
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

            # AppKit only renders UI mutations made on the main thread; this
            # runs on a worker thread, so marshal the update via callAfter.
            from PyObjCTools import AppHelper
            AppHelper.callAfter(self._apply_ui)

        def _apply_ui(self):
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
        QMessageBox, QComboBox, QFormLayout, QTableWidget, QTableWidgetItem,
        QHeaderView, QAbstractItemView,
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
    usage_data = {"usage": None, "error": None, "updated": None, "budget": None}

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
            self.setMinimumWidth(640)

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

            layout.addWidget(self._accounts_group())

            self.guard_widgets = None
            if budget.available():
                layout.addWidget(self._guard_group())

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

        def _accounts_group(self):
            group = QGroupBox("Accounts")
            box = QVBoxLayout(group)
            note = QLabel("Accounts logged into a Claude Desktop profile show up here on their own. "
                          "Add others by organization ID: with a session cookie the tray fetches their "
                          "usage, without one they count as unused until they appear in a profile.")
            note.setWordWrap(True)
            note.setStyleSheet("color: #888;")
            box.addWidget(note)

            table = QTableWidget(0, 4)
            table.setHorizontalHeaderLabels(["Track", "Name", "Organization ID", "Now"])
            table.verticalHeader().setVisible(False)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            header = table.horizontalHeader()
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            table.setColumnWidth(1, 110)
            self.accounts_table = table
            cache = usage_cache.load().get("accounts", {})
            for org, acc in self.cfg.get("accounts", {}).items():
                self._add_row(org, acc, cache.get(org, {}))
            box.addWidget(table)

            buttons = QHBoxLayout()
            add_btn = QPushButton("Add by ID…")
            add_btn.clicked.connect(self._add_account)
            remove_btn = QPushButton("Remove")
            remove_btn.clicked.connect(self._remove_account)
            buttons.addWidget(add_btn)
            buttons.addWidget(remove_btn)
            buttons.addStretch()
            box.addLayout(buttons)
            return group

        def _add_row(self, org, acc, cached):
            table = self.accounts_table
            row = table.rowCount()
            table.insertRow(row)
            track = QTableWidgetItem()
            track.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            track.setCheckState(Qt.CheckState.Checked if acc.get("track", True) else Qt.CheckState.Unchecked)
            # The row keeps the account's stored fields (e.g. its cookie) for saving.
            track.setData(Qt.ItemDataRole.UserRole, (org, dict(acc), list(cached.get("profiles") or [])))
            table.setItem(row, 0, track)
            table.setItem(row, 1, QTableWidgetItem(acc.get("label") or org[:8]))
            for col, text in ((2, org), (3, self._now_text(acc, cached))):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                table.setItem(row, col, item)

        @staticmethod
        def _now_text(acc, cached):
            parts = []
            active = cached.get("active") or {}
            if active.get("sessions"):
                parts.append(f"{active['sessions']} sessions")
            if active.get("desktop"):
                parts.append("Desktop")
            if not parts:
                profiles = cached.get("profiles") or []
                if profiles:
                    parts.append("profile " + ", ".join(profiles))
                elif acc.get("cookie"):
                    parts.append("manual cookie")
                else:
                    parts.append("no data yet")
            return " · ".join(parts)

        def _table_accounts(self):
            accounts = {}
            table = self.accounts_table
            for row in range(table.rowCount()):
                track = table.item(row, 0)
                org, acc, _ = track.data(Qt.ItemDataRole.UserRole)
                acc["track"] = track.checkState() == Qt.CheckState.Checked
                acc["label"] = table.item(row, 1).text().strip() or org[:8]
                accounts[org] = acc
            return accounts

        def _tracked_count(self):
            return sum(a["track"] for a in self._table_accounts().values())

        def _add_account(self):
            import re
            dlg = QDialog(self)
            dlg.setWindowTitle("Add account")
            dlg.setMinimumWidth(420)
            form = QFormLayout(dlg)
            org_in = QLineEdit()
            name_in = QLineEdit()
            cookie_in = QLineEdit()
            cookie_in.setEchoMode(QLineEdit.EchoMode.Password)
            org_in.setPlaceholderText("optional with a cookie")
            cookie_in.setPlaceholderText("sessionKey, to fetch its usage")
            form.addRow("Session cookie:", cookie_in)
            form.addRow("Organization ID:", org_in)
            form.addRow("Name:", name_in)
            hint = QLabel("Give the cookie, the ID, or both. Without a cookie the account counts as "
                          "unused until it shows up in a Desktop profile. The ID is in claude.ai/settings "
                          "URLs, or CLAUDE_CODE_ORGANIZATION_UUID in a Claude Code session.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #888;")
            form.addRow(hint)
            row = QHBoxLayout()
            row.addStretch()
            ok = QPushButton("Add")
            ok.setDefault(True)
            ok.clicked.connect(dlg.accept)
            cancel = QPushButton("Cancel")
            cancel.clicked.connect(dlg.reject)
            row.addWidget(cancel)
            row.addWidget(ok)
            form.addRow(row)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            org = re.sub(r"^org_", "", org_in.text().strip().lower())
            cookie = cookie_in.text().strip()
            if not org and cookie:
                try:
                    org = fetch_org_id(cookie)
                except Exception as e:
                    QMessageBox.warning(self, "Cookie not accepted", f"Couldn't read the account from that cookie: {e}")
                    return
            if not org:
                QMessageBox.warning(self, "Nothing to add", "Give a session cookie or an organization ID.")
                return
            if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", org):
                QMessageBox.warning(self, "Invalid ID", "That doesn't look like an organization ID (a UUID).")
                return
            if org in self._table_accounts():
                QMessageBox.information(self, "Already there", "That account is already in the list.")
                return
            acc = {"label": name_in.text().strip() or org[:8], "track": True}
            if cookie:
                acc["cookie"] = cookie
            self._add_row(org, acc, {})

        def _remove_account(self):
            table = self.accounts_table
            row = table.currentRow()
            if row < 0:
                return
            org, acc, profiles = table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if profiles:
                QMessageBox.information(
                    self, "Logged into Desktop",
                    f"This account is logged into the Claude Desktop profile {', '.join(profiles)} "
                    "and would come back on the next refresh. Untick Track to ignore it.")
                return
            table.removeRow(row)

        def _guard_group(self):
            g = budget.load_guard_config()
            group = QGroupBox("Daily budget (Claude Code usage guard)")
            form = QFormLayout(group)

            enabled = QCheckBox("Stop for the day when weekly usage runs ahead of pace")
            enabled.setChecked(bool(g["enabled"]))
            form.addRow(enabled)

            mode = QComboBox()
            mode.addItem("Block tools until the next day", "block")
            mode.addItem("Only warn", "warn")
            mode.setCurrentIndex(max(0, mode.findData(g["mode"])))
            form.addRow("When the budget is spent:", mode)

            def spin(lo, hi, value, suffix=""):
                box = QSpinBox()
                box.setRange(lo, hi)
                box.setValue(int(value))
                box.setSuffix(suffix)
                return box

            target = spin(10, 100, g["target_pct"], " %")
            day_start = spin(0, 23, g["day_start_hour"], ":00")
            warn = spin(0, 50, g["warn_margin"], " %")
            form.addRow("Weekly target per account:", target)
            form.addRow("Day starts at:", day_start)
            form.addRow("Warn when less than this is left today:", warn)
            floor = spin(1, 10, g["accounts"])
            floor.setToolTip("Accounts not in the list yet still count, up to this number.")
            form.addRow("Budget counts at least this many accounts:", floor)

            hint = QLabel("")
            hint.setStyleSheet("color: #888;")
            def update_hint():
                n = max(self._tracked_count(), floor.value())
                daily = n * target.value() / 7
                hint.setText(f"{n} account(s) = {daily:.0f}% of one account per day; "
                             "unused budget rolls over.")
            target.valueChanged.connect(update_hint)
            floor.valueChanged.connect(update_hint)
            self.accounts_table.itemChanged.connect(lambda _: update_hint())
            update_hint()
            form.addRow(hint)

            self.guard_widgets = {"enabled": enabled, "mode": mode, "target_pct": target,
                                  "day_start_hour": day_start, "warn_margin": warn, "accounts": floor}
            return group

        def _guard_values(self):
            w = self.guard_widgets
            return {
                "enabled": w["enabled"].isChecked(),
                "mode": w["mode"].currentData(),
                "target_pct": w["target_pct"].value(),
                "day_start_hour": w["day_start_hour"].value(),
                "warn_margin": w["warn_margin"].value(),
                "accounts": w["accounts"].value(),
            }

        def _on_save(self):
            cookie = self.cookie_input.text().strip()
            accounts = self._table_accounts()
            if not cookie and not accounts:
                QMessageBox.warning(self, "Missing", "Log into Claude Desktop, add an account, "
                                    "or paste your session cookie.")
                return
            if self.guard_widgets:
                budget.save_guard_config(self._guard_values())
            self.result_config = {
                "session_cookie": cookie,
                "refresh_interval": self.interval_spin.value(),
                "accounts": accounts,
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

        budget_lines = budget.summary_lines(usage_data["budget"])
        if budget_lines:
            for line in budget_lines:
                if line:
                    menu.addAction(line).setEnabled(False)
                else:
                    menu.addSeparator()
        elif u:
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

    def active_account():
        """The account the icon shows: the one most in use right now."""
        st = usage_data["budget"]
        if not st or not st["accounts"]:
            return None
        return max(st["accounts"], key=lambda a: ((a.get("active") or {}).get("sessions", 0),
                                                  (a.get("active") or {}).get("desktop", False)))

    def update_icon():
        u = usage_data["usage"]
        active = active_account()
        if active:
            session = f"{active['session']:.0f}%" if active["session"] is not None else "–"
            tray.setIcon(QIcon(create_icon_pixmap(session, f"{active['weekly']:.0f}%")))
            tray.setToolTip("\n".join(budget.summary_lines(usage_data["budget"])))
        elif u:
            tray.setIcon(QIcon(create_icon_pixmap(f"{u['session_pct']}%", f"{u['weekly_pct']}%")))
            # With the guard's status the tooltip shows every account; otherwise just this one.
            tray.setToolTip("\n".join(budget.summary_lines(usage_data["budget"]) or [
                f"Session (5h): {u['session_pct']}% resets {u['session_reset']}",
                f"Weekly (7d): {u['weekly_pct']}% resets {u['weekly_reset']}",
            ]))
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
        try:
            _, changed = usage_cache.refresh_all(config)
            if changed:
                save_config(config)
        except Exception as e:
            print(f"usage cache refresh failed: {e}", file=sys.stderr)
        usage_data["budget"] = budget.status()
        if not config.get("session_cookie"):
            usage_data["error"] = None if usage_data["budget"] else "Not configured"
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

    # The budget changes with the clock too (a new day frees more), not only per poll.
    def refresh_budget():
        try:
            usage_cache.update_activity()
        except Exception as e:
            print(f"activity refresh failed: {e}", file=sys.stderr)
        usage_data["budget"] = budget.status()
        update_icon()
    budget_timer = QTimer()
    budget_timer.timeout.connect(refresh_budget)
    budget_timer.start(60 * 1000)

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
