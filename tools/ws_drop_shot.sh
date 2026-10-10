#!/bin/sh
# The workspace "drop": the focused-workspace blob slides between buttons,
# stretching on the way. Frames of the bar strip while switching 1 -> 5 and
# back, at growing delays: tools/out/wsdrop-<move>-<ms>.png
#   tools/sandbox.sh --fx /home/repo/tools/ws_drop_shot.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /tmp
mkdir -p bar
printf '{"modules_left":["workspaces"],"modules_center":["clock"],"modules_right":["status"],"height":38}' > bar/config.json
# a stale generated theme: key-coloured workspace text, nothing about the drop
printf ".workspace, .workspace label { color: #ff00fe; }\n" > bar/style.css
for n in 1 2 3 4 5; do
    swaymsg "workspace $n" >/dev/null
    foot -T "ws$n" sleep 600 >/dev/null 2>&1 &
    sleep 0.6
done
swaymsg "workspace 1" >/dev/null
/home/repo/swayctl-bar/target/release/swayctl-bar --config-dir /tmp/bar 2>/tmp/out/wsdrop.log &
sleep 2.5
grim -g "0,0 400x40" /tmp/out/wsdrop-rest.png
shot() { # move label, then frames at delays (ms) after the switch
    move=$1; shift
    for ms in 0 40 80 120 180 260 400 900; do
        swaymsg "workspace $1" >/dev/null
        t0=$(date +%s%N)
        while :; do
            now=$(( ($(date +%s%N) - t0) / 1000000 ))
            [ "$now" -ge "$ms" ] && break
        done
        grim -g "0,0 400x40" "/tmp/out/wsdrop-$move-$ms.png"
        sleep 1.2
        swaymsg "workspace $2" >/dev/null
        sleep 1.2
    done
}
shot right 5 1
shot left 1 5
echo done
