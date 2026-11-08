"""Screenshots: grim captures, slurp picks the region, satty annotates
(arrows, boxes, text, blur, numbering) and copies/saves. Runs in the caller's
process (a keyboard shortcut), so it works whether or not the daemon is up.
Nothing user-provided is interpolated into the shell pipelines.
"""
from __future__ import annotations

import subprocess

_SATTY = ('satty --filename - --early-exit --copy-command wl-copy --save-after-copy '
          '--output-filename "$HOME/Pictures/Screenshots/%Y-%m-%d_%H-%M-%S.png"')
_PREP = 'mkdir -p "$HOME/Pictures/Screenshots"; '
_SLURP = "slurp -b '#00000066' -c '#ffffffff' -w 2"

PIPELINES = {
    # drag a region (Esc cancels), then annotate
    "region": _PREP + 'geom=$(' + _SLURP + ') || exit 0; grim -g "$geom" -t ppm - | ' + _SATTY,
    # the whole layout, then annotate
    "full": _PREP + "grim -t ppm - | " + _SATTY,
    # click a window (slurp snaps to the windows sway lists), then annotate
    "window": _PREP + 'geom=$(swaymsg -t get_tree | jq -r \'.. | select(.pid? and .visible?) '
              '| .rect | "\\(.x),\\(.y) \\(.width)x\\(.height)"\' | ' + _SLURP + ') || exit 0; '
              'grim -g "$geom" -t ppm - | ' + _SATTY,
    # region straight to the clipboard, no editor
    "quick": 'geom=$(' + _SLURP + ') || exit 0; grim -g "$geom" - | wl-copy -t image/png',
}

ACTIONS = tuple(PIPELINES)


def run(what: str, wait: bool = True) -> int:
    proc = subprocess.Popen(["sh", "-c", PIPELINES[what]], start_new_session=True)
    return proc.wait() if wait else 0
