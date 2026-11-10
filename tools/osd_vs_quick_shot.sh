#!/bin/sh
# OSD (one pill, box glass) next to Quick Settings (shaped glass), same backdrop and knobs.
#   WALL=rim_grid.png tools/sandbox.sh --fx /home/repo/tools/osd_vs_quick_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
swaymsg 'output HEADLESS-1 mode 3072x1920; output HEADLESS-1 scale 2' >/dev/null
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon > /tmp/out/ov-daemon.log 2>&1 &
sleep 2.5
sw() { python3 -m swayctl_center set "$1" "$2" >/dev/null; }
sw background.image /tmp/out/${WALL:-rim_grid.png}
sw effects.glass true; sw appearance.ui_style liquid
for kv in glass_refraction=${REFR:-50} glass_blur=0 glass_edge=${EDGE:-100} glass_thickness=${THICK:-90} glass_chroma=${CHROMA:-0.35} glass_highlight=0.9; do sw "effects.${kv%%=*}" "${kv#*=}"; done
sleep 4
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
# a pactl that answers (the sandbox has no sound server), so the OSD has a volume to show
mkdir -p /tmp/fakebin; cat > /tmp/fakebin/pactl <<'PA'
#!/bin/sh
case "$1" in
  get-sink-volume) echo "Volume: front-left: 32768 /  50% / -18.06 dB,   front-right: 32768 /  50% / -18.06 dB" ;;
  get-sink-mute) echo "Mute: no" ;;
  get-default-sink) echo fake ;;
  --format=json) echo '[{"name":"fake","description":"Sony WH-1000XM4 (Bluetooth headset)"},{"name":"hdmi","description":"HDMI / DisplayPort"}]' ;;
esac
PA
chmod +x /tmp/fakebin/pactl
python3 /home/repo/tools/fake_bluez.py ${BT_BATTERY:-72} >/tmp/out/fakebluez.log 2>&1 &
sleep 1
DBUS_SYSTEM_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS PATH=/tmp/fakebin:$PATH $bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/dev/null &
sleep 2
PATH=/tmp/fakebin:$PATH $bin osd volume-up; sleep 0.35
grim -g "520,400 500x90" /tmp/out/ov-osd-live-${TAG:-q}.png
sleep 2
$bin quick; sleep 2.5
grim -g "1100,30 430x520" /tmp/out/ov-quick-${TAG:-q}.png
