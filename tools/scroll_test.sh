#!/bin/sh
# Compare what an app receives with compositor smooth scrolling off and on.
#   tools/sandbox.sh --fx /home/repo/tools/scroll_test.sh
set -eu
case "${SWAYSOCK:-}" in /run/sandbox/*) ;; *) echo "run me through tools/sandbox.sh --fx" >&2; exit 1 ;; esac
cd /home/repo/tools
python3 scroll_probe.py /tmp/probe.log > /dev/null 2>&1 &
sleep 1.5
run() {
  : > /tmp/probe.log
  sleep 0.2
  "$@"
  sleep 2
  python3 - "$label" <<'PY'
import json, sys
ev = [json.loads(l) for l in open("/tmp/probe.log")]
s = [e for e in ev if "dy" in e]
ends = [e for e in ev if e.get("end")]
if not s:
    print(f"{sys.argv[1]:<24} no events"); sys.exit()
span = s[-1]["t"] - s[0]["t"]
print(f"{sys.argv[1]:<24} events {len(s):>3}  total dy {sum(e['dy'] for e in s):7.1f}  "
      f"span {span:6.0f} ms  largest step {max(abs(e['dy']) for e in s):5.1f}  unit {s[0]['unit']}  "
      f"stops {len(ends)}")
PY
}
for mode in disabled enabled; do
  swaymsg "input type:pointer smooth_scroll $mode" > /dev/null
  label="finger, smooth $mode"; run ./vptr/vptr finger 20 8 10
  label="wheel x3, smooth $mode"; run ./vptr/vptr wheel 3 60
done
swaymsg '[title="scroll-probe"] scroll_native enable' > /dev/null
label="finger, scroll_native"; run ./vptr/vptr finger 20 8 10
