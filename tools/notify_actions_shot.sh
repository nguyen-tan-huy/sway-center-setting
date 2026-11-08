#!/bin/sh
# A notification with action buttons, in the popup and in the Quick Settings list:
#   tools/sandbox.sh --fx sh /home/repo/tools/notify_actions_shot.sh   -> tools/out/na-{popup,list}.png
cd /home/repo
python3 -c "from swayctl_center.pages import ui_state; ui_state.set(\"setup_done\", True)"
python3 -m swayctl_center daemon >/tmp/out/na-daemon.log 2>&1 &
sleep 2.5
python3 -m swayctl_center set notifications.enabled true >/dev/null 2>&1 || true
bin=/home/repo/swayctl-bar/target/release/swayctl-bar
$bin --config-dir "$HOME/.config/swayctl-center/generated/bar" 2>/tmp/out/na-bar.log &
sleep 2.5
notify-send -a Bluetooth -u critical -A yes=Pair -A cancel=Cancel "Pair with HUAWEI FreeClip?" "Make sure HUAWEI FreeClip shows this code:
346213" >/tmp/out/na-action.txt &
sleep 1.5
grim -g "1200,0 720x360" /tmp/out/na-popup.png
$bin quick >/dev/null 2>&1; sleep 1.5
grim -g "1000,0 920x700" /tmp/out/na-list.png
# click Pair in the list: the app gets "yes" and the card goes
swaymsg 'seat - cursor set 1646 340' >/dev/null; swaymsg 'seat - cursor press button1' >/dev/null
swaymsg 'seat - cursor release button1' >/dev/null; sleep 1.5
echo "answer: $(cat /tmp/out/na-action.txt)"
grim -g "1000,0 920x500" /tmp/out/na-after.png
