#!/bin/sh
# Build swayctl-center, swayctl-bar and swayctl-fx and pack them with the
# installer into one archive for a new machine that has (only) SwayFX:
#   packaging/make-bundle.sh            -> packaging/dist/swayctl-setup-<date>.tar.gz
# swayctl-fx is built from ../../swayctl-fx (local, unpushed work) when that
# folder exists, else from the published forks.
# On the new machine:  tar xf swayctl-setup-*.tar.gz && cd swayctl-setup && ./install.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "swayctl-bar (bar, Quick Settings, notifications, OSD, lock screen)"
# -d: cargo usually comes from rustup, not a pacman package
(cd swayctl-bar && makepkg -fd --noconfirm)

say "swayctl-fx (SwayFX fork: liquid glass, smooth scrolling, animations)"
fx_dir=$(cd "$here/../.." && pwd)/swayctl-fx
if [ -d "$fx_dir/swayfx" ] && [ -d "$fx_dir/scenefx" ]; then
  (cd swayctl-fx && SWAYCTL_FX_DIR="$fx_dir" makepkg -f --noconfirm)
else
  (cd swayctl-fx && makepkg -f --noconfirm)
fi

say "swayctl-center (settings app and daemon)"
makepkg -f --noconfirm

newest() { ls -1 "$1"/"$2"-*.pkg.tar.zst | sort -V | tail -n1; }
out=dist/swayctl-setup
rm -rf "$out"; mkdir -p "$out"
# the apps from their own repos, when they are here (each built with its own makepkg)
apps=""
for p in "$HOME"/Downloads/Element/matrix-egui-client/tauri-app/packaging/arch/chosua \
         "$HOME"/Git-projects/chodilamide/packaging/arch/chodilamide-ide; do
  f=$(ls -1 "$p"-*.pkg.tar.zst 2>/dev/null | sort -V | tail -n1 || true)
  [ -n "$f" ] && apps="$apps $f"
done
# shellcheck disable=SC2086
cp $apps "$out/" 2>/dev/null || true
cp "$(newest . swayctl-center)" "$(newest swayctl-bar swayctl-bar)" "$(newest swayctl-fx swayctl-fx)" \
   install.sh README.txt "$out/"
tarball="dist/swayctl-setup-$(date +%Y%m%d).tar.gz"
tar -C dist -czf "$tarball" swayctl-setup
say "Done: packaging/$tarball"
ls -1 "$out"
