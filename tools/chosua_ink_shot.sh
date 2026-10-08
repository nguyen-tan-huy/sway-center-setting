#!/bin/sh
# ChoSua (GTK) over liquid glass with key ink, on a half dark / half light
# wallpaper: its text must come out light on the dark side, dark on the
# light side, and no key colour (#FF00FE) left anywhere. Copy the binary in
# first (the sandbox can't see ~/Downloads):
#   cp .../target/release/chosua-gtk tools/out/ && tools/sandbox.sh --fx /home/repo/tools/chosua_ink_shot.sh
# Shot: tools/out/chosua-ink.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
trap 'cp /tmp/sway.log /tmp/out/chosua-ink-sway.log 2>/dev/null || true' EXIT
cd /tmp
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
python3 - <<'PY'
import cairo
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 3072, 1920)
c = cairo.Context(s)
c.set_source_rgb(0.08, 0.10, 0.22); c.rectangle(0, 0, 1536, 1920); c.fill()
c.set_source_rgb(0.95, 0.93, 0.88); c.rectangle(1536, 0, 1536, 1920); c.fill()
s.write_to_png("/tmp/wall.png")
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
# ChoSua turns its glass styling on from swayctl-center's settings
mkdir -p "$HOME/.config/swayctl-center"
echo '{"values": {"effects": {"glass": true, "glass_refraction": 140}}}' > "$HOME/.config/swayctl-center/settings.json"
swaymsg 'for_window [app_id="chosua"] "floating enable, resize set 1500 900, move position 400 200, border none, glass enable, glass refraction 140, glass blur 0, glass highlight 0.9, glass edge 20, glass thickness 652, glass chroma 0.083, glass text auto, shadows disable"' >/dev/null
/tmp/out/chosua-gtk >/tmp/out/chosua-ink-app.log 2>&1 &
sleep 8
grim /tmp/out/chosua-ink.png
python3 - <<'PY'
from PIL import Image
im = Image.open("/tmp/out/chosua-ink.png").convert("RGB")
px = list(im.getdata())
key = sum(1 for (r, g, b) in px if r > 200 and b > 200 and g < 90)
print("key-coloured pixels left:", key)
PY
