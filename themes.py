"""
Look-and-feel data for the Auto Clicker window: colours, labels, pixel fonts and
tiny pixel-art icons. Standard library only.

Pixel fonts (in the fonts folder, both SIL Open Font License) are loaded for this
program only - nothing is installed on the PC.
"""
import ctypes
import os
import re
import sys

# Where the bundled files (fonts, icon) are: next to this file, or inside the .exe's own
# folder when the program has been packaged with PyInstaller.
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(HERE, "fonts")
PS = "Press Start 2P"   # chunky headings / buttons
VT = "VT323"            # body text


def load_fonts():
    """Make the bundled pixel fonts usable by this process (FR_PRIVATE = 0x10)."""
    for name in ("PressStart2P-Regular.ttf", "VT323-Regular.ttf"):
        path = os.path.join(FONT_DIR, name)
        if os.path.exists(path):
            try:
                ctypes.windll.gdi32.AddFontResourceExW(path, 0x10, 0)
            except (OSError, AttributeError):
                pass


# ----------------------------------------------------------------- pixel art
COG = [
    "....###....",
    ".#..###..#.",
    ".#########.",
    "..###.###..",
    "###.....###",
    "###.....###",
    "###.....###",
    "..###.###..",
    ".#########.",
    ".#..###..#.",
    "....###....",
]
LOCK_CLOSED = [
    "..#####..",
    ".##...##.",
    ".#.....#.",
    ".#.....#.",
    "#########",
    "#########",
    "####.####",
    "####.####",
    "#########",
    "#########",
]
LOCK_OPEN = [
    "..#####..",
    ".##...##.",
    ".#.......",
    ".#.......",
    "#########",
    "#########",
    "####.####",
    "####.####",
    "#########",
    "#########",
]
HEART = [
    ".##.##.",
    "#######",
    "#######",
    ".#####.",
    "..###..",
    "...#...",
]


# -------------------------------------------------------------------- labels
CLASSIC_LABELS = dict(
    title="Auto Clicker",
    mode="Mode",
    toggle="Toggle  -  press {key} to start / stop",
    hold="Manual  -  clicks while you hold your mouse button",
    cps="Clicks per second",
    button="Mouse button",
    left="Left", right="Right", middle="Middle",
    off="OFF  -  click to start",
    on="ON  -  click to stop",
    clicking="CLICKING",
    ready="READY  (hold mouse)",
    settings="Settings",
    themes="Themes",
    overlay="Overlay",
    show_overlay="Show the ON/OFF overlay",
    overlay_help="The badge shows ON/OFF, mode and speed. Drag it to move it, and use its "
                 "padlock to lock it in place.",
    restore_help="Puts every setting back to its default: theme, mode, speed, mouse button, "
                 "overlay, keybinds and sound.",
    keybinds="Keybinds",
    sound="Sound",
    sound_on="Play a sound for every click",
    volume="Volume",
    sound_theme="Sound theme",
    sound_sync="Sound sync",
    sound_sync_help="Raise it if you hear the sound AFTER the click; lower it if you hear it before.",
    test_sound="Test",
    act_toggle="Start/Stop",
    act_quit="Close/Quit",
    act_slower="Slower",
    act_faster="Faster",
    act_mode="Switch mode",
    change="Change",
    press_key="Press a key...",
    kb_help="Press the new key, or Esc to cancel.",
    restore="Restore",
    restore_btn="Restore defaults",
    restore_ask="Restore ALL settings to their defaults?\n\nThis resets the theme, mode, speed, "
                "mouse button, overlay, keybinds and sound.",
)


def retro_labels(**over):
    """Retro themes shout: upper-case versions of the classic text, with overrides."""
    labels = {k: re.sub(" {2,}", " ", v.upper()).replace("{KEY}", "{key}")
              for k, v in CLASSIC_LABELS.items()}
    labels.update(
        toggle="TOGGLE - PRESS {key}",
        hold="MANUAL - HOLD MOUSE",
        ready="READY - HOLD MOUSE",
        show_overlay="SHOW THE OVERLAY",
    )
    labels.update(over)
    return labels


# -------------------------------------------------------------------- themes
THEMES = {
    "light": dict(
        name="Classic light", kind="classic", dark=False, caption=None,
        bg="#f3f3f3", fg="#1b1b1b", field="#ffffff", border="#b8b8b8", hint="#5a5a5a",
        accent="#2b7de9", btn="#e4e4e4", btn_hover="#d4d4d4",
        status_on_bg="#1a9c3c", status_off_bg="#b3261e", status_fg="#ffffff",
        ov_on="#1a9c3c", ov_off="#b3261e", ov_fg="#ffffff", ov_drag="#2b7de9",
        labels=CLASSIC_LABELS),
    "dark": dict(
        name="Classic dark", kind="classic", dark=True, caption=None,
        bg="#1f1f1f", fg="#e8e8e8", field="#2d2d2d", border="#4d4d4d", hint="#a0a0a0",
        accent="#4c9aff", btn="#363636", btn_hover="#444444",
        status_on_bg="#1a9c3c", status_off_bg="#b3261e", status_fg="#ffffff",
        ov_on="#1a9c3c", ov_off="#b3261e", ov_fg="#ffffff", ov_drag="#2b7de9",
        labels=CLASSIC_LABELS),

    # Doom: rusted metal, blood red, yellow HUD digits
    "doom": dict(
        name="Doom", kind="retro", dark=True, caption="#5a4330", caption_text="#f4c20d",
        bg="#2a1b10", panel="#160d06", fg="#f4c20d", hint="#a8884f", label_color="#c40000",
        btn_bg="#3b2a1c", btn_fg="#f4c20d", btn_hover="#5a4330", btn_relief="raised",
        sec_style="bevel", sec_border="#5a4330",
        radio_on="#c40000", radio_ring="#f4c20d", radio_off="#8a6a48",
        seg_on="#c40000", seg_off="#3b2a1c", seg_frame="#5a4330", heart=False,
        field_bg="#000000", field_fg="#e01010", field_border="#5a4330",
        status_on_bg="#1f7a1f", status_off_bg="#8b0000", status_fg="#ffd400",
        status_relief="raised", status_border=None,
        ov_on="#1f7a1f", ov_off="#8b0000", ov_fg="#ffd400", ov_drag="#5a4330",
        title_align="w", title_bg="#5a4330", title_fg="#f4c20d",
        labels=retro_labels()),

    # Castlevania: gothic stone, gold trim, heart counter, health bar
    "castlevania": dict(
        name="Castlevania", kind="retro", dark=True, caption="#2a2440", caption_text="#d9a441",
        bg="#0b0818", panel="#0b0818", fg="#f2e6c9", hint="#8e86a8", label_color="#d9a441",
        btn_bg="#0b0818", btn_fg="#d9a441", btn_hover="#2a2440", btn_relief="groove",
        sec_style="double", sec_border="#5a5470",
        radio_on="#c8302a", radio_ring="#d9a441", radio_off="#5a5470",
        seg_on="#e8602c", seg_off="#3a2a2a", seg_frame="#5a5470", heart=True,
        field_bg="#000000", field_fg="#f2e6c9", field_border="#d9a441",
        status_on_bg="#2a6b2a", status_off_bg="#7a1414", status_fg="#f2e6c9",
        status_relief="flat", status_border="#d9a441",
        ov_on="#2a6b2a", ov_off="#7a1414", ov_fg="#f2e6c9", ov_drag="#5a5470",
        title_align="center", title_bg="#0b0818", title_fg="#d9a441",
        labels=retro_labels(cps="HEART POWER")),

    # Metroid: visor-green HUD, orange beam button, energy tanks
    "metroid": dict(
        name="Metroid", kind="retro", dark=True, caption="#07141c", caption_text="#26d9b0",
        bg="#04070d", panel="#07141c", fg="#b9f5e6", hint="#4fa896", label_color="#ff8a1f",
        btn_bg="#07141c", btn_fg="#26d9b0", btn_hover="#0f3a40", btn_relief="flat",
        btn_border="#26d9b0",
        sec_style="flat", sec_border="#1b6e63",
        radio_on="#ff8a1f", radio_ring="#26d9b0", radio_off="#1b6e63",
        seg_on="#26d9b0", seg_off="#0f3a40", seg_frame="#1b6e63", heart=False,
        field_bg="#07141c", field_fg="#ff8a1f", field_border="#26d9b0",
        status_on_bg="#26d9b0", status_off_bg="#d8431f", status_fg="#04070d",
        status_relief="flat", status_border="#ff8a1f",
        ov_on="#26d9b0", ov_off="#d8431f", ov_fg="#04070d", ov_drag="#ff8a1f",
        title_align="w", title_bg="#04070d", title_fg="#ff8a1f",
        labels=retro_labels(
            mode="BEAM MODE", toggle="TOGGLE BEAM - {key}", hold="MANUAL BEAM - HOLD",
            cps="RATE OF FIRE", button="FIRE BUTTON")),
}

THEME_ORDER = ["light", "dark", "doom", "castlevania", "metroid"]
