#!/bin/sh
# swayctl-lock against test PAM services (tools/pam-test): it locks, the
# "fingerprint" succeeds after 3 s and unlocks, --daemonize returns once locked.
#   SANDBOX_PAM=tools/pam-test tools/sandbox.sh --fx /home/repo/tools/lock_test.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh" >&2; exit 1 ;; esac
lock=/home/repo/swayctl-bar/target/release/swayctl-lock
foot >/dev/null 2>&1 &
sleep 1
t0=$(date +%s%N)
$lock --fingerprint ${WALLFILE:+--wallpaper $WALLFILE} --service-prefix ${PREFIX:-swayctl-test-} --daemonize 2>/tmp/out/lock.log
echo "daemonize returned $? after $(( ($(date +%s%N) - t0) / 1000000 )) ms (screen locked)"
sleep 1
grim /tmp/out/lock-screen.png
sleep 3.5
pgrep -x swayctl-lock >/dev/null && echo "still locked: FAIL" || echo "unlocked by itself: OK"
grim /tmp/out/lock-after.png
cat /tmp/out/lock.log
