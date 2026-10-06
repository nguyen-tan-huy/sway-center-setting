#!/bin/sh
# Prepare what tools/liquid-demo.html and tools/liquid_shot.sh need, from the
# *real* configuration (host only — the sandbox has its own HOME, and this only
# reads ~/.config and writes into tools/out, which is git-ignored):
#   out/liquid-bg.png, out/wall-real.png  your wallpaper  (page / compositor bg)
#   out/busy-wall.jpg                     the busiest wallpaper = refraction test
#   out/bgs/*.jpg + out/liquid-config.js  the page's background picker
#   out/liquid-config.json                the page's / harness' settings
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)
python3 - "$repo" <<'PY'
import json, os, re, shutil, sys
from datetime import datetime
from pathlib import Path

repo = Path(sys.argv[1])
out = repo / "tools" / "out"
out.mkdir(parents=True, exist_ok=True)
cfg_dir = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "swayctl-center"

values = {}
try:
    values = json.loads((cfg_dir / "settings.json").read_text()).get("values", {})
except OSError as e:
    print(f"liquid_wall: {cfg_dir}/settings.json: {e}", file=sys.stderr)

from PIL import Image, ImageFilter, ImageStat            # noqa: E402

def load(p):
    im = Image.open(p).convert("RGB")
    if im.width > 1920:
        im = im.resize((1920, max(1, round(im.height * 1920 / im.width))), Image.LANCZOS)
    return im

def luma_grid(im):
    import base64
    small = im.resize((160, 90), Image.BOX)
    lin = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    enc = lambda y: 12.92 * y if y <= 0.0031308 else 1.055 * y ** (1 / 2.4) - 0.055
    out = bytes(round(255 * enc(0.2126 * lin(r / 255) + 0.7152 * lin(g / 255) + 0.0722 * lin(b / 255)))
                for r, g, b in small.getdata())
    return base64.b64encode(out).decode()

def busyness(im):
    """Edge energy: how much there is behind the glass to bend."""
    g = im.convert("L").resize((320, 180))
    return ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]

# --- your wallpaper: the page's default background and the harness' output bg -
rel = ((values.get("background") or {}).get("image")) or ""
configured = cfg_dir / rel if rel else None
src = configured if configured is not None and configured.is_file() else None
if src is None and (cfg_dir / "wallpapers").is_dir():
    shots = sorted((cfg_dir / "wallpapers").glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    src = shots[0] if shots else None
if src is None:
    print("liquid_wall: no wallpaper found; the page draws its own", file=sys.stderr)
else:
    try:
        im = load(src)
        im.save(out / "liquid-bg.png")
        im.save(out / "wall-real.png")
        print(f"liquid_wall: {src.name} -> liquid-bg.png, wall-real.png ({im.width}x{im.height})")
    except Exception as e:
        shutil.copyfile(src, out / "liquid-bg.png")
        shutil.copyfile(src, out / "wall-real.png")
        print(f"liquid_wall: {src.name} -> *.png (copied: {e})")

# --- every wallpaper, for the picker; the busiest one goes on by default -----
bgs_dir = out / "bgs"
bgs_dir.mkdir(exist_ok=True)
for old in bgs_dir.glob("*"):
    old.unlink()
bgs = []
if (cfg_dir / "wallpapers").is_dir():
    for p in sorted((cfg_dir / "wallpapers").glob("*")):
        if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        try:
            im = load(p)
        except Exception as e:
            print(f"liquid_wall: {p.name}: {e}", file=sys.stderr)
            continue
        name = f"bg{len(bgs)}.jpg"
        im.save(bgs_dir / name, quality=86, optimize=True)
        bgs.append({
            "file": name,
            # 160x90 luminance grid (sRGB-encoded grey, base64): Chrome won't let a
            # file:// page read image pixels, so the adaptive text colour uses this
            "luma": luma_grid(im),
            "label": re.sub(r"^[0-9a-f]{6,}-", "", p.stem)[:36],
            "current": configured is not None and p == configured,
            "busy": round(busyness(im), 1),
        })
if bgs:
    busiest = max(bgs, key=lambda b: b["busy"])
    shutil.copyfile(bgs_dir / busiest["file"], out / "busy-wall.jpg")
    print(f"liquid_wall: {len(bgs)} wallpapers in out/bgs/, busiest = {busiest['label']} "
          f"({busiest['busy']}) -> default background + out/busy-wall.jpg")
else:
    busiest = None
    print("liquid_wall: no wallpapers for the picker", file=sys.stderr)

# --- what the shell runs with ----------------------------------------------
sys.path.insert(0, str(repo))
from swayctl_center import schema, themes                      # noqa: E402
from swayctl_center.modules import Context                     # noqa: E402
from swayctl_center.modules.components import BarModule        # noqa: E402

v = schema.defaults()
for sec in ("appearance", "bar", "effects", "font"):
    if isinstance(values.get(sec), dict):
        v.setdefault(sec, {}).update(values[sec])
mode = (v["appearance"] or {}).get("mode", "auto")
hour = datetime.now().hour
dark = mode == "dark" or (mode == "auto" and not (7 <= hour < 19))
theme = themes.BUILTIN["dark" if dark else "light"]
ctx = Context(out, values=v, theme=theme)
bar = v["bar"]
cfg = {
    "accent": theme.tokens["accent"],
    "accent_fg": theme.tokens["accent_fg"],
    "dark": dark,
    # LC_TIME is what swayctl-bar's clock formats with (vi_VN here); the mock
    # passes it to Intl so both show the same date
    "locale": os.environ.get("LC_TIME") or os.environ.get("LC_ALL") or os.environ.get("LANG") or "",
    "font": dict(v["font"]),
    "bar": {
        "height": bar["height"], "position": bar["position"], "spacing": bar["spacing"],
        "clock_format": schema.strftime_format(bar["clock_format"]),
        "margins": BarModule().margins(bar, ctx),
        "modules_left": bar["modules_left"], "modules_center": bar["modules_center"],
        "modules_right": bar["modules_right"],
    },
    "effects": {k: val for k, val in sorted(v["effects"].items()) if k == "glass" or k.startswith("glass_")},
    # every shell surface reads the same Liquid glass knobs (mock readout shape)
    "demo_lens": {ns: {k: v["effects"]["glass_" + k] for k in
                       ("edge", "thickness", "refraction", "highlight", "chroma", "blur")}
                  for ns in ("swayctl-bar", "swayctl-quick", "swayctl-osd")},
    # a busy photo by default: on a flat wallpaper the lens has nothing to bend
    "bgs": bgs,
    "default_bg": f"file:{busiest['file']}" if busiest else "pattern",
}
(out / "liquid-config.js").write_text(
    "// written by tools/liquid_wall.sh - the real shell's bar and glass settings\n"
    "window.LIQUID_CFG = " + json.dumps(cfg, ensure_ascii=False, indent=1) + ";\n")
# the same settings, as data, for tools/liquid_shot.sh (it runs where
# ~/.config does not exist)
(out / "liquid-config.json").write_text(json.dumps({"dark": dark, "values": v}, ensure_ascii=False, indent=1))
print("liquid_wall: tools/out/liquid-config.{js,json} written")
PY
echo "open: google-chrome-stable --new-window \"$repo/tools/liquid-demo.html\""
