#!/bin/sh
# Do the Apple-like animation settings change how a window opens and closes? Counts the frames the
# compositor draws while a window opens and while it closes, under different settings.
#   SWAY_FRAME_TIMES=/tmp/out/ft.log tools/sandbox.sh --fx /home/repo/tools/window_anim_check.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
[ -n "${SWAY_FRAME_TIMES:-}" ] || { echo "set SWAY_FRAME_TIMES=/tmp/out/ft.log" >&2; exit 1; }
swaymsg 'output * bg #e8e6f0 solid_color; animations open_close enable; animation_duration_ms 300; animation_curve spring' >/dev/null
swaymsg 'for_window [app_id="w"] "floating enable, resize set 600 380, move position 200 200"' >/dev/null
frames() { wc -l < "$SWAY_FRAME_TIMES"; }
measure() {   # label, then sway commands
  label=$1; shift
  for c in "$@"; do swaymsg "$c" >/dev/null; done
  foot --app-id w -e sleep 60 >/dev/null 2>&1 & pid=$!; sleep 1.8
  swaymsg '[app_id=w] kill' >/dev/null; sleep 2.0                   # warm up this setting
  foot --app-id w -e sleep 60 >/dev/null 2>&1 & pid=$!
  a=$(frames); sleep 1.8; o=$(( $(frames) - a ))
  a=$(frames); swaymsg '[app_id=w] kill' >/dev/null; sleep 2.0; c=$(( $(frames) - a ))
  echo "$label: open $o frames, close $c frames"
}
measure "spring 400, close same     " "animation_spring 400 0" "animation_close 1 same" "animation_popin 0.8" "animation_fade 1"
measure "spring 400, close at 50%   " "animation_close 0.5 0"
measure "spring 400, close 50% +bounce" "animation_close 0.5 0.4"
