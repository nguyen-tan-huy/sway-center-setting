#!/bin/sh
# B3 backdrop IPC probe: put a two-tone (red/blue) wallpaper on the headless
# output, ask the compositor (IPC get_backdrop) for RGB grids and check the
# colors AND orientation come back right. Run only inside the sandbox:
#
#   tools/sandbox.sh --fx /home/repo/tools/backdrop_probe.sh
#
# Writes /tmp/out/backdrop_probe.log (+ backdrop.json); exits non-zero on
# any mismatch.
set -eu
: "${SWAYSOCK:?run inside: tools/sandbox.sh --fx /home/repo/tools/backdrop_probe.sh}"
LOG=/tmp/out/backdrop_probe.log
WALL=/tmp/out/backdrop-wall.png
JSON=/tmp/out/backdrop.json
SMSG=/home/fx/swayfx/build/swaymsg/swaymsg
fail() { echo "FAIL: $*" >>"$LOG"; exit 1; }
: >"$LOG"
command -v "$SMSG" >/dev/null || fail "fork swaymsg missing at $SMSG"

# two-tone wallpaper (top red / bottom blue) so orientation errors show up;
# drawn at output size to avoid scaler artifacts at the edges
/usr/bin/python3 - "$WALL" >>"$LOG" 2>&1 <<'EOF'
import sys
import cairo
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080)
ctx = cairo.Context(s)
ctx.set_source_rgb(200 / 255, 60 / 255, 60 / 255)
ctx.rectangle(0, 0, 1920, 540); ctx.fill()
ctx.set_source_rgb(60 / 255, 60 / 255, 200 / 255)
ctx.rectangle(0, 540, 1920, 540); ctx.fill()
s.write_to_png(sys.argv[1])
print("wallpaper written")
EOF
/usr/bin/swaymsg output HEADLESS-1 bg "$WALL" fill >>"$LOG" 2>&1 \
	|| fail "could not set wallpaper"
sleep 0.5

# the compositor may need a frame or two after the wallpaper change
ok=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
	if "$SMSG" -r -t get_backdrop '{"output":"HEADLESS-1","cols":4,"rows":4}' \
		>"$JSON" 2>>"$LOG"; then
		if /usr/bin/python3 -c 'import json,sys; d=json.load(open(sys.argv[1]));
sys.exit(0 if d.get("success") else 1)' "$JSON"; then ok=1; break; fi
	fi
	sleep 0.3
done
[ "$ok" = 1 ] || fail "get_backdrop never succeeded: $(cat "$JSON" 2>/dev/null || echo no-reply)"

# 1) 4x4 grid: top rows red, bottom rows blue (catches a vertical flip)
/usr/bin/python3 - "$JSON" >>"$LOG" 2>&1 <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("success"), d.get("error")
assert d.get("cols") == 4 and d.get("rows") == 4, d
cells = d["cells"]
assert len(cells) == 4 * 4 * 3, len(cells)
bad = []
for i in range(0, len(cells), 3):
    row = (i // 3) // 4
    r, g, b = cells[i:i + 3]
    top = row < 2
    ok = (r > 150 and b < 100) if top else (b > 150 and r < 100)
    if not ok:
        bad.append((i // 3, (r, g, b), "red" if top else "blue"))
assert not bad, f"{len(bad)} cells off, first: {bad[:4]}"
print(f"grid ok: {len(cells) // 3} cells match top-red/bottom-blue (orientation)")
EOF

# 2) defaults: cols=96 rows=54, full output rect
"$SMSG" -r -t get_backdrop '{"output":"HEADLESS-1"}' >"$JSON" 2>>"$LOG" \
	|| fail "default get_backdrop failed"
/usr/bin/python3 - "$JSON" >>"$LOG" 2>&1 <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("success"), d.get("error")
assert d.get("cols") == 96 and d.get("rows") == 54, d
assert len(d["cells"]) == 96 * 54 * 3, len(d["cells"])
assert abs(d["w"] - 1920) < 2 and abs(d["h"] - 1080) < 2, d
c = d["cells"]
def cell(gx, gy): return tuple(c[(gy * 96 + gx) * 3:(gy * 96 + gx) * 3 + 3])
first, last, mid = cell(0, 0), cell(95, 53), cell(48, 30)
assert first[0] > 150 and first[2] < 100, first      # top-left red
assert last[2] > 150 and last[0] < 100, last         # bottom-right blue
assert mid[2] > 150 and mid[0] < 100, mid            # middle of blue half
print("defaults ok: 96x54, top red / bottom blue (orientation correct)")
EOF

# 3) a small rect in the TOP (red) half: 1x1 cell must be red
"$SMSG" -r -t get_backdrop \
	'{"output":"HEADLESS-1","x":100,"y":100,"w":50,"h":50,"cols":1,"rows":1}' \
	>"$JSON" 2>>"$LOG" || fail "rect get_backdrop failed"
/usr/bin/python3 - "$JSON" >>"$LOG" 2>&1 <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("success"), d.get("error")
assert d.get("cols") == 1 and d.get("rows") == 1, d
got = tuple(d["cells"])
assert got[0] > 150 and got[2] < 100, got  # red (top half)
print(f"rect ok: 1x1 cell {got}")
EOF

# 4) error paths: unknown output and a missing payload (swaymsg exits
# non-zero on success:false replies, so judge by the JSON only)
"$SMSG" -r -t get_backdrop '{"output":"NOPE-9"}' >"$JSON" 2>>"$LOG" || true
/usr/bin/python3 - "$JSON" >>"$LOG" 2>&1 <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("success") is False and d.get("error"), d
print("unknown output rejected:", d["error"])
EOF
"$SMSG" -r -t get_backdrop >"$JSON" 2>>"$LOG" || true
/usr/bin/python3 - "$JSON" >>"$LOG" 2>&1 <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert d.get("success") is False and d.get("error"), d
print("missing payload rejected:", d["error"])
EOF

# 5) the per-cell envelope: a white/black split INSIDE one cell keeps the
#    true floor and peak (what text contrast needs) instead of the average
/usr/bin/python3 - "$WALL" >>"$LOG" 2>&1 <<'EOF'
import sys, cairo
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080)
ctx = cairo.Context(s)
ctx.set_source_rgb(1, 1, 1); ctx.rectangle(0, 0, 965, 1080); ctx.fill()
ctx.set_source_rgb(0, 0, 0); ctx.rectangle(965, 0, 955, 1080); ctx.fill()
s.write_to_png(sys.argv[1])
print("envelope wallpaper written")
EOF
/usr/bin/swaymsg output HEADLESS-1 bg "$WALL" fill >>"$LOG" 2>&1 \
	|| fail "could not set envelope wallpaper"
sleep 0.5
ok=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
	if "$SMSG" -r -t get_backdrop '{"output":"HEADLESS-1","cols":96,"rows":54}' \
		>"$JSON" 2>>"$LOG"; then
		if /usr/bin/python3 -c 'import json,sys; d=json.load(open(sys.argv[1]));
sys.exit(0 if d.get("success") else 1)' "$JSON"; then ok=1; break; fi
	fi
	sleep 0.3
done
[ "$ok" = 1 ] || fail "get_backdrop never succeeded (envelope): $(cat "$JSON" 2>/dev/null || echo no-reply)"
/usr/bin/python3 - "$JSON" >>"$LOG" 2>&1 <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
n = 96 * 54
lmin, lmax = d["lmin"], d["lmax"]
assert len(lmin) == n and len(lmax) == n, (len(lmin), len(lmax))
assert all(a <= b for a, b in zip(lmin, lmax)), "lmin > lmax somewhere"
k = 27 * 96 + 48  # the cell straddling x=965 (5 white + 15 black px)
assert lmin[k] <= 5, lmin[k]
assert lmax[k] >= 250, lmax[k]
avg = d["cells"][k * 3:k * 3 + 3]
assert 40 <= avg[0] <= 90 and avg[1] == avg[0] and avg[2] == avg[0], avg
print(f"envelope ok: mixed cell avg={avg[0]} lmin={lmin[k]} lmax={lmax[k]}")
EOF

echo "PASS" >>"$LOG"
cat "$LOG"
