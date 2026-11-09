"""The one liquid glass look.

There are no glass settings: every pane of glass in the shell (the OSD, Quick Settings, the launcher, the
notifications, the glass desk's frame) gets this look, at any size. The shell's UI draws only the SHAPE of a
pane (a thin white body); the compositor (swayctl-fx) draws all of the glass - the bend at the rim, the soft
light along it and the faint colour fringe - from these values, the same for every pane. A pane's rim width
follows its own size (a pill narrower than two rims gets a narrower one), so a small tile and a big sheet both
bend at their edges.
"""
from __future__ import annotations

LOOK = {
    "refraction": 50,    # px of pull at the rim (the compositor holds it to what a pane can bend without folding)
    "blur": 0,           # crystal clear: a frost blurs the screen again for every frame of a video behind
    "highlight": 0.9,    # the soft light along the rim
    "edge_share": 100,   # rim width, % of the pane's corners (effects.EDGE_CAP)
    "thickness": 90,     # optical depth, px
    "chroma": 0.1,       # a faint colour fringe, as on the OSD
    "opacity": 10,       # the pane's white body, % (thinned to the 4 % floor shaped panes need to be seen)
}
