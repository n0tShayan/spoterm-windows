# SpoTerm — Lightweight Spotify Terminal Client

A clean, keyboard-driven Spotify client that lives entirely in your terminal.
Zero Electron. Zero background services. Minimal CPU/RAM.

---

## Requirements

- Python 3.8+  (already on most systems)
- A Spotify account (Free or Premium)
- Spotify open on **any** device (phone, desktop, browser) — the Web API
  needs an active device to send commands to.

---

## 1. Install the only dependency

```
pip install spotipy
```

---

## 2. Create a Spotify App (one-time, ~2 minutes)

1. Go to https://developer.spotify.com/dashboard
2. Click **Create App**
3. Fill in any name/description
4. Set **Redirect URI** to:  `http://localhost:8888/callback`
5. Enable **Web API**
6. Save → open the app → copy **Client ID** and **Client Secret**

---

## 3. Configure credentials

**Option A — environment variables (recommended)**

```bat
set SPOTIPY_CLIENT_ID=your_client_id_here
set SPOTIPY_CLIENT_SECRET=your_client_secret_here
set SPOTIPY_REDIRECT_URI=http://localhost:8888/callback
```

Add these to your `~/.bashrc` / PowerShell profile to make them permanent.

**Option B — edit the file directly**

Open `spoterm.py` and change the CONFIG block near the top:

```python
CONFIG = {
    "client_id":     "paste_your_client_id_here",
    "client_secret": "paste_your_client_secret_here",
    "redirect_uri":  "http://localhost:8888/callback",
    ...
}
```

---

## 4. Run

```
python spoterm.py
```

The first time you run it, a browser window will open asking you to log in
and authorize the app. After that, a `.cache` file stores your token and
you won't be asked again.

---

## Controls

| Key          | Action                          |
|--------------|---------------------------------|
| `1`          | Playlists view                  |
| `2`          | Liked Songs view                |
| `3`          | Search view                     |
| `j` / `↓`   | Scroll down                     |
| `k` / `↑`   | Scroll up                       |
| `PgDn/PgUp`  | Scroll fast                     |
| `Tab`        | Toggle focus sidebar ↔ tracklist|
| `Enter`      | Open playlist / Play track      |
| `/`          | Jump to search & start typing   |
| `p`          | Play / Pause                    |
| `n`          | Next track                      |
| `b`          | Previous track                  |
| `+` / `=`    | Volume up 10%                   |
| `-`          | Volume down 10%                 |
| `q`          | Quit                            |

---

## Why it's fast

- **`curses` differential rendering** — only changed cells are redrawn
- **200ms input poll**, **2s API poll** — no busy-waiting
- **In-memory cache** for playlists and tracks (TTL-based)
- **Background thread** for API calls — UI never blocks
- **Single Python process**, no daemon, no server

Typical RAM: ~15–25 MB.  CPU at idle: <0.5%.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "No active playback" | Open Spotify on any device and start playing something once |
| Browser doesn't open | Copy the URL printed in terminal and open it manually |
| `ModuleNotFoundError` | Run `pip install spotipy` |
| Garbled display (Windows) | Use Windows Terminal (not old cmd.exe) |
| Colors look wrong | Try `set TERM=xterm-256color` |
