#!/bin/sh
# swayctl-bar as the notification server, over a busy wallpaper with glass:
# pop-ups, replace, close by app, actions, expiry, DND, Quick Settings list.
# tools/sandbox.sh --fx /home/repo/tools/notify_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
python3 - <<'PY'
import cairo, math
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080)
c = cairo.Context(s)
g = cairo.LinearGradient(0, 0, 1920, 1080)
g.add_color_stop_rgb(0, 0.10, 0.20, 0.55); g.add_color_stop_rgb(0.5, 0.75, 0.25, 0.55); g.add_color_stop_rgb(1, 0.98, 0.65, 0.20)
c.set_source(g); c.paint()
for i in range(40):
    c.set_source_rgba(1, 1, 1, 0.18 if i % 2 else 0.05); c.rectangle(i * 48, 0, 20, 1080); c.fill()
for x, y, r, col in ((1650, 200, 140, (0.2, 0.9, 0.6)), (1400, 420, 110, (0.3, 0.6, 1))):
    c.set_source_rgb(*col); c.arc(x, y, r, 0, 2 * math.pi); c.fill()
s.write_to_png("/tmp/wall.png")
import sys, json, pathlib; sys.path.insert(0, "/home/repo")
from swayctl_center import themes, schema
from swayctl_center.modules import Context
from swayctl_center.modules.components import BarModule
from swayctl_center.modules.effects import EffectsModule
v = schema.defaults(); v["appearance"]["style"] = "modern"; v["effects"]["glass"] = True
v["notifications"]["timeout"] = 4
ctx = Context(pathlib.Path("/tmp/app"), values=v, theme=themes.BUILTIN[__import__("os").environ.get("THEME", "dark")],
              live={"sway_original_version": "x", "swayctl_features": ["glass", "glass-shaped", "glass-blur"]})
d = pathlib.Path("/tmp/bar"); d.mkdir(exist_ok=True)
cfg = BarModule().native_config(v["bar"] | {"program": "swayctl-bar"}, ctx)
(d / "config.json").write_text(json.dumps(cfg))
(d / "style.css").write_text(BarModule().native_css(ctx, ctx.theme))
open("/tmp/fx.cmds", "w").write("\n".join(EffectsModule().commands("effects", v["effects"], None, ctx)))
PY
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
while IFS= read -r c; do swaymsg -- "$c" >/dev/null 2>&1 || echo "fx: $c failed" >&2; done < /tmp/fx.cmds
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir /tmp/bar 2>/tmp/out/notify-bar.log &
sleep 2
gdbus call --session -d org.freedesktop.Notifications -o /org/freedesktop/Notifications \
  -m org.freedesktop.Notifications.GetServerInformation > /tmp/out/notify-info.txt
notify-send -a Firefox -i firefox "Download finished" "report-2026.pdf (2.4 MB) saved to <b>Downloads</b>"
sleep 0.4
id=$(notify-send -p -a Mail -i mail-unread "Nguyễn Văn A" "Họp lúc 15:00 nhé? Mình gửi tài liệu trước.")
sleep 0.4
notify-send -u critical -a Battery -i battery-caution "Battery low" "5% remaining"
sleep 0.4
notify-send -a Chat -A reply=Reply -A mute=Mute "Lan" "Tối nay đi ăn không?" > /tmp/out/notify-action.txt &
sleep 1
grim /tmp/out/notify-1.png
notify-send -r "$id" -a Mail -i mail-unread "Nguyễn Văn A (2)" "Đổi sang 16:00."
sleep 0.6
grim /tmp/out/notify-2-replaced.png
sleep 4.5   # normal ones expire (critical stays)
grim /tmp/out/notify-3-expired.png
$bin quick
sleep 1
grim /tmp/out/notify-4-quick.png
$bin quick; sleep 0.4
$bin dnd on
notify-send -a Test "Hidden while DND" "should not pop up"
sleep 0.6
grim /tmp/out/notify-5-dnd.png
grep -c . /tmp/out/notify-bar.log || true
