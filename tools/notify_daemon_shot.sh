#!/bin/sh
# Like the real session: the daemon applies effects (glass on), swaync runs
# with the files the daemon generated, then a notification.
#   tools/sandbox.sh --fx /home/repo/tools/notify_daemon_shot.sh
set -eu
cd /home/repo
python3 -c "
import cairo, math
s = cairo.ImageSurface(cairo.FORMAT_RGB24, 1920, 1080); c = cairo.Context(s)
g = cairo.LinearGradient(0, 0, 1920, 1080)
g.add_color_stop_rgb(0, .1, .2, .55); g.add_color_stop_rgb(1, .98, .65, .2); c.set_source(g); c.paint()
for i in range(40):
    c.set_source_rgba(1, 1, 1, .2 if i % 2 else .05); c.rectangle(i * 48, 0, 20, 1080); c.fill()
c.set_source_rgb(.2, .9, .6); c.arc(1700, 120, 120, 0, 2 * math.pi); c.fill()
s.write_to_png('/tmp/wall.png')"
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null
python3 -m swayctl_center daemon -v > /tmp/out/dn.log 2>&1 &
sleep 2.5
for kv in effects.glass=true effects.panels=true effects.glass_blur=${GLASS_BLUR:-0} effects.glass_opacity=${TINT:-0} effects.glass_refraction=30; do
  python3 -m swayctl_center set "${kv%%=*}" "${kv#*=}" >/dev/null
done
sleep 1.5
swaymsg 'output * bg /tmp/wall.png fill' >/dev/null   # the daemon set the theme color
gen=$XDG_CONFIG_HOME/swayctl-center/generated/notifications
swaync -c $gen/config.json -s $gen/style.css >/tmp/out/swaync.log 2>&1 &
sleep 2
notify-send -a Firefox "Tải xuống hoàn tất" "swayctl-fx-0.6.pkg.tar.zst đã được lưu vào Downloads"
sleep 1.2
swaymsg -t get_outputs | python3 -c "
import json,sys
for l in json.load(sys.stdin)[0].get('layer_shell_surfaces',[]):
    print(l['namespace'], l.get('effects'))"
grim -g "1300,0 620x260" /tmp/out/noti-daemon.png
grep -iE "layer_effects|swaync|error" /tmp/out/dn.log | head -20
