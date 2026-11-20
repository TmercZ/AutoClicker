"""
Click sounds for the Auto Clicker. Standard library only (Windows waveOut via ctypes).

Every click the program makes plays one short sound, so you can HEAR that it is
clicking and how fast. The sounds are generated in code (no audio files).

How the sound lines up with the click
-------------------------------------
Sound cards always add a delay between "play this" and "you hear it". If the click
happened at once and the sound followed, the sound would always trail behind it.
So instead the clicker WAITS for the sound: it hands the engine each click ahead of
time ("this click happens at time T"), the engine places the sound in the audio
stream so it comes out of the speakers at exactly T, and the click is performed at
exactly T. Every sound is placed with sample accuracy (1/44100 s), so 10 clicks a
second is exactly 10 evenly spaced sounds a second.

How much delay to allow for the sound card is the "Sound sync" setting
(output_latency): raise it if the sound comes after the click, lower it if before.

When clicking stops, cancel() throws away every sound that hasn't been heard yet and
flushes the audio buffers, so the sound stops with the clicks (only the natural tail
of a sound that was already playing finishes).
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
IDLE_CLOSE = 2.0       # close the audio device after this many silent seconds
DEFAULT_SYNC_MS = 40   # assumed delay of the sound card + Windows audio engine
MAX_SYNC_MS = 200


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
    for i in range(int(RATE * 0.07)):
        t = i / RATE
        low += 0.22 * (rnd.uniform(-1, 1) - low)
        out.append(low * math.exp(-t / 0.014) * 1.6
                   + math.sin(2 * math.pi * 85 * t) * math.exp(-t / 0.024) * 0.9
                   + rnd.uniform(-1, 1) * math.exp(-t / 0.002) * 0.6)
    return _norm(out)


def _castlevania():
    """A whip crack: a sharp noise snap over a falling whistle."""
    rnd = random.Random(3)
    out, prev, phase, dur = [], 0.0, 0.0, 0.04
    for i in range(int(RATE * 0.05)):
        t = i / RATE
        x = rnd.uniform(-1, 1)
        high, prev = x - prev, x
        phase += 2 * math.pi * (2600 - 2150 * min(t / dur, 1.0)) / RATE
        out.append(high * math.exp(-t / 0.004) * 0.7 + math.sin(phase) * math.exp(-t / 0.016) * 0.5)
    return _norm(out)


def _metroid():
    """A power-beam shot: a fast falling laser sweep with a little warble."""
    out, phase = [], 0.0
    for i in range(int(RATE * 0.06)):
        t = i / RATE
        freq = 2300 * (500 / 2300) ** min(t / 0.055, 1.0)
        phase += 2 * math.pi * freq / RATE
        env = min(t / 0.002, 1.0) * math.exp(-t / 0.024)
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


class MMTIME(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("wType", ctypes.c_uint), ("u", ctypes.c_ubyte * 8)]


WHDR_DONE = 0x1
TIME_SAMPLES = 2
_winmm = ctypes.windll.winmm
_winmm.waveOutGetPosition.argtypes = [ctypes.c_void_p, ctypes.POINTER(MMTIME), ctypes.c_uint]
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
    """Plays one sound per click.

    settings()    -> (enabled, volume 0-100, theme id, sync in milliseconds)
    should_stop() -> True when the program is quitting

    For every click the program calls trigger(T), where T is the time (perf_counter)
    the click will be performed; the sound is timed to be heard at T. When clicking
    stops it calls cancel(). sync_delay() says how long the clicker must wait between
    handing over a click and performing it.
    """

    def __init__(self, settings, should_stop):
        self.settings, self.should_stop = settings, should_stop
        self.pending = collections.deque()   # (heard-at time, theme, volume)
        self.wake = threading.Event()
        self.voices = []                     # [start sample, samples, gain, heard-at time]
        self.cursor = 0                      # first sample of the next buffer
        self.anchor = None                   # (heard-at time, sample) the clicks are measured from
        self.broken = None                   # error text if audio can't be used
        self.sessions = 0
        self.buffers_played = 0
        self.late = 0                        # sounds that couldn't be placed on time
        self.placed = 0
        self.last_error_ms = 0.0
        self._cancel_at = None
        self._off = []                       # recent placement errors (see _place)
        self._ready = False                  # device open AND the card is really playing
        self._thread = None
        self._lock = threading.Lock()

    # ---- called from other threads
    def close(self, timeout=1.0):
        """Program is quitting (should_stop() is now True): end the audio thread and let it
        release the sound device."""
        self.wake.set()
        t = self._thread
        if t is not None:
            t.join(timeout)

    def is_ready(self):
        """True once the sound card is playing (so the first click's sound will be on time).
        Always True if audio can't be used, so clicking never waits for nothing."""
        return self._ready or bool(self.broken)

    def output_latency(self):
        """Seconds the sound card + Windows audio engine are assumed to add (the 'Sound sync')."""
        return max(0, min(MAX_SYNC_MS, self.settings()[3])) / 1000.0

    def sync_delay(self):
        """How long before a click is performed its sound must be handed over, in seconds:
        the sound-card delay plus the engine's own buffers (4 ms each) plus a safety margin
        of 3 more buffers for the mixer thread to wake up and place the sound in time."""
        return self.output_latency() + (NBUF + 3) * CHUNK / RATE

    def _ensure_thread(self):
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()

    def trigger(self, when=None, force=False):
        """A click will be performed at perf_counter time `when`: be heard exactly then."""
        enabled, volume, theme = self.settings()[:3]
        if (not enabled and not force) or volume <= 0 or self.broken:
            return
        with self._lock:
            self.pending.append((time.perf_counter() if when is None else when, theme, volume))
        self._ensure_thread()
        self.wake.set()

    def cancel(self, at=None):
        """Clicking stopped at perf_counter time `at` (now): drop every sound that would be
        heard after that and flush the audio buffers."""
        at = time.perf_counter() if at is None else at
        with self._lock:
            kept = [p for p in self.pending if p[0] <= at]
            self.pending.clear()
            self.pending.extend(kept)
            self._cancel_at = at if self._cancel_at is None else min(self._cancel_at, at)
        self.wake.set()

    def warm(self):
        """Clicking is about to start: open the audio device now so the first click isn't late."""
        enabled, volume = self.settings()[:2]
        if enabled and volume > 0 and not self.broken:
            self._ensure_thread()
            self.wake.set()

    def preview(self, count=3, cps=7):
        """A few clicks at a gentle speed, so you can hear the chosen sound and volume."""
        start = time.perf_counter() + self.sync_delay()
        for k in range(count):
            self.trigger(start + k / cps, force=True)

    # ---- the mixer (runs on its own thread)
    def _place(self, heard_at, theme, volume, now, consumed):
        """Put one click into the stream so it is heard at `heard_at`.

        consumed = the sample the sound card is playing right now. A sample `n` samples
        after it is heard n/44100 s later, plus the card's own delay (output_latency)."""
        target = consumed + round((heard_at - now - self.output_latency()) * RATE)
        if self.anchor is not None:
            t0, s0 = self.anchor
            idx = s0 + round((heard_at - t0) * RATE)      # keep exact spacing between clicks
            if abs(idx - target) > 0.006 * RATE:          # 3 in a row off by > 6 ms: the audio
                self._off.append(idx - target)            # clock really has drifted -> start over
                if len(self._off) >= 3:
                    self.anchor = None
            else:
                self._off.clear()
        if self.anchor is None:
            self._off.clear()
            idx = target
        if idx < self.cursor:                             # too late to place exactly
            self.late += 1
            idx = self.cursor
            self.anchor = None
        if self.anchor is None:
            self.anchor = (heard_at, idx)
        self.last_error_ms = (idx - target) / RATE * 1000
        self.placed += 1
        self.voices.append([idx, samples_for(theme), gain_for(volume), heard_at])

    def _take_pending(self, now, consumed):
        while True:
            with self._lock:
                item = self.pending.popleft() if self.pending else None
            if item is None:
                return
            self._place(item[0], item[1], item[2], now, consumed)

    def _mix(self, cursor, n):
        """Audio for samples [cursor, cursor + n) as 16-bit little-endian bytes."""
        out = [0.0] * n
        keep = []
        for voice in self.voices:
            start, smp, gain = voice[0], voice[1], voice[2]
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
            base = 0                    # stream sample number the card's position counter starts at
            last_active = time.perf_counter()

            def consumed_estimate():
                """The stream sample the sound card is playing right now. The card's own
                position counter is sample-accurate; it restarts at 0 after every flush."""
                m = MMTIME(TIME_SAMPLES)
                _winmm.waveOutGetPosition(handle, ctypes.byref(m), ctypes.sizeof(m))
                if m.wType == TIME_SAMPLES:
                    return base + int.from_bytes(bytes(m.u)[:4], "little")
                waiting = sum(1 for i in range(NBUF)       # fallback: count unfinished buffers
                              if queued[i] and not (hdrs[i].dwFlags & WHDR_DONE))
                return self.cursor - max(0, waiting * CHUNK - CHUNK // 2)

            while not self.should_stop():
                with self._lock:
                    cancel_at, self._cancel_at = self._cancel_at, None
                if cancel_at is not None:
                    # Clicking stopped: forget every sound not yet heard by then, flush the
                    # card's queue, and carry on from where playback really is, so the tail of
                    # a sound that is already playing still finishes naturally.
                    now_c = consumed_estimate()
                    self.voices = [v for v in self.voices if v[3] <= cancel_at]
                    _winmm.waveOutReset(handle)
                    queued = [False] * NBUF
                    nxt = 0
                    self.cursor, self.anchor = max(0, now_c), None
                    base = self.cursor
                consumed = consumed_estimate()
                if not self._ready and consumed > 2 * CHUNK:        # the card has started playing
                    self._ready = True
                self._take_pending(time.perf_counter(), consumed)   # notice hand-overs at once
                filled = False
                while True:
                    h = hdrs[nxt]
                    if queued[nxt] and not (h.dwFlags & WHDR_DONE):
                        break                              # still playing: wait
                    if queued[nxt]:
                        self.buffers_played += 1
                    consumed = consumed_estimate()
                    self._take_pending(time.perf_counter(), consumed)
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
            self._ready = False
            _winmm.waveOutReset(handle)
            for h in hdrs[:prepared]:
                _winmm.waveOutUnprepareHeader(handle, ctypes.byref(h), ctypes.sizeof(h))
            _winmm.waveOutClose(handle)
