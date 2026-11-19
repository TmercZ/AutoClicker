"""
Simple Windows auto clicker with a control window and an ON/OFF overlay.
Standard library only (plus the pixel fonts bundled in the fonts folder).

Pick the mode and speed in the window, then use the hotkeys:
  TOGGLE mode: press F6 to start / stop clicking.
  MANUAL mode: clicks while you hold your real mouse button (the one chosen
               in the window, default left). Release it and clicking stops.
  F10  = switch between TOGGLE and HOLD mode
  F8 / F9 = slower / faster
  F7   = quit (or just close the window)

The cog button opens Settings, where you can pick a theme (Classic light,
Classic dark, Doom, Castlevania, Metroid).

Clicks happen wherever the mouse pointer currently is, so move the pointer to
your target first. Failsafe: the top-left corner of the screen stops clicking.
The overlay (top-left) is click-through, so it never blocks clicks.

Optional start values:  python autoclicker.py --cps 20 --mode hold --button right
"""
import argparse
import ctypes
import json
import math
import os
import threading
from ctypes import wintypes
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

import sounds
import themes
from themes import THEMES, THEME_ORDER

user32 = ctypes.windll.user32

DEFAULT_KEYS = {"toggle": 0x75, "quit": 0x76, "slower": 0x77, "faster": 0x78, "mode": 0x79}
ACTIONS = ["toggle", "quit", "slower", "faster", "mode"]   # order shown in Settings
SETTINGS_PAGES = ["themes", "keybinds", "overlay", "sound", "restore"]  # the list on the left
_KEY_NAMES = {0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x13: "Pause", 0x14: "CapsLock",
              0x20: "Space", 0x21: "PgUp", 0x22: "PgDn", 0x23: "End", 0x24: "Home",
              0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down", 0x2D: "Insert",
              0x2E: "Delete", 0x6A: "Num*", 0x6B: "Num+", 0x6D: "Num-", 0x6E: "Num.",
              0x6F: "Num/", 0x90: "NumLock", 0x91: "ScrollLock", 0xBA: ";", 0xBB: "=",
              0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`", 0xDB: "[",
              0xDC: "\\", 0xDD: "]", 0xDE: "'"}
# keys that can't be bound: mouse buttons, Shift/Ctrl/Alt, Windows keys, Esc (cancels)
_UNBINDABLE = set(range(0x01, 0x07)) | {0x10, 0x11, 0x12, 0x1B, 0x5B, 0x5C, 0x5D} | set(range(0xA0, 0xA6))
MOUSEEVENTF = {
    "left": (0x0002, 0x0004),    # down, up
    "right": (0x0008, 0x0010),
    "middle": (0x0020, 0x0040),
}
MIN_CPS, MAX_CPS = 1, 100

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20      # click-through
WS_EX_TOOLWINDOW = 0x80       # no taskbar button
WS_EX_NOACTIVATE = 0x08000000  # never steals focus


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class State:
    active = False
    quit = False
    cps = 10
    mode = "toggle"  # or "hold"
    button = "left"
    theme = "light"  # any key of THEMES
    overlay_x = 8    # where the ON/OFF badge sits on screen
    overlay_y = 8
    overlay_hwnd = 0
    overlay_movable = False   # True = unlocked (can be dragged)
    overlay_icon_rect = None  # screen rectangle of the padlock, always clickable
    overlay_enabled = True    # False = overlay hidden
    overlay_goto = None       # set by the overlay: move it to overlay_x / overlay_y
    capturing = False         # True while Settings waits for a new keybind
    keys = dict(DEFAULT_KEYS)
    sound_enabled = True      # play a sound for every click
    sound_volume = sounds.DEFAULT_VOLUME   # 0-100
    sound_theme = sounds.DEFAULT_SOUND
    sound = None              # the sound engine (sounds.ClickSound), set in main()
    ui_hwnd = 0
    dialog_hwnd = 0  # the Settings window, while it's open
    saved = None  # last settings written to disk
    # Physical (real, not injected) mouse button state, kept by the mouse hook
    phys = {"left": False, "right": False, "middle": False}


SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


def system_theme():
    """Windows' own light/dark app setting (used the first time, before you choose)."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if light else "dark"
    except OSError:
        return "light"


def _colorref(hex_colour):
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return r | (g << 8) | (b << 16)


def set_titlebar(hwnd, T):
    """Dark / coloured title bar on Windows 11 (dark only on late Windows 10).
    Silently skipped where unsupported."""
    def attr(code, value):
        v = ctypes.c_uint(value)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, code, ctypes.byref(v), ctypes.sizeof(v))
    try:
        default = 0xFFFFFFFF
        attr(20, 1 if T["dark"] else 0)
        cap = _colorref(T["caption"]) if T.get("caption") else default
        text = _colorref(T["caption_text"]) if T.get("caption") else default
        attr(35, cap)    # caption colour
        attr(36, text)   # caption text colour
        attr(34, cap)    # border colour
        # nudge Windows to repaint the frame (no move / resize / z-order change)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x37)
    except (OSError, AttributeError):
        pass


def vk_name(vk):
    """Human-readable name of a Windows virtual-key code."""
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return f"Num{vk - 0x60}"
    return _KEY_NAMES.get(vk, f"Key {vk}")


def snapshot(state):
    return {"mode": state.mode, "cps": state.cps, "button": state.button,
            "theme": state.theme, "overlay_x": state.overlay_x,
            "overlay_y": state.overlay_y, "overlay_locked": not state.overlay_movable,
            "overlay_enabled": state.overlay_enabled, "keys": dict(state.keys),
            "sound_enabled": state.sound_enabled, "sound_volume": state.sound_volume,
            "sound_theme": state.sound_theme}


def load_settings():
    """Read remembered settings; ignore a missing or damaged file."""
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        out = {}
        if data.get("mode") in ("toggle", "hold"):
            out["mode"] = data["mode"]
        if data.get("button") in MOUSEEVENTF:
            out["button"] = data["button"]
        if data.get("theme") in THEMES:
            out["theme"] = data["theme"]
        for k in ("overlay_x", "overlay_y"):
            v = data.get(k)
            if isinstance(v, int) and not isinstance(v, bool):
                out[k] = v
        if isinstance(data.get("overlay_locked"), bool):
            out["overlay_locked"] = data["overlay_locked"]
        if isinstance(data.get("overlay_enabled"), bool):
            out["overlay_enabled"] = data["overlay_enabled"]
        if isinstance(data.get("sound_enabled"), bool):
            out["sound_enabled"] = data["sound_enabled"]
        v = data.get("sound_volume")
        if isinstance(v, int) and not isinstance(v, bool):
            out["sound_volume"] = max(0, min(100, v))
        if data.get("sound_theme") in sounds.SOUND_THEMES:
            out["sound_theme"] = data["sound_theme"]
        keys = data.get("keys")
        if (isinstance(keys, dict) and set(keys) == set(DEFAULT_KEYS)
                and all(isinstance(v, int) and not isinstance(v, bool)
                        and 1 <= v <= 254 and v not in _UNBINDABLE for v in keys.values())
                and len(set(keys.values())) == len(keys)):
            out["keys"] = dict(keys)  # only accepted as a complete, conflict-free set
        if isinstance(data.get("cps"), int):
            out["cps"] = min(MAX_CPS, max(MIN_CPS, data["cps"]))
        return out
    except (OSError, ValueError, AttributeError):
        return {}


def save_if_changed(state):
    snap = snapshot(state)
    if snap == state.saved:
        return
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(snap, f)
        state.saved = snap
    except OSError:
        pass  # can't save (read-only folder, etc.) - not worth interrupting the clicker


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
WH_MOUSE_LL = 14
LLMHF_INJECTED = 0x01
# message -> (button, is_down)
MOUSE_MSGS = {0x201: ("left", True), 0x202: ("left", False),
              0x204: ("right", True), 0x205: ("right", False),
              0x207: ("middle", True), 0x208: ("middle", False)}


def mouse_hook_thread(state):
    """Watches the REAL mouse buttons. Clicks we inject ourselves are ignored,
    so the auto clicker can't mistake its own clicks for you holding the button."""
    def proc(n_code, w_param, l_param):
        if n_code >= 0 and w_param in MOUSE_MSGS:
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not info.flags & LLMHF_INJECTED:
                name, down = MOUSE_MSGS[w_param]
                state.phys[name] = down
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    cb = HOOKPROC(proc)  # keep a reference so it isn't garbage collected
    hook = user32.SetWindowsHookExW(WH_MOUSE_LL, cb, None, 0)
    if not hook:
        return
    msg = wintypes.MSG()
    while not state.quit and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        pass


def tapped(vk):
    """True if the key was pressed since the last check."""
    return bool(user32.GetAsyncKeyState(vk) & 1)


def held(vk):
    """True while the key is physically down."""
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def click(button):
    down, up = MOUSEEVENTF[button]
    user32.mouse_event(down, 0, 0, 0, 0)
    user32.mouse_event(up, 0, 0, 0, 0)


def in_failsafe_corner():
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x <= 2 and p.y <= 2


def over_ui(state):
    """True if the pointer is over our own window(s) (never click ourselves).
    The overlay counts only while it's unlocked for moving; otherwise it's click-through."""
    hwnds = [state.ui_hwnd, state.dialog_hwnd]
    if state.overlay_movable and state.overlay_enabled:
        hwnds.append(state.overlay_hwnd)
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    r = state.overlay_icon_rect  # the padlock can always be clicked, so never auto-click it
    if r and r[0] <= p.x <= r[2] and r[1] <= p.y <= r[3]:
        return True
    for h in hwnds:
        if not h:
            continue
        r = wintypes.RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        if r.left <= p.x <= r.right and r.top <= p.y <= r.bottom:
            return True
    return False


def step(cps):
    return 1 if cps < 20 else 5


def clicker_loop(state):
    def clear_presses():
        for vk in state.keys.values():
            tapped(vk)  # forget stale presses
    clear_presses()
    next_click = 0.0
    prev_active = False
    while not state.quit:
        keys = dict(state.keys)
        if state.capturing:  # Settings is waiting for a new key: hotkeys do nothing
            clear_presses()
            time.sleep(0.01)
            continue
        if tapped(keys["quit"]):
            state.quit = True
            break
        if tapped(keys["slower"]):
            state.cps = max(MIN_CPS, state.cps - step(state.cps - 1))
        if tapped(keys["faster"]):
            state.cps = min(MAX_CPS, state.cps + step(state.cps))
        if tapped(keys["mode"]):
            state.mode = "hold" if state.mode == "toggle" else "toggle"
            state.active = False
            tapped(keys["toggle"])

        if state.mode == "toggle":
            if tapped(keys["toggle"]):
                state.active = not state.active
                next_click = time.perf_counter()
        else:
            was = state.active
            state.active = state.phys[state.button]
            if state.active and not was:
                next_click = time.perf_counter()

        if state.active and not prev_active:       # clicking just started (any way it happens)
            next_click = time.perf_counter()
            if state.sound:
                state.sound.warm()                  # open the audio device before the first click
        prev_active = state.active

        if state.active and in_failsafe_corner():
            if state.mode == "toggle":
                state.active = False
        elif state.active and not over_ui(state):
            now = time.perf_counter()
            if now >= next_click:
                click(state.button)
                if state.sound:
                    state.sound.trigger(now)        # one sound per click, same timing
                interval = 1.0 / state.cps
                next_click += interval              # fixed schedule: no drift, exact CPS
                if now - next_click > 3 * interval:   # far behind (e.g. paused): don't burst
                    next_click = now + interval
            elif next_click - now < 0.002:
                while time.perf_counter() < next_click:
                    pass                            # last ~2 ms: wait precisely
                continue
        time.sleep(0.001)


# ------------------------------------------------------------------- looks
FONT_STATE = {"head": False, "body": False}


def init_fonts(root):
    fams = set(tkfont.families(root))
    FONT_STATE["head"] = themes.PS in fams
    FONT_STATE["body"] = themes.VT in fams


def ui_font(role):
    """Pixel fonts when available (negative sizes = exact pixels); Consolas otherwise."""
    if role == "body":
        return (themes.VT, -22) if FONT_STATE["body"] else ("Consolas", -17, "bold")
    size = {"status": 16, "digits": 16, "title": 12, "small": 8, "ovl": 8}[role]
    if FONT_STATE["head"]:
        return (themes.PS, -size)
    return ("Consolas", -(size if size > 8 else 11), "bold")


class PixelIcon(tk.Canvas):
    """A small pixel-art picture; optionally a button."""

    def __init__(self, parent, grid, cell, color, bg, hover=None, command=None):
        super().__init__(parent, width=len(grid[0]) * cell, height=len(grid) * cell,
                         bg=bg, highlightthickness=0, cursor="hand2" if command else "")
        self.grid_, self.cell = grid, cell
        self.color, self.hover = color, hover or color
        self.draw(color)
        if command:
            self.bind("<Enter>", lambda e: self.draw(self.hover))
            self.bind("<Leave>", lambda e: self.draw(self.color))
            self.bind("<Button-1>", lambda e: command())

    def update_look(self, grid=None, color=None, bg=None):
        """Change picture / colours in place (used by the overlay's padlock)."""
        if grid is not None and (len(grid) != len(self.grid_) or len(grid[0]) != len(self.grid_[0])):
            self.configure(width=len(grid[0]) * self.cell, height=len(grid) * self.cell)
        if grid is not None:
            self.grid_ = grid
        if color is not None:
            self.color = self.hover = color
        if bg is not None:
            self.configure(bg=bg)
        self.draw(self.color)

    def draw(self, color):
        self.delete("all")
        c = self.cell
        for y, row in enumerate(self.grid_):
            for x, ch in enumerate(row):
                if ch == "#":
                    self.create_rectangle(x * c, y * c, (x + 1) * c, (y + 1) * c,
                                          fill=color, outline="")


class PixelButton(tk.Label):
    """A button drawn as a label, so it can have a coloured pixel border
    (native Windows buttons ignore border colours)."""

    def __init__(self, parent, command, hover_bg=None, **kw):
        kw.pop("activebackground", None)
        kw.pop("activeforeground", None)
        super().__init__(parent, **kw)
        self.command, self.hover_bg, self._normal_bg = command, hover_bg, None
        self._relief = kw.get("relief", "flat")
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)

    def configure(self, cnf=None, **kw):
        kw.pop("activebackground", None)
        kw.pop("activeforeground", None)
        if "relief" in kw:
            self._relief = kw["relief"]
        return super().configure(cnf, **kw)

    config = configure

    def _enter(self, _e):
        if self.hover_bg and self._normal_bg is None:
            self._normal_bg = self.cget("bg")
            super().configure(bg=self.hover_bg)

    def _leave(self, _e):
        if self._normal_bg is not None:
            super().configure(bg=self._normal_bg)
            self._normal_bg = None
        super().configure(relief=self._relief)

    def _press(self, _e):
        if self._relief != "flat":
            super().configure(relief="sunken")

    def _release(self, e):
        super().configure(relief=self._relief)
        if 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height() and self.command:
            self.command()


class RetroRadio(tk.Frame):
    """Square pixel radio button."""

    def __init__(self, parent, T, text, var, value, command):
        super().__init__(parent, bg=T["panel"], cursor="hand2")
        self.T, self.var, self.value, self.command = T, var, value, command
        self.box = tk.Canvas(self, width=16, height=16, bg=T["panel"], highlightthickness=0)
        self.box.pack(side="left", padx=(0, 8))
        self.label = tk.Label(self, text=text, font=ui_font("body"), bg=T["panel"], fg=T["fg"])
        self.label.pack(side="left")
        for w in (self, self.box, self.label):
            w.bind("<Button-1>", self.choose)
        self._trace = var.trace_add("write", lambda *a: self.draw())
        self.bind("<Destroy>", self._cleanup)
        self.draw()

    def _cleanup(self, e):
        if e.widget is self:
            try:
                self.var.trace_remove("write", self._trace)
            except (tk.TclError, ValueError):
                pass

    def choose(self, _e=None):
        self.var.set(self.value)
        if self.command:
            self.command()

    def draw(self):
        T, on = self.T, self.var.get() == self.value
        self.box.delete("all")
        self.box.create_rectangle(1, 1, 15, 15, width=2,
                                  fill=T["radio_on"] if on else T["panel"],
                                  outline=T["radio_ring"] if on else T["radio_off"])


class RetroCheck(tk.Frame):
    """Square pixel check box bound to a BooleanVar."""

    def __init__(self, parent, T, text, var, command):
        super().__init__(parent, bg=T["panel"], cursor="hand2")
        self.T, self.var, self.command = T, var, command
        self.box = tk.Canvas(self, width=16, height=16, bg=T["panel"], highlightthickness=0)
        self.box.pack(side="left", padx=(0, 8))
        self.label = tk.Label(self, text=text, font=ui_font("body"), bg=T["panel"], fg=T["fg"])
        self.label.pack(side="left")
        for w in (self, self.box, self.label):
            w.bind("<Button-1>", self.toggle)
        self._trace = var.trace_add("write", lambda *a: self.draw())
        self.bind("<Destroy>", self._cleanup)
        self.draw()

    def _cleanup(self, e):
        if e.widget is self:
            try:
                self.var.trace_remove("write", self._trace)
            except (tk.TclError, ValueError):
                pass

    def toggle(self, _e=None):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def draw(self):
        T, on = self.T, bool(self.var.get())
        self.box.delete("all")
        self.box.create_rectangle(1, 1, 15, 15, width=2, fill=T["panel"],
                                  outline=T["radio_ring"] if on else T["radio_off"])
        if on:
            self.box.create_rectangle(4, 4, 12, 12, width=0, fill=T["radio_on"], outline="")


class Knob(tk.Canvas):
    """A round volume wheel, 0-100. Drag around it, or use the mouse wheel over it.
    The dial sweeps 270 degrees, from lower-left (0) clockwise to lower-right (100)."""
    SIZE = 96

    def __init__(self, parent, bg, track, fill, pointer, value, command, on_release=None):
        super().__init__(parent, width=self.SIZE, height=self.SIZE, bg=bg,
                         highlightthickness=0, cursor="hand2")
        self.track, self.fill, self.pointer = track, fill, pointer
        self.value, self.command, self.on_release = value, command, on_release
        self.bind("<ButtonPress-1>", lambda e: self._drag(e, jump=True))
        self.bind("<B1-Motion>", lambda e: self._drag(e, jump=False))
        self.bind("<ButtonRelease-1>", lambda e: self.on_release and self.on_release())
        self.bind("<MouseWheel>", self._wheel)
        self.draw()

    def set(self, v):
        self.value = max(0, min(100, int(v)))
        self.draw()

    def _change(self, v):
        v = max(0, min(100, int(round(v))))
        if v != self.value:
            self.set(v)
            self.command(self.value)

    def _drag(self, e, jump):
        c = self.SIZE / 2
        dx, dy = e.x - c, e.y - c
        if math.hypot(dx, dy) < 8:
            return
        angle = max(-135.0, min(135.0, math.degrees(math.atan2(dx, -dy))))  # 0 = straight up
        new = (angle + 135.0) / 270.0 * 100.0
        if not jump and abs(new - self.value) > 60:   # dragged across the gap at the bottom
            return
        self._change(new)

    def _wheel(self, e):
        self._change(self.value + (5 if e.delta > 0 else -5))
        if self.on_release:
            self.on_release()

    def draw(self):
        self.delete("all")
        c, r = self.SIZE / 2, self.SIZE / 2 - 10
        box = (c - r, c - r, c + r, c + r)
        self.create_arc(*box, start=225, extent=-270, style="arc", width=9, outline=self.track)
        if self.value > 0:
            self.create_arc(*box, start=225, extent=-270 * self.value / 100, style="arc",
                            width=9, outline=self.fill)
        a = math.radians(-135 + 270 * self.value / 100)
        sx, sy = math.sin(a), -math.cos(a)
        self.create_line(c + sx * 8, c + sy * 8, c + sx * (r - 7), c + sy * (r - 7),
                         width=4, fill=self.pointer, capstyle="round")
        self.create_oval(c - 4, c - 4, c + 4, c + 4, fill=self.pointer, outline="")


class SegBar(tk.Canvas):
    """Segmented bar (health bar / energy tanks) used as the speed slider.
    Each of the 20 segments is worth 5 clicks per second."""
    N = 20

    def __init__(self, parent, T, command):
        super().__init__(parent, height=24, width=200, bg=T["panel"], highlightthickness=2,
                         highlightbackground=T["seg_frame"], highlightcolor=T["seg_frame"],
                         cursor="hand2")
        self.T, self.command, self.value = T, command, MIN_CPS
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Button-1>", self.pick)
        self.bind("<B1-Motion>", self.pick)

    def get(self):
        return self.value

    def set(self, v):
        self.value = v
        self.draw()

    def _geometry(self):
        gap = 3
        w = max(self.winfo_width() - 4, 60)
        return gap, (w - gap * (self.N - 1)) / self.N

    def draw(self):
        self.delete("all")
        gap, sw = self._geometry()
        h = max(self.winfo_height() - 4, 6)
        filled = min(self.N, max(1, math.ceil(self.value / 5)))
        for i in range(self.N):
            x = 2 + i * (sw + gap)
            self.create_rectangle(x, 2, x + sw, 2 + h, outline="",
                                  fill=self.T["seg_on"] if i < filled else self.T["seg_off"])

    def pick(self, e):
        gap, sw = self._geometry()
        i = min(self.N - 1, max(0, int((e.x - 2) / (sw + gap))))
        self.command(max(MIN_CPS, (i + 1) * 5))


class Kit:
    """Builds the same widgets in whichever theme is active: normal ttk widgets for
    the Classic themes, hand-drawn pixel widgets for the retro ones."""

    def __init__(self, T):
        self.T = T
        self.retro = T["kind"] == "retro"
        self.panel = T.get("panel", T["bg"])

    def txt(self, s):
        return s.upper() if self.retro else s

    def configure_ttk(self, style):
        c = self.T
        if self.retro:
            return
        style.theme_use("clam")  # the default Windows theme ignores most colours
        style.configure("TLabelframe", background=c["bg"], bordercolor=c["border"])
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["fg"])
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("Hint.TLabel", background=c["bg"], foreground=c["hint"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TRadiobutton", background=c["bg"], foreground=c["fg"],
                        indicatorbackground=c["field"], indicatorforeground=c["fg"],
                        focuscolor=c["bg"])
        style.map("TRadiobutton", background=[("active", c["bg"])],
                  foreground=[("active", c["fg"])],
                  indicatorbackground=[("pressed", c["btn_hover"]), ("!pressed", c["field"])])
        style.configure("TCheckbutton", background=c["bg"], foreground=c["fg"],
                        indicatorbackground=c["field"], indicatorforeground=c["fg"],
                        focuscolor=c["bg"])
        style.map("TCheckbutton", background=[("active", c["bg"])],
                  foreground=[("active", c["fg"])],
                  indicatorbackground=[("pressed", c["btn_hover"]), ("!pressed", c["field"])])
        style.configure("TEntry", fieldbackground=c["field"], foreground=c["fg"],
                        insertcolor=c["fg"], bordercolor=c["border"],
                        lightcolor=c["field"], darkcolor=c["field"])
        style.map("TEntry", bordercolor=[("focus", c["accent"])])
        style.configure("TScale", background=c["accent"], troughcolor=c["field"],
                        bordercolor=c["border"], lightcolor=c["accent"], darkcolor=c["accent"])
        style.configure("TButton", background=c["btn"], foreground=c["fg"],
                        bordercolor=c["border"], lightcolor=c["btn"], darkcolor=c["btn"],
                        focuscolor=c["btn"], padding=4)
        style.map("TButton", background=[("active", c["btn_hover"]), ("pressed", c["btn_hover"])],
                  foreground=[("active", c["fg"])])

    def row(self, parent):
        if self.retro:
            return tk.Frame(parent, bg=self.panel)
        return ttk.Frame(parent)

    def title(self, parent, text):
        T = self.T
        if T["title_align"] == "center":
            lbl = tk.Label(parent, text=text, font=ui_font("title"), fg=T["title_fg"],
                           bg=T["title_bg"], pady=10)
            lbl.pack(fill="x")
        else:
            lbl = tk.Label(parent, text=text, font=ui_font("title"), fg=T["title_fg"],
                           bg=T["title_bg"], anchor="w", padx=14, pady=10)
            lbl.pack(fill="x")
        return lbl

    def section(self, parent, title, pady=(0, 0)):
        """A titled box; returns the frame to put the contents in."""
        T = self.T
        if not self.retro:
            lf = ttk.LabelFrame(parent, text=title, padding=8)
            lf.pack(fill="x", padx=14, pady=pady)
            return lf
        holder = tk.Frame(parent, bg=T["bg"])
        holder.pack(fill="x", padx=14, pady=pady)
        style = T["sec_style"]
        if style == "bevel":
            box = tk.Frame(holder, bg=self.panel, bd=3, relief="sunken")
            box.pack(fill="x")
            inner = tk.Frame(box, bg=self.panel, padx=10, pady=8)
        elif style == "double":
            outer = tk.Frame(holder, bg=T["sec_border"], padx=2, pady=2)
            outer.pack(fill="x")
            mid = tk.Frame(outer, bg=self.panel, padx=2, pady=2)
            mid.pack(fill="x")
            ring = tk.Frame(mid, bg=T["sec_border"], padx=1, pady=1)
            ring.pack(fill="x")
            inner = tk.Frame(ring, bg=self.panel, padx=10, pady=8)
        else:
            box = tk.Frame(holder, bg=T["sec_border"], padx=2, pady=2)
            box.pack(fill="x")
            inner = tk.Frame(box, bg=self.panel, padx=10, pady=8)
        inner.pack(fill="x")
        tk.Label(inner, text=title, font=ui_font("body"), fg=T["label_color"],
                 bg=self.panel, anchor="w").pack(fill="x")
        return inner

    def radio(self, parent, text, var, value, command):
        if self.retro:
            return RetroRadio(parent, self.T, text, var, value, command)
        return ttk.Radiobutton(parent, text=text, variable=var, value=value, command=command)

    def check(self, parent, text, var, command):
        if self.retro:
            return RetroCheck(parent, self.T, text, var, command)
        return ttk.Checkbutton(parent, text=text, variable=var, command=command)

    def label(self, parent, text, accent=False):
        T = self.T
        if self.retro:
            return tk.Label(parent, text=text, font=ui_font("body"), bg=self.panel, anchor="w",
                            fg=T["label_color"] if accent else T["fg"])
        return ttk.Label(parent, text=text, foreground=T["accent"] if accent else T["fg"])

    def button(self, parent, text, command, width=None):
        T = self.T
        if self.retro:
            return PixelButton(parent, command, hover_bg=T["btn_hover"], text=text,
                               font=ui_font("small"), bg=T["btn_bg"], fg=T["btn_fg"],
                               relief=T["btn_relief"], bd=3, padx=8, pady=6, cursor="hand2",
                               highlightthickness=2 if T.get("btn_border") else 0,
                               highlightbackground=T.get("btn_border") or T["bg"],
                               highlightcolor=T.get("btn_border") or T["bg"])
        return ttk.Button(parent, text=text, command=command, width=width, cursor="hand2")

    def status(self, parent, command):
        T = self.T
        if self.retro:
            border = T.get("status_border")
            return PixelButton(parent, command, text="", font=ui_font("status"),
                               fg=T["status_fg"], relief=T["status_relief"], bd=4, pady=14,
                               cursor="hand2", highlightthickness=3 if border else 0,
                               highlightbackground=border or T["bg"],
                               highlightcolor=border or T["bg"])
        return tk.Button(parent, text="", command=command, font=("Segoe UI", 14, "bold"),
                         fg="white", activeforeground="white", relief="flat", bd=0, pady=8,
                         cursor="hand2")

    def entry(self, parent, textvariable):
        T = self.T
        if self.retro:
            return tk.Entry(parent, textvariable=textvariable, width=4, justify="center",
                            font=ui_font("digits"), bg=T["field_bg"], fg=T["field_fg"],
                            insertbackground=T["field_fg"], relief="flat", bd=0,
                            highlightthickness=3, highlightbackground=T["field_border"],
                            highlightcolor=T["field_border"],
                            selectbackground=T["field_fg"], selectforeground=T["field_bg"])
        return ttk.Entry(parent, width=4, justify="center", font=("Segoe UI", 12, "bold"),
                         textvariable=textvariable)

    def slider(self, parent, command):
        """command(cps) is called with whole numbers."""
        if self.retro:
            return SegBar(parent, self.T, command)
        return ttk.Scale(parent, from_=MIN_CPS, to=MAX_CPS, orient="horizontal", length=200,
                         command=lambda v: command(round(float(v))))

    def hint(self, parent, text):
        T = self.T
        if self.retro:
            return tk.Label(parent, text=text, font=ui_font("body"), fg=T["hint"], bg=T["bg"],
                            justify="left", wraplength=390)
        return ttk.Label(parent, text=text, justify="left", style="Hint.TLabel")


# ----------------------------------------------------------------- overlay
def clamp_to_screen(x, y):
    """Keep the overlay on the (possibly multi-monitor) desktop."""
    vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
    return max(vx, min(x, vx + vw - 80)), max(vy, min(y, vy + vh - 40))


def cursor_pos():
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def build_overlay(root, state):
    """Returns refresh().

    Drag the badge to move it, and use the padlock at its end to lock / unlock it.
    Locked: the badge is click-through (clicks pass straight to what's underneath);
    only the padlock reacts, and only while the pointer is over it.
    Unlocked: the whole badge can be dragged."""
    ov = tk.Toplevel(root)
    ov.overrideredirect(True)
    ov.attributes("-topmost", True)
    ov.attributes("-alpha", 0.85)
    x, y = clamp_to_screen(state.overlay_x, state.overlay_y)
    ov.geometry(f"+{x}+{y}")
    label = tk.Label(ov, text="", padx=10, pady=4)
    label.pack(side="left")

    def toggle_lock():
        state.overlay_movable = not state.overlay_movable
        label.config(cursor="fleur" if state.overlay_movable else "")
        poll()

    lock = PixelIcon(ov, themes.LOCK_CLOSED, 2, "#ffffff", "#000000", command=toggle_lock)
    lock.pack(side="left", padx=(0, 9))

    ov.update_idletasks()
    hwnd = user32.GetParent(ov.winfo_id()) or ov.winfo_id()
    state.overlay_hwnd = hwnd
    flags = WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | flags)
    click_through = {"on": False}

    def set_click_through(on):
        if click_through["on"] == on:
            return
        click_through["on"] = on
        st = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              (st | WS_EX_TRANSPARENT) if on else (st & ~WS_EX_TRANSPARENT))

    def poll():
        """Locked badge lets clicks through, except while the pointer is on the padlock."""
        if state.quit:
            return
        if not state.overlay_enabled:      # hidden: nothing to click
            state.overlay_icon_rect = None
        else:
            l, t = lock.winfo_rootx() - 5, lock.winfo_rooty() - 5
            state.overlay_icon_rect = (l, t, l + lock.winfo_width() + 10,
                                       t + lock.winfo_height() + 10)
            px, py = cursor_pos()
            over_lock = (state.overlay_icon_rect[0] <= px <= state.overlay_icon_rect[2]
                         and state.overlay_icon_rect[1] <= py <= state.overlay_icon_rect[3])
            set_click_through(not state.overlay_movable and not over_lock)
        try:
            ov.after(15, poll)
        except tk.TclError:
            pass

    drag = {"dx": 0, "dy": 0}

    def on_press(e):
        drag["dx"], drag["dy"] = e.x_root - ov.winfo_x(), e.y_root - ov.winfo_y()

    def on_motion(e):
        if state.overlay_movable:
            nx, ny = clamp_to_screen(e.x_root - drag["dx"], e.y_root - drag["dy"])
            ov.geometry(f"+{nx}+{ny}")

    label.bind("<ButtonPress-1>", on_press)
    label.bind("<B1-Motion>", on_motion)
    label.config(cursor="fleur" if state.overlay_movable else "")

    def goto():
        nx, ny = clamp_to_screen(state.overlay_x, state.overlay_y)
        ov.geometry(f"+{nx}+{ny}")
    state.overlay_goto = goto

    def refresh():
        if not state.overlay_enabled:
            if ov.state() != "withdrawn":
                ov.withdraw()
            return
        if ov.state() == "withdrawn":
            ov.deiconify()
            ov.attributes("-topmost", True)
        T = THEMES[state.theme]
        font = ui_font("ovl") if T["kind"] == "retro" else ("Segoe UI", 11, "bold")
        mode = "TOGGLE" if state.mode == "toggle" else "MANUAL"
        status = "ON" if state.active else "OFF"
        bg = T["ov_on"] if state.active else T["ov_off"]
        label.config(text=f"CLICKER {status}  |  {mode}  |  {state.cps} CPS", font=font,
                     bg=bg, fg=T["ov_fg"])
        ov.configure(bg=bg)
        lock.update_look(grid=themes.LOCK_OPEN if state.overlay_movable else themes.LOCK_CLOSED,
                         color=T["ov_fg"], bg=bg)
        if state.overlay_movable:
            state.overlay_x, state.overlay_y = ov.winfo_x(), ov.winfo_y()

    poll()
    return refresh


# ------------------------------------------------------------------ window
def build_ui(state):
    themes.load_fonts()
    root = tk.Tk()
    init_fonts(root)
    root.title("Auto Clicker")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autoclicker.ico")
    try:
        root.iconbitmap(icon)
    except tk.TclError:
        pass

    style = ttk.Style(root)
    mode_var = tk.StringVar(value=state.mode)
    btn_var = tk.StringVar(value=state.button)
    cps_text = tk.StringVar(value=str(state.cps))
    theme_var = tk.StringVar(value=state.theme)
    ov_var = tk.BooleanVar(value=state.overlay_enabled)
    snd_var = tk.BooleanVar(value=state.sound_enabled)
    snd_theme_var = tk.StringVar(value=state.sound_theme)

    W = {}      # widgets that refresh() updates; rebuilt whenever the theme changes
    KB = {}     # keybind rows in the Settings window: action -> (key label, button)
    ctx = {"content": None, "dialog": None, "dlg_body": None, "cap": None}

    def cur():
        return THEMES[state.theme]

    # ---- shared actions
    def on_status():
        # Big button: starts / stops clicking in Toggle mode
        if state.mode == "toggle":
            state.active = not state.active

    def on_mode():
        state.mode = mode_var.get()
        state.active = False

    def on_button():
        state.button = btn_var.get()

    def sync_slider():
        s = W.get("slider")
        if s is not None and int(round(s.get())) != state.cps:
            s.set(state.cps)

    def set_cps(value, update_text=True):
        """Single place that changes the speed (slider, typing)."""
        state.cps = max(MIN_CPS, min(MAX_CPS, int(value)))
        if update_text:
            cps_text.set(str(state.cps))
        sync_slider()

    def on_typed(_e=None):
        # Apply live while typing, as long as it's a valid number
        try:
            v = int(cps_text.get())
        except ValueError:
            return
        if MIN_CPS <= v <= MAX_CPS:
            set_cps(v, update_text=False)

    def on_commit(_e=None):
        # Enter / clicking away: fix up empty or out-of-range text
        try:
            set_cps(int(cps_text.get()))
        except ValueError:
            set_cps(state.cps)
        if _e is not None and _e.keysym == "Return":
            root.focus_set()

    def key_name(action, t):
        name = vk_name(state.keys[action])
        return name.upper() if t["kind"] == "retro" else name

    def hint_text(t):
        """The shortcut list under the controls, always showing the current keys."""
        L = t["labels"]
        return "\n".join(f"{key_name(a, t)} - {L['act_' + a]}" for a in ACTIONS)

    # ---- main window content
    def build_content():
        t = cur()
        kit = Kit(t)
        L = dict(t["labels"])
        L["toggle"] = L["toggle"].format(key=key_name("toggle", t))
        if ctx["content"] is not None:
            ctx["content"].destroy()
        W.clear()
        root.configure(bg=t["bg"])
        kit.configure_ttk(style)
        content = tk.Frame(root, bg=t["bg"])
        content.pack()
        ctx["content"] = content

        if kit.retro:
            kit.title(content, L["title"])
        body = tk.Frame(content, bg=t["bg"])
        body.pack(pady=12)

        top = tk.Frame(body, bg=t["bg"])
        top.pack(fill="x", padx=14, pady=(0, 8))
        cog_colour = t["btn_fg"] if kit.retro else t["fg"]
        PixelIcon(top, themes.COG, 2, cog_colour, t["bg"],
                  hover=t["label_color"] if kit.retro else t["accent"],
                  command=open_settings).pack(side="right", padx=4)

        W["status"] = kit.status(body, on_status)
        W["status"].pack(fill="x", padx=14, pady=(0, 10))

        sec = kit.section(body, L["mode"])
        kit.radio(sec, L["toggle"], mode_var, "toggle", on_mode).pack(anchor="w")
        kit.radio(sec, L["hold"], mode_var, "hold", on_mode).pack(anchor="w")

        sec = kit.section(body, L["cps"], pady=8)
        row = kit.row(sec)
        row.pack(fill="x", pady=(4 if kit.retro else 0, 0))
        if t.get("heart"):
            PixelIcon(row, themes.HEART, 3, "#c8302a", t["panel"]).pack(side="left", padx=(0, 10))
        W["slider"] = kit.slider(row, set_cps)
        W["slider"].pack(side="left", fill="x", expand=True)
        W["entry"] = kit.entry(row, cps_text)
        W["entry"].pack(side="left", padx=(10, 0))
        W["entry"].bind("<KeyRelease>", on_typed)
        W["entry"].bind("<Return>", on_commit)
        W["entry"].bind("<FocusOut>", on_commit)

        sec = kit.section(body, L["button"])
        row = kit.row(sec)
        row.pack(fill="x", pady=(4 if kit.retro else 0, 0))
        for name in ("left", "right", "middle"):
            kit.radio(row, L[name], btn_var, name, on_button).pack(side="left", padx=(0, 14))

        W["hint"] = kit.hint(body, hint_text(t))
        W["hint"].pack(pady=(10, 0), padx=14, anchor="w")

        mode_var.set(state.mode)
        btn_var.set(state.button)
        cps_text.set(str(state.cps))
        sync_slider()
        if kit.retro:
            W["slider"].set(state.cps)

    # ---- keybind capture
    def held_keys():
        return {vk for vk in range(8, 255) if user32.GetAsyncKeyState(vk) & 0x8000}

    def set_msg(text):
        try:
            ctx["kb_msg"].config(text=text)
        except (KeyError, tk.TclError, AttributeError):
            pass

    def cancel_capture(rebuild=True):
        was = ctx.get("cap") is not None
        ctx["cap"] = None
        # keep hotkeys off briefly so the key just pressed can't also trigger something
        root.after(150, lambda: setattr(state, "capturing", ctx.get("cap") is not None))
        d = ctx["dialog"]
        if was and rebuild and d is not None and d.winfo_exists():
            build_dialog_content()

    def start_capture(action):
        cancel_capture(rebuild=False)
        if ctx["dialog"] is None:
            return
        L = cur()["labels"]
        state.capturing = True
        ctx["cap"] = {"action": action, "held": held_keys()}
        for a, (_k, b) in KB.items():
            b.config(text=L["press_key"] if a == action else L["change"])
        set_msg(L["kb_help"])
        root.after(25, poll_capture)

    def poll_capture():
        cap = ctx.get("cap")
        if not cap:
            return
        L = cur()["labels"]
        now = held_keys()
        cap["held"] &= now                      # released keys no longer count as held
        for vk in sorted(now - cap["held"]):
            cap["held"].add(vk)
            if vk == 0x1B:                      # Esc cancels
                cancel_capture()
                return
            if vk in _UNBINDABLE:
                set_msg("That key can't be used.")
                continue
            clash = [a for a in ACTIONS if a != cap["action"] and state.keys[a] == vk]
            if clash:
                set_msg(f"{vk_name(vk)} is already used for {L['act_' + clash[0]]}.")
                continue
            state.keys = {**state.keys, cap["action"]: vk}
            tapped(vk)                          # consume the press
            cancel_capture(rebuild=False)
            build_content()                     # shortcut list + Toggle text
            if ctx["dialog"] is not None and ctx["dialog"].winfo_exists():
                build_dialog_content()
            return
        root.after(25, poll_capture)

    def on_overlay_toggle():
        state.overlay_enabled = ov_var.get()

    def on_sound_toggle():
        state.sound_enabled = snd_var.get()

    def on_sound_theme():
        state.sound_theme = snd_theme_var.get()
        if state.sound:
            state.sound.preview(2)      # let you hear the one you just picked

    def restore_defaults():
        d = ctx["dialog"]
        if not messagebox.askyesno("Restore defaults", themes.CLASSIC_LABELS["restore_ask"],
                                   parent=d if d is not None else root):
            return
        cancel_capture(rebuild=False)
        state.mode, state.cps, state.button = "toggle", 10, "left"
        state.theme = system_theme()
        state.keys = dict(DEFAULT_KEYS)
        state.overlay_enabled, state.overlay_movable = True, False
        state.overlay_x = state.overlay_y = 8
        state.sound_enabled = True
        state.sound_volume = sounds.DEFAULT_VOLUME
        state.sound_theme = sounds.DEFAULT_SOUND
        state.active = False
        if state.overlay_goto:
            state.overlay_goto()
        for vk in state.keys.values():
            tapped(vk)
        ov_var.set(True)
        apply_theme(state.theme)

    # ---- settings window
    def select_page(key):
        if key == ctx.get("page", "themes"):
            return
        cancel_capture(rebuild=False)
        ctx["page"] = key

        def show():
            d = ctx["dialog"]
            if d is not None and d.winfo_exists():
                build_dialog_content()
        root.after(1, show)     # rebuild after this click has finished being handled

    def build_dialog_content():
        dlg = ctx["dialog"]
        t = cur()
        kit = Kit(t)
        L = t["labels"]
        KB.clear()
        if ctx["dlg_body"] is not None:
            ctx["dlg_body"].destroy()
        dlg.configure(bg=t["bg"])
        body = tk.Frame(dlg, bg=t["bg"])
        body.pack()
        ctx["dlg_body"] = body
        if kit.retro:
            kit.title(body, L["settings"])
        else:
            tk.Label(body, text=L["settings"], font=("Segoe UI", 14, "bold"),
                     bg=t["bg"], fg=t["fg"]).pack(anchor="w", padx=14, pady=(12, 4))
        page = ctx.get("page", "themes")
        row_main = tk.Frame(body, bg=t["bg"])
        row_main.pack(padx=14, pady=12)

        # ---- left: the list of settings pages (the open one is highlighted)
        side_bg = t["panel"] if kit.retro else t["field"]
        frame = tk.Frame(row_main, bg=t["sec_border"] if kit.retro else t["border"],
                         padx=2, pady=2)
        frame.pack(side="left", anchor="n", fill="y")
        side = tk.Frame(frame, bg=side_bg)
        side.pack(fill="both", expand=True)
        if kit.retro:
            sel_bg, sel_fg, nav_font = t["status_off_bg"], t["status_fg"], ui_font("body")
        else:
            sel_bg, sel_fg, nav_font = t["accent"], "#ffffff", ("Segoe UI", 11)
        for key in SETTINGS_PAGES:
            chosen = key == page
            item = tk.Label(side, text=L[key], font=nav_font, anchor="w", padx=14, pady=8,
                            width=11, cursor="hand2", bg=sel_bg if chosen else side_bg,
                            fg=sel_fg if chosen else t["fg"])
            item.pack(fill="x")
            item.bind("<Button-1>", lambda e, k=key: select_page(k))
            if not chosen:
                item.bind("<Enter>", lambda e, w=item: w.config(bg=t["btn_hover"]))
                item.bind("<Leave>", lambda e, w=item: w.config(bg=side_bg))

        # ---- right: the page for the highlighted setting (fixed size so the window
        # doesn't jump around when you switch pages)
        pw, ph = (440, 360) if kit.retro else (400, 310)
        pane = tk.Frame(row_main, bg=t["bg"], width=pw, height=ph)
        pane.pack(side="left", anchor="n", padx=(12, 0))
        pane.pack_propagate(False)
        sec = kit.section(pane, L[page])

        def note(text):
            lbl = kit.label(sec, text)
            lbl.config(wraplength=pw - 70, justify="left")
            lbl.pack(anchor="w", pady=(2, 8))

        if page == "themes":
            theme_var.set(state.theme)
            for tid in THEME_ORDER:
                kit.radio(sec, kit.txt(THEMES[tid]["name"]), theme_var, tid,
                          lambda: root.after(10, lambda: apply_theme(theme_var.get()))
                          ).pack(anchor="w", pady=2)
        elif page == "overlay":
            note(L["overlay_help"])
            ov_var.set(state.overlay_enabled)
            kit.check(sec, L["show_overlay"], ov_var, on_overlay_toggle).pack(anchor="w", pady=2)
        elif page == "sound":
            snd_var.set(state.sound_enabled)
            snd_theme_var.set(state.sound_theme)
            kit.check(sec, L["sound_on"], snd_var, on_sound_toggle).pack(anchor="w", pady=(2, 6))
            cols = kit.row(sec)
            cols.pack(fill="x")
            left = kit.row(cols)
            left.pack(side="left", anchor="n", padx=(0, 18))
            if kit.retro:
                colours = (t["seg_off"], t["seg_on"], t["fg"], t["panel"])
            else:
                colours = (t["border"], t["accent"], t["fg"], t["bg"])
            vol_label = kit.label(left, f"{L['volume']} {state.sound_volume}%")

            def on_volume(v):
                state.sound_volume = v
                vol_label.config(text=f"{L['volume']} {v}%")
            Knob(left, colours[3], colours[0], colours[1], colours[2], state.sound_volume,
                 on_volume, on_release=lambda: state.sound and state.sound.preview(2)
                 ).pack()
            vol_label.pack(pady=(2, 0))
            kit.button(left, L["test_sound"], lambda: state.sound and state.sound.preview(4),
                       width=8).pack(pady=(6, 0))
            right = kit.row(cols)
            right.pack(side="left", anchor="n")
            kit.label(right, L["sound_theme"], accent=True).pack(anchor="w")
            for sid in sounds.SOUND_ORDER:
                kit.radio(right, kit.txt(sounds.SOUND_THEMES[sid][0]), snd_theme_var, sid,
                          on_sound_theme).pack(anchor="w", pady=1)
        elif page == "keybinds":
            capturing = ctx.get("cap")
            for a in ACTIONS:
                row = kit.row(sec)
                row.pack(fill="x", pady=2)
                kit.label(row, L["act_" + a]).pack(side="left")
                btn = kit.button(row, L["press_key"] if capturing and capturing["action"] == a
                                 else L["change"], lambda a=a: start_capture(a), width=12)
                btn.pack(side="right")
                key = kit.label(row, key_name(a, t), accent=True)
                key.pack(side="right", padx=10)
                KB[a] = (key, btn)
            ctx["kb_msg"] = kit.label(sec, L["kb_help"] if capturing else "")
            ctx["kb_msg"].config(wraplength=pw - 70, justify="left")
            ctx["kb_msg"].pack(anchor="w", pady=(4, 0))
        else:  # restore
            note(L["restore_help"])
            kit.button(sec, L["restore_btn"], restore_defaults, width=18).pack(anchor="w")

    def open_settings():
        d = ctx["dialog"]
        if d is not None and d.winfo_exists():
            d.lift()
            return
        d = tk.Toplevel(root)
        d.title("Settings")
        d.resizable(False, False)
        d.attributes("-topmost", True)
        try:
            d.iconbitmap(icon)
        except tk.TclError:
            pass
        d.geometry(f"+{root.winfo_x() + 40}+{root.winfo_y() + 60}")
        d.protocol("WM_DELETE_WINDOW", close_settings)
        ctx["dialog"] = d
        ctx["page"] = "themes"
        build_dialog_content()
        d.update_idletasks()
        state.dialog_hwnd = user32.GetParent(d.winfo_id()) or d.winfo_id()
        apply_titlebars()

    def close_settings():
        cancel_capture(rebuild=False)
        d = ctx["dialog"]
        ctx["dialog"] = None
        ctx["dlg_body"] = None
        state.dialog_hwnd = 0
        if d is not None and d.winfo_exists():
            d.destroy()

    def apply_titlebars():
        for h in (state.ui_hwnd, state.dialog_hwnd):
            if h:
                set_titlebar(h, cur())

    def apply_theme(name):
        cancel_capture(rebuild=False)
        state.theme = name
        build_content()
        d = ctx["dialog"]
        if d is not None and d.winfo_exists():
            build_dialog_content()
        root.update_idletasks()
        apply_titlebars()

    # ---- start up
    overlay_refresh = build_overlay(root, state)
    state.overlay_x, state.overlay_y = clamp_to_screen(state.overlay_x, state.overlay_y)
    root.update_idletasks()
    state.ui_hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
    apply_theme(state.theme)

    def refresh():
        if state.quit:
            save_if_changed(state)
            root.destroy()
            return
        save_if_changed(state)
        t = cur()
        L = t["labels"]
        # keep the window in sync with hotkey changes
        if mode_var.get() != state.mode:
            mode_var.set(state.mode)
        sync_slider()
        try:
            typing = root.focus_get() is W.get("entry")
        except KeyError:
            typing = False
        if not typing and cps_text.get() != str(state.cps):  # leave the box alone while typing
            cps_text.set(str(state.cps))
        if state.mode == "toggle":
            text = L["on"] if state.active else L["off"]
            cursor = "hand2"
        else:
            text = L["clicking"] if state.active else L["ready"]
            cursor = "arrow"
        if t["kind"] == "retro":
            text = text.upper()
        hint = hint_text(t)
        if W["hint"].cget("text") != hint:   # keys changed, e.g. by Restore defaults
            W["hint"].config(text=hint)
        bg = t["status_on_bg"] if state.active else t["status_off_bg"]
        W["status"].config(text=text, bg=bg, activebackground=bg, fg=t["status_fg"],
                           activeforeground=t["status_fg"], cursor=cursor)
        overlay_refresh()
        root.after(50, refresh)

    refresh()
    root.protocol("WM_DELETE_WINDOW", lambda: setattr(state, "quit", True))
    return root


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cps", type=int, help="starting clicks per second")
    ap.add_argument("--button", choices=MOUSEEVENTF)
    ap.add_argument("--mode", choices=("toggle", "hold"))
    args = ap.parse_args()

    # Priority: command-line option > remembered setting > built-in default
    saved = load_settings()
    state = State()
    state.cps = min(MAX_CPS, max(MIN_CPS, args.cps or saved.get("cps", 10)))
    state.mode = args.mode or saved.get("mode", "toggle")
    state.button = args.button or saved.get("button", "left")
    state.theme = saved.get("theme") or system_theme()
    state.overlay_x = saved.get("overlay_x", 8)
    state.overlay_y = saved.get("overlay_y", 8)
    state.overlay_movable = not saved.get("overlay_locked", True)
    state.overlay_enabled = saved.get("overlay_enabled", True)
    state.keys = saved.get("keys", dict(DEFAULT_KEYS))
    state.sound_enabled = saved.get("sound_enabled", True)
    state.sound_volume = saved.get("sound_volume", sounds.DEFAULT_VOLUME)
    state.sound_theme = saved.get("sound_theme", sounds.DEFAULT_SOUND)
    state.sound = sounds.ClickSound(
        lambda: (state.sound_enabled, state.sound_volume, state.sound_theme),
        lambda: state.quit)
    state.saved = snapshot(state)

    ctypes.windll.winmm.timeBeginPeriod(1)  # finer timer, steadier clicks at high CPS
    threading.Thread(target=mouse_hook_thread, args=(state,), daemon=True).start()
    threading.Thread(target=clicker_loop, args=(state,), daemon=True).start()
    try:
        build_ui(state).mainloop()
    except KeyboardInterrupt:
        pass
    state.quit = True
    save_if_changed(state)


if __name__ == "__main__":
    main()
