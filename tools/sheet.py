#!/usr/bin/env python3
"""Contact sheet of numbered frames: tools/sheet.py tools/out/qo-open -> tools/out/qo-open-sheet.png"""
import glob, sys
from PIL import Image

prefix = sys.argv[1]
fs = sorted(glob.glob(prefix + "-[0-9]*.png"), key=lambda p: int(p.rsplit("-", 1)[1][:-4]))
ims = [Image.open(f) for f in fs]
w, h = ims[0].size
sc = 0.5
tw, th = int(w * sc), int(h * sc)
cols = 5
sheet = Image.new("RGB", (tw * cols, th * ((len(ims) + cols - 1) // cols)))
for i, im in enumerate(ims):
    sheet.paste(im.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
sheet.save(prefix + "-sheet.png")
print(prefix + "-sheet.png", len(ims), "frames")
