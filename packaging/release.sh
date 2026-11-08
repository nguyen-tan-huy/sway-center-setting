#!/bin/sh
# Build the three packages and publish them as a GitHub release that get-swayctl.sh installs from:
#   packaging/release.sh              build, write packaging/dist/release/, create the release when `gh` is there
#   packaging/release.sh --no-build   reuse the newest packages already built (skips make-bundle.sh)
# Assets (stable names, so .../releases/latest/download/<name> always works):
#   swayctl-setup.tar.gz   the bundle (packages + install.sh)       SHA256SUMS   its checksum
#   plus each .pkg.tar.zst on its own, for `sudo pacman -U`.
# Commit and push swayctl-fx's work first: the fx package is built from ../../swayctl-fx.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
tag="v$(date +%Y%m%d)-$(grep '^pkgrel=' PKGBUILD | cut -d= -f2)"
build=1; [ "${1:-}" = "--no-build" ] && build=0
if [ $build = 1 ]; then ./make-bundle.sh; else ./make-bundle.sh --no-build; fi
bundle=$(ls -1t dist/swayctl-setup-*.tar.gz | head -n1)
out=dist/release; rm -rf "$out"; mkdir -p "$out"
cp "$bundle" "$out/swayctl-setup.tar.gz"
cp dist/swayctl-setup/*.pkg.tar.zst "$out/"
( cd "$out" && sha256sum swayctl-setup.tar.gz > SHA256SUMS && sha256sum -c SHA256SUMS >/dev/null )
echo "release $tag: $(ls "$out" | wc -l) files in packaging/$out"
if command -v gh >/dev/null; then
  gh release create "$tag" "$out"/* --title "swayctl $tag" \
    --notes "Install: curl -fsSL https://raw.githubusercontent.com/nguyen-tan-huy/sway-center-setting/master/get-swayctl.sh | sh"
else
  echo "no gh: create release $tag at https://github.com/nguyen-tan-huy/sway-center-setting/releases/new"
  echo "and attach everything in packaging/$out (the names must stay as they are)"
fi
