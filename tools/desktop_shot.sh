#!/bin/sh
# Full-desktop screenshot of a preset, inside the sandbox:
#   tools/sandbox.sh --fx tools/desktop_shot.sh modern dark   # SwayFX fork
#   tools/sandbox.sh --sway tools/desktop_shot.sh classic light
# Writes /tmp/out/desktop-<preset>-<mode>-<sway|fx>.png. Runs the real daemon
# against the sandboxed sway; systemd units can't start here, so the bar is
# launched by hand from the files the daemon generated.
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh" >&2; exit 1 ;; esac
preset=${1:-modern} mode=${2:-dark}
cd /home/repo
kind=$(swaymsg -t get_version | grep -q sway_original_version && echo fx || echo sway)
python3 -m swayctl_center daemon > "/tmp/out/daemon-$kind.log" 2>&1 &
daemon=$!
sleep 2.5
python3 -m swayctl_center action "preset.$preset"
python3 -m swayctl_center set appearance.mode "$mode" > /dev/null
sleep 1.5
gen="$XDG_CONFIG_HOME/swayctl-center/generated"
waybar -c "$gen/bar/config.json" -s "$gen/bar/style.css" > /dev/null 2>&1 &
foot sh -c 'printf "\033[1mswayctl-center\033[0m %s preset, %s\n\n" "$0" "$1"; ls -la /home/repo; sleep 60' "$preset" "$mode" > /dev/null 2>&1 &
sleep 0.7
foot sh -c 'top -d 1' > /dev/null 2>&1 &
sleep 0.7
swaymsg 'floating enable, resize set 700 360, move position center' > /dev/null
sleep 2.5
grim "/tmp/out/desktop-$preset-$mode-$kind.png"
kill $daemon
echo "/tmp/out/desktop-$preset-$mode-$kind.png"
