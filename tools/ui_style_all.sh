#!/bin/sh
# Shots of every interface style in light/dark, without and with glass, then
# one contact sheet per case: tools/out/uis-sheet-<mode>-<glass>.png
#   sh tools/ui_style_all.sh
cd "$(dirname "$0")/.."
for mode in light dark; do
  for glass in false; do
    MODE=$mode GLASS=$glass tools/sandbox.sh --fx /home/repo/tools/ui_style_shot.sh >/dev/null 2>&1
    for s in flat rounded liquid; do
      montage tools/out/uis-$s-quick.png tools/out/uis-$s-tray.png tools/out/uis-$s-osd.png -tile 3x1 -geometry +4+0 tools/out/uis-$s-row.png
    done
    montage tools/out/uis-flat-row.png tools/out/uis-rounded-row.png tools/out/uis-liquid-row.png -tile 1x3 -geometry +0+8 tools/out/uis-sheet-$mode-$glass.png
    montage tools/out/uis-flat-screen.png tools/out/uis-rounded-screen.png tools/out/uis-liquid-screen.png -tile 3x1 -geometry +6+0 tools/out/uis-screens-$mode-$glass.png
  done
done
