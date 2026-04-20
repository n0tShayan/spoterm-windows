"""
spoterm.py — Lightweight Spotify Terminal Client
Requires: pip install spotipy
Setup:    Set SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI
          or edit CONFIG below.
"""

import curses
import time
import threading
import sys
import os
import textwrap

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    print("Missing dependency. Run:  pip install spotipy")
    sys.exit(1)

# ─── CONFIG ──────────────────────────────────────────────────────────────────
CONFIG = {
    "client_id":     os.getenv("SPOTIPY_CLIENT_ID",     "YOUR_CLIENT_ID"),
    "client_secret": os.getenv("SPOTIPY_CLIENT_SECRET", "YOUR_CLIENT_SECRET"),
    "redirect_uri":  os.getenv("SPOTIPY_REDIRECT_URI",  "http://localhost:8888/callback"),
    "scope": (
        "user-read-playback-state "
        "user-modify-playback-state "
        "user-library-read "
        "playlist-read-private "
        "playlist-read-collaborative"
    ),
    "poll_interval": 2.0,   # seconds between Spotify API polls
}

# ─── COLOUR PAIRS ────────────────────────────────────────────────────────────
C_NORMAL   = 1
C_ACCENT   = 2
C_DIM      = 3
C_SELECTED = 4
C_PLAYING  = 5
C_HEADER   = 6
C_BAR      = 7
C_SUCCESS  = 8
C_WARN     = 9

# ─── ICONS (ASCII safe) ──────────────────────────────────────────────────────
ICON_PLAY    = ">"
ICON_PAUSE   = "||"
ICON_PREV    = "|<"
ICON_NEXT    = ">|"
ICON_MUSIC   = "~"
ICON_LIST    = "#"
ICON_HEART   = "v"
ICON_SEARCH  = "?"
ICON_VOL     = ")"
ICON_MUTE    = "x"


# ─── HELPERS ─────────────────────────────────────────────────────────────────
def ms_to_mmss(ms):
    if ms is None:
        return "0:00"
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"

def trunc(s, n):
    if len(s) <= n:
        return s
    return s[:n - 1] + "…" if n > 1 else ""

def bar(filled, total, width):
    if total == 0:
        return "─" * width
    pos = int((filled / total) * width)
    return "─" * pos + "●" + "─" * (width - pos - 1)


# ─── SPOTIFY WRAPPER ─────────────────────────────────────────────────────────
class SpotifyClient:
    def __init__(self):
        self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=CONFIG["client_id"],
            client_secret=CONFIG["client_secret"],
            redirect_uri=CONFIG["redirect_uri"],
            scope=CONFIG["scope"],
            open_browser=True,
        ))
        self._cache = {}

    def _get(self, key, fn, ttl=30):
        now = time.time()
        if key in self._cache:
            val, ts = self._cache[key]
            if now - ts < ttl:
                return val
        try:
            val = fn()
            self._cache[key] = (val, now)
            return val
        except Exception:
            return self._cache.get(key, (None, 0))[0]

    def playback(self):
        return self._get("pb", lambda: self.sp.current_playback(), ttl=CONFIG["poll_interval"])

    def playlists(self):
        def _fetch():
            items, r = [], self.sp.current_user_playlists(limit=50)
            while r:
                items += r["items"]
                r = self.sp.next(r) if r["next"] else None
            return items
        return self._get("pl", _fetch, ttl=120)

    def liked_tracks(self):
        def _fetch():
            items, r = [], self.sp.current_user_saved_tracks(limit=50)
            while r:
                items += [i["track"] for i in r["items"] if i["track"]]
                r = self.sp.next(r) if r["next"] else None
            return items
        return self._get("lt", _fetch, ttl=120)

    def playlist_tracks(self, pl_id):
        def _fetch():
            items, r = [], self.sp.playlist_items(pl_id, limit=100,
                fields="items(track(id,name,artists,duration_ms,uri)),next")
            while r:
                items += [i["track"] for i in r["items"] if i.get("track")]
                r = self.sp.next(r) if r["next"] else None
            return items
        return self._get(f"pt_{pl_id}", _fetch, ttl=60)

    def search_tracks(self, query, limit=30):
        r = self.sp.search(q=query, type="track", limit=limit)
        return r["tracks"]["items"] if r else []

    # ── Playback controls ────────────────────────────────────────────────────
    def play_uri(self, uri):
        try:
            dev = self._active_device()
            self.sp.start_playback(device_id=dev, uris=[uri])
            self._cache.pop("pb", None)
        except Exception:
            pass

    def play_context(self, context_uri, offset=0):
        try:
            dev = self._active_device()
            self.sp.start_playback(device_id=dev,
                                   context_uri=context_uri,
                                   offset={"position": offset})
            self._cache.pop("pb", None)
        except Exception:
            pass

    def toggle_pause(self):
        pb = self.playback()
        try:
            if pb and pb["is_playing"]:
                self.sp.pause_playback()
            else:
                self.sp.start_playback()
            self._cache.pop("pb", None)
        except Exception:
            pass

    def next_track(self):
        try:
            self.sp.next_track()
            self._cache.pop("pb", None)
        except Exception:
            pass

    def prev_track(self):
        try:
            self.sp.previous_track()
            self._cache.pop("pb", None)
        except Exception:
            pass

    def set_volume(self, vol):
        try:
            self.sp.volume(max(0, min(100, vol)))
        except Exception:
            pass

    def _active_device(self):
        devs = self.sp.devices().get("devices", [])
        active = next((d for d in devs if d["is_active"]), None)
        return active["id"] if active else (devs[0]["id"] if devs else None)


# ─── VIEWS ───────────────────────────────────────────────────────────────────
VIEW_PLAYLISTS = 0
VIEW_LIKED     = 1
VIEW_SEARCH    = 2

SIDEBAR_LABELS = [
    f"{ICON_LIST} Playlists",
    f"{ICON_HEART} Liked Songs",
    f"{ICON_SEARCH} Search",
]


# ─── MAIN APP ────────────────────────────────────────────────────────────────
class SpoTerm:
    def __init__(self, stdscr):
        self.scr  = stdscr
        self.sp   = SpotifyClient()

        # layout
        self.h = self.w = 0
        self.sidebar_w = 22
        self.bar_h     = 3

        # state
        self.view          = VIEW_PLAYLISTS
        self.sidebar_sel   = 0          # selected sidebar item
        self.list_items    = []         # current main pane items (tracks)
        self.list_sel      = 0
        self.list_offset   = 0
        self.playlists     = []
        self.pl_sel        = 0
        self.pl_offset     = 0

        self.search_mode   = False
        self.search_query  = ""
        self.search_cursor = 0

        self.playback      = None
        self.status_msg    = ""
        self.status_ts     = 0

        self.dirty         = True
        self.running       = True

        # background poll thread
        self._poll_t = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_t.start()

    # ── Init curses ──────────────────────────────────────────────────────────
    def init_colors(self):
        curses.start_color()
        curses.use_default_colors()
        bg = -1
        curses.init_pair(C_NORMAL,   curses.COLOR_WHITE,   bg)
        curses.init_pair(C_ACCENT,   curses.COLOR_GREEN,   bg)
        curses.init_pair(C_DIM,      curses.COLOR_BLACK+8, bg)   # bright black = grey
        curses.init_pair(C_SELECTED, curses.COLOR_BLACK,   curses.COLOR_GREEN)
        curses.init_pair(C_PLAYING,  curses.COLOR_GREEN,   bg)
        curses.init_pair(C_HEADER,   curses.COLOR_BLACK,   curses.COLOR_WHITE)
        curses.init_pair(C_BAR,      curses.COLOR_BLACK,   curses.COLOR_GREEN)
        curses.init_pair(C_SUCCESS,  curses.COLOR_GREEN,   bg)
        curses.init_pair(C_WARN,     curses.COLOR_YELLOW,  bg)

    # ── Background polling ───────────────────────────────────────────────────
    def _poll_loop(self):
        while self.running:
            try:
                new_pb = self.sp.sp.current_playback()
                self.sp._cache["pb"] = (new_pb, time.time())
                if new_pb != self.playback:
                    self.playback = new_pb
                    self.dirty = True
            except Exception:
                pass
            time.sleep(CONFIG["poll_interval"])

    # ── Status flash ────────────────────────────────────────────────────────
    def flash(self, msg, warn=False):
        self.status_msg  = msg
        self.status_ts   = time.time()
        self._status_warn = warn
        self.dirty = True

    # ── Data loaders ────────────────────────────────────────────────────────
    def load_playlists(self):
        self.playlists = self.sp.playlists() or []
        self.pl_sel = self.pl_offset = 0
        self.dirty = True

    def load_liked(self):
        self.list_items  = self.sp.liked_tracks() or []
        self.list_sel = self.list_offset = 0
        self.dirty = True

    def load_playlist_tracks(self, pl_id):
        self.list_items  = self.sp.playlist_tracks(pl_id) or []
        self.list_sel = self.list_offset = 0
        self.dirty = True

    def run_search(self):
        if not self.search_query.strip():
            return
        self.list_items  = self.sp.search_tracks(self.search_query) or []
        self.list_sel = self.list_offset = 0
        self.dirty = True

    # ── Drawing helpers ──────────────────────────────────────────────────────
    def _addstr(self, win, y, x, s, attr=0):
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        avail = w - x
        if avail <= 0:
            return
        s = s[:avail]
        try:
            win.addstr(y, x, s, attr)
        except curses.error:
            pass

    def _hline(self, win, y, ch="─"):
        h, w = win.getmaxyx()
        if 0 <= y < h:
            try:
                win.hline(y, 0, ch, w)
            except curses.error:
                pass

    # ── Draw: header ────────────────────────────────────────────────────────
    def draw_header(self, win):
        h, w = win.getmaxyx()
        win.bkgd(" ", curses.color_pair(C_NORMAL))

        # logo
        logo = " SPOTERM "
        self._addstr(win, 0, 1, logo, curses.color_pair(C_ACCENT) | curses.A_BOLD)

        # playback device / user info
        pb = self.playback
        if pb and pb.get("device"):
            dev = trunc(pb["device"]["name"], 24)
            self._addstr(win, 0, w - len(dev) - 3, f"[{dev}]",
                         curses.color_pair(C_DIM))

        # separator
        self._addstr(win, 1, 0, "─" * w, curses.color_pair(C_DIM))

    # ── Draw: sidebar ────────────────────────────────────────────────────────
    def draw_sidebar(self, win):
        h, w = win.getmaxyx()
        win.bkgd(" ", curses.color_pair(C_NORMAL))

        # Navigation tabs
        for i, label in enumerate(SIDEBAR_LABELS):
            attr = curses.color_pair(C_SELECTED) | curses.A_BOLD if i == self.view \
                   else curses.color_pair(C_DIM)
            self._addstr(win, i, 0, f" {label:<{w-1}}", attr)

        self._addstr(win, 3, 0, "─" * w, curses.color_pair(C_DIM))

        # Playlist list (only shown in playlists view)
        if self.view == VIEW_PLAYLISTS:
            visible_h = h - 4
            pls = self.playlists
            for idx in range(visible_h):
                real = idx + self.pl_offset
                if real >= len(pls):
                    break
                pl   = pls[real]
                name = trunc(pl.get("name", "?"), w - 3)
                if real == self.pl_sel:
                    attr = curses.color_pair(C_SELECTED) | curses.A_BOLD
                    self._addstr(win, 4 + idx, 0, f" >{name:<{w-2}}", attr)
                else:
                    attr = curses.color_pair(C_NORMAL)
                    self._addstr(win, 4 + idx, 0, f"  {name:<{w-2}}", attr)

    # ── Draw: main pane ──────────────────────────────────────────────────────
    def draw_main(self, win):
        h, w = win.getmaxyx()
        win.bkgd(" ", curses.color_pair(C_NORMAL))

        # Search bar (view == SEARCH)
        top = 0
        if self.view == VIEW_SEARCH:
            prompt = f" {ICON_SEARCH} "
            query_disp = self.search_query
            bar_text = f"{prompt}{query_disp}"
            if self.search_mode:
                attr = curses.color_pair(C_ACCENT) | curses.A_BOLD
                self._addstr(win, 0, 0, f"{bar_text:<{w}}", attr)
                # cursor
                cx = len(prompt) + self.search_cursor
                if cx < w:
                    try:
                        win.chgat(0, cx, 1, curses.color_pair(C_SELECTED))
                    except curses.error:
                        pass
            else:
                attr = curses.color_pair(C_DIM)
                self._addstr(win, 0, 0, f"{bar_text:<{w}}", attr)
            self._addstr(win, 1, 0, "─" * w, curses.color_pair(C_DIM))
            top = 2

        # Track list
        pb      = self.playback
        now_uri = pb["item"]["uri"] if pb and pb.get("item") else None
        vis_h   = h - top
        items   = self.list_items

        if not items:
            hint = "No items.  Press Enter on a playlist, or / to search."
            self._addstr(win, top + vis_h // 2, (w - len(hint)) // 2, hint,
                         curses.color_pair(C_DIM))
            return

        for idx in range(vis_h):
            real = idx + self.list_offset
            if real >= len(items):
                break
            track = items[real]
            if not track:
                continue

            name    = track.get("name", "Unknown")
            artists = ", ".join(a["name"] for a in track.get("artists", []))
            dur     = ms_to_mmss(track.get("duration_ms"))
            is_now  = track.get("uri") == now_uri

            # build row
            dur_w    = 6
            num_w    = 4
            rest     = w - num_w - dur_w - 4
            art_w    = rest // 3
            name_w   = rest - art_w

            num_s    = f"{real+1:>3}."
            name_s   = trunc(name, name_w)
            art_s    = trunc(artists, art_w)
            row      = f"{num_s} {name_s:<{name_w}} {art_s:<{art_w}} {dur:>{dur_w}}"

            y = top + idx
            if real == self.list_sel:
                self._addstr(win, y, 0, f"{row:<{w}}",
                             curses.color_pair(C_SELECTED) | curses.A_BOLD)
            elif is_now:
                self._addstr(win, y, 0, f"{row:<{w}}",
                             curses.color_pair(C_PLAYING) | curses.A_BOLD)
            else:
                self._addstr(win, y, 0, f"{row:<{w}}",
                             curses.color_pair(C_NORMAL))

    # ── Draw: player bar ─────────────────────────────────────────────────────
    def draw_playerbar(self, win):
        h, w = win.getmaxyx()
        win.bkgd(" ", curses.color_pair(C_NORMAL))
        self._hline(win, 0, "─")

        pb = self.playback

        if not pb or not pb.get("item"):
            self._addstr(win, 1, 2, "No active playback  ·  Open Spotify on any device first",
                         curses.color_pair(C_DIM))
            hint = "[p] play  [n] next  [b] prev  [+/-] vol  [/] search  [q] quit"
            self._addstr(win, 2, 2, hint, curses.color_pair(C_DIM))
            return

        item      = pb["item"]
        title     = item.get("name", "")
        artists   = ", ".join(a["name"] for a in item.get("artists", []))
        is_play   = pb.get("is_playing", False)
        prog_ms   = pb.get("progress_ms", 0)
        dur_ms    = item.get("duration_ms", 0)
        vol       = pb.get("device", {}).get("volume_percent", 0)

        icon      = ICON_PAUSE if is_play else ICON_PLAY
        prog_s    = ms_to_mmss(prog_ms)
        dur_s     = ms_to_mmss(dur_ms)

        # row 1: title + artist
        info = f" {icon}  {trunc(title, 36)}  —  {trunc(artists, 30)}"
        self._addstr(win, 1, 0, f"{info:<{w}}", curses.color_pair(C_ACCENT) | curses.A_BOLD)

        # row 2: progress bar + volume + shortcuts
        bar_w   = max(10, w - 36)
        prog_bar = bar(prog_ms, dur_ms, bar_w)
        vol_icon = ICON_MUTE if vol == 0 else ICON_VOL
        left     = f" {prog_s} {prog_bar} {dur_s}  {vol_icon}{vol:3}%"
        keys     = "[p]pause [n]next [b]prev [+/-]vol [/]search [q]quit"
        pad      = w - len(left) - len(keys) - 1
        if pad > 0:
            row2 = left + " " * pad + keys
        else:
            row2 = left
        self._addstr(win, 2, 0, trunc(row2, w), curses.color_pair(C_DIM))

        # status flash
        if self.status_msg and time.time() - self.status_ts < 3:
            attr = curses.color_pair(C_WARN) if getattr(self, "_status_warn", False) \
                   else curses.color_pair(C_SUCCESS)
            msg = f"  {self.status_msg}  "
            x   = w - len(msg) - 1
            if x > 0:
                self._addstr(win, 1, x, msg, attr | curses.A_BOLD)

    # ── Full redraw ──────────────────────────────────────────────────────────
    def redraw(self):
        self.h, self.w = self.scr.getmaxyx()
        if self.h < 10 or self.w < 40:
            self.scr.clear()
            self._addstr(self.scr, 0, 0, "Terminal too small!", curses.color_pair(C_WARN))
            self.scr.refresh()
            return

        header_h = 2
        bar_h    = 3
        body_h   = self.h - header_h - bar_h

        # create sub-windows (no panels lib needed)
        try:
            hdr_win  = self.scr.derwin(header_h, self.w, 0, 0)
            side_win = self.scr.derwin(body_h, self.sidebar_w, header_h, 0)
            div_x    = self.sidebar_w
            main_win = self.scr.derwin(body_h, self.w - div_x - 1, header_h, div_x + 1)
            bar_win  = self.scr.derwin(bar_h, self.w, self.h - bar_h, 0)
        except curses.error:
            return

        # vertical divider
        for y in range(header_h, self.h - bar_h):
            try:
                self.scr.addch(y, self.sidebar_w, curses.ACS_VLINE,
                               curses.color_pair(C_DIM))
            except curses.error:
                pass

        self.draw_header(hdr_win)
        self.draw_sidebar(side_win)
        self.draw_main(main_win)
        self.draw_playerbar(bar_win)

        self.scr.noutrefresh()
        hdr_win.noutrefresh()
        side_win.noutrefresh()
        main_win.noutrefresh()
        bar_win.noutrefresh()
        curses.doupdate()
        self.dirty = False

    # ── Scrolling helpers ────────────────────────────────────────────────────
    def _vis_h(self):
        extra = 2 if self.view == VIEW_SEARCH else 0
        return max(1, self.h - 2 - 3 - extra)

    def list_scroll(self, delta):
        n = len(self.list_items)
        if n == 0:
            return
        self.list_sel = max(0, min(n - 1, self.list_sel + delta))
        vis = self._vis_h()
        if self.list_sel < self.list_offset:
            self.list_offset = self.list_sel
        elif self.list_sel >= self.list_offset + vis:
            self.list_offset = self.list_sel - vis + 1
        self.dirty = True

    def pl_scroll(self, delta):
        n = len(self.playlists)
        if n == 0:
            return
        self.pl_sel = max(0, min(n - 1, self.pl_sel + delta))
        vis = self._vis_h()
        if self.pl_sel < self.pl_offset:
            self.pl_offset = self.pl_sel
        elif self.pl_sel >= self.pl_offset + vis:
            self.pl_offset = self.pl_sel - vis + 1
        self.dirty = True

    # ── Key handler ─────────────────────────────────────────────────────────
    def handle_key(self, key):
        # search input mode
        if self.search_mode:
            if key in (curses.KEY_ENTER, 10, 13):
                self.search_mode = False
                self.run_search()
            elif key in (27,):           # ESC
                self.search_mode = False
                self.dirty = True
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                if self.search_cursor > 0:
                    self.search_query = (self.search_query[:self.search_cursor-1] +
                                         self.search_query[self.search_cursor:])
                    self.search_cursor -= 1
                    self.dirty = True
            elif key == curses.KEY_LEFT:
                self.search_cursor = max(0, self.search_cursor - 1)
                self.dirty = True
            elif key == curses.KEY_RIGHT:
                self.search_cursor = min(len(self.search_query), self.search_cursor + 1)
                self.dirty = True
            elif 32 <= key <= 126:
                ch = chr(key)
                self.search_query = (self.search_query[:self.search_cursor] +
                                     ch + self.search_query[self.search_cursor:])
                self.search_cursor += 1
                self.dirty = True
            return

        # ── global ──────────────────────────────────────────────────────────
        if key == ord('q'):
            self.running = False

        elif key == ord('/'):
            self.view = VIEW_SEARCH
            self.search_mode = True
            self.dirty = True

        elif key == ord('p'):
            self.sp.toggle_pause()
            self.flash("Toggled playback")

        elif key == ord('n'):
            self.sp.next_track()
            self.flash("Next track")

        elif key == ord('b'):
            self.sp.prev_track()
            self.flash("Previous track")

        elif key in (ord('+'), ord('=')):
            pb = self.playback
            vol = pb["device"]["volume_percent"] if pb and pb.get("device") else 50
            self.sp.set_volume(vol + 10)
            self.flash(f"Volume {min(100, vol+10)}%")

        elif key == ord('-'):
            pb = self.playback
            vol = pb["device"]["volume_percent"] if pb and pb.get("device") else 50
            self.sp.set_volume(vol - 10)
            self.flash(f"Volume {max(0, vol-10)}%")

        # ── view switch ─────────────────────────────────────────────────────
        elif key == ord('1'):
            self.view = VIEW_PLAYLISTS
            if not self.playlists:
                threading.Thread(target=self.load_playlists, daemon=True).start()
            self.dirty = True

        elif key == ord('2'):
            self.view = VIEW_LIKED
            threading.Thread(target=self.load_liked, daemon=True).start()
            self.dirty = True

        elif key == ord('3'):
            self.view = VIEW_SEARCH
            self.dirty = True

        # ── navigation ──────────────────────────────────────────────────────
        elif key in (ord('j'), curses.KEY_DOWN):
            if self.view == VIEW_PLAYLISTS and self._focus == "sidebar":
                self.pl_scroll(1)
            else:
                self.list_scroll(1)

        elif key in (ord('k'), curses.KEY_UP):
            if self.view == VIEW_PLAYLISTS and self._focus == "sidebar":
                self.pl_scroll(-1)
            else:
                self.list_scroll(-1)

        elif key == curses.KEY_PPAGE:
            if self.view == VIEW_PLAYLISTS and self._focus == "sidebar":
                self.pl_scroll(-10)
            else:
                self.list_scroll(-10)

        elif key == curses.KEY_NPAGE:
            if self.view == VIEW_PLAYLISTS and self._focus == "sidebar":
                self.pl_scroll(10)
            else:
                self.list_scroll(10)

        elif key == 9:   # TAB — toggle focus sidebar/main (playlists view)
            if self.view == VIEW_PLAYLISTS:
                self._focus = "main" if self._focus == "sidebar" else "sidebar"
                self.dirty = True

        elif key in (curses.KEY_ENTER, 10, 13):
            if self.view == VIEW_PLAYLISTS:
                if self._focus == "sidebar" and self.playlists:
                    pl = self.playlists[self.pl_sel]
                    self._focus = "main"
                    threading.Thread(target=self.load_playlist_tracks,
                                     args=(pl["id"],), daemon=True).start()
                    self.flash(f"Loading: {pl['name']}")
                elif self._focus == "main" and self.list_items:
                    track = self.list_items[self.list_sel]
                    pl    = self.playlists[self.pl_sel]
                    self.sp.play_context(pl["uri"], offset=self.list_sel)
                    self.flash(f"Playing: {track['name']}")

            elif self.view == VIEW_LIKED:
                if self.list_items:
                    track = self.list_items[self.list_sel]
                    self.sp.play_uri(track["uri"])
                    self.flash(f"Playing: {track['name']}")

            elif self.view == VIEW_SEARCH:
                if self.list_items:
                    track = self.list_items[self.list_sel]
                    self.sp.play_uri(track["uri"])
                    self.flash(f"Playing: {track['name']}")

        elif key == curses.KEY_RESIZE:
            self.dirty = True

    # ── Main loop ────────────────────────────────────────────────────────────
    def run(self):
        self.init_colors()
        curses.curs_set(0)
        self.scr.nodelay(True)
        self.scr.timeout(200)       # 200ms input timeout → ~5 redraws/sec max
        self._focus = "sidebar"

        # initial data load
        threading.Thread(target=self.load_playlists, daemon=True).start()
        self.playback = self.sp.playback()

        while self.running:
            key = self.scr.getch()
            if key != -1:
                self.handle_key(key)

            # cursor visibility in search mode
            curses.curs_set(1 if self.search_mode else 0)

            if self.dirty:
                self.redraw()

        curses.curs_set(1)


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
def main(stdscr):
    app = SpoTerm(stdscr)
    app.run()


if __name__ == "__main__":
    # Windows: enable VT processing
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
