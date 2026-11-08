#!/usr/bin/env python3
"""How much of the Quick Settings area differs from a picture taken before it opened, over time.
Usage: anim_probe_quick.py BASELINE.ppm SECONDS   (both taken with grim -g "960,40 960x480" -t ppm)"""
import subprocess, sys, time

def pixels(ppm: bytes):
    parts = ppm.split(b"\n", 3)
    w, h = map(int, parts[1].split())
    return w, h, parts[3]

def diff(a: bytes, b: bytes, w: int) -> int:
    n = 0
    for y in range(0, len(a) // (w * 3), 4):          # every 4th row is plenty
        ra, rb = a[y * w * 3:(y + 1) * w * 3], b[y * w * 3:(y + 1) * w * 3]
        if ra != rb:
            n += sum(1 for x in range(0, w * 3, 6) if ra[x:x + 3] != rb[x:x + 3])
    return n

def main():
    base = open(sys.argv[1], "rb").read()
    w, _h, base_px = pixels(base)
    t0 = time.monotonic()
    pts = []
    while time.monotonic() - t0 < float(sys.argv[2]):
        t = time.monotonic()
        out = subprocess.run(["grim", "-g", "960,40 960x480", "-t", "ppm", "-"], capture_output=True).stdout
        pts.append(((t - t0) * 1000, diff(base_px, pixels(out)[2], w)))
    for t, d in pts:
        print(f"{t:7.0f} {d}")
    ds = [d for _, d in pts]
    big = max(ds)
    first_big = next((i for i, d in enumerate(ds) if d >= big * 0.9), len(ds))
    partial = sum(1 for d in ds[:first_big] if d > big * 0.08)
    print(f"max={big} frames={len(ds)} partial_frames_before_full={partial}")

main()
