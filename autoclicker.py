"""
Simple Windows auto clicker with a control window and an ON/OFF overlay.
Standard library only.

Pick the mode and speed in the window, then use the hotkeys:
  TOGGLE mode: press F6 to start / stop clicking.
  MANUAL mode: clicks while you hold your real mouse button (the one chosen
               in the window, default left). Release it and clicking stops.
  F10  = switch between TOGGLE and HOLD mode
  F8 / F9 = slower / faster
  F7   = quit (or just close the window)

Clicks happen wherever the mouse pointer currently is, so move the pointer to
your target first. Failsafe: the top-left corner of the screen stops clicking.
The overlay (top-left) is click-through, so it never blocks clicks.

Optional start values:  python autoclicker.py --cps 20 --mode hold --button right
"""
import argparse
import ctypes
import json
import os
import threading
from ctypes import wintypes
import time
import tkinter as tk
from tkinter import ttk

user32 = ctypes.windll.user32

VK_F6, VK_F7, VK_F8, VK_F9, VK_F10 = 0x75, 0x76, 0x77, 0x78, 0x79
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
    theme = "light"  # or "dark"
    ui_hwnd = 0
    saved = None  # last settings written to disk
    # Physical (real, not injected) mouse button state, kept by the mouse hook
    phys = {"left": False, "right": False, "middle": False}


SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


THEMES = {
    "light": dict(bg="#f3f3f3", fg="#1b1b1b", field="#ffffff", border="#b8b8b8",
                  hint="#5a5a5a", accent="#2b7de9", btn="#e4e4e4", btn_hover="#d4d4d4"),
    "dark": dict(bg="#1f1f1f", fg="#e8e8e8", field="#2d2d2d", border="#4d4d4d",
                 hint="#a0a0a0", accent="#4c9aff", btn="#363636", btn_hover="#444444"),
}


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


def set_titlebar_dark(hwnd, dark):
    """Dark title bar on Windows 10 (build 18985+) / 11. Silently skipped if unsupported."""
    try:
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        # nudge Windows to repaint the frame (no move / resize / z-order change)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x37)
    except (OSError, AttributeError):
        pass


def snapshot(state):
    return {"mode": state.mode, "cps": state.cps, "button": state.button,
            "theme": state.theme}


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
    """True if the pointer is over our own control window (never click ourselves)."""
    if not state.ui_hwnd:
        return False
    p = POINT()
    r = wintypes.RECT()
    user32.GetCursorPos(ctypes.byref(p))
    user32.GetWindowRect(state.ui_hwnd, ctypes.byref(r))
    return r.left <= p.x <= r.right and r.top <= p.y <= r.bottom


def step(cps):
    return 1 if cps < 20 else 5


def clicker_loop(state):
    for vk in (VK_F6, VK_F7, VK_F8, VK_F9, VK_F10):
        tapped(vk)  # clear stale presses
    next_click = 0.0
    while not state.quit:
        if tapped(VK_F7):
            state.quit = True
            break
        if tapped(VK_F8):
            state.cps = max(MIN_CPS, state.cps - step(state.cps - 1))
        if tapped(VK_F9):
            state.cps = min(MAX_CPS, state.cps + step(state.cps))
        if tapped(VK_F10):
            state.mode = "hold" if state.mode == "toggle" else "toggle"
            state.active = False
            tapped(VK_F6)

        if state.mode == "toggle":
            if tapped(VK_F6):
                state.active = not state.active
                next_click = time.perf_counter()
        else:
            was = state.active
            state.active = state.phys[state.button]
            if state.active and not was:
                next_click = time.perf_counter()

        if state.active and in_failsafe_corner():
            if state.mode == "toggle":
                state.active = False
        elif state.active and not over_ui(state):
            now = time.perf_counter()
            if now >= next_click:
                click(state.button)
                next_click = now + 1.0 / state.cps
        time.sleep(0.001)


def build_overlay(root, state):
    ov = tk.Toplevel(root)
    ov.overrideredirect(True)
    ov.attributes("-topmost", True)
    ov.attributes("-alpha", 0.85)
    ov.geometry("+8+8")
    label = tk.Label(ov, text="", font=("Segoe UI", 11, "bold"),
                     fg="white", padx=10, pady=4)
    label.pack()

    ov.update_idletasks()
    hwnd = user32.GetParent(ov.winfo_id()) or ov.winfo_id()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                          style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)

    def refresh():
        mode = "TOGGLE" if state.mode == "toggle" else "MANUAL"
        status = "ON" if state.active else "OFF"
        label.config(text=f"CLICKER {status}  |  {mode}  |  {state.cps} CPS",
                     bg="#1a9c3c" if state.active else "#b3261e")
    return refresh


def build_ui(state):
    root = tk.Tk()
    root.title("Auto Clicker")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    try:
        root.iconbitmap(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "autoclicker.ico"))
    except tk.TclError:
        pass

    pad = {"padx": 14}
    style = ttk.Style(root)
    main = ttk.Frame(root, padding=(0, 12, 0, 12))
    main.pack()

    # Top row: dark / light toggle
    top = ttk.Frame(main)
    top.pack(fill="x", padx=14, pady=(0, 8))
    theme_btn = ttk.Button(top, width=11, cursor="hand2",
                           command=lambda: apply_theme("light" if state.theme == "dark" else "dark"))
    theme_btn.pack(side="right")

    def apply_theme(name):
        c = THEMES[name]
        state.theme = name
        style.theme_use("clam")  # the default Windows theme ignores most colours
        root.configure(bg=c["bg"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TLabelframe", background=c["bg"], bordercolor=c["border"])
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["fg"])
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("Hint.TLabel", background=c["bg"], foreground=c["hint"])
        style.configure("TRadiobutton", background=c["bg"], foreground=c["fg"],
                        indicatorbackground=c["field"], indicatorforeground=c["fg"],
                        focuscolor=c["bg"])
        style.map("TRadiobutton", background=[("active", c["bg"])],
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
        theme_btn.config(text="Light mode" if name == "dark" else "Dark mode")
        if state.ui_hwnd:
            set_titlebar_dark(state.ui_hwnd, name == "dark")

    def on_status():
        # Big button: starts / stops clicking in Toggle mode
        if state.mode == "toggle":
            state.active = not state.active

    status = tk.Button(main, text="", font=("Segoe UI", 14, "bold"), fg="white",
                       activeforeground="white", relief="flat", bd=0, pady=8,
                       cursor="hand2", command=on_status)
    status.pack(fill="x", padx=14, pady=(0, 10))

    # Mode
    mode_var = tk.StringVar(value=state.mode)

    def on_mode():
        state.mode = mode_var.get()
        state.active = False

    mf = ttk.LabelFrame(main, text="Mode", padding=8)
    mf.pack(fill="x", **pad)
    ttk.Radiobutton(mf, text="Toggle  -  press F6 to start / stop",
                    variable=mode_var, value="toggle", command=on_mode).pack(anchor="w")
    ttk.Radiobutton(mf, text="Manual  -  clicks while you hold your mouse button",
                    variable=mode_var, value="hold", command=on_mode).pack(anchor="w")

    # Speed
    cps_text = tk.StringVar(value=str(state.cps))
    sf = ttk.LabelFrame(main, text="Clicks per second", padding=8)
    sf.pack(fill="x", pady=8, **pad)

    def set_cps(value, update_text=True):
        """Single place that changes the speed (slider, typing, arrows)."""
        state.cps = max(MIN_CPS, min(MAX_CPS, int(value)))
        if update_text:
            cps_text.set(str(state.cps))
        if int(round(scale.get())) != state.cps:
            scale.set(state.cps)

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

    scale = ttk.Scale(sf, from_=MIN_CPS, to=MAX_CPS, orient="horizontal", length=200,
                      command=lambda v: set_cps(round(float(v))))
    scale.set(state.cps)
    scale.pack(side="left")
    cps_entry = ttk.Entry(sf, width=4, justify="center",
                          font=("Segoe UI", 12, "bold"), textvariable=cps_text)
    cps_entry.pack(side="left", padx=(10, 0))
    cps_entry.bind("<KeyRelease>", on_typed)
    cps_entry.bind("<Return>", on_commit)
    cps_entry.bind("<FocusOut>", on_commit)

    # Button
    btn_var = tk.StringVar(value=state.button)
    bf = ttk.LabelFrame(main, text="Mouse button", padding=8)
    bf.pack(fill="x", **pad)
    for name in ("left", "right", "middle"):
        ttk.Radiobutton(bf, text=name.capitalize(), variable=btn_var, value=name,
                        command=lambda: setattr(state, "button", btn_var.get())
                        ).pack(side="left", padx=(0, 12))

    ttk.Label(main, justify="left", style="Hint.TLabel",
              text="Click the big button (or press F6), then move the pointer\n"
                   "off this window onto your target. It never clicks this window.\n"
                   "F6 start/stop (Toggle)   F8/F9 slower/faster   F10 switch mode   F7 quit"
              ).pack(pady=(10, 0), **pad)

    overlay_refresh = build_overlay(root, state)
    root.update_idletasks()
    state.ui_hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
    apply_theme(state.theme)

    def refresh():
        if state.quit:
            save_if_changed(state)
            root.destroy()
            return
        save_if_changed(state)
        # keep the window in sync with hotkey changes
        if mode_var.get() != state.mode:
            mode_var.set(state.mode)
        # Hotkeys (F8/F9) can change the speed behind the window's back
        if int(round(scale.get())) != state.cps:
            scale.set(state.cps)
        # (leave the box alone while you're typing in it)
        if root.focus_get() is not cps_entry and cps_text.get() != str(state.cps):
            cps_text.set(str(state.cps))
        if state.mode == "toggle":
            if state.active:
                status.config(text="ON  -  click to stop", bg="#1a9c3c",
                              activebackground="#1a9c3c", cursor="hand2")
            else:
                status.config(text="OFF  -  click to start", bg="#b3261e",
                              activebackground="#b3261e", cursor="hand2")
        else:
            if state.active:
                status.config(text="CLICKING", bg="#1a9c3c",
                              activebackground="#1a9c3c", cursor="arrow")
            else:
                status.config(text="READY  (hold mouse)", bg="#b3261e",
                              activebackground="#b3261e", cursor="arrow")
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
