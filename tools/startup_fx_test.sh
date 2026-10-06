#!/bin/sh
# Effects from the first frame: the daemon writes generated/swayctl-fx.conf;
# a fresh swayctl-fx reads it at startup, so the bar is glass before any daemon.
#   tools/sandbox.sh --fx /home/repo/tools/startup_fx_test.sh
set -eu
cd /home/repo
python3 -m swayctl_center daemon > /tmp/out/sf-daemon.log 2>&1 &
d=$!
sleep 2.5
python3 -m swayctl_center set effects.glass true >/dev/null
python3 -m swayctl_center set effects.glass_opacity 0 >/dev/null
sleep 1.5
kill $d; sleep 0.5
f=$XDG_CONFIG_HOME/swayctl-center/generated/swayctl-fx.conf
echo "file: $(wc -l < $f) lines"; grep -c layer_effects $f; grep for_window $f || true
# a second, fresh compositor: no daemon on it
WLR_BACKENDS=headless WLR_RENDERER=gles2 WLR_LIBINPUT_NO_DEVICES=1 $SWAY_BIN -c /tmp/sway.conf >/tmp/out/sf-sway2.log 2>&1 &
sleep 1.5
s2=$(ls -t $XDG_RUNTIME_DIR/sway-ipc.* | head -1); w2=$(ls -t $XDG_RUNTIME_DIR/wayland-* | grep -v lock | head -1)
SWAYSOCK=$s2 swaymsg 'output * bg #ff3060 solid_color' >/dev/null
SWAYSOCK=$s2 WAYLAND_DISPLAY=$(basename $w2) /home/repo/swayctl-bar/target/release/swayctl-bar \
  --config-dir $XDG_CONFIG_HOME/swayctl-center/generated/bar >/dev/null 2>&1 &
sleep 1.5
SWAYSOCK=$s2 WAYLAND_DISPLAY=$(basename $w2) grim -g "0,0 1920 60" /tmp/out/sf-bar.png 2>/dev/null || \
  WAYLAND_DISPLAY=$(basename $w2) grim /tmp/out/sf-bar.png
grep -iE "error|invalid" /tmp/out/sf-sway2.log | head -5 || true
