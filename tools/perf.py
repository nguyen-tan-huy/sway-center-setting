"""Idle cost of a shell program: RSS (PSS when readable) and CPU over a window.

    tools/sandbox.sh --sway python3 tools/perf.py [--seconds 10] [--max-rss-mb 40] -- CMD ARGS...

Starts CMD, waits for it to settle, then samples. Exits 1 when over budget, so
it can gate a change. Budget from the roadmap: swayctl-bar < 40 MB, ~0% CPU.
"""
import argparse
import os
import subprocess
import sys
import time

if not os.environ.get("SWAYSOCK", "").startswith("/run/sandbox/"):
    sys.exit("refusing to run outside tools/sandbox.sh --sway")


def tree(pid: int) -> list[int]:
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        out.append(p)
        try:
            with open(f"/proc/{p}/task/{p}/children") as f:
                todo += [int(c) for c in f.read().split()]
        except OSError:
            pass
    return out


def mem_kb(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/smaps_rollup") as f:
            for line in f:
                if line.startswith("Pss:"):
                    return int(line.split()[1])
    except OSError:
        pass
    with open(f"/proc/{pid}/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0


def cpu_ticks(pid: int) -> int:
    with open(f"/proc/{pid}/stat") as f:
        fields = f.read().rsplit(")", 1)[1].split()
    return int(fields[11]) + int(fields[12])  # utime + stime


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10)
    ap.add_argument("--settle", type=float, default=3)
    ap.add_argument("--max-rss-mb", type=float, default=40)
    ap.add_argument("--max-cpu", type=float, default=1.0, help="percent of one core")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(a.settle)
    if proc.poll() is not None:
        print(f"{cmd[0]} exited with {proc.returncode}")
        return 1
    hz = os.sysconf("SC_CLK_TCK")
    pids = tree(proc.pid)
    start = sum(cpu_ticks(p) for p in pids)
    time.sleep(a.seconds)
    pids = tree(proc.pid)
    cpu = (sum(cpu_ticks(p) for p in pids) - start) / hz / a.seconds * 100
    mb = sum(mem_kb(p) for p in pids) / 1024
    proc.terminate()
    proc.wait(5)
    ok = mb <= a.max_rss_mb and cpu <= a.max_cpu
    print(f"{os.path.basename(cmd[0])}: memory {mb:.1f} MB, idle CPU {cpu:.2f}% "
          f"(budget {a.max_rss_mb:g} MB / {a.max_cpu:g}%) {'OK' if ok else 'OVER BUDGET'}"
          f"  [started in {a.settle:g}s window, total {time.monotonic() - t0:.0f}s]")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
