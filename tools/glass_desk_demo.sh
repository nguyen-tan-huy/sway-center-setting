#!/bin/sh
# Demo shots of the glass desk: windows, Quick Settings, launcher, notifications, other video frames.
#   tools/sandbox.sh --fx /home/repo/tools/glass_desk_demo.sh      -> tools/out/demo-*.png
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
swaymsg 'output HEADLESS-1 resolution 2560x1600 scale 1.25' >/dev/null; sleep 1
python3 -m swayctl_center daemon > /tmp/out/gd-daemon.log 2>&1 &
sleep 2.5
sw() { python3 -m swayctl_center set "$1" "$2" >/dev/null; }
sw appearance.ui_style glass
sw effects.glass_style clear
sleep 3
wall() { swaymsg "output * bg /tmp/out/mesh_t$1.png fill" >/dev/null; }
wall 1
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/tmp/out/gd-bar.log &
sleep 2
cat > /tmp/term.sh <<'T'
printf '\033[1;31m~\033[0m \033[35m❯\033[0m \033[32mneofetch\033[0m\n'
printf '\033[34mOS\033[0m      Arch Linux\n\033[34mWM\033[0m      swayctl-fx\n\033[34mBar\033[0m     swayctl-bar · liquid glass\n\033[34mGaps\033[0m    14px\n\033[34mFont\033[0m    Inter\n\n'
printf '\033[1;31m~\033[0m \033[35m❯\033[0m \033[32mswaymsg -t get_tree\033[0m\n  { "layout": "splith" }\n\033[1;31m~\033[0m \033[35m❯\033[0m '
sleep 600
T
swaymsg exec "foot -o colors-dark.background=11141a -e sh /tmp/term.sh" >/dev/null; sleep 1.5
swaymsg exec "foot -o colors-dark.background=1d2a44 sleep 600" >/dev/null; sleep 3
grim /tmp/out/demo-1-desk.png
wall 4; sleep 1.5; grim /tmp/out/demo-2-desk-later.png
wall 7; sleep 1.5; grim /tmp/out/demo-3-desk-later2.png
wall 1; sleep 1
$bin quick; sleep 2; grim /tmp/out/demo-4-quick.png
$bin quick; sleep 1
notify-send -a Messages "Huy" "Tối nay họp lúc 8 giờ nhé, nhớ mang laptop"; sleep 0.4
notify-send -a Calendar "Họp nhóm" "Bắt đầu sau 10 phút"; sleep 2; grim /tmp/out/demo-5-notifications.png
$bin launcher 2>/dev/null; sleep 2; grim /tmp/out/demo-6-launcher.png
