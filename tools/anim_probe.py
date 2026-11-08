#!/usr/bin/env python3
"""Sample the right edge of the red window while another one opens next to it.

Prints "t_ms edge" for each grim frame, then a summary: where the edge ends,
the lowest it got (a spring with bounce undershoots the half-width target) and
how many frames the motion took. Run inside the sandbox (WAYLAND_DISPLAY set).
"""
import subprocess, sys, time

def red_edge(ppm: bytes, y: int = 540) -> int:
    # P6\nW H\n255\n then raw RGB
    parts = ppm.split(b"\n", 3)
    w, h = map(int, parts[1].split())
    data = parts[3]
    row = data[y * w * 3:(y + 1) * w * 3]
    edge = 0
    for x in range(w):
        r, g, b = row[3 * x], row[3 * x + 1], row[3 * x + 2]
        if r > 200 and g < 70 and b < 70:
            edge = x
    return edge

def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    t0 = time.monotonic()
    pts = []
    while time.monotonic() - t0 < dur:
        t = time.monotonic()
        out = subprocess.run(["grim", "-t", "ppm", "-"], capture_output=True).stdout
        pts.append(((t - t0) * 1000, red_edge(out)))
    for t, e in pts:
        print(f"{t:7.0f} {e}")
    edges = [e for _, e in pts]
    final = edges[-1]
    print(f"frames={len(pts)} start={edges[0]} final={final} min={min(edges)} undershoot={final - min(edges)}")

main()
