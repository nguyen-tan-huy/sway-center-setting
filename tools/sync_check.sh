#!/bin/sh
# Chứng minh: setting trong center → file của bar/Quick Settings/notification
# được daemon sinh lại, và bar đang chạy tự nạp (không restart). Chạy:
#   tools/sandbox.sh --fx /home/repo/tools/sync_check.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh" >&2; exit 1 ;; esac
export PYTHONPATH=/home/repo
OUT=/tmp/out
GEN="$XDG_CONFIG_HOME/swayctl-center/generated/bar"

python3 -c "from swayctl_center.pages import ui_state; ui_state.set('setup_done', True)"
python3 -m swayctl_center daemon > "$OUT/sync-daemon.log" 2>&1 &
sleep 2.5
# --- state 1: kính bật, độ đục 10%, notification timeout 4 -------------------
python3 -m swayctl_center set effects.glass true
python3 -m swayctl_center set appearance.mode dark
python3 -m swayctl_center set effects.glass_opacity 10
python3 -m swayctl_center set notifications.timeout 4
swaymsg 'output * bg #0d0d14 solid_color' >/dev/null
sleep 1.5
ls -la "$GEN" > "$OUT/sync-gen-list.txt" 2>&1 || { echo "khong co $GEN" >&2; exit 1; }
cp "$GEN/style.css" /tmp/style-tint10.css
cp "$GEN/config.json" /tmp/config-timeout4.json

bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir "$GEN" > "$OUT/sync-bar1.log" 2>&1 &
pid1=$!
sleep 2.5
grim "$OUT/sync-a.png"

# --- đổi center setting (không đụng bar) -------------------------------------
python3 -m swayctl_center set effects.glass_opacity 70
python3 -m swayctl_center set notifications.timeout 9
sleep 2   # daemon ghi file + bar inotify nạp

alive=no
kill -0 "$pid1" 2>/dev/null && alive=yes
diff /tmp/style-tint10.css "$GEN/style.css" > "$OUT/sync-style.diff" || true
diff /tmp/config-timeout4.json "$GEN/config.json" > "$OUT/sync-config.diff" || true
grim "$OUT/sync-b.png"

# --- bước 3: đổi theme dark→light (đổi lớn, thuần GTK) ------------------------
python3 -m swayctl_center set appearance.mode light
sleep 2.5
grim "$OUT/sync-c.png"
kill "$pid1" 2>/dev/null || true

BAR_ALIVE="$alive" python3 - <<'PY'
import cairo, os, sys
OUT = "/tmp/out"

def load(path):
    s = cairo.ImageSurface.create_from_png(path)
    return s.get_stride(), bytes(s.get_data())

def region(path, x0, y0, w, h):
    st, buf = load(path)
    out = []
    for y in range(y0, y0 + h):
        base = y * st
        for x in range(x0, x0 + w):
            i = base + x * 4
            out.append(0.2126 * buf[i+2] + 0.7152 * buf[i+1] + 0.0722 * buf[i])
    return out

# toàn thanh bar (0..46): reload => milk/adaptive đổi hết; không reload => 0
a = region(f"{OUT}/sync-a.png", 0, 0, 1920, 46)
b = region(f"{OUT}/sync-b.png", 0, 0, 1920, 46)
c = region(f"{OUT}/sync-c.png", 0, 0, 1920, 46)
delta = sum(abs(x - y) for x, y in zip(a, b)) / len(a)
delta_lc = sum(abs(x - y) for x, y in zip(b, c)) / len(b)
style = open(f"{OUT}/sync-style.diff").read().strip()
conf = open(f"{OUT}/sync-config.diff").read().strip()
timeout9 = '"timeout": 9' in conf
tint70 = "0.140" in style and "1.000" in style   # milk 0.040->0.140 + adaptive .on-dark top 1.000
print(f"bar strip: mean|delta| tint10->70 = {delta:.2f}, dark->light = {delta_lc:.2f}")
print("style.css sau doi:", "CO DOI (tint 10->70)" if style else "KHONG DOI",
      "| chua gia tri milk tint70:", tint70)
print("config.json sau doi:", "CO DOI (timeout ->9)" if conf else "KHONG DOI")
print("bar van chay (khong restart):", os.environ["BAR_ALIVE"])
ok = delta_lc > 3 and bool(style) and timeout9 and os.environ["BAR_ALIVE"] == "yes"
if ok:
    print("PASS: center setting cap nhat live vao bar/quick/notification")
else:
    print("FAIL:", dict(delta=delta, delta_lc=delta_lc, style=bool(style), timeout9=timeout9,
                        bar_alive=os.environ["BAR_ALIVE"]))
    sys.exit(1)
PY
echo "--- style.css diff ---"; cat "$OUT/sync-style.diff"
echo "--- config.json diff ---"; cat "$OUT/sync-config.diff"
