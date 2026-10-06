#!/bin/sh
# Run a command isolated from the real session: throwaway HOME and
# XDG_RUNTIME_DIR, so the real sway socket, session D-Bus, systemd --user and
# ~/.config are unreachable. Repo is mounted read-only at /home/repo; write
# artifacts to /tmp/out (= tools/out/ on the host).
#
#   tools/sandbox.sh python3 -m unittest discover -s tests -t .
#   tools/sandbox.sh --sway CMD...   # also start a headless sway (pixman), SWAYSOCK set
#   tools/sandbox.sh --fx CMD...     # same with the SwayFX fork built in ../swayctl-fx
#   SANDBOX_PAM=dir tools/sandbox.sh ...  # dir replaces /etc/pam.d inside
#                                    # (GLES2 on the GPU render node; scenefx needs it)
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$repo/tools/out"
fx="$repo/../swayctl-fx"
with_sway=0 sway_bin=sway renderer=pixman dri=""
case "${1:-}" in
  --sway) with_sway=1; shift ;;
  --fx) with_sway=1; shift
        sway_bin=/home/fx/swayfx/build/sway/sway renderer=gles2 dri="--dev-bind /dev/dri /dev/dri"
        [ -x "$fx/swayfx/build/sway/sway" ] || { echo "build the fork first" >&2; exit 1; } ;;
esac
fx_mount=""
# SANDBOX_PAM=DIR: use DIR as /etc/pam.d (test services; the real one is never touched)
pam_mount=""
[ -n "${SANDBOX_PAM:-}" ] && pam_mount="--ro-bind $(cd "$SANDBOX_PAM" && pwd) /etc/pam.d"
[ -d "$fx" ] && fx_mount="--ro-bind $(cd "$fx" && pwd) /home/fx"

inner='
set -eu
export HOME=/home/sandbox XDG_RUNTIME_DIR=/run/sandbox XDG_CONFIG_HOME=/home/sandbox/.config
mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" && chmod 700 "$XDG_RUNTIME_DIR"
cd /home/repo
if [ "$WITH_SWAY" = 1 ]; then
  printf "xwayland disable\noutput HEADLESS-1 resolution 1920x1080\n" > /tmp/sway.conf
  WLR_BACKENDS=headless WLR_RENDERER=$RENDERER WLR_LIBINPUT_NO_DEVICES=1 \
    $SWAY_BIN -c /tmp/sway.conf >/tmp/sway.log 2>&1 &
  for _ in $(seq 50); do s=$(ls "$XDG_RUNTIME_DIR"/sway-ipc.* 2>/dev/null | head -1); [ -n "$s" ] && break; sleep 0.1; done
  [ -n "${s:-}" ] || { cat /tmp/sway.log; exit 1; }
  export SWAYSOCK=$s WAYLAND_DISPLAY=wayland-1
fi
# a private session bus: GTK apps need one, and it must not be the real one
export NO_AT_BRIDGE=1 GTK_USE_PORTAL=0
exec dbus-run-session --config-file=/home/repo/tools/sandbox-bus.conf -- "$@"
'
exec bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --tmpfs /run \
  --tmpfs /home --bind "$repo/tools/out" /tmp/out --ro-bind "$repo" /home/repo $fx_mount $dri $pam_mount \
  --unsetenv SWAYSOCK --unsetenv WAYLAND_DISPLAY --unsetenv DBUS_SESSION_BUS_ADDRESS \
  --unsetenv I3SOCK --setenv WITH_SWAY "$with_sway" --setenv SWAY_BIN "$sway_bin" --setenv RENDERER "$renderer" --setenv PYTHONDONTWRITEBYTECODE 1 \
  --die-with-parent --unshare-ipc --unshare-pid \
  sh -c "$inner" sh "$@"
