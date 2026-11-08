"""Keeps the desktop responsive while heavy work runs: builds, language servers
and indexers are put behind the program you are using.

macOS does this with QoS classes; here it is nice values, the scheduling policy
and the I/O priority of the user's own processes, all things an ordinary user
may change (lowering priority always; raising it down to RLIMIT_NICE).

Everything that decides is pure - `classify` and `plan` take plain data - and
`Governor` is the thin part that reads /proc and makes the syscalls, remembering
each process's original values so they can be put back.
"""
from __future__ import annotations

import ctypes
import logging
import os
import platform
import re
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

IO_NONE, IO_REALTIME, IO_BEST_EFFORT, IO_IDLE = 0, 1, 2, 3
SCHED_NORMAL_POLICIES = (os.SCHED_OTHER, os.SCHED_BATCH, os.SCHED_IDLE)
PF_KTHREAD = 0x00200000

TIER_NAMES = ("ui", "interactive", "background", "batch")
RAISING = ("ui", "interactive")   # tiers that only ever raise a program, and are not inherited


@dataclass(frozen=True)
class Tier:
    nice: int
    io_class: int
    io_level: int
    policy: int


def tiers(background_nice: int, focus_nice: int, ui_nice: int = -10) -> dict[str, Tier]:
    """ui: the bar, launcher and notifications - above everything, even what a
    favored app has just started (those are born at its nice); interactive: what
    you are using; background: useful but can wait (language server, indexer);
    batch: heavy and not urgent (builds)."""
    return {
        "ui": Tier(ui_nice, IO_BEST_EFFORT, 0, os.SCHED_OTHER),
        "interactive": Tier(focus_nice, IO_BEST_EFFORT, 2, os.SCHED_OTHER),
        "background": Tier(background_nice, IO_BEST_EFFORT, 6, os.SCHED_OTHER),
        "batch": Tier(19, IO_IDLE, 0, os.SCHED_BATCH),
    }


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    ppid: int
    comm: str
    cmdline: str
    start: int          # clock ticks since boot: pid + start identify one process
    nice: int
    policy: int
    kernel: bool = False


@dataclass(frozen=True)
class Rule:
    match: re.Pattern
    field: str          # "name" (the process name) or "cmdline"
    tier: str

    def hits(self, p: ProcInfo) -> bool:
        return bool(self.match.search(p.comm if self.field == "name" else p.cmdline))


def compile_rules(items: Iterable[dict[str, Any]]) -> list[Rule]:
    out = []
    for it in items:
        if not it.get("enabled", True):
            continue
        try:
            out.append(Rule(re.compile(it["match"]), it.get("field", "name"), it["tier"]))
        except (re.error, KeyError) as e:
            log.warning("priority rule %r skipped: %s", it, e)
    return out


def classify(p: ProcInfo, rules: list[Rule], protect: re.Pattern | None) -> str | None:
    """The tier a rule gives this process (the first matching rule wins), or None
    when it is left alone."""
    if p.kernel or (protect is not None and protect.search(p.comm)):
        return None
    if p.policy not in SCHED_NORMAL_POLICIES:
        return None  # real-time work (the compositor, audio) is never touched
    for r in rules:
        if r.hits(p):
            return r.tier
    return None


@dataclass
class Settings:
    rules: list[Rule]
    protect: re.Pattern | None
    background_nice: int = 10
    focus_boost: bool = True
    favor_windows: bool = True  # every program that draws on the screen (has the GPU open) is favored
    focus_nice: int = -4
    ui_nice: int = -10
    pressure_guard: bool = True
    compositor_realtime: bool = True
    compositor_names: tuple[str, ...] = ("sway", "swayctl-fx", "swayfx")
    cpu_cap: int = 100          # % of all processor time the demoted programs may use together
    gpu_guard: bool = True
    gpu_limit: int = 80         # % busy at which the GPU guard starts holding back unfocused GPU clients


def protect_pattern(names: Iterable[str]) -> re.Pattern | None:
    names = [n for n in names if n]
    if not names:
        return None
    return re.compile("^(" + "|".join(re.escape(n) for n in names) + ")$")


def descendants(procs: dict[int, ProcInfo], root: int) -> list[int]:
    kids: dict[int, list[int]] = {}
    for p in procs.values():
        kids.setdefault(p.ppid, []).append(p.pid)
    out, stack, seen = [], [root], {root}
    while stack:
        for c in kids.get(stack.pop(), ()):
            if c in seen:  # a parent loop (a stale or odd table) must not hang the scan
                continue
            seen.add(c)
            out.append(c)
            stack.append(c)
    return out


def plan(procs: dict[int, ProcInfo], s: Settings, focus_pid: int | None,
         under_pressure: bool, own_pid: int = 0, gpu_heavy: Iterable[int] = (),
         held: Iterable[int] = (), windows: Iterable[int] = ()) -> dict[int, Tier]:
    """pid -> the tier values it should have. Processes not in the result keep
    (or get back) their own values.

    Rules decide first, and a rule's tier reaches the whole subtree under the
    matched process (a build's compilers) unless something there is protected
    or matched by its own rule. The focused window's program (and what it
    spawned) is raised to `focus_nice`, but only when that really is more
    priority than it has, and never over a rule. `held` are the processes this
    governor already changed: their nice is its own doing, not the program's,
    so it must not count as "already has more" (or the next scan would let go
    of what the last one raised, and raise it again, forever)."""
    held = set(held)
    table = tiers(s.background_nice, s.focus_nice, s.ui_nice)
    if under_pressure:  # the machine is struggling: what can wait waits harder
        table["background"] = table["batch"]
    chosen: dict[int, str] = {}
    for p in procs.values():
        if p.pid == own_pid:
            continue
        t = classify(p, s.rules, s.protect)
        if t:
            chosen[p.pid] = t
    # the GPU is saturated: programs that are hogging it and that nobody asked to favor wait
    for pid in gpu_heavy:
        p = procs.get(pid)
        if (p is None or pid in chosen or pid == own_pid or p.kernel or p.policy not in SCHED_NORMAL_POLICIES
                or (s.protect is not None and s.protect.search(p.comm))):
            continue
        chosen[pid] = "background"
    # programs that draw on the screen (they hold the GPU open) are the interface of
    # the moment: favored without anyone listing them, behind any rule
    for pid in windows:
        p = procs.get(pid)
        if (p is None or pid in chosen or pid == own_pid or p.kernel or p.policy not in SCHED_NORMAL_POLICIES
                or (s.protect is not None and s.protect.search(p.comm))):
            continue
        chosen[pid] = "interactive"
    # a matched process hands its tier down to its children (what it launches
    # is not "the interface" just because the bar launched it)
    for pid in list(chosen):
        if chosen[pid] in RAISING:
            continue
        for c in descendants(procs, pid):
            child = procs[c]
            if c in chosen or c == own_pid or child.kernel or child.policy not in SCHED_NORMAL_POLICIES:
                continue
            if s.protect is not None and s.protect.search(child.comm):
                continue
            chosen[c] = chosen[pid]
    # "interactive" only ever raises: a process with more priority already keeps it
    result = {pid: table[t] for pid, t in chosen.items()
              if t in table and not (t in RAISING and pid not in held and procs[pid].nice <= table[t].nice)}
    if s.focus_boost and focus_pid and focus_pid in procs and focus_pid not in chosen:
        boost = table["interactive"]
        for pid in [focus_pid, *descendants(procs, focus_pid)]:
            p = procs.get(pid)
            if p is None or pid in chosen or pid == own_pid or p.kernel or p.policy not in SCHED_NORMAL_POLICIES:
                continue
            if s.protect is not None and s.protect.search(p.comm):
                continue
            if p.nice > boost.nice or pid in held:
                result[pid] = boost
    return result


# --- the compositor ----------------------------------------------------------

def realtime_candidates(procs: dict[int, ProcInfo], names: Iterable[str]) -> list[int]:
    """Compositor processes (by name) that run at normal priority: the screen is
    drawn by them, so a busy machine must never delay them. Ones already
    real-time (swayctl-fx sets itself SCHED_RR) are left alone."""
    names = set(names)
    return [p.pid for p in procs.values()
            if p.comm in names and not p.kernel and p.policy in SCHED_NORMAL_POLICIES]


def can_realtime() -> bool:
    """A user may use SCHED_RR when RLIMIT_RTPRIO allows it (the audio group's
    limits.d file does)."""
    import resource
    soft = resource.getrlimit(resource.RLIMIT_RTPRIO)[0]
    return soft == resource.RLIM_INFINITY or soft >= 1


# --- pressure (PSI) -----------------------------------------------------------

def read_pressure(root: Path = Path("/proc/pressure")) -> dict[str, float]:
    """{"cpu": some avg10, "io": full avg10, "memory": some avg10}, in percent;
    missing files (PSI off) read as 0."""
    out = {"cpu": 0.0, "io": 0.0, "memory": 0.0}
    for name, kind in (("cpu", "some"), ("io", "full"), ("memory", "some")):
        try:
            for line in (root / name).read_text().splitlines():
                if line.startswith(kind + " "):
                    m = re.search(r"avg10=([\d.]+)", line)
                    if m:
                        out[name] = float(m.group(1))
        except OSError:
            pass
    return out


def pressure_high(now: dict[str, float], cpu_limit: float, io_limit: float, engaged: bool) -> bool:
    """With hysteresis: engages at the limit and lets go below 60 % of it, so a
    reading hovering at the limit doesn't flip the tiers every scan."""
    scale = 0.6 if engaged else 1.0
    return now["cpu"] >= cpu_limit * scale or now["io"] >= io_limit * scale


# --- /proc and the syscalls -----------------------------------------------------

_SYS_IOPRIO = {"x86_64": (251, 252), "aarch64": (30, 31), "riscv64": (30, 31)}
_libc: ctypes.CDLL | None = None


def _syscall_numbers() -> tuple[int, int] | None:
    return _SYS_IOPRIO.get(platform.machine())


def _libc_handle() -> ctypes.CDLL:
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL(None, use_errno=True)
    return _libc


def ioprio_get(tid: int) -> int | None:
    nums = _syscall_numbers()
    if nums is None:
        return None
    r = _libc_handle().syscall(nums[1], 1, tid)  # IOPRIO_WHO_PROCESS
    return None if r < 0 else r


def ioprio_set(tid: int, io_class: int, level: int) -> bool:
    nums = _syscall_numbers()
    if nums is None:
        return False
    return _libc_handle().syscall(nums[0], 1, tid, (io_class << 13) | level) == 0


def read_proc(pid: int, root: Path = Path("/proc"), cmd_cache: dict | None = None) -> ProcInfo | None:
    try:
        raw = (root / str(pid) / "stat").read_text()
        # "pid (comm) S ppid ..." - comm may hold spaces and parentheses
        lp, rp = raw.index("("), raw.rindex(")")
        comm = raw[lp + 1:rp]
        f = raw[rp + 2:].split()
        flags, ppid, nice, start, policy = int(f[6]), int(f[1]), int(f[16]), int(f[19]), int(f[38])
    except (OSError, ValueError, IndexError):
        return None
    key = (pid, start)
    cmd = cmd_cache.get(key) if cmd_cache is not None else None
    if cmd is None:
        try:
            cmd = (root / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        except OSError:
            cmd = ""
        if cmd_cache is not None:
            cmd_cache[key] = cmd
    return ProcInfo(pid, ppid, comm, cmd, start, nice, policy, kernel=bool(flags & PF_KTHREAD))


def scan(root: Path = Path("/proc"), uid: int | None = None, cmd_cache: dict | None = None) -> dict[int, ProcInfo]:
    uid = os.getuid() if uid is None else uid
    out = {}
    try:
        names = os.listdir(root)
    except OSError:
        return out
    for name in names:
        if not name.isdigit():
            continue
        try:
            if (root / name).stat().st_uid != uid:
                continue
        except OSError:
            continue
        p = read_proc(int(name), root, cmd_cache)
        if p is not None:
            out[p.pid] = p
    return out


def draws_on_screen(pid: int, root: Path = Path("/proc")) -> bool:
    """The program has a GPU device open: every program with something on the
    screen does (the browser, the terminal, the IDE, the bar), builds and
    language servers never do."""
    try:
        fds = os.listdir(root / str(pid) / "fd")
    except OSError:
        return False
    for fd in fds:
        try:
            t = os.readlink(root / str(pid) / "fd" / fd)
        except OSError:
            continue
        if t.startswith(("/dev/dri/render", "/dev/dri/card")):
            return True
    return False


def threads(pid: int, root: Path = Path("/proc")) -> list[int]:
    try:
        return [int(t) for t in os.listdir(root / str(pid) / "task")]
    except (OSError, ValueError):
        return []


# --- the processor ceiling (a systemd slice, in the user manager's own tree) ----------

SLICE = "swayctl-background.slice"
CGROUP_ROOT = Path("/sys/fs/cgroup")


def cgroup_of(pid: int, proc_root: Path = Path("/proc")) -> str | None:
    try:
        for line in (proc_root / str(pid) / "cgroup").read_text().splitlines():
            if line.startswith("0::"):
                return line[3:]
    except OSError:
        pass
    return None


def movable(path: str | None, uid: int | None = None) -> bool:
    """Can the daemon move a process out of this cgroup? Only inside the user
    manager's tree (`user@UID.service`, which it owns): not out of the login
    session's scope, and not out of a service - systemd stops a service by its
    cgroup, so a service's process moved away would outlive its restart."""
    uid = os.getuid() if uid is None else uid
    prefix = f"/user.slice/user-{uid}.slice/user@{uid}.service/"
    if not path or not path.startswith(prefix):
        return False
    return not any(part.endswith(".service") for part in path[len(prefix):].split("/"))


def quota_percent(cap: int, ncpu: int) -> int:
    """cap % of all processor time, as systemd's CPUQuota (100 % = one thread)."""
    return max(1, round(cap * ncpu))


def ensure_slice(cap: int, ncpu: int | None = None, slice_name: str | None = None, run=subprocess.run) -> str | None:
    """Start the slice and give it its ceiling and a low weight (runtime only: it
    is gone on logout). Returns its cgroup path, None when it can't be made."""
    ncpu = ncpu or os.cpu_count() or 1
    slice_name = slice_name or SLICE
    run(["systemctl", "--user", "start", slice_name], capture_output=True)
    r = run(["systemctl", "--user", "set-property", "--runtime", slice_name,
             f"CPUQuota={quota_percent(cap, ncpu)}%", "CPUWeight=20"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = run(["systemctl", "--user", "show", "-p", "ControlGroup", "--value", slice_name],
              capture_output=True, text=True).stdout.strip()
    return out or None


def move_to(cgroup: str, pid: int, root: Path = CGROUP_ROOT) -> bool:
    try:
        (root / cgroup.lstrip("/") / "cgroup.procs").write_text(str(pid))
        return True
    except OSError:
        return False


# --- the GPU --------------------------------------------------------------------

GPU_HEAVY_SHARE = 5.0   # % of one engine: below that a client isn't what fills the GPU


def read_gpu_busy(root: Path = Path("/sys/class/drm")) -> int | None:
    """The busiest GPU's utilization (amdgpu), None when the driver doesn't say."""
    best = None
    for f in sorted(root.glob("card*/device/gpu_busy_percent")):
        try:
            v = int(f.read_text().strip())
        except (OSError, ValueError):
            continue
        best = v if best is None else max(best, v)
    return best


def gpu_engaged(history: Iterable[int], limit: int, engaged: bool) -> bool:
    """Mean of the last readings against the limit; lets go below 75 % of it, so
    a reading hovering at the limit doesn't toggle the guard."""
    h = list(history)
    if not h:
        return False
    mean = sum(h) / len(h)
    return mean >= limit * (0.75 if engaged else 1.0)


def gpu_clients(pids: Iterable[int], proc_root: Path = Path("/proc")) -> dict[int, int]:
    """pid -> graphics-engine time used so far, ns (drm fdinfo; each GPU client
    counted once however many fds it has). Only readable for the user's own."""
    out: dict[int, int] = {}
    for pid in pids:
        seen: set[str] = set()
        total = 0
        try:
            fds = os.listdir(proc_root / str(pid) / "fdinfo")
        except OSError:
            continue
        for fd in fds:
            try:
                txt = (proc_root / str(pid) / "fdinfo" / fd).read_text()
            except OSError:
                continue
            if "drm-driver" not in txt:
                continue
            cid = re.search(r"drm-client-id:\s*(\d+)", txt)
            if cid:
                if cid.group(1) in seen:
                    continue
                seen.add(cid.group(1))
            m = re.search(r"drm-engine-gfx:\s*(\d+) ns", txt)
            if m:
                total += int(m.group(1))
        if total:
            out[pid] = total
    return out


def gpu_shares(before: dict[int, int], after: dict[int, int], seconds: float) -> dict[int, float]:
    """% of one graphics engine each client used between two readings."""
    if seconds <= 0:
        return {}
    return {pid: (ns - before[pid]) / (seconds * 1e9) * 100 for pid, ns in after.items() if pid in before}


def on_battery(root: Path = Path("/sys/class/power_supply")) -> bool:
    for f in root.glob("BAT*/status"):
        try:
            return f.read_text().strip() == "Discharging"
        except OSError:
            pass
    return False


@dataclass
class Original:
    nice: int
    policy: int
    ioprio: int | None


@dataclass
class Applied:
    tier: Tier
    start: int
    originals: dict[int, Original] = field(default_factory=dict)  # per thread
    cgroup: str | None = None       # where it was before it went into the capped slice


def _apply_thread(tid: int, tier: Tier) -> Original | None:
    """Put one thread in the tier; returns what it had, or None when it vanished
    or wasn't ours to change."""
    try:
        original = Original(os.getpriority(os.PRIO_PROCESS, tid), os.sched_getscheduler(tid), ioprio_get(tid))
        if original.policy != tier.policy and original.policy in SCHED_NORMAL_POLICIES:
            os.sched_setscheduler(tid, tier.policy, os.sched_param(0))
        os.setpriority(os.PRIO_PROCESS, tid, tier.nice)
    except (ProcessLookupError, PermissionError, OSError):
        return None
    ioprio_set(tid, tier.io_class, tier.io_level)
    return original


def _restore_thread(tid: int, o: Original) -> None:
    try:
        if os.sched_getscheduler(tid) != o.policy and o.policy in SCHED_NORMAL_POLICIES:
            os.sched_setscheduler(tid, o.policy, os.sched_param(0))
        os.setpriority(os.PRIO_PROCESS, tid, o.nice)
    except (ProcessLookupError, PermissionError, OSError):
        return
    if o.ioprio is not None:
        nums = _syscall_numbers()
        if nums is not None:
            _libc_handle().syscall(nums[0], 1, tid, o.ioprio)


class Governor:
    """Scans the user's processes and keeps `plan()` applied. Safe to call
    `tick()` often: a process already in its tier costs no syscalls."""

    def __init__(self, proc_root: Path = Path("/proc"), uid: int | None = None, slice_name: str | None = None,
                 cgroup_root: Path = CGROUP_ROOT):
        self.root = proc_root
        self.uid = uid
        self.slice_name = slice_name or SLICE
        self.cgroup_root = cgroup_root
        self.slice_path: str | None = None
        self.slice_cap: int | None = None      # the ceiling the slice has now
        self.gpu_hist: deque[int] = deque(maxlen=3)
        self.gpu_engaged = False
        self.gpu_busy: int | None = None
        self.gpu_prev: tuple[float, dict[int, int]] | None = None
        self.gpu_heavy: dict[int, float] = {}
        self.applied: dict[int, Applied] = {}
        self.cmd_cache: dict[tuple[int, int], str] = {}
        self.window_cache: dict[tuple[int, int], tuple[bool, float]] = {}  # (pid, start) -> (draws, when checked)
        self.rt: dict[int, tuple[int, int]] = {}   # compositor pid -> (start, policy it had)
        self.helpers: dict[int, Original] = {}     # compositor thread -> what it had before we raised it
        self.compositor: dict[str, Any] = {}       # what the last scan saw, for status
        self._seen: set[str] | None = None   # pids at the last new_pids()
        self.engaged = False       # pressure guard state
        self.pressure: dict[str, float] = {"cpu": 0.0, "io": 0.0, "memory": 0.0}
        self.last_error = ""

    def new_pids(self) -> bool:
        """True when a process has appeared since the last call. Listing /proc
        costs well under a millisecond, so this can run twice a second and let
        a scan happen right after something starts - a program is born with its
        parent's priority, and until the scan it competes with it."""
        try:
            now = {n for n in os.listdir(self.root) if n.isdigit()}
        except OSError:
            return False
        fresh = bool(now - self._seen) if self._seen is not None else False  # the first scan happens anyway
        self._seen = now
        return fresh

    # one pass over the machine
    def tick(self, s: Settings, focus_pid: int | None, cpu_limit: float, io_limit: float) -> dict[int, Tier]:
        procs = scan(self.root, self.uid, self.cmd_cache)
        self._forget_gone(procs)
        if s.pressure_guard:
            self.pressure = read_pressure()
            self.engaged = pressure_high(self.pressure, cpu_limit, io_limit, self.engaged)
        else:
            self.engaged = False
        self._compositor(procs, s)
        self._gpu(procs, s, focus_pid)
        wanted = plan(procs, s, focus_pid, self.engaged, own_pid=os.getpid(), gpu_heavy=self.gpu_heavy,
                      held=self.applied, windows=self.windows(procs) if s.favor_windows else ())
        for pid in [p for p in self.applied if p not in wanted]:
            self._release(pid)
        self._ceiling(s)
        for pid, tier in wanted.items():
            self._put(pid, procs[pid].start, tier)
            self._cap(pid, tier, s)
        return wanted

    def _gpu(self, procs: dict[int, ProcInfo], s: Settings, focus_pid: int | None) -> None:
        """The GPU guard: while the GPU is saturated, find who is filling it. The
        per-process reading (drm fdinfo) is only taken while engaged."""
        if not s.gpu_guard:
            self.gpu_engaged, self.gpu_heavy, self.gpu_prev = False, {}, None
            return
        self.gpu_busy = read_gpu_busy()
        if self.gpu_busy is None:
            return
        self.gpu_hist.append(self.gpu_busy)
        self.gpu_engaged = gpu_engaged(self.gpu_hist, s.gpu_limit, self.gpu_engaged)
        if not self.gpu_engaged:
            self.gpu_heavy, self.gpu_prev = {}, None
            return
        now = time.monotonic()
        clients = gpu_clients(procs, self.root)
        if self.gpu_prev is not None:
            shares = gpu_shares(self.gpu_prev[1], clients, now - self.gpu_prev[0])
            # what you are looking at is yours to spend: only the others are held back
            exempt = {focus_pid, *descendants(procs, focus_pid)} if focus_pid else set()
            self.gpu_heavy = {pid: sh for pid, sh in shares.items() if sh >= GPU_HEAVY_SHARE and pid not in exempt}
        self.gpu_prev = (now, clients)

    def _ceiling(self, s: Settings) -> None:
        """Give the slice the processor ceiling (only when it changed)."""
        if s.cpu_cap >= 100:
            self.slice_path, self.slice_cap = None, None
            return
        if self.slice_cap == s.cpu_cap and self.slice_path:
            return
        self.slice_path = ensure_slice(s.cpu_cap, slice_name=self.slice_name)
        self.slice_cap = s.cpu_cap if self.slice_path else None

    def _cap(self, pid: int, tier: Tier, s: Settings) -> None:
        """Programs that wait (background, batch, held-back GPU clients) go into the
        capped slice together, so what they use in total stays under the ceiling.
        What they start afterwards is born in it. Only where moving is allowed."""
        a = self.applied.get(pid)
        if a is None or a.cgroup is not None or tier.nice <= 0 or not self.slice_path or s.cpu_cap >= 100:
            return
        here = cgroup_of(pid, self.root)
        if here == self.slice_path:
            a.cgroup = self._released_path()
            return  # put there by an earlier run: nothing to restore to but the apps' own cgroup
        if movable(here, self.uid) and move_to(self.slice_path, pid, self.cgroup_root):
            a.cgroup = here

    def _uncap(self, pid: int, a: Applied) -> None:
        """Out of the slice, back where it was. When that cgroup is gone (a scope
        left empty is removed by systemd) it goes to a plain cgroup of its own
        among the apps: still out of the ceiling. (Not into `app.slice` itself:
        a cgroup that has children can't hold processes.)"""
        if not a.cgroup:
            return
        if not move_to(a.cgroup, pid, self.cgroup_root) or a.cgroup == self._released_path():
            leaf = self._released_path()
            try:
                (self.cgroup_root / leaf.lstrip("/")).mkdir(exist_ok=True)
            except OSError:
                pass
            move_to(leaf, pid, self.cgroup_root)
        a.cgroup = None

    def _released_path(self) -> str:
        uid = os.getuid() if self.uid is None else self.uid
        return f"/user.slice/user-{uid}.slice/user@{uid}.service/app.slice/swayctl-center-released"

    def _compositor(self, procs: dict[int, ProcInfo], s: Settings) -> None:
        """Keep the compositor real-time (when asked and permitted)."""
        found = [p for p in procs.values() if p.comm in s.compositor_names and not p.kernel]
        self.compositor = {"names": [p.comm for p in found],
                           "realtime": bool(found) and all(p.policy not in SCHED_NORMAL_POLICIES for p in found)
                                       or any(p.pid in self.rt for p in found)}
        for pid in [p for p in self.rt if p not in procs or procs[p].start != self.rt[p][0]]:
            del self.rt[pid]
        if not s.compositor_realtime:
            return
        self._compositor_threads(found, s)
        todo = realtime_candidates(procs, s.compositor_names)
        if not todo:
            return
        if not can_realtime():
            self.compositor["error"] = "RLIMIT_RTPRIO is 0: add yourself to the audio group (limits.d/20-audio.conf)"
            return
        for pid in todo:
            try:
                policy = os.sched_getscheduler(pid)
                os.sched_setscheduler(pid, os.SCHED_RR, os.sched_param(1))
            except OSError as e:
                self.compositor["error"] = f"cannot make {procs[pid].comm} real-time: {e.strerror}"
                continue
            self.rt[pid] = (procs[pid].start, policy)
            self.compositor["realtime"] = True
            log.info("priority: %s (pid %d) is now real-time", procs[pid].comm, pid)

    def _compositor_threads(self, found: list[ProcInfo], s: Settings) -> None:
        """The compositor's main thread is real-time, but the threads it hands the
        drawing to (the GL driver thread that submits the frames, shader compilers)
        are ordinary ones and wait in line behind everything. They get the interface
        tier. Threads it keeps low on purpose (SCHED_BATCH: disk cache, tracing) stay."""
        ui = tiers(s.background_nice, s.focus_nice, s.ui_nice)["ui"]
        alive: set[int] = set()
        for p in found:
            for tid in threads(p.pid, self.root):
                alive.add(tid)
                if tid in self.helpers:
                    continue
                try:
                    policy = os.sched_getscheduler(tid)
                except OSError:
                    continue
                if policy not in (os.SCHED_OTHER, os.SCHED_RR, os.SCHED_FIFO):
                    continue
                o = _apply_thread(tid, ui)
                if o is not None:
                    self.helpers[tid] = o
        for tid in [t for t in self.helpers if t not in alive]:
            del self.helpers[tid]

    def release_realtime(self) -> int:
        """Back to normal scheduling for what we made real-time."""
        for tid, o in list(self.helpers.items()):
            _restore_thread(tid, o)
        self.helpers.clear()
        n = len(self.rt)
        for pid, (_start, policy) in list(self.rt.items()):
            try:
                os.sched_setscheduler(pid, policy, os.sched_param(0))
            except OSError:
                pass
        self.rt.clear()
        return n

    WINDOW_RECHECK = 60.0   # a program that did not draw yet may open the GPU later

    def windows(self, procs: dict[int, ProcInfo], now: float | None = None) -> list[int]:
        """Programs drawing on the screen. A yes is kept for the life of the process,
        a no is looked at again after a minute, so a scan reads /proc/<pid>/fd only for
        what is new."""
        now = time.monotonic() if now is None else now
        out = []
        for p in procs.values():
            if p.kernel:
                continue
            key = (p.pid, p.start)
            hit = self.window_cache.get(key)
            if hit is None or (not hit[0] and now - hit[1] > self.WINDOW_RECHECK):
                hit = self.window_cache[key] = (draws_on_screen(p.pid, self.root), now)
            if hit[0]:
                out.append(p.pid)
        if len(self.window_cache) > 4 * max(len(procs), 64):
            live = {(p.pid, p.start) for p in procs.values()}
            self.window_cache = {k: v for k, v in self.window_cache.items() if k in live}
        return out

    def _forget_gone(self, procs: dict[int, ProcInfo]) -> None:
        for pid in list(self.applied):
            p = procs.get(pid)
            if p is None or p.start != self.applied[pid].start:
                del self.applied[pid]  # exited (or the pid was reused)
        if len(self.cmd_cache) > 4 * max(len(procs), 64):
            live = {(p.pid, p.start) for p in procs.values()}
            self.cmd_cache = {k: v for k, v in self.cmd_cache.items() if k in live}

    def _put(self, pid: int, start: int, tier: Tier) -> None:
        a = self.applied.get(pid)
        if a is None:
            a = self.applied[pid] = Applied(tier, start)
        same = a.tier == tier
        a.tier = tier
        for tid in threads(pid, self.root):
            if tid in a.originals:
                if not same and _apply_thread(tid, tier) is None:
                    a.originals.pop(tid, None)  # keeps the first original otherwise
                continue
            o = _apply_thread(tid, tier)
            if o is not None:
                a.originals[tid] = o

    def _release(self, pid: int) -> None:
        a = self.applied.pop(pid, None)
        if a is None:
            return
        for tid, o in a.originals.items():
            _restore_thread(tid, o)
        self._uncap(pid, a)

    def restore_all(self) -> int:
        n = len(self.applied)
        for pid in list(self.applied):
            self._release(pid)
        if self.slice_path:
            subprocess.run(["systemctl", "--user", "stop", self.slice_name], capture_output=True)
            self.slice_path, self.slice_cap = None, None
        return n

    def status(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for a in self.applied.values():
            counts[_tier_name(a.tier)] = counts.get(_tier_name(a.tier), 0) + 1
        return {"managed": len(self.applied), "tiers": counts, "pressure": self.pressure,
                "guard_engaged": self.engaged, "compositor": self.compositor,
                "capped": sum(1 for a in self.applied.values() if a.cgroup), "cpu_cap": self.slice_cap,
                "gpu": {"busy": self.gpu_busy, "engaged": self.gpu_engaged, "held_back": len(self.gpu_heavy)}}


def _tier_name(t: Tier) -> str:
    if t.policy == os.SCHED_BATCH:
        return "batch"
    if t.nice < -6:
        return "ui"
    return "interactive" if t.nice < 0 else "background"


def focused_pid(tree: dict[str, Any]) -> int | None:
    """The pid of the focused window in a sway tree (None when nothing is)."""
    stack = [tree]
    while stack:
        n = stack.pop()
        if n.get("focused") and n.get("pid"):
            return int(n["pid"])
        stack.extend(n.get("nodes") or ())
        stack.extend(n.get("floating_nodes") or ())
    return None
