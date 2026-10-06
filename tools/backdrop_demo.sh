#!/bin/sh
# Backdrop IPC demo — "bar đọc nền qua IPC" TRƯỚC khi áp dụng hệ thống.
# Chạy trong sandbox (phiên thật không bị đụng tới):
#
#   tools/sandbox.sh --fx /home/repo/tools/backdrop_demo.sh
#
# Wallpaper sáng/tối như adaptive_shot, rồi:
#   1) lấy lưới 96x54 RGB qua IPC get_backdrop (đúng thứ Grid::capture của bar xin)
#   2) chụp grim cùng output, trung bình box về 96x54 làm tham chiếu
#   3) in heatmap ASCII + số liệu lệch, ghép ảnh so sánh
#   4) chạy adaptive_shot — minh họa popup tag chữ theo lưới đó
# Kết quả trong tools/out/ (bên trong: /tmp/out/).
set -eu
: "${SWAYSOCK:?run inside: tools/sandbox.sh --fx /home/repo/tools/backdrop_demo.sh}"
OUT=/tmp/out
SMSG=/home/fx/swayfx/build/swaymsg/swaymsg
LOG=$OUT/backdrop-demo.log
: >"$LOG"
command -v "$SMSG" >/dev/null || { echo "fork swaymsg missing: $SMSG" >>"$LOG"; exit 1; }

# --- wallpaper nửa sáng / nửa tối (cùng mẫu adaptive_shot) -----------------
/usr/bin/python3 - >>"$LOG" 2>&1 <<'EOF'
import cairo
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080)
c = cairo.Context(s)
c.set_source_rgb(0.97, 0.97, 0.97); c.rectangle(0, 0, 1100, 1080); c.fill()
c.set_source_rgb(0.05, 0.05, 0.08); c.rectangle(1100, 0, 820, 1080); c.fill()
c.select_font_face("Sans", 0, 1); c.set_font_size(36)
for row in range(26):
    c.set_source_rgb(*((0.1, 0.1, 0.1) if row % 2 else (0.9, 0.9, 0.9)))
    c.move_to(1300, 140 + row * 36); c.show_text("light and dark text behind")
s.write_to_png("/tmp/out/demo-wall.png")
print("wallpaper: /tmp/out/demo-wall.png")
EOF
/usr/bin/swaymsg output HEADLESS-1 bg "$OUT/demo-wall.png" fill >>"$LOG" 2>&1
sleep 0.6

# --- 1) lưới qua IPC (y hệt request của bar: 96x54 cả output) ---------------
$SMSG -r -t get_backdrop '{"output":"HEADLESS-1","cols":96,"rows":54}' \
	>"$OUT/backdrop-demo.json" 2>>"$LOG" || true
# --- 2) tham chiếu grim ------------------------------------------------------
grim -o HEADLESS-1 "$OUT/backdrop-demo-grim.png" >>"$LOG" 2>&1

/usr/bin/python3 - >>"$LOG" 2>&1 <<'EOF'
import json, cairo

GW, GH = 96, 54
d = json.load(open("/tmp/out/backdrop-demo.json"))
assert d.get("success"), d.get("error")
assert d["cols"] == GW and d["rows"] == GH and d["format"] == "rgb", d
cells = [(d["cells"][i], d["cells"][i+1], d["cells"][i+2])
         for i in range(0, len(d["cells"]), 3)]
assert len(cells) == GW * GH

def load_rgb(path):
    surf = cairo.ImageSurface.create_from_png(path)
    w, h, stride = surf.get_width(), surf.get_height(), surf.get_stride()
    buf = bytes(surf.get_data())
    rgb = bytearray(w * h * 3)
    for y in range(h):
        row = buf[y * stride:y * stride + w * 4]
        rgb[y*w*3:(y+1)*w*3] = b"".join(bytes(t) for t in zip(row[2::4], row[1::4], row[0::4]))
    return w, h, bytes(rgb)

def box96(w, h, rgb):
    out = []
    for gy in range(GH):
        y0, y1 = gy * h // GH, max(gy * h // GH + 1, (gy + 1) * h // GH)
        for gx in range(GW):
            x0, x1 = gx * w // GW, max(gx * w // GW + 1, (gx + 1) * w // GW)
            r = g = b = n = 0
            for y in range(y0, y1):
                base = y * w * 3
                for x in range(x0, x1):
                    i = base + x * 3
                    r += rgb[i]; g += rgb[i+1]; b += rgb[i+2]; n += 1
            out.append((r // n, g // n, b // n))
    return out

w, h, grim = load_rgb("/tmp/out/backdrop-demo-grim.png")
ref = box96(w, h, grim)

# lệch IPC vs grim
diffs = []
for a, b in zip(cells, ref):
    diffs.append(sum(abs(x - y) for x, y in zip(a, b)) / 3)
mean = sum(diffs) / len(diffs)
worst = max(range(len(diffs)), key=lambda i: diffs[i])
print(f"cells={len(cells)}  mean|diff|={mean:.2f}/255  "
      f"max={max(diffs):.1f}@cell#{worst} ({worst%GW},{worst//GW})")
print(f"IPC  cell {worst%GW},{worst//GW} = {cells[worst]}   grim = {ref[worst]}")
for name, idx in (("IPC top-left (nen sang)", 0), ("IPC top-right (nen toi)", GW - 1)):
    print(f"  {name}: {cells[idx]}")
ok = mean <= 8.0
print("PASS" if ok else "FAIL (lech qua lon)")

# ảnh lưới IPC phóng to 20px/ô
img = cairo.ImageSurface(cairo.FORMAT_RGB24, GW * 20, GH * 20)
c = cairo.Context(img)
for gy in range(GH):
    for gx in range(GW):
        r, g, b = cells[gy * GW + gx]
        c.set_source_rgb(r / 255, g / 255, b / 255)
        c.rectangle(gx * 20, gy * 20, 20, 20); c.fill()
img.write_to_png("/tmp/out/backdrop-demo-grid.png")

# ghép: lưới IPC | grim thật, có nhãn + số liệu (paint từng lớp riêng —
# hai lần set_source_surface thì source bị ghi đè, lớp đầu biến mất)
gap, band = 24, 56
side = cairo.ImageSurface(cairo.FORMAT_RGB24, GW * 20 * 2 + gap, GH * 20 + band)
c = cairo.Context(side)
c.set_source_rgb(0.12, 0.12, 0.14); c.paint()
c.set_source_rgb(1, 1, 1); c.select_font_face("Sans", 0, 1); c.set_font_size(24)
c.move_to(8, 36); c.show_text("IPC get_backdrop 96x54 (bar Grid::capture)")
c.move_to(GW * 20 + gap + 8, 36)
c.show_text(f"grim box-96x54  mean|diff|={mean:.2f}/255  {'PASS' if ok else 'FAIL'}")
c.set_source_surface(img, 0, band)
c.paint()
c.save()
c.translate(GW * 20 + gap, band)
c.set_source_surface(cairo.ImageSurface.create_from_png("/tmp/out/backdrop-demo-grim.png"), 0, 0)
c.paint()
c.restore()
side.write_to_png("/tmp/out/backdrop-demo-side.png")
print("anh: backdrop-demo-grid.png, backdrop-demo-grim.png, backdrop-demo-side.png")
if not ok:
    raise SystemExit(1)
EOF

# --- 4) demo effect thật: popup tag chữ theo lưới IPC ------------------------
echo "--- adaptive_shot (popup tag theo backend IPC) ---"
THEME=dark TINT=0 /home/repo/tools/adaptive_shot.sh >>"$LOG" 2>&1 \
	|| { echo "adaptive_shot failed" >>"$LOG"; exit 1; }
echo "anh popup: adaptive-{bar,quick,cal,notify}-dark.png"
cat "$LOG"
