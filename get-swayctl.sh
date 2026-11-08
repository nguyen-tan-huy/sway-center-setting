#!/bin/sh
# Install swayctl-center (settings app + daemon), swayctl-bar (bar, Quick Settings, launcher,
# notifications, lock screen) and swayctl-fx (SwayFX fork with liquid glass) from the latest
# GitHub release, on Arch / CachyOS:
#
#   curl -fsSL https://raw.githubusercontent.com/nguyen-tan-huy/sway-center-setting/master/get-swayctl.sh | sh
#   curl -fsSL .../get-swayctl.sh | sh -s -- --yes      # take every recommended extra
#
# Then log out and pick "Sway (swayctl-fx)" on the login screen.
# SWAYCTL_BASE_URL overrides where swayctl-setup.tar.gz and SHA256SUMS are fetched from
# (a release's .../releases/latest/download, or a file:// folder); --download-only stops
# after unpacking.
set -eu
base=${SWAYCTL_BASE_URL:-https://github.com/nguyen-tan-huy/sway-center-setting/releases/latest/download}
args=""; download_only=0
for a in "$@"; do
  case "$a" in --download-only) download_only=1 ;; *) args="$args $a" ;; esac
done
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { echo "error: $*" >&2; exit 1; }

command -v pacman >/dev/null || die "needs pacman (Arch / CachyOS)"
command -v curl >/dev/null || die "needs curl (sudo pacman -S curl)"
command -v sha256sum >/dev/null || die "needs sha256sum (coreutils)"
[ "$(id -u)" -ne 0 ] || die "run as your own user, not root (it asks for sudo itself)"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM
cd "$tmp"

say "Downloading the latest swayctl release"
curl -fL --progress-bar -o swayctl-setup.tar.gz "$base/swayctl-setup.tar.gz" || die "could not download $base/swayctl-setup.tar.gz"
curl -fsSL -o SHA256SUMS "$base/SHA256SUMS" || die "could not download $base/SHA256SUMS"
say "Checking the download"
grep ' swayctl-setup.tar.gz$' SHA256SUMS | sha256sum -c - || die "checksum mismatch: not installing"

tar -xzf swayctl-setup.tar.gz
[ -x swayctl-setup/install.sh ] || [ -f swayctl-setup/install.sh ] || die "the archive has no install.sh"
if [ "$download_only" = 1 ]; then
  keep=${PWD}/../swayctl-setup-unpacked; rm -rf "$keep"; mv swayctl-setup "$keep"
  trap - EXIT; echo "unpacked in $keep"; exit 0
fi
cd swayctl-setup
say "Installing"
# shellcheck disable=SC2086
sh ./install.sh $args
