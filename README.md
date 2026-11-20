# Auto Clicker

A small, local Windows auto clicker with a control window and an on-screen ON/OFF badge.
No third-party packages - just Python's standard library.

## Features

- **Toggle mode** - click the big button (or press **F6**) to start / stop.
- **Manual mode** - clicks repeatedly while you hold your real mouse button.
- Adjustable speed from 1 to 100 clicks per second (slider or type a number).
- Left, right or middle button.
- **Settings** (the cog at the top right):
  - **Themes** - Classic light, Classic dark, and three 16-bit game looks: **Doom**,
    **Castlevania** and **Metroid**. Classic starts with your Windows light/dark setting.
  - **Overlay** - a check box to show or hide the ON/OFF badge.
  - **Sound** - a click sound for every click (so you can hear that it's working and how
    fast), a round volume wheel, and five sound themes: Classic click, 8-bit blip, Doom pistol,
    Whip crack and Power beam. The sounds are generated in code, no audio files.
    Each click waits a moment for its sound so the two line up, and the sound stops the instant
    the clicking stops. **Sound sync** fine-tunes this for your speakers or headphones:
    raise it if you hear the sound after the click, lower it if before.
  - **Keybinds** - see every hotkey and change any of them (press the new key, Esc cancels).
  - **Restore** - one button to put every setting back to its default.
- Exact click rate: clicks run on a fixed schedule, so 20 clicks per second really is 20.
- Draggable ON/OFF badge: click the padlock at its end to unlock it, drag it where you like,
  click the padlock again to lock it. Locked, it's click-through, so it never gets in your way.
- Remembers your last mode, speed, button, theme, and badge position and lock.
- Never clicks its own window. Moving the pointer to the top-left screen corner stops clicking.

## Quick install (Windows 10 / 11)

1. Click **Code > Download ZIP** on GitHub and unzip it.
2. Double-click **`install.bat`**.

That's it. It finds Python (or installs it with winget if missing), copies the app to
`%LOCALAPPDATA%\AutoClicker`, adds an **Auto Clicker** shortcut to your Desktop and Start
menu, and launches it. To remove everything, double-click **`uninstall.bat`**.

(If Windows shows a blue "protected your PC" box, click **More info > Run anyway**.
The installer is a plain, readable script: `install.ps1`.)

## Download the program (no Python needed)

Open the **Releases** page of this repository, download **`AutoClicker-windows.zip`**, unzip it,
and double-click **`AutoClicker.exe`**. Keep the unzipped folder together (the program needs the
files next to it). There is nothing to install and nothing to uninstall: delete the folder.

Windows SmartScreen or your antivirus may warn about it, because the program is unsigned and
it sends mouse clicks. Click **More info > Run anyway**. All of the source is in this repository,
and you can build the program yourself by double-clicking `build_exe.bat`.

## Nothing runs in the background

- It is a normal window program with a single process: no services, no startup entries, no
  scheduled tasks, and it never starts another program.
- Close the window (or press the quit key, F7 by default) and every part of it stops: the
  clicker, the mouse watching, the sound and the audio device. Nothing is left running.
- While you are in Toggle mode it doesn't watch the mouse at all. The mouse is only watched
  while Manual mode is selected.
- Settings are saved in `%LOCALAPPDATA%\AutoClicker` (the downloaded program) or next to the
  script (the Python version). Delete that folder to remove them.

## Requirements (manual setup)

- Windows 10 / 11
- [Python 3.8+](https://www.python.org/downloads/) (the standard installer includes tkinter)

## Run without installing

```
python autoclicker.py
```

Use `pythonw autoclicker.py` to run without a console window.
Optional start values: `python autoclicker.py --cps 20 --mode hold --button right`

## Hotkeys (defaults - change them in Settings)

| Key | Action |
|---|---|
| F6 | Start / stop (Toggle mode) |
| F8 / F9 | Slower / faster |
| F10 | Switch Toggle / Manual |
| F7 | Quit |

## Notes

- Clicks happen wherever your pointer is.
- Many online games and some apps forbid automated input. Use it responsibly and
  only where it's allowed.
- Settings are stored in `settings.json` next to the script (not tracked by git).

## License and credits

MIT - see [LICENSE](LICENSE).

The retro themes use two pixel fonts bundled in the `fonts` folder, both under the
SIL Open Font License 1.1 (license texts included): **Press Start 2P** (CodeMan38) and
**VT323** (Peter Hull). They are loaded by the program only; nothing is installed on your PC.
The theme names are tributes to classic games; this project isn't affiliated with them.
