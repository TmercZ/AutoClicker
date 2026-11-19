"""
Click sounds for the Auto Clicker. Standard library only (Windows waveOut via ctypes).

Every click the program makes triggers one short sound, so you can HEAR that it is
clicking and at what speed. The sounds are generated in code (no audio files).

How the timing works: the sound engine mixes all the clicks into one continuous
audio stream. A click is placed in that stream at exactly the same spacing as the
clicks themselves (sample-accurate, 1/44100 s), so 10 clicks per second sounds like
exactly 10 evenly spaced sounds per second. The whole stream is delayed by a small
constant (about 20-30 ms) so the spacing never wobbles.
"""
import collections
import ctypes
import math
import random
import threading
import time
from array import array
from ctypes import wintypes

RATE = 44100
CHUNK = 176            # samples per audio buffer (4 ms)
NBUF = 4               # buffers queued ahead (16 ms)
AHEAD = 5 * CHUNK      # a click's sound is scheduled ~20 ms after the first one
IDLE_CLOSE = 2.0       # close the audio device after this many silent seconds


# ------------------------------------------------------------ the sound themes
def _norm(samples, peak=0.9):
    top = max(abs(x) for x in samples) or 1.0
    return [x * peak / top for x in samples]


def _classic():
    """A crisp mechanical mouse click."""
    rnd = random.Random(1)
    out = []
    for i in range(int(RATE * 0.024)):
        t = i / RATE
        out.append(rnd.uniform(-1, 1) * math.exp(-t / 0.0011) * 0.7
                   + math.sin(2 * math.pi * 170 * t) * math.exp(-t / 0.0045) * 0.7
                   + math.sin(2 * math.pi * 3300 * t) * math.exp(-t / 0.0014) * 0.35)
    return _norm(out)


def _retro():
    """An 8-bit blip: a short rising square wave."""
    out, phase, dur = [], 0.0, 0.03
    for i in range(int(RATE * dur)):
        t = i / RATE
        phase += 2 * math.pi * (1100 + 900 * t / dur) / RATE
        out.append((1.0 if math.sin(phase) >= 0 else -1.0) * (1 - t / dur) * 0.6)
    return _norm(out, 0.7)


def _doom():
    """A pistol shot: crack, low-passed noise and a deep boom."""
    rnd = random.Random(2)
    out, low = [], 0.0
    for i in range(int(RATE * 0.1)):
        t = i / RATE
        low += 0.22 * (rnd.uniform(-1, 1) - low)
        out.append(low * math.exp(-t / 0.02) * 1.6
                   + math.sin(2 * math.pi * 85 * t) * math.exp(-t / 0.035) * 0.9
                   + rnd.uniform(-1, 1) * math.exp(-t / 0.002) * 0.6)
    return _norm(out)


def _castlevania():
    """A whip crack: a sharp noise snap over a falling whistle."""
    rnd = random.Random(3)
    out, prev, phase, dur = [], 0.0, 0.0, 0.05
    for i in range(int(RATE * 0.07)):
        t = i / RATE
        x = rnd.uniform(-1, 1)
        high, prev = x - prev, x
        phase += 2 * math.pi * (2600 - 2150 * min(t / dur, 1.0)) / RATE
        out.append(high * math.exp(-t / 0.0045) * 0.7 + math.sin(phase) * math.exp(-t / 0.022) * 0.5)
    return _norm(out)


def _metroid():
    """A power-beam shot: a fast falling laser sweep with a little warble."""
    out, phase = [], 0.0
    for i in range(int(RATE * 0.09)):
        t = i / RATE
        freq = 2300 * (500 / 2300) ** min(t / 0.08, 1.0)
        phase += 2 * math.pi * freq / RATE
        env = min(t / 0.002, 1.0) * math.exp(-t / 0.035)
        out.append((math.sin(phase) + 0.3 * math.sin(2 * phase)) * env
                   * (1 + 0.25 * math.sin(2 * math.pi * 60 * t)))
    return _norm(out)


SOUND_THEMES = {
    "classic": ("Classic click", _classic),
    "retro": ("8-bit blip", _retro),
    "doom": ("Doom pistol", _doom),
    "castlevania": ("Whip crack", _castlevania),
    "metroid": ("Power beam", _metroid),
}
SOUND_ORDER = ["classic", "retro", "doom", "castlevania", "metroid"]
DEFAULT_SOUND = "classic"
DEFAULT_VOLUME = 60
_cache = {}


def samples_for(theme):
    """The click for a theme as a list of floats in -1..1 (built once, then cached)."""
    if theme not in SOUND_THEMES:
        theme = DEFAULT_SOUND
    if theme not in _cache:
        _cache[theme] = SOUND_THEMES[theme][1]()
    return _cache[theme]


def gain_for(volume):
    """Volume 0-100 -> gain. Squared so the knob feels even to the ear."""
    return (max(0, min(100, volume)) / 100.0) ** 2 * 0.8


# --------------------------------------------------------------- Windows audio
class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
                ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
                ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD),
                ("cbSize", wintypes.WORD)]


class WAVEHDR(ctypes.Structure):
    _fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
                ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_size_t),
                ("dwFlags", wintypes.DWORD), ("dwLoops", wintypes.DWORD),
                ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]


WHDR_DONE = 0x1
_winmm = ctypes.windll.winmm
_winmm.waveOutOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint,
                               ctypes.POINTER(WAVEFORMATEX), ctypes.c_size_t,
                               ctypes.c_size_t, ctypes.c_uint]
for _name in ("waveOutPrepareHeader", "waveOutWrite", "waveOutUnprepareHeader"):
    getattr(_winmm, _name).argtypes = [ctypes.c_void_p, ctypes.POINTER(WAVEHDR), ctypes.c_uint]
_winmm.waveOutReset.argtypes = [ctypes.c_void_p]
_winmm.waveOutClose.argtypes = [ctypes.c_void_p]


def _check(result, what):
    if result:
        raise OSError(f"{what} failed (error {result})")


class ClickSound:
    """Plays one sound per click. Create once, then call trigger() for every click.

    settings()    -> (enabled, volume 0-100, theme id)   read on every click
    should_stop() -> True when the program is quitting
    """

    def __init__(self, settings, should_stop):
        self.settings, self.should_stop = settings, should_stop
        self.pending = collections.deque()   # (timestamp, theme, volume) from the clicker
        self.wake = threading.Event()
        self.voices = []                     # [start sample, samples, gain]
        self.cursor = 0                      # first sample of the next buffer
        self.anchor = None                   # (timestamp, sample) the clicks are measured from
        self.broken = None                   # error text if audio can't be used
        self.sessions = 0
        self.buffers_played = 0
        self._thread = None
        self._lock = threading.Lock()

    # ---- called from other threads
    def _ensure_thread(self):
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()

    def trigger(self, when=None, force=False):
        """One click happened at perf_counter time `when` (now if omitted)."""
        enabled, volume, theme = self.settings()
        if (not enabled and not force) or volume <= 0 or self.broken:
            return
        self.pending.append((time.perf_counter() if when is None else when, theme, volume))
        self._ensure_thread()
        self.wake.set()

    def warm(self):
        """Clicking is about to start: open the audio device now so the first click isn't late."""
        enabled, volume, _ = self.settings()
        if enabled and volume > 0 and not self.broken:
            self._ensure_thread()
            self.wake.set()

    def preview(self, count=3, cps=7):
        """A few clicks at a gentle speed, so you can hear the chosen sound and volume."""
        start = time.perf_counter()
        for k in range(count):
            self.trigger(start + k / cps, force=True)

    # ---- the mixer (runs on its own thread)
    def _place(self, when, theme, volume):
        """Put one click into the stream at the right sample position."""
        if self.anchor is None:
            self.anchor = (when, self.cursor + AHEAD)
        t0, s0 = self.anchor
        start = s0 + round((when - t0) * RATE)
        if start < self.cursor or start > self.cursor + RATE:   # fell behind / drifted: re-anchor
            self.anchor = (when, self.cursor + AHEAD)
            start = self.cursor + AHEAD
        self.voices.append([start, samples_for(theme), gain_for(volume)])

    def _take_pending(self):
        while self.pending:
            self._place(*self.pending.popleft())

    def _mix(self, cursor, n):
        """Audio for samples [cursor, cursor + n) as 16-bit little-endian bytes."""
        out = [0.0] * n
        keep = []
        for voice in self.voices:
            start, smp, gain = voice
            lo, hi = max(start, cursor), min(start + len(smp), cursor + n)
            for i in range(lo, hi):
                out[i - cursor] += smp[i - start] * gain
            if start + len(smp) > cursor + n:
                keep.append(voice)
        self.voices = keep
        pcm = array("h", [int(max(-1.0, min(1.0, x)) * 32767) for x in out])
        return pcm.tobytes()

    def _run(self):
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentThread.restype = ctypes.c_void_p
            kernel32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
            kernel32.SetThreadPriority(kernel32.GetCurrentThread(), 1)   # above normal
        except (OSError, AttributeError):
            pass
        while not self.should_stop():
            self.wake.wait(0.25)
            if not self.wake.is_set():
                continue
            self.wake.clear()
            try:
                self._session()
            except Exception as exc:         # no sound device, driver trouble, ...
                self.broken = repr(exc)
                return
            self.wake.clear()                # clicks during the session also set this flag
            if self.pending:                 # ...but anything that arrived too late to be played
                self.wake.set()              # starts a new session

    def _session(self):
        """Open the sound device, stream until nothing has clicked for a while, close it."""
        fmt = WAVEFORMATEX(1, 1, RATE, RATE * 2, 2, 16, 0)       # mono, 16-bit PCM
        handle = ctypes.c_void_p()
        _check(_winmm.waveOutOpen(ctypes.byref(handle), 0xFFFFFFFF, ctypes.byref(fmt), 0, 0, 0),
               "waveOutOpen")
        self.sessions += 1
        bufs = [ctypes.create_string_buffer(CHUNK * 2) for _ in range(NBUF)]
        hdrs = [WAVEHDR(ctypes.addressof(b), CHUNK * 2, 0, 0, 0, 0, None, 0) for b in bufs]
        prepared = 0
        try:
            for h in hdrs:
                _check(_winmm.waveOutPrepareHeader(handle, ctypes.byref(h), ctypes.sizeof(h)),
                       "waveOutPrepareHeader")
                prepared += 1
            queued = [False] * NBUF
            nxt = 0
            self.cursor, self.anchor, self.voices = 0, None, []
            last_active = time.perf_counter()
            while not self.should_stop():
                filled = False
                while True:
                    h = hdrs[nxt]
                    if queued[nxt] and not (h.dwFlags & WHDR_DONE):
                        break                              # still playing: wait
                    if queued[nxt]:
                        self.buffers_played += 1
                    self._take_pending()
                    ctypes.memmove(bufs[nxt], self._mix(self.cursor, CHUNK), CHUNK * 2)
                    _check(_winmm.waveOutWrite(handle, ctypes.byref(h), ctypes.sizeof(h)),
                           "waveOutWrite")
                    queued[nxt] = True
                    nxt = (nxt + 1) % NBUF
                    self.cursor += CHUNK
                    filled = True
                now = time.perf_counter()
                if self.voices or self.pending:
                    last_active = now
                elif now - last_active > IDLE_CLOSE:
                    break
                if not filled:
                    time.sleep(0.001)
        finally:
            _winmm.waveOutReset(handle)
            for h in hdrs[:prepared]:
                _winmm.waveOutUnprepareHeader(handle, ctypes.byref(h), ctypes.sizeof(h))
            _winmm.waveOutClose(handle)
