#!/bin/sh
# Demo KÍNH KHÓI TỐI đồng bộ cả 3: bar + Quick Settings + app Cài đặt cùng
# một look (nền tối → panes smoked, chữ sáng, milk mỏng ×0.20, adaptive bật
# cả trong app) — xem trước trước khi áp thật. Chạy:
#   tools/sandbox.sh --fx /home/repo/tools/dark_glass_demo.sh
# Ảnh: tools/out/dgd-full.png (màn hình đủ), dgd-app.png (crop app + QS)
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
mkdir -p bar
OUT=/tmp/out
export PYTHONPATH=/home/repo

# --- wallpaper tối mềm: nền khói + quầng màu (thấy rõ "trong" kính khói) -----
python3 - <<'PY'
import sys, math, cairo
sys.path.insert(0, "/home/repo")
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080); c = cairo.Context(s)
c.set_source_rgb(0.04, 0.04, 0.06); c.rectangle(0, 0, 1920, 1080); c.fill()
# quầng sáng mềm (teal/tím/cam) — nội dung sáng vừa xuyên qua kính khói
for cx, cy, r, col, a in ((420, 320, 480, (0.10, 0.55, 0.55), 0.50),
                          (1450, 720, 540, (0.45, 0.22, 0.65), 0.45),
                          (1050, 160, 420, (0.85, 0.45, 0.14), 0.38),
                          (1750, 260, 380, (0.12, 0.35, 0.60), 0.42)):
    g = cairo.RadialGradient(cx, cy, 0, cx, cy, r)
    g.add_color_stop_rgba(0, *col, a)
    g.add_color_stop_rgba(1, *col, 0)
    c.set_source(g); c.arc(cx, cy, r, 0, 2 * math.pi); c.fill()
# dải màu dưới đáy + hạt sáng nhỏ: chi tiết sáng để thấy độ trong của kính
BANDS = [(0.85, 0.16, 0.12), (0.90, 0.45, 0.10), (0.95, 0.78, 0.12),
         (0.15, 0.68, 0.32), (0.09, 0.63, 0.52), (0.16, 0.48, 0.75),
         (0.56, 0.27, 0.68), (0.91, 0.12, 0.39)]
for i, col in enumerate(BANDS):
    c.set_source_rgb(*col)
    c.rectangle(i * 240, 980, 240, 100); c.fill()
c.set_source_rgba(1, 1, 1, 0.9)
for i in range(40):
    x = (i * 173) % 1860 + 30
    y = (i * 331) % 940 + 40
    c.arc(x, y, 3 + (i % 3), 0, 2 * math.pi); c.fill()
s.write_to_png("/tmp/out/wall-darksmoke.png")
print("wallpaper ready")
PY

# --- state: glass on, dark mode, tint ---------------------------------------
python3 -c "from swayctl_center.pages import ui_state; ui_state.set('setup_done', True)"
python3 -m swayctl_center daemon > "$OUT/dgd-daemon.log" 2>&1 &
sleep 2.5
TINT=${TINT:-10}
python3 -m swayctl_center set effects.glass true
python3 -m swayctl_center set appearance.mode dark
python3 -m swayctl_center set effects.glass_opacity "$TINT"
python3 -m swayctl_center set background.image /tmp/out/wall-darksmoke.png
swaymsg 'output * bg /tmp/out/wall-darksmoke.png fill' >/dev/null
sleep 1

# --- bar: config đúng đường sản phẩm (BarModule.files) ----------------------
python3 - <<'PY'
import os, sys, pathlib
sys.path.insert(0, "/home/repo")
from swayctl_center import themes, schema
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = True
v["effects"]["glass_opacity"] = int(os.environ.get("TINT", 10))
v["background"]["image"] = "/tmp/out/wall-darksmoke.png"
v["appearance"]["mode"] = "dark"
t = themes.BUILTIN[os.environ.get("THEME", "dark")]
ctx = Context(pathlib.Path("/tmp"), values=v, theme=t,
              live={"sway_original_version": "x", "swayctl_features": ["glass", "glass-shaped", "glass-blur", "glass-text"]})
files = BarModule().files(v["bar"] | {"program": "swayctl-bar"}, ctx)
pathlib.Path("/tmp/bar/config.json").write_text(files["config.json"])
pathlib.Path("/tmp/bar/style.css").write_text(files["style.css"])
print("bar config ready")
PY
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir /tmp/bar 2>"$OUT/dgd-bar.log" &
sleep 2.5

# --- app Cài đặt (Appearance) -----------------------------------------------
python3 -m swayctl_center ui --page appearance > "$OUT/dgd-ui.log" 2>&1 &
ui=$!
sleep 4
swaymsg 'floating enable, resize set 1300 860, move position center' >/dev/null 2>&1 || true
sleep 1.5

# --- Quick Settings mở đè lên app + bar --------------------------------------
$bin quick
sleep 1.4
grim "$OUT/dgd-full.png"
$bin quick; sleep 0.5

kill $ui 2>/dev/null || true
sleep 0.6

# --- crop vùng app + QS + ghép nhãn -------------------------------------------
python3 - <<'PY'
import cairo, shutil
OUT = "/tmp/out"
full = cairo.ImageSurface.create_from_png(f"{OUT}/dgd-full.png")
W, H = full.get_width(), full.get_height()
cw, ch, band = 1460, 940, 52
canvas = cairo.ImageSurface(cairo.FORMAT_RGB24, cw, ch + band)
c = cairo.Context(canvas)
c.set_source_rgb(0.10, 0.10, 0.12); c.paint()
c.save()
c.translate(0, band)
c.rectangle(0, 0, cw, ch); c.clip()
# neo: app căn giữa, QS góc trên-phải
c.translate(max(0, (W - cw) // 2), 0)
c.set_source_surface(full, 0, 0); c.paint()
c.restore()
c.set_source_rgb(1, 1, 1); c.select_font_face("Sans", 0, 1); c.set_font_size(18)
c.move_to(8, 34)
c.show_text("dark smoked glass: app + Quick Settings + bar (tint %s%%)" % __import__("os").environ.get("TINT", "10"))
canvas.write_to_png(f"{OUT}/dgd-app.png")
shutil.copy("/tmp/bar/style.css", f"{OUT}/dgd-style.css")
print("anh: dgd-full.png, dgd-app.png")
PY

# --- cổng WCAG: chữ SÁNG trên kính khói (4.5:1) / icon (3.0:1) ---------------
python3 - <<'PY'
import sys, cairo
img = cairo.ImageSurface.create_from_png("/tmp/out/dgd-full.png")

def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def contrast(x0, y0, w, h):
    st, buf = img.get_stride(), bytes(img.get_data())
    vals = []
    for y in range(y0, y0 + h):
        base = y * st
        for x in range(x0, x0 + w):
            i = base + x * 4
            vals.append(0.2126 * _lin(buf[i+2]) + 0.7152 * _lin(buf[i+1])
                        + 0.0722 * _lin(buf[i]))
    vals.sort()
    n = len(vals)
    bg = vals[n // 2]
    p01, p99 = vals[min(n - 1, int(n * 0.01))], vals[max(0, int(n * 0.99))]
    text = p99 if (p99 - bg) >= (bg - p01) else p01
    hi, lo = max(text, bg), min(text, bg)
    return (hi + 0.05) / (lo + 0.05)

RECTS = [
    ("QS DND title",  1595,  68, 165, 26, 4.5),
    ("QS DND Off",    1595,  93,  40, 16, 4.5),
    ("QS slider icon", 1573, 144,  30, 25, 3.0),
    ("btn gear",      1779, 205,  21, 21, 3.0),
    ("btn lock",      1821, 205,  21, 21, 3.0),
    ("btn power",     1863, 205,  21, 21, 3.0),
    ("clock",          930,  10,  60, 34, 4.5),
    ("right module",  1836,  12,  61, 30, 3.0),
    ("app hdr title", 1060, 152, 140, 26, 4.5),
    ("app row Sound",  370, 466,  64, 27, 4.5),
    ("app row Power",  370, 610, 100, 27, 4.5),
    ("app card label", 617, 666, 105, 24, 4.5),
]
fails = []
for name, x, y, w, h, need in RECTS:
    v = contrast(x, y, w, h)
    mark = "ok " if v >= need else "FAIL"
    print(f"  {name:15s} contrast={v:5.2f}:1 (>= {need}) {mark}")
    if v < need:
        fails.append((name, round(v, 2)))
if fails:
    print("KHONG DAT nguong WCAG:", fails)
    sys.exit(1)
print("PASS: chu sang tren kinh khoi dat WCAG ca 3 lop (bar, quick, app)")
PY
