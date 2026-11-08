#!/usr/bin/env python3
"""Sample a workspace switch: the red window's right edge and the blue window's left edge
(a sliding switch moves both; a fade leaves them where they are). 0 = colour not on the row."""
import subprocess, sys, time

def edges(ppm: bytes, y: int = 540):
    parts = ppm.split(b"\n", 3)
    w, _h = map(int, parts[1].split())
    row = parts[3][y * w * 3:(y + 1) * w * 3]
    red_right, blue_left = -1, -1
    for x in range(w):
        r, g, b = row[3 * x], row[3 * x + 1], row[3 * x + 2]
        if r > 200 and g < 70 and b < 70:
            red_right = x
        if b > 200 and r < 70 and g < 70 and blue_left < 0:
            blue_left = x
    return red_right, blue_left

def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 1.2
    t0 = time.monotonic()
    pts = []
    while time.monotonic() - t0 < dur:
        t = time.monotonic()
        pts.append(((t - t0) * 1000, *edges(subprocess.run(["grim", "-t", "ppm", "-"], capture_output=True).stdout)))
    for t, r, b in pts:
        print(f"{t:7.0f} red_right={r:5d} blue_left={b:5d}")
    rr = [r for _, r, _ in pts if r >= 0]
    bl = [b for _, _, b in pts if b >= 0]
    print(f"red_right: first={rr[0] if rr else None} min={min(rr) if rr else None} | "
          f"blue_left: first={bl[0] if bl else None} last={bl[-1] if bl else None} min={min(bl) if bl else None}")

main()
