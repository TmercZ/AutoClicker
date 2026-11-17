# Auto Clicker

A small, local Windows auto clicker with a control window and an on-screen ON/OFF badge.
No third-party packages - just Python's standard library.

## Features

- **Toggle mode** - click the big button (or press **F6**) to start / stop.
- **Manual mode** - clicks repeatedly while you hold your real mouse button.
- Adjustable speed from 1 to 100 clicks per second (slider or type a number).
- Left, right or middle button.
- Remembers your last mode, speed and button.
- Never clicks its own window. Moving the pointer to the top-left screen corner stops clicking.

## Quick install (Windows 10 / 11)

1. Click **Code > Download ZIP** on GitHub and unzip it.
2. Double-click **`install.bat`**.

That's it. It finds Python (or installs it with winget if missing), copies the app to
`%LOCALAPPDATA%\AutoClicker`, adds an **Auto Clicker** shortcut to your Desktop and Start
menu, and launches it. To remove everything, double-click **`uninstall.bat`**.

(If Windows shows a blue "protected your PC" box, click **More info > Run anyway**.
The installer is a plain, readable script: `install.ps1`.)

## Requirements (manual setup)

- Windows 10 / 11
- [Python 3.8+](https://www.python.org/downloads/) (the standard installer includes tkinter)

## Run without installing

```
python autoclicker.py
```

Use `pythonw autoclicker.py` to run without a console window.
Optional start values: `python autoclicker.py --cps 20 --mode hold --button right`

## Hotkeys

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

## License

MIT - see [LICENSE](LICENSE).
