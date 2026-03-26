"""Settings dialog for Claude Usage Tray (tkinter). Used on Linux/Windows."""

import sys
import tkinter as tk
from tkinter import ttk, messagebox


def show_settings(current_config: dict, first_run: bool = False) -> dict | None:
    """Show the settings/auth dialog.

    Args:
        current_config: Current config dict.
        first_run: If True, shows welcome text.

    Returns:
        Updated config dict on save, None on cancel/close.
    """
    result = [None]

    root = tk.Tk()
    root.title("Claude Usage Tray — Setup" if first_run else "Claude Usage Tray — Settings")
    root.resizable(False, False)

    w, h = 520, 380
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    pad = {"padx": 12, "pady": 4}

    if first_run:
        ttk.Label(
            root,
            text="Welcome! Paste your Claude session cookie to get started.",
            font=("TkDefaultFont", 12, "bold"),
            wraplength=480,
        ).pack(pady=(12, 4))

    # --- Auth Section ---
    auth_frame = ttk.LabelFrame(root, text="Authentication", padding=10)
    auth_frame.pack(fill="x", **pad)

    ttk.Label(auth_frame, text="How to get your session cookie:", font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
    instructions = (
        "1. Open claude.ai in your browser and sign in\n"
        "2. Open DevTools (F12 or Cmd+Opt+I)\n"
        "3. Go to Application > Cookies > https://claude.ai\n"
        "4. Find 'sessionKey' and copy its value"
    )
    ttk.Label(auth_frame, text=instructions, font=("TkDefaultFont", 9), foreground="#555").pack(anchor="w", pady=(0, 8))

    ttk.Label(auth_frame, text="Session Cookie:").pack(anchor="w")
    cookie_var = tk.StringVar(value=current_config.get("session_cookie", ""))
    cookie_entry = ttk.Entry(auth_frame, textvariable=cookie_var, show="*", width=60)
    cookie_entry.pack(fill="x", pady=(0, 4))

    show_var = tk.BooleanVar(value=False)
    def toggle_show():
        cookie_entry.config(show="" if show_var.get() else "*")
    ttk.Checkbutton(auth_frame, text="Show", variable=show_var, command=toggle_show).pack(anchor="w")

    ttk.Label(auth_frame, text="Organization ID is detected automatically from your cookie.", font=("TkDefaultFont", 9), foreground="#555").pack(anchor="w", pady=(8, 0))

    # --- Preferences Section ---
    pref_frame = ttk.LabelFrame(root, text="Preferences", padding=10)
    pref_frame.pack(fill="x", **pad)

    interval_frame = ttk.Frame(pref_frame)
    interval_frame.pack(fill="x")
    ttk.Label(interval_frame, text="Refresh interval (minutes):").pack(side="left")
    interval_var = tk.IntVar(value=current_config.get("refresh_interval", 5))
    ttk.Spinbox(interval_frame, from_=1, to=60, textvariable=interval_var, width=5).pack(side="left", padx=(8, 0))

    # --- Buttons ---
    btn_frame = ttk.Frame(root)
    btn_frame.pack(fill="x", padx=12, pady=12)

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

    ttk.Button(btn_frame, text="Save", command=on_save).pack(side="right", padx=(8, 0))
    ttk.Button(btn_frame, text="Cancel" if not first_run else "Quit", command=on_cancel).pack(side="right")

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.mainloop()

    return result[0]
