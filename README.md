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

## Requirements

- Windows 10 / 11
- [Python 3.8+](https://www.python.org/downloads/) (the standard installer includes tkinter)

## Run

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
