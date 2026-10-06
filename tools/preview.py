"""Screenshot the generated bar for a theme and style, inside the sandbox:

    tools/sandbox.sh --sway python3 tools/preview.py modern-dark modern
    tools/sandbox.sh --fx python3 tools/preview.py modern-dark modern native   # swayctl-bar + Quick Settings

Writes /tmp/out/preview-<theme>-<style>.png (tools/out/ on the host). Never run
outside tools/sandbox.sh: it starts programs on whatever sway SWAYSOCK names.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swayctl_center import schema, themes  # noqa: E402
from swayctl_center.modules import Context  # noqa: E402
from swayctl_center.modules.components import BarModule  # noqa: E402

if not os.environ.get("SWAYSOCK", "").startswith("/run/sandbox/"):
    sys.exit("refusing to run outside tools/sandbox.sh --sway")

theme_name, style, program = (sys.argv[1:] + ["dark", "modern", "waybar"][len(sys.argv) - 1:])[:3]
native = program == "native"
theme = themes.BUILTIN.get(theme_name) or themes.BUILTIN[themes.LEGACY.get(theme_name, "dark")]
values = schema.defaults()
values["appearance"]["style"] = style
values["font"].update(family="Inter", size=11)
ctx = Context(Path("/tmp/app"), values=values, theme=theme)

bar = values["bar"] | {"modules_right": ["pulseaudio", "network", "battery", "clock"],
                       "modules_center": ["sway/window"], "program": "swayctl-bar" if native else "waybar"}
work = Path("/tmp/bar")
work.mkdir(exist_ok=True)
for name, text in BarModule().files(bar, ctx).items():
    (work / name).write_text(text)

k = theme.tokens
sway = lambda *c: subprocess.run(["swaymsg", *c], capture_output=True)  # noqa: E731
sway(f"output * bg {k['surface_overlay']} solid_color")
for n in ("1", "2", "3"):
    sway(f"workspace {n}")
sway("workspace 2")
if native:
    binary = "/home/repo/swayctl-bar/target/release/swayctl-bar"
    procs = [subprocess.Popen([binary, "--config-dir", str(work)], stderr=open("/tmp/out/swayctl-bar.log", "w"))]
else:
    procs = [subprocess.Popen(["waybar", "-c", str(work / "config.json"), "-s", str(work / "style.css")],
                              stdout=subprocess.DEVNULL, stderr=open("/tmp/out/waybar.log", "w"))]
if os.environ.get("SWAYSOCK"):
    for ns in ("swayctl-bar",):
        for effect in ("blur enable", "blur_ignore_transparent enable"):
            subprocess.run(["swaymsg", "layer_effects", ns, effect], capture_output=True)
subprocess.Popen(["foot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2.5)
tag = f"{theme_name}-{style}{'-native' if native else ''}"
out = f"/tmp/out/preview-{tag}.png"
subprocess.run(["grim", "-g", "0,0 1920x90", out], check=True)
print(out)
if native:
    subprocess.run([binary, "quick"])
    time.sleep(0.09)
    subprocess.run(["grim", "-g", "1300,0 620x700", f"/tmp/out/quick-{tag}-opening.png"], check=True)
    time.sleep(1.0)
    subprocess.run(["grim", "-g", "1300,0 620x700", f"/tmp/out/quick-{tag}.png"], check=True)
    subprocess.run([binary, "osd", "volume-up"])
    time.sleep(0.6)
    subprocess.run(["grim", "-g", "560,800 800x280", f"/tmp/out/osd-{tag}.png"], check=True)
    print(f"/tmp/out/quick-{tag}.png")
for p in procs:
    p.terminate()
