#!/usr/bin/env python3
"""macOS-like smooth + inertial scrolling for both the touchpad (two-finger)
and an external wheel mouse, on Linux/Wayland (Sway).

Part of swayctl-center. Runs as a root system service (it needs the input
devices); its settings come from the JSON file named by $SMOOTH_SCROLL_CONFIG,
which swayctl-center writes. Changes to that file are picked up within a
second, no restart. Standalone on purpose: needs only python-evdev.

Touchpad: read raw two-finger movement in parallel with libinput (no grab),
emit scroll as a virtual wheel device. Requires `scroll_method none` set on
the touchpad in your Sway config so libinput doesn't also scroll natively.

Mouse: grabbed exclusively (EVIOCGRAB) so we can intercept its wheel notches;
everything else (movement, buttons) is cloned through unchanged via
UInput.from_device(), and only the wheel axis is re-emitted smoothed.
"""
import json
import math
import os
import signal
import sys
import threading
import time

from evdev import InputDevice, UInput, ecodes, list_devices

# ---- touchpad tunables ------------------------------------------------------
FRICTION = 0.98       # velocity multiplier applied every inertia tick (0-1). Higher = slides longer.
GAIN = 1.2000000000000002             # hi-res wheel units emitted per mm of finger travel. Raise = faster scroll.
MIN_VELOCITY = 7.0     # hi-res units/sec below which inertia stops.
NATURAL_SCROLL = True # True: content follows finger direction (macOS/Sway default).
RAMP_MS = 290.0        # how long (ms) after touch-down before scroll reaches full speed.
RAMP_POWER = 1.9       # ease-in curve exponent (progress**power => a real parabola, not linear). Higher = slower/gentler start.
SMOOTHING = 0.4        # low-pass filter factor (0-1) easing output velocity toward input while touching. Lower = smoother but laggier, higher = snappier but choppier.
CURSOR_MOVE_THRESHOLD = 3.0  # raw device units of 1-finger travel per SYN_REPORT before it counts as "moving the cursor" (vs. sensor jitter).
LIFTOFF_GRACE_MS = 250.0  # right after a two-finger scroll ends, ignore the trailing single-finger drag (one finger often leaves the pad slightly before the other) so it doesn't get mistaken for a deliberate cursor move and cancel the coast.
AXIS_LOCK_DECIDE_MM = 5.0  # cumulative pan movement (mm) since gesture start before deciding whether to lock the scroll to one axis.
AXIS_LOCK_RATIO = 2.2      # one axis must have moved at least this many times more than the other, at decision time, to lock to it (otherwise stays a free diagonal scroll).
AXIS_LOCK_SUPPRESS = 0.15  # fraction of the non-dominant axis that still gets through once locked (soft lock), so an early misjudged lock doesn't fully eat the intended axis.
PINCH_MIN_MM = 0.15    # minimum change (mm) in inter-finger spacing per sample to even consider it a pinch, not scroll jitter.
PINCH_RATIO = 0.6      # spacing change must be at least this fraction of the pan distance to be classified as pinch/zoom instead of a two-finger pan.
PINCH_STREAK_MIN = 2   # consecutive pinch-looking samples required before actually suppressing scroll (debounces single-sample noise during fast pans).
RETOUCH_GRACE_MS = 120.0  # a touch-down within this long after a touch-up is treated as the same gesture continuing (see touch_start), not a fresh one.

# ---- mouse tunables ---------------------------------------------------------
MOUSE_GAIN = 0.45             # multiplier on raw wheel notch value (120 hi-res units = 1 notch).
MOUSE_NATURAL_SCROLL = False # invert mouse wheel direction independently of the touchpad.
MOUSE_FRICTION = 0.98        # a bit shorter inertia than the touchpad by default.
MOUSE_MIN_VELOCITY = 4.5
MOUSE_RAMP_MS = 290.0        # longer ramp so wheel speed doesn't spike so abruptly on fast spins.
MOUSE_RAMP_POWER = 0.7999999999999997        # gentler curve so the very first notch still responds quickly.
MOUSE_BURST_RESET_MS = 400.0 # idle gap (ms) between notches that restarts the ramp from zero.
MOUSE_SMOOTHING = 0.99        # low-pass filter factor while actively spinning the wheel.
MOUSE_AUTO_RELEASE_MS = 180.0 # how long after the last notch before switching to inertia decay.
MOUSE_RAMP_FLOOR = 0.45        # min fraction of full speed the very first wheel notch of a gesture gets (0-1); without this it's exactly 0, so the first notch of a scroll does nothing.

TICK_HZ = 240.0        # output emission rate; higher = finer, less steppy motion (independent of the touchpad's own polling rate).
# -----------------------------------------------------------------------------

TICK_DT = 1.0 / TICK_HZ

TOUCHPAD_ENABLED = True  # False: the touchpad scrolls through libinput instead
MOUSE_ENABLED = True     # False: wheel events pass through unchanged

CONFIG_PATH = os.environ.get("SMOOTH_SCROLL_CONFIG", "")
CONFIG_POLL_S = 1.0

# JSON key -> (global name, ScrollSmoother attribute or None)
_TOUCHPAD_KEYS = {
    "enabled": ("TOUCHPAD_ENABLED", None), "natural": ("NATURAL_SCROLL", None), "speed": ("GAIN", None),
    "glide": ("FRICTION", "friction"), "min_velocity": ("MIN_VELOCITY", "min_velocity"),
    "ramp_ms": ("RAMP_MS", "ramp_ms"), "ramp_power": ("RAMP_POWER", "ramp_power"),
    "smoothing": ("SMOOTHING", "smoothing"),
}
_MOUSE_KEYS = {
    "enabled": ("MOUSE_ENABLED", None), "natural": ("MOUSE_NATURAL_SCROLL", None), "speed": ("MOUSE_GAIN", None),
    "glide": ("MOUSE_FRICTION", "friction"), "min_velocity": ("MOUSE_MIN_VELOCITY", "min_velocity"),
    "ramp_ms": ("MOUSE_RAMP_MS", "ramp_ms"), "ramp_power": ("MOUSE_RAMP_POWER", "ramp_power"),
    "smoothing": ("MOUSE_SMOOTHING", "smoothing"), "burst_reset_ms": ("MOUSE_BURST_RESET_MS", "burst_reset_ms"),
    "auto_release_ms": ("MOUSE_AUTO_RELEASE_MS", "auto_release_ms"), "ramp_floor": ("MOUSE_RAMP_FLOOR", "ramp_floor"),
}


def apply_config(cfg, touchpad_smoother=None, mouse_smoother=None):
    """Set tunables from the settings file; unknown or badly typed values are ignored."""
    for section, keys, smoother in (("touchpad", _TOUCHPAD_KEYS, touchpad_smoother),
                                     ("mouse", _MOUSE_KEYS, mouse_smoother)):
        values = cfg.get(section) if isinstance(cfg, dict) else None
        if not isinstance(values, dict):
            continue
        for key, (name, attr) in keys.items():
            if key not in values:
                continue
            value = values[key]
            current = globals()[name]
            if isinstance(current, bool):
                if not isinstance(value, bool):
                    continue
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            else:
                value = float(value)
            globals()[name] = value
            if smoother is not None and attr is not None:
                setattr(smoother, attr, value)


def read_config():
    if not CONFIG_PATH:
        return None
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f"settings: {e}", file=sys.stderr)
        return None


def watch_config(stop_flag, touchpad_smoother, mouse_smoother):
    last = None
    while not stop_flag.is_set():
        try:
            mtime = os.stat(CONFIG_PATH).st_mtime_ns if CONFIG_PATH else None
        except OSError:
            mtime = None
        if mtime is not None and mtime != last:
            last = mtime
            cfg = read_config()
            if cfg is not None:
                apply_config(cfg, touchpad_smoother, mouse_smoother)
                print("settings: loaded", file=sys.stderr)
        stop_flag.wait(CONFIG_POLL_S)
WHEEL_CODES = {
    ecodes.REL_WHEEL,
    ecodes.REL_WHEEL_HI_RES,
    ecodes.REL_HWHEEL,
    ecodes.REL_HWHEEL_HI_RES,
}
POINTER_MOVE_CODES = {ecodes.REL_X, ecodes.REL_Y}


class ScrollSmoother:
    """Decouples input arrival (irregular touchpad/mouse timing) from output
    emission (a fixed-rate loop), so choppy hardware polling never shows up
    as jerky scrolling.

    - `feed()` is called whenever new input arrives; it only updates a
      *target* velocity, it never emits directly.
    - `tick()` is called at a fixed TICK_HZ from one shared loop. While
      `continuous_input` and held, it low-pass-filters the actual output
      velocity toward the target (smooths out irregular polling). Once
      input stops (or for discrete sources like a mouse wheel notch), it
      decays the velocity via friction (inertia) and emits that.
    """

    def __init__(
        self,
        emit,
        *,
        friction,
        min_velocity,
        ramp_ms,
        ramp_power,
        continuous_input=True,
        smoothing=SMOOTHING,
        burst_reset_ms=250.0,
        auto_release_ms=None,
        ramp_floor=0.0,
    ):
        self.emit = emit
        self.friction = friction
        self.min_velocity = min_velocity
        self.ramp_ms = ramp_ms
        self.ramp_power = ramp_power
        self.continuous_input = continuous_input
        self.smoothing = smoothing
        self.burst_reset_ms = burst_reset_ms
        self.ramp_floor = ramp_floor  # min fraction of full speed on the very first sample of a gesture (see feed())
        self.auto_release_ms = auto_release_ms  # discrete sources (mouse notches): auto-clear `held`
        self.lock = threading.Lock()
        self.velocity = [0.0, 0.0]        # actual output velocity (what tick() emits from)
        self.target_velocity = [0.0, 0.0]  # where feed() wants velocity to go
        self.last_t = None
        self.gesture_start_t = None
        self.held = False  # True while actively receiving input (fingers down, or recent notch)
        self.last_touch_end_t = None

    def touch_start(self):
        with self.lock:
            now = time.time()
            # Fast swipes sometimes make the touchpad firmware briefly lose and
            # immediately reacquire finger tracking (ABS_MT_TRACKING_ID flips to
            # -1 and back within a frame or two). If we always reset velocity
            # and the ramp here, that hiccup reads as the scroll stuttering to
            # a stop and restarting mid-swipe. Treat a touch-down this soon
            # after a touch-up as a continuation of the same gesture instead.
            recent_end = (
                self.last_touch_end_t is not None
                and (now - self.last_touch_end_t) * 1000.0 < RETOUCH_GRACE_MS
            )
            self.held = True
            self.last_t = None
            if not recent_end:
                self.gesture_start_t = None
                self.velocity = [0.0, 0.0]
                self.target_velocity = [0.0, 0.0]

    def touch_end(self):
        with self.lock:
            self.held = False
            self.last_t = None
            self.target_velocity = [0.0, 0.0]
            self.last_touch_end_t = time.time()

    def cancel_inertia(self):
        """Kill any residual coasting immediately. No-op while an active
        gesture is still driving velocity (`held`), so this only cuts short
        the post-release decay, not a live scroll."""
        with self.lock:
            if not self.held:
                self.velocity[0] = self.velocity[1] = 0.0

    def recently_ended(self, grace_ms, now=None):
        now = now if now is not None else time.time()
        with self.lock:
            return self.last_touch_end_t is not None and (now - self.last_touch_end_t) * 1000.0 < grace_ms

    def feed(self, dx_raw, dy_raw, now=None):
        now = now if now is not None else time.time()
        with self.lock:
            if self.gesture_start_t is None or (
                self.last_t is not None and (now - self.last_t) * 1000.0 > self.burst_reset_ms
            ):
                self.gesture_start_t = now
            dt = max(now - self.last_t, 1e-4) if self.last_t is not None else TICK_DT
            elapsed_ms = (now - self.gesture_start_t) * 1000.0
            progress = min(1.0, elapsed_ms / self.ramp_ms)
            # On the very first sample of a gesture, elapsed_ms is exactly 0 (gesture_start_t
            # was just set to `now` above), so progress**power would be exactly 0 - the very
            # first notch/touch would move nothing at all. ramp_floor guarantees it still
            # produces real, if reduced, velocity immediately.
            ramp = max(self.ramp_floor, progress ** self.ramp_power)
            vx = (dx_raw * ramp) / dt
            vy = (dy_raw * ramp) / dt
            self.last_t = now
            if self.auto_release_ms is not None:
                self.held = True
            if self.continuous_input:
                self.target_velocity[0] = vx
                self.target_velocity[1] = vy
            else:
                # discrete source: apply as an immediate impulse
                self.velocity[0] = vx
                self.velocity[1] = vy

    def tick(self):
        now = time.time()
        with self.lock:
            if (
                self.auto_release_ms is not None
                and self.held
                and self.last_t is not None
                and (now - self.last_t) * 1000.0 > self.auto_release_ms
            ):
                self.held = False
            if self.continuous_input and self.held:
                vx, vy = self.velocity
                tx, ty = self.target_velocity
                vx += (tx - vx) * self.smoothing
                vy += (ty - vy) * self.smoothing
                self.velocity[0] = vx
                self.velocity[1] = vy
            else:
                vx, vy = self.velocity
                if abs(vx) < self.min_velocity and abs(vy) < self.min_velocity:
                    if vx or vy:
                        self.velocity[0] = self.velocity[1] = 0.0
                    return
                self.velocity[0] = vx * self.friction
                self.velocity[1] = vy * self.friction
            dx = self.velocity[0] * TICK_DT
            dy = self.velocity[1] * TICK_DT
        if dx or dy:
            self.emit(dx, dy)


def make_emitter(ui):
    accum = [0.0, 0.0]

    def emit(dx_units, dy_units):
        accum[0] += dx_units
        accum[1] += dy_units
        ix = int(accum[0])
        iy = int(accum[1])
        wrote = False
        if ix:
            ui.write(ecodes.EV_REL, ecodes.REL_HWHEEL_HI_RES, ix)
            accum[0] -= ix
            wrote = True
        if iy:
            ui.write(ecodes.EV_REL, ecodes.REL_WHEEL_HI_RES, iy)
            accum[1] -= iy
            wrote = True
        if wrote:
            ui.syn()

    return emit


def stop_all_inertia(smoothers):
    for s in smoothers:
        s.cancel_inertia()


def find_touchpad():
    for path in list_devices():
        dev = InputDevice(path)
        caps = dev.capabilities()
        if "touchpad" in dev.name.lower() and ecodes.EV_ABS in caps:
            abs_codes = [c for c, _ in caps[ecodes.EV_ABS]]
            if ecodes.ABS_MT_POSITION_X in abs_codes:
                return dev
    raise RuntimeError("No touchpad with ABS_MT_POSITION_X found")


def find_mouse():
    devices = [InputDevice(path) for path in list_devices()]

    # A remapper daemon (e.g. keyd, with `[ids] *`) grabs every physical input
    # device exclusively and re-emits through its own virtual device -
    # grabbing the physical mouse ourselves at that point fails with EBUSY
    # ("Device or resource busy"), silently disabling mouse smoothing
    # entirely. When one is running, its virtual pointer output is the real
    # live stream to attach to instead.
    for dev in devices:
        name = dev.name.lower()
        if "keyd" in name and "pointer" in name:
            return dev

    for dev in devices:
        if "touchpad" in dev.name.lower():
            continue
        caps = dev.capabilities()
        rel_codes = list(caps.get(ecodes.EV_REL, []))  # plain list of ints, not (code, info) tuples
        key_codes = list(caps.get(ecodes.EV_KEY, []))
        if ecodes.REL_WHEEL in rel_codes and ecodes.BTN_LEFT in key_codes:
            return dev
    return None


def make_mouse_clone(dev):
    """Build the mouse's UInput clone with hi-res wheel capability forced on,
    regardless of what the source device itself declares.

    Remapper daemons (e.g. keyd) often expose a virtual pointer that only
    advertises the legacy REL_WHEEL/REL_HWHEEL codes, not the hi-res
    variants. UInput.from_device() mirrors capabilities 1:1, so a clone built
    that way silently rejects our REL_WHEEL_HI_RES/REL_HWHEEL_HI_RES writes
    (the kernel uinput driver errors on event codes never registered via
    UI_SET_RELBIT) -- killing mouse scroll smoothing with no visible error.
    """
    caps = {k: set(v) if k == ecodes.EV_REL else v for k, v in dev.capabilities().items()}
    caps.pop(ecodes.EV_SYN, None)
    caps.pop(ecodes.EV_FF, None)
    rel = caps.setdefault(ecodes.EV_REL, set())
    rel.update({ecodes.REL_WHEEL_HI_RES, ecodes.REL_HWHEEL_HI_RES})
    caps[ecodes.EV_REL] = list(rel)
    return UInput(caps, name="mouse-inertia-clone")


def touchpad_worker(smoother, stop_flag, all_smoothers):
    dev = find_touchpad()
    print(f"Using touchpad: {dev.path} ({dev.name})", file=sys.stderr)

    info_x = dev.absinfo(ecodes.ABS_MT_POSITION_X)
    info_y = dev.absinfo(ecodes.ABS_MT_POSITION_Y)
    res_x = info_x.resolution or 40
    res_y = info_y.resolution or 40

    slots = {}
    active_fingers = set()
    cur_slot = 0
    last_avg = None
    last_sep_mm = None  # inter-finger spacing (mm), to tell pinch/zoom apart from a two-finger pan
    last_single = None  # tracks 1-finger position, to detect real cursor movement (not scroll)
    pinch_streak = 0  # consecutive pinch-looking samples; debounces single-sample noise during fast pans
    axis_lock = None  # None = still deciding, 'x'/'y' = locked, 'free' = decided diagonal (no lock)
    cum_dx_mm = 0.0  # cumulative pan movement (mm) since the current gesture started, used to pick axis_lock
    cum_dy_mm = 0.0

    for event in dev.read_loop():
        if stop_flag.is_set():
            return
        if event.type == ecodes.EV_ABS:
            if event.code == ecodes.ABS_MT_SLOT:
                cur_slot = event.value
            elif event.code == ecodes.ABS_MT_TRACKING_ID:
                if event.value == -1:
                    active_fingers.discard(cur_slot)
                    slots.pop(cur_slot, None)
                else:
                    active_fingers.add(cur_slot)
                    slots[cur_slot] = {"x": None, "y": None}
                if len(active_fingers) == 2:
                    smoother.touch_start()
                    last_avg = None
                    last_sep_mm = None
                    pinch_streak = 0
                    axis_lock = None
                    cum_dx_mm = cum_dy_mm = 0.0
                else:
                    smoother.touch_end()
                    last_avg = None
                    last_sep_mm = None
                    pinch_streak = 0
                    axis_lock = None
                    cum_dx_mm = cum_dy_mm = 0.0
                last_single = None
            elif event.code == ecodes.ABS_MT_POSITION_X:
                slots.setdefault(cur_slot, {})["x"] = event.value
            elif event.code == ecodes.ABS_MT_POSITION_Y:
                slots.setdefault(cur_slot, {})["y"] = event.value
        elif event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
            if len(active_fingers) == 2:
                pts = [
                    slots[s]
                    for s in active_fingers
                    if slots.get(s) and slots[s].get("x") is not None and slots[s].get("y") is not None
                ]
                if len(pts) == 2:
                    ax = (pts[0]["x"] + pts[1]["x"]) / 2.0
                    ay = (pts[0]["y"] + pts[1]["y"]) / 2.0
                    sep_mm = math.hypot(
                        (pts[0]["x"] - pts[1]["x"]) / res_x * 25.4,
                        (pts[0]["y"] - pts[1]["y"]) / res_y * 25.4,
                    )
                    now = time.time()
                    if last_avg is not None and last_sep_mm is not None:
                        dmx_mm = (ax - last_avg[0]) / res_x * 25.4
                        dmy_mm = (ay - last_avg[1]) / res_y * 25.4
                        dsep_mm = abs(sep_mm - last_sep_mm)
                        pan_mm = math.hypot(dmx_mm, dmy_mm)
                        looks_pinchy = dsep_mm > PINCH_MIN_MM and dsep_mm > pan_mm * PINCH_RATIO
                        pinch_streak = pinch_streak + 1 if looks_pinchy else 0
                        if pinch_streak >= PINCH_STREAK_MIN:
                            # Fingers spreading/pinching, not panning together, for several
                            # samples in a row (not just one noisy sample -- fast pans can
                            # briefly desync the two fingers' spacing too): this is a zoom
                            # gesture -- let libinput's own pinch recognizer handle it
                            # untouched, and ease our scroll velocity to zero instead of
                            # emitting wheel events for the midpoint drift.
                            smoother.feed(0.0, 0.0, now)
                        else:
                            cum_dx_mm += dmx_mm
                            cum_dy_mm += dmy_mm
                            if axis_lock is None and math.hypot(cum_dx_mm, cum_dy_mm) > AXIS_LOCK_DECIDE_MM:
                                # Enough movement to tell intent: pick whichever axis
                                # dominates so far and lock to it for the rest of the
                                # gesture, muting cross-axis drift from an imperfectly
                                # straight swipe. A genuinely diagonal swipe (neither
                                # axis dominant) stays unlocked.
                                if abs(cum_dy_mm) > abs(cum_dx_mm) * AXIS_LOCK_RATIO:
                                    axis_lock = "y"
                                elif abs(cum_dx_mm) > abs(cum_dy_mm) * AXIS_LOCK_RATIO:
                                    axis_lock = "x"
                                else:
                                    axis_lock = "free"
                            if axis_lock == "y":
                                dmx_mm *= AXIS_LOCK_SUPPRESS
                            elif axis_lock == "x":
                                dmy_mm *= AXIS_LOCK_SUPPRESS
                            if TOUCHPAD_ENABLED:
                                sign = -1 if NATURAL_SCROLL else 1
                                smoother.feed(sign * dmx_mm * GAIN, sign * dmy_mm * GAIN, now)
                    last_avg = (ax, ay)
                    last_sep_mm = sep_mm
                last_single = None
            elif len(active_fingers) == 1:
                # Single-finger touch drives the real cursor via libinput (we don't
                # emit anything for it) -- if it's actually moving, treat that as
                # "the user moved the pointer" and cut any residual scroll coast.
                s = next(iter(active_fingers))
                pt = slots.get(s)
                if pt and pt.get("x") is not None and pt.get("y") is not None:
                    if last_single is not None and not smoother.recently_ended(LIFTOFF_GRACE_MS):
                        dx = pt["x"] - last_single[0]
                        dy = pt["y"] - last_single[1]
                        if abs(dx) > CURSOR_MOVE_THRESHOLD or abs(dy) > CURSOR_MOVE_THRESHOLD:
                            stop_all_inertia(all_smoothers)
                    last_single = (pt["x"], pt["y"])
                else:
                    last_single = None
                last_avg = None
                last_sep_mm = None
            else:
                last_avg = None
                last_sep_mm = None
                last_single = None


def mouse_worker(smoother, stop_flag, all_smoothers):
    dev = find_mouse()
    if dev is None:
        print("No external mouse found; mouse smoothing disabled.", file=sys.stderr)
        return
    print(f"Using mouse: {dev.path} ({dev.name})", file=sys.stderr)

    dev.grab()
    clone = make_mouse_clone(dev)
    smoother.emit = make_emitter(clone)

    frame_hires = [0, 0]
    frame_legacy = [0, 0]
    got_hires = [False, False]
    moved = False
    frame_wheel = []  # this frame's raw wheel events, re-sent as they are when smoothing is off

    try:
        for event in dev.read_loop():
            if stop_flag.is_set():
                return
            if event.type == ecodes.EV_REL and event.code in WHEEL_CODES:
                frame_wheel.append((event.code, event.value))
                if event.code == ecodes.REL_HWHEEL:
                    frame_legacy[0] += event.value
                elif event.code == ecodes.REL_WHEEL:
                    frame_legacy[1] += event.value
                elif event.code == ecodes.REL_HWHEEL_HI_RES:
                    frame_hires[0] += event.value
                    got_hires[0] = True
                elif event.code == ecodes.REL_WHEEL_HI_RES:
                    frame_hires[1] += event.value
                    got_hires[1] = True
                continue
            if event.type == ecodes.EV_REL and event.code in POINTER_MOVE_CODES:
                moved = True
                clone.write(event.type, event.code, event.value)
                continue
            if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
                dx_raw = frame_hires[0] if got_hires[0] else frame_legacy[0] * 120
                dy_raw = frame_hires[1] if got_hires[1] else frame_legacy[1] * 120
                if (dx_raw or dy_raw) and not MOUSE_ENABLED:
                    for code, value in frame_wheel:
                        clone.write(ecodes.EV_REL, code, value)
                elif dx_raw or dy_raw:
                    sign = -1 if MOUSE_NATURAL_SCROLL else 1
                    smoother.feed(sign * dx_raw * MOUSE_GAIN, sign * dy_raw * MOUSE_GAIN, time.time())
                elif moved:
                    # Physically moving the mouse: stop any residual scroll coast
                    # from this mouse's own wheel, and from the touchpad's.
                    stop_all_inertia(all_smoothers)
                frame_wheel.clear()
                frame_hires[0] = frame_hires[1] = 0
                frame_legacy[0] = frame_legacy[1] = 0
                got_hires[0] = got_hires[1] = False
                moved = False
                clone.syn()
                continue
            clone.write(event.type, event.code, event.value)
    finally:
        try:
            dev.ungrab()
        except OSError:
            pass
        clone.close()


def main():
    stop_flag = threading.Event()
    cfg = read_config()
    if cfg is not None:
        apply_config(cfg)  # before the smoothers are built from these values

    touchpad_ui = UInput(
        {
            ecodes.EV_REL: [
                ecodes.REL_WHEEL,
                ecodes.REL_WHEEL_HI_RES,
                ecodes.REL_HWHEEL,
                ecodes.REL_HWHEEL_HI_RES,
            ]
        },
        name="touchpad-inertia-scroll-wheel",
    )
    touchpad_smoother = ScrollSmoother(
        make_emitter(touchpad_ui),
        friction=FRICTION,
        min_velocity=MIN_VELOCITY,
        ramp_ms=RAMP_MS,
        ramp_power=RAMP_POWER,
        smoothing=SMOOTHING,  # the default argument was bound before the settings file was read
    )

    smoothers = [touchpad_smoother]

    try:
        mouse_dev = find_mouse()
    except Exception:
        mouse_dev = None
    mouse_smoother = None
    if mouse_dev is not None:
        # mouse_worker creates its own clone UInput internally (mirrors mouse_dev's caps)
        mouse_smoother = ScrollSmoother(
            lambda dx, dy: None,  # placeholder; replaced once clone UInput exists
            friction=MOUSE_FRICTION,
            min_velocity=MOUSE_MIN_VELOCITY,
            ramp_ms=MOUSE_RAMP_MS,
            ramp_power=MOUSE_RAMP_POWER,
            continuous_input=True,
            smoothing=MOUSE_SMOOTHING,
            burst_reset_ms=MOUSE_BURST_RESET_MS,
            auto_release_ms=MOUSE_AUTO_RELEASE_MS,
            ramp_floor=MOUSE_RAMP_FLOOR,
        )
        smoothers.append(mouse_smoother)

    threads = [
        threading.Thread(target=touchpad_worker, args=(touchpad_smoother, stop_flag, smoothers), daemon=True)
    ]
    if mouse_smoother is not None:
        threads.append(threading.Thread(target=mouse_worker, args=(mouse_smoother, stop_flag, smoothers), daemon=True))

    def inertia_loop():
        while not stop_flag.is_set():
            time.sleep(TICK_DT)
            for s in smoothers:
                s.tick()

    threads.append(threading.Thread(target=inertia_loop, daemon=True))
    threads.append(threading.Thread(target=watch_config, args=(stop_flag, touchpad_smoother, mouse_smoother),
                                    daemon=True))

    def handle_sigterm(_sig, _frame):
        stop_flag.set()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
