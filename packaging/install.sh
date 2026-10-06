#!/bin/sh
# swayctl-center: install on an Arch / CachyOS machine that has (only) SwayFX.
#   ./install.sh            asks before anything optional
#   ./install.sh --yes      takes every recommended extra
# Then log out and pick "Sway (swayctl-fx)" on the login screen.
set -eu
cd "$(dirname "$0")"
yes_all=0; [ "${1:-}" = "--yes" ] && yes_all=1
ask() { [ $yes_all = 1 ] && return 0; printf '%s [Y/n] ' "$1"; read -r a; case "$a" in n|N|no) return 1;; esac; }
say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

command -v pacman >/dev/null || { echo "needs pacman (Arch / CachyOS)"; exit 1; }
if ! pacman -Qq sway swayfx 2>/dev/null | grep -q .; then
  echo "Neither sway nor swayfx is installed: install one first (sudo pacman -S swayfx)."; exit 1
fi

say "Installing swayctl-center, swayctl-bar and swayctl-fx (dependencies come from the repos)"
# one package per name: the newest (the folder can hold several versions if it was
# extracted on top of an old one; pacman would then say "duplicate target")
pick() { ls -1 "$1"-*.pkg.tar.zst 2>/dev/null | sort -V | tail -n1; }
center=$(pick swayctl-center); bar=$(pick swayctl-bar); fx=$(pick swayctl-fx)
for p in "$center" "$bar" "$fx"; do
  [ -n "$p" ] && [ -f "$p" ] || { echo "missing package in this folder"; exit 1; }
  echo "  $p"
done
sudo pacman -U --needed "$center" "$bar" "$fx"

# what each settings page / Quick Settings tile talks to; only what's missing
extras=""
want() { pacman -Qq "$1" >/dev/null 2>&1 || extras="$extras $1"; }
for p in adw-gtk-theme pipewire-pulse wireplumber pavucontrol networkmanager bluez bluez-utils upower \
         power-profiles-daemon brightnessctl wl-clip-persist; do want "$p"; done
if [ -n "$extras" ]; then
  say "Recommended:$extras"
  echo "  sound (pipewire-pulse, pavucontrol), Wi-Fi (networkmanager), Bluetooth (bluez), battery (upower),"
  echo "  power modes, screen brightness, dark GTK 3 apps (adw-gtk-theme), clipboard that outlives apps"
  if ask "Install them?"; then
    # one at a time: a conflict (e.g. tlp vs power-profiles-daemon) only skips that one
    for p in $extras; do sudo pacman -S --needed --noconfirm "$p" || echo "  skipped $p"; done
  fi
fi

for svc in NetworkManager bluetooth power-profiles-daemon; do
  if systemctl list-unit-files "$svc.service" >/dev/null 2>&1 && ! systemctl is-enabled -q "$svc" 2>/dev/null; then
    if ask "Start $svc now and at boot?"; then sudo systemctl enable --now "$svc" || true; fi
  fi
done

aur=$(command -v paru || command -v yay || true)
if ! command -v walker >/dev/null; then
  if [ -n "$aur" ]; then
    if ask "Install the Walker launcher (AUR: walker-bin, elephant-bin and its providers)?"; then
      # the providers swayctl-center's Search page uses (modules/launcher.py)
      $aur -S --needed walker-bin elephant-bin elephant-providerlist-bin elephant-desktopapplications-bin \
        elephant-menus-bin elephant-calc-bin elephant-files-bin elephant-websearch-bin elephant-symbols-bin \
        elephant-windows-bin elephant-runner-bin || echo "  Walker not installed; fuzzel stays the launcher"
    fi
  else
    echo "  (no paru/yay: the launcher stays fuzzel; Settings > Search can install Walker later)"
  fi
fi

# the daemon starts from /etc/sway/config.d; a personal config must include it
cfg="${XDG_CONFIG_HOME:-$HOME/.config}/sway/config"
if [ -f "$cfg" ] && ! grep -qE '^\s*include\s+/etc/sway/config\.d' "$cfg"; then
  say "Your $cfg doesn't include /etc/sway/config.d"
  if ask "Add 'include /etc/sway/config.d/*' at its end?"; then
    printf '\n# swayctl-center (and the distro) drop-ins\ninclude /etc/sway/config.d/*\n' >> "$cfg"
  else
    echo "  add it yourself, or swayctl-center won't start with sway"
  fi
fi

say "Done"
echo "Log out and pick \"Sway (swayctl-fx)\" on the login screen (plain SwayFX works too, without liquid glass"
echo "and smooth scrolling). The first start opens a short setup; later: \"Settings\" in the launcher, or the"
echo "gear in Quick Settings (click the status icons on the right of the bar)."
