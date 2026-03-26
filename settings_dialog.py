"""Settings dialog for Claude Usage Tray.

Uses kdialog on KDE, zenity as fallback, tkinter as last resort.
"""

import os
import shutil
import subprocess
import sys


def _run_kdialog(*args):
    """Run kdialog and return (returncode, stdout)."""
    r = subprocess.run(["kdialog", *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def _show_settings_kdialog(current_config: dict, first_run: bool = False) -> dict | None:
    """Show settings using kdialog (KDE-native)."""

    title = "Claude Usage Tray — Setup" if first_run else "Claude Usage Tray — Settings"

    if first_run:
        _run_kdialog(
            "--title", title,
            "--msgbox",
            "Welcome to Claude Usage Tray!\n\n"
            "You need to paste your Claude session cookie to get started.\n\n"
            "How to get it:\n"
            "1. Open claude.ai in your browser and sign in\n"
            "2. Open DevTools (F12 or Ctrl+Shift+I)\n"
            "3. Go to Application > Cookies > https://claude.ai\n"
            "4. Find 'sessionKey' and copy its value",
        )

    # Ask for session cookie
    current_cookie = current_config.get("session_cookie", "")
    rc, cookie = _run_kdialog(
        "--title", title,
        "--inputbox",
        "Paste your Claude sessionKey cookie:\n\n"
        "(Organization ID is detected automatically)",
        current_cookie,
    )
    if rc != 0:
        if first_run:
            _run_kdialog("--title", title, "--sorry", "No cookie configured. The app will exit.")
        return None

    cookie = cookie.strip()
    if not cookie:
        _run_kdialog("--title", title, "--error", "Please enter your session cookie.")
        return None

    # Ask for refresh interval
    current_interval = str(current_config.get("refresh_interval", 5))
    rc, interval_str = _run_kdialog(
        "--title", title,
        "--inputbox",
        "Refresh interval in minutes (1-60):",
        current_interval,
    )
    if rc != 0:
        return None

    try:
        interval = max(1, min(60, int(interval_str.strip())))
    except ValueError:
        interval = 5

    return {
        "session_cookie": cookie,
        "refresh_interval": interval,
    }


def _show_settings_zenity(current_config: dict, first_run: bool = False) -> dict | None:
    """Show settings using zenity (GNOME/GTK fallback)."""

    title = "Claude Usage Tray — Setup" if first_run else "Claude Usage Tray — Settings"

    if first_run:
        subprocess.run([
            "zenity", "--info", "--title", title,
            "--text",
            "Welcome to Claude Usage Tray!\n\n"
            "You need to paste your Claude session cookie to get started.\n\n"
            "How to get it:\n"
            "1. Open claude.ai in your browser and sign in\n"
            "2. Open DevTools (F12 or Ctrl+Shift+I)\n"
            "3. Go to Application > Cookies > https://claude.ai\n"
            "4. Find 'sessionKey' and copy its value",
        ])

    current_cookie = current_config.get("session_cookie", "")
    r = subprocess.run(
        ["zenity", "--entry", "--title", title,
         "--text", "Paste your Claude sessionKey cookie:",
         "--entry-text", current_cookie],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None

    cookie = r.stdout.strip()
    if not cookie:
        subprocess.run(["zenity", "--error", "--title", title, "--text", "Please enter your session cookie."])
        return None

    current_interval = str(current_config.get("refresh_interval", 5))
    r = subprocess.run(
        ["zenity", "--entry", "--title", title,
         "--text", "Refresh interval in minutes (1-60):",
         "--entry-text", current_interval],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None

    try:
        interval = max(1, min(60, int(r.stdout.strip())))
    except ValueError:
        interval = 5

    return {
        "session_cookie": cookie,
        "refresh_interval": interval,
    }


def _show_settings_tkinter(current_config: dict, first_run: bool = False) -> dict | None:
    """Fallback to tkinter if no native dialog tool is available."""
    import tkinter as tk
    from tkinter import ttk, messagebox

    result = [None]

    root = tk.Tk()
    root.title("Claude Usage Tray — Setup" if first_run else "Claude Usage Tray — Settings")
    root.minsize(500, 450)

    pad = {"padx": 14, "pady": 6}

    if first_run:
        ttk.Label(
            root,
            text="Welcome! Paste your Claude session cookie to get started.",
            font=("TkDefaultFont", 13, "bold"),
            wraplength=460,
        ).pack(pady=(16, 8))

    auth_frame = ttk.LabelFrame(root, text="  Authentication  ", padding=12)
    auth_frame.pack(fill="x", **pad)

    ttk.Label(
        auth_frame,
        text="How to get your session cookie:",
        font=("TkDefaultFont", 10, "bold"),
    ).pack(anchor="w")

    instructions = (
        "1. Open claude.ai in your browser and sign in\n"
        "2. Open DevTools (F12 or Ctrl+Shift+I)\n"
        "3. Go to Application > Cookies > https://claude.ai\n"
        "4. Find 'sessionKey' and copy its value"
    )
    ttk.Label(
        auth_frame, text=instructions, font=("TkDefaultFont", 10), foreground="#555"
    ).pack(anchor="w", pady=(4, 10))

    ttk.Label(auth_frame, text="Session Cookie:", font=("TkDefaultFont", 10)).pack(anchor="w")
    cookie_var = tk.StringVar(value=current_config.get("session_cookie", ""))
    cookie_entry = ttk.Entry(auth_frame, textvariable=cookie_var, show="*", width=60, font=("TkDefaultFont", 10))
    cookie_entry.pack(fill="x", pady=(2, 4))

    show_var = tk.BooleanVar(value=False)
    def toggle_show():
        cookie_entry.config(show="" if show_var.get() else "*")
    ttk.Checkbutton(auth_frame, text="Show cookie", variable=show_var, command=toggle_show).pack(anchor="w")

    ttk.Label(
        auth_frame,
        text="Organization ID is detected automatically.",
        font=("TkDefaultFont", 9, "italic"),
        foreground="#888",
    ).pack(anchor="w", pady=(8, 0))

    pref_frame = ttk.LabelFrame(root, text="  Preferences  ", padding=12)
    pref_frame.pack(fill="x", **pad)

    interval_frame = ttk.Frame(pref_frame)
    interval_frame.pack(fill="x")
    ttk.Label(interval_frame, text="Refresh interval (minutes):", font=("TkDefaultFont", 10)).pack(side="left")
    interval_var = tk.IntVar(value=current_config.get("refresh_interval", 5))
    ttk.Spinbox(interval_frame, from_=1, to=60, textvariable=interval_var, width=5, font=("TkDefaultFont", 10)).pack(side="left", padx=(10, 0))

    btn_frame = ttk.Frame(root)
    btn_frame.pack(fill="x", padx=14, pady=(16, 14))

    def on_save():
        cookie = cookie_var.get().strip()
        interval = interval_var.get()
        if not cookie:
            messagebox.showwarning("Missing", "Please enter your session cookie.")
            return
        if interval < 1 or interval > 60:
            messagebox.showwarning("Invalid", "Refresh interval must be between 1 and 60 minutes.")
            return
        result[0] = {
            "session_cookie": cookie,
            "refresh_interval": interval,
        }
        root.destroy()

    def on_cancel():
        if first_run:
            if messagebox.askokcancel("Quit", "No cookie configured. The app will exit."):
                root.destroy()
        else:
            root.destroy()

    save_btn = ttk.Button(btn_frame, text="  Save  ", command=on_save)
    save_btn.pack(side="right", padx=(10, 0))
    cancel_btn = ttk.Button(btn_frame, text="  Cancel  " if not first_run else "  Quit  ", command=on_cancel)
    cancel_btn.pack(side="right")

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.update_idletasks()
    w = root.winfo_reqwidth()
    h = root.winfo_reqheight()
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"+{x}+{y}")
    root.mainloop()
    return result[0]


def show_settings(current_config: dict, first_run: bool = False) -> dict | None:
    """Show the settings/auth dialog using the best available backend.

    Returns updated config dict on save, None on cancel/close.
    """
    # Prefer kdialog on KDE
    if shutil.which("kdialog") and os.environ.get("XDG_CURRENT_DESKTOP", "").upper() in ("KDE", "PLASMA"):
        return _show_settings_kdialog(current_config, first_run)

    # Fallback to zenity (GNOME, etc.)
    if shutil.which("zenity"):
        return _show_settings_zenity(current_config, first_run)

    # Last resort: tkinter
    return _show_settings_tkinter(current_config, first_run)
