#!/bin/sh
# swayctl-bar memory over popups and rebuilds: open/close Quick Settings and
# rewrite the bar config many times; heap (RSS) must level off, not climb.
#   tools/sandbox.sh --fx /home/repo/tools/bar_leak_test.sh [binary]
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
bin=${1:-/home/repo/swayctl-bar/target/release/swayctl-bar}
cd /tmp
mkdir -p bar
cfg='"modules_left":["workspaces"],"modules_center":["clock"],"modules_right":["status","tray"],"height":38,"notifications":{"enabled":true}'
printf '{%s}' "$cfg" > bar/config.json
: > bar/style.css
$bin --config-dir /tmp/bar 2>/tmp/out/leak.log &
pid=$!
sleep 3
rss() { awk '/VmRSS/{print $2}' /proc/$pid/status; }
echo "start:                 $(rss) kB"
for round in 1 2 3; do
    i=0; while [ $i -lt 30 ]; do $bin quick; sleep 0.35; $bin quick; sleep 0.25; i=$((i+1)); done
    echo "quick x$((round*30)) open/close:  $(rss) kB"
done
for round in 1 2 3; do
    i=0; while [ $i -lt 30 ]; do printf '{%s,"padding":%d}' "$cfg" $((i%5)) > bar/config.json; sleep 0.2; i=$((i+1)); done
    sleep 1
    echo "rebuild x$((round*30)):          $(rss) kB"
done
# each notification reaches every panel ever opened if they leak (the
# list of up to 30 cards is rebuilt in each)
i=0; while [ $i -lt 40 ]; do notify-send "leak test $i" "body $i"; sleep 0.1; i=$((i+1)); done
sleep 1
echo "after 40 notifications: $(rss) kB"
# what the leaked panels and bars cost afterwards: every sway event reached
# each of them (workspace buttons rebuilt per dead bar)
i=0; while [ $i -lt 200 ]; do swaymsg "workspace $((i%4+1))" >/dev/null; i=$((i+1)); done
sleep 1
echo "after 200 ws switches:  $(rss) kB"
kill $pid
