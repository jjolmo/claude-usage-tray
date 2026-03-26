"""Settings dialog for Claude Usage Tray (tkinter)."""

import tkinter as tk
from tkinter import ttk, messagebox


def show_settings(current_config: dict, first_run: bool = False) -> dict | None:
    """Show the settings/auth dialog.

    Args:
        current_config: Current config dict.
        first_run: If True, shows welcome text and disables Cancel.

    Returns:
        Updated config dict on save, None on cancel.
    """
    result = [None]

    root = tk.Tk()
    root.title("Claude Usage Tray — Settings" if not first_run else "Claude Usage Tray — Setup")
    root.resizable(False, False)

    # Center on screen
    w, h = 520, 520
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    pad = {"padx": 12, "pady": 4}

    # --- Welcome ---
    if first_run:
        welcome = ttk.Label(
            root,
            text="Welcome! Configure your Claude account to get started.",
            font=("TkDefaultFont", 12, "bold"),
            wraplength=480,
        )
        welcome.pack(pady=(12, 4))

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

    # Show/hide toggle
    show_var = tk.BooleanVar(value=False)

    def toggle_show():
        cookie_entry.config(show="" if show_var.get() else "*")

    ttk.Checkbutton(auth_frame, text="Show", variable=show_var, command=toggle_show).pack(anchor="w")

    ttk.Label(auth_frame, text="").pack()  # spacer

    ttk.Label(auth_frame, text="Organization ID:").pack(anchor="w")
    ttk.Label(
        auth_frame,
        text="Found in your URL: claude.ai/settings → look at the URL for the org UUID",
        font=("TkDefaultFont", 9),
        foreground="#555",
    ).pack(anchor="w")
    org_var = tk.StringVar(value=current_config.get("org_id", ""))
    ttk.Entry(auth_frame, textvariable=org_var, width=60).pack(fill="x", pady=(0, 4))

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
        org_id = org_var.get().strip()
        interval = interval_var.get()

        if not cookie:
            messagebox.showwarning("Missing", "Please enter your session cookie.")
            return
        if not org_id:
            messagebox.showwarning("Missing", "Please enter your organization ID.")
            return
        if interval < 1 or interval > 60:
            messagebox.showwarning("Invalid", "Refresh interval must be between 1 and 60 minutes.")
            return

        result[0] = {
            "session_cookie": cookie,
            "org_id": org_id,
            "refresh_interval": interval,
        }
        root.destroy()

    def on_cancel():
        root.destroy()

    ttk.Button(btn_frame, text="Save", command=on_save).pack(side="right", padx=(8, 0))
    if not first_run:
        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="right")

    root.protocol("WM_DELETE_WINDOW", on_cancel if not first_run else lambda: None)
    root.mainloop()

    return result[0]


if __name__ == "__main__":
    # Test dialog standalone
    from config import load_config
    r = show_settings(load_config(), first_run=True)
    print("Result:", r)
