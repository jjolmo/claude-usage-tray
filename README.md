# Claude Usage Tray

A lightweight, cross-platform system tray app that shows your Claude subscription usage at a glance.

Displays your **session (5-hour)** and **weekly (7-day)** usage percentages directly in the system tray, with reset timers and a dropdown with full details.

Works on **macOS**, **Linux** (KDE, GNOME, etc.), and **Windows**.

## Installation

### Download a release

Go to [Releases](https://github.com/jjolmo/claude-usage-tray/releases) and download the binary for your platform:

- `claude-usage-tray-macos` — macOS (Intel & Apple Silicon)
- `claude-usage-tray-linux` — Linux (x86_64)
- `claude-usage-tray-windows.exe` — Windows

### Run from source

```bash
git clone https://github.com/jjolmo/claude-usage-tray.git
cd claude-usage-tray
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
python claude_tray.py
```

#### Linux dependencies

On Linux you may need AppIndicator support for the tray icon:

```bash
# Debian/Ubuntu
sudo apt install gir1.2-appindicator3-0.1

# Fedora
sudo dnf install libappindicator-gtk3

# Arch
sudo pacman -S libappindicator-gtk3
```

## Setup

On first launch, a setup dialog will ask for two things:

### 1. Session Cookie

The app authenticates with claude.ai using your browser session cookie.

1. Open [claude.ai](https://claude.ai) in your browser and sign in
2. Open DevTools (`F12` or `Cmd+Opt+I` on Mac)
3. Go to **Application** tab > **Cookies** > `https://claude.ai`
4. Find the cookie named `sessionKey`
5. Copy its **Value** and paste it into the app

### 2. Organization ID

1. While on claude.ai, go to **Settings**
2. Look at the URL — it contains your org ID:
   ```
   https://claude.ai/settings/org_XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
   ```
3. Copy the UUID part (everything after `org_` or just the UUID)

### Refreshing your session

The session cookie expires periodically. When it does, the tray will show **ERR**. Simply:

1. Click the tray icon > **Settings...**
2. Get a fresh `sessionKey` from your browser (same steps as above)
3. Paste it and save

## Configuration

Settings are stored locally on your machine:

| Platform | Location |
|----------|----------|
| macOS | `~/Library/Application Support/claude-usage-tray/config.json` |
| Linux | `~/.config/claude-usage-tray/config.json` |
| Windows | `%APPDATA%\claude-usage-tray\config.json` |

You can also change the **refresh interval** (1–60 minutes) from Settings.

## What it shows

- **Tray icon**: `9/40%` — session usage / weekly usage
- **Dropdown menu**:
  - Session (5h): 9% resets 2h30m
  - Weekly (7d): 40% resets 3d 4h
  - Sonnet only: 15% resets 3d 4h (if applicable)
  - Last update time
  - Refresh / Settings / Quit

## Platform notes

- **macOS**: You may need to allow the app in System Settings > Privacy & Security
- **Linux (KDE)**: Works via StatusNotifierItem (SNI) protocol. Needs `libappindicator`
- **Windows**: May show a SmartScreen warning on first run — click "More info" > "Run anyway"

## Security

- Your session cookie is stored **locally** on your machine with restricted file permissions
- The app only communicates with `claude.ai` — no telemetry, no third-party services
- **Never share your `config.json` file** — it contains your session cookie

## Building releases

Releases are built automatically via GitHub Actions when a version tag is pushed:

```bash
git tag v0.1.0
git push origin v0.1.0
```

This triggers builds for all three platforms using PyInstaller.

## License

MIT
