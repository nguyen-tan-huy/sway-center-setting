#!/bin/sh
# Demo: panel liquid glass ĐỔI CHỮ theo nền — cùng một Quick Settings chụp
# 3 lần (nền tối / nền sáng / nền NHIỀU MÀU dải ngang) rồi ghép cạnh để
# kiểm tra trước khi áp dụng hệ thống. Chạy:
#   tools/sandbox.sh --fx /home/repo/tools/glass_text_demo.sh
# Ảnh: tools/out/gtd-{quick-darkbg,quick-lightbg,quick-colorbg,side}.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
mkdir -p bar
OUT=/tmp/out

# --- cấu hình bar (cùng adaptive_shot) + 2 wallpaper -------------------------
python3 - <<'PY'
import os, sys, json, pathlib, cairo
sys.path.insert(0, "/home/repo")

def wallpaper(right_dark: bool):
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080); c = cairo.Context(s)
    left, right = ((0.97, 0.97, 0.97), (0.05, 0.05, 0.08)) if right_dark \
        else ((0.05, 0.05, 0.08), (0.97, 0.97, 0.97))
    c.set_source_rgb(*left);  c.rectangle(0, 0, 1100, 1080); c.fill()
    c.set_source_rgb(*right); c.rectangle(1100, 0, 820, 1080); c.fill()
    # dòng chữ đối lập hai bên, thấy rõ kính lấy mẫu gì sau lưng
    c.select_font_face("Sans", 0, 1); c.set_font_size(36)
    for row in range(26):
        dark_side = right_dark
        if row % 2:
            col = (0.9, 0.9, 0.9) if dark_side else (0.1, 0.1, 0.1)
        else:
            col = (0.1, 0.1, 0.1) if dark_side else (0.9, 0.9, 0.9)
        c.set_source_rgb(*col)
        c.move_to(1300 if right_dark else 160, 140 + row * 36)
        c.show_text("light and dark text behind")
    return s

wallpaper(True).write_to_png("/tmp/wall-dark.png")
wallpaper(False).write_to_png("/tmp/wall-light.png")

# nền NHIỀU MÀU: dải ngang 40px xoay 9 màu (đỏ/cam/vàng/lục/lam/tím/hồng/
# xám) + chữ trắng/đen nền — mỗi dải là một bài test "đọc rõ trên mọi màu"
BANDS = [(0.06, 0.06, 0.08), (0.85, 0.16, 0.12), (0.90, 0.45, 0.10),
         (0.95, 0.78, 0.12), (0.15, 0.68, 0.32), (0.09, 0.63, 0.52),
         (0.16, 0.48, 0.75), (0.56, 0.27, 0.68), (0.91, 0.12, 0.39),
         (0.45, 0.50, 0.55)]
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080); c = cairo.Context(s)
for i in range(1080 // 40 + 1):
    c.set_source_rgb(*BANDS[i % len(BANDS)])
    c.rectangle(0, i * 40, 1920, 40); c.fill()
c.select_font_face("Sans", 0, 1); c.set_font_size(36)
for row in range(30):
    c.set_source_rgb(*((1, 1, 1) if row % 2 else (0.03, 0.03, 0.03)))
    c.move_to(1300, 130 + row * 36)
    c.show_text("light and dark text behind")
s.write_to_png("/tmp/wall-colors.png")

from swayctl_center import themes, schema
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
from swayctl_center.modules.effects import EffectsModule
v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = True
v["effects"]["glass_opacity"] = int(os.environ.get("TINT", 10))
v["background"]["image"] = "wall-dark.png"
v["bar"]["modules_center"] = ["clock"]
t = themes.BUILTIN[os.environ.get("THEME", "dark")]
ctx = Context(pathlib.Path("/tmp"), values=v, theme=t,
              live={"sway_original_version": "x", "swayctl_features": ["glass", "glass-shaped", "glass-blur", "glass-text"]})
# sinh config + style.css đúng đường đi của sản phẩm (BarModule.files:
# adaptive=True trong backdrop_config + rule .on-dark/.tint-N nối vào style.css)
files = BarModule().files(v["bar"] | {"program": "swayctl-bar"}, ctx)
pathlib.Path("/tmp/bar/config.json").write_text(files["config.json"])
pathlib.Path("/tmp/bar/style.css").write_text(files["style.css"])
open("/tmp/fx.cmds", "w").write("\n".join(EffectsModule().commands("effects", v["effects"], None, ctx)))
print("wallpapers + bar config ready")
PY
swaymsg 'output * bg /tmp/wall-dark.png fill' >/dev/null
while IFS= read -r c; do swaymsg -- "$c" >/dev/null 2>&1 || echo "fx failed: $c" >&2; done < /tmp/fx.cmds
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir /tmp/bar 2>/tmp/out/gtd-bar.log &
sleep 2.5

# --- state A: panel trên NỀN TỐI (phải) --------------------------------------
$bin quick; sleep 1.2
grim "$OUT/gtd-quick-darkbg.png"
$bin quick; sleep 0.6   # đóng

# --- state B: đổi nền (phải sáng), mở lại => capture lại qua IPC -------------
swaymsg 'output * bg /tmp/wall-light.png fill' >/dev/null
sleep 2.6   # bar retag module theo timer 2s
$bin quick; sleep 1.2
grim "$OUT/gtd-quick-lightbg.png"
$bin quick; sleep 0.4

# --- state C: nền NHIỀU MÀU (dải ngang) => chữ vẫn rõ trên từng dải ---------
swaymsg 'output * bg /tmp/wall-colors.png fill' >/dev/null
sleep 2.6   # bar retag module theo timer 2s
$bin quick; sleep 1.2
grim "$OUT/gtd-quick-colorbg.png"
$bin quick; sleep 0.4

# --- ghép 3 ảnh + số liệu tương phản (cổng 4.5:1) ---------------------------
python3 - <<'PY'
import sys, cairo
OUT = "/tmp/out"
cw, ch, gap, band = 560, 640, 20, 52   # crop quanh panel (góc trên-phải + bar)

def load(name):
    return cairo.ImageSurface.create_from_png(f"{OUT}/{name}")

a, b, col = (load("gtd-quick-darkbg.png"), load("gtd-quick-lightbg.png"),
             load("gtd-quick-colorbg.png"))
canvas = cairo.ImageSurface(cairo.FORMAT_RGB24, cw * 3 + gap * 2, ch + band)
c = cairo.Context(canvas)
c.set_source_rgb(0.10, 0.10, 0.12); c.paint()
c.set_source_rgb(1, 1, 1); c.select_font_face("Sans", 0, 1); c.set_font_size(18)

def crop(img, dx, label):
    c.save()
    c.translate(dx, band)
    c.rectangle(0, 0, cw, ch); c.clip()
    c.translate(cw - img.get_width(), 0)  # neo crop vào góc trên-phải
    c.set_source_surface(img, 0, 0)
    c.paint()
    c.restore()
    c.move_to(dx + 8, 34); c.show_text(label)

crop(a, 0, "DARK bg -> light text (on-dark)")
crop(b, cw + gap, "LIGHT bg -> dark text (on-light)")
crop(col, (cw + gap) * 2, "COLOR bands -> readable on every band")
canvas.write_to_png(f"{OUT}/gtd-side.png")
import shutil
try:
    shutil.copy("/tmp/bar/style.css", f"{OUT}/gtd-style.css")
except OSError as e:
    print("copy style.css loi:", e)

# tương phản WCAG: Y tuyến tính (srgb→linear), chữ = percentile cực trị
# (p1/p99) của đuôi xa median, nền = median. Ngưỡng 4.5:1 chữ, 3.0:1 icon.
def _lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def contrast(img, x0, y0, w, h):
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
    if (p99 - bg) >= (bg - p01):          # chữ sáng (đuôi trên)
        text = p99
    else:                                  # chữ tối (đuôi dưới)
        text = p01
    hi, lo = max(text, bg), min(text, bg)
    return (hi + 0.05) / (lo + 0.05)

# ô thật trên ảnh: (tên, x, y, w, h, ngưỡng) — chữ 4.5:1, icon 3.0:1
# nút tròn: đo interior từng vòng (loại viền rim sáng để không lẫn "chữ")
RECTS = [
    ("DND title",    1595,  68, 165, 26, 4.5),
    ("DND Off",      1595,  93,  40, 16, 4.5),
    ("slider icon",  1573, 144,  30, 25, 3.0),
    ("btn gear",     1779, 205,  21, 21, 3.0),
    ("btn lock",     1821, 205,  21, 21, 3.0),
    ("btn power",    1863, 205,  21, 21, 3.0),
    ("clock",         930,  10,  60, 34, 4.5),
    ("right module", 1836,  12,  61, 30, 3.0),
]
fails = []
for state, img in (("colorbg", col), ("darkbg", a), ("lightbg", b)):
    for name, x, y, w, h, need in RECTS:
        v = contrast(img, x, y, w, h)
        mark = "ok " if v >= need else "FAIL"
        print(f"  {state} {name:13s} contrast={v:5.2f}:1 (>= {need}) {mark}")
        if v < need:
            fails.append((f"{state}/{name}", round(v, 2)))

if fails:
    print("KHONG DAT nguong WCAG:", fails)
    sys.exit(1)
print("PASS: moi o chu tren nen mau deu dat WCAG (chu 4.5:1, icon 3.0:1)")
print("anh: gtd-quick-{darkbg,lightbg,colorbg}.png, gtd-side.png")
PY
cat /tmp/out/gtd-bar.log 2>/dev/null | grep -iv "system bus\|a11y\|pa_context\|Connection" || true
