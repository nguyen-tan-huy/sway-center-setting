//! Services driven by command-line tools: volume (pactl, which also covers
//! PipeWire), brightness (brightnessctl) and do-not-disturb (swaync-client).
//! Volume follows `pactl subscribe`; the others change only through us or
//! keys that call `swayctl-bar osd ...`, so they are read on demand.

use crate::watch::Watch;
use gtk::glib;
use std::process::Command;
use std::rc::Rc;

fn output(args: &[&str]) -> Option<String> {
    let out = Command::new(args[0]).args(&args[1..]).output().ok()?;
    out.status.success().then(|| String::from_utf8_lossy(&out.stdout).into_owned())
}

pub fn spawn(args: &[&str]) {
    if let Err(e) = Command::new(args[0]).args(&args[1..]).spawn() {
        eprintln!("swayctl-bar: {}: {e}", args[0]);
    }
}

pub fn shell(cmd: &str) {
    spawn(&["sh", "-c", cmd]);
}

// ---- volume -----------------------------------------------------------------

#[derive(Clone, PartialEq, Default, Debug)]
pub struct Volume {
    pub available: bool,
    pub percent: u32,
    pub muted: bool,
}

#[derive(Clone, PartialEq, Debug)]
pub struct Sink {
    pub name: String,
    pub description: String,
    pub default: bool,
}

pub fn read_volume() -> Volume {
    let Some(v) = output(&["pactl", "get-sink-volume", "@DEFAULT_SINK@"]) else {
        return Volume::default();
    };
    // "Volume: front-left: 32768 /  50% / -18.06 dB,   front-right: ..."
    let percent = v
        .split('/')
        .nth(1)
        .and_then(|p| p.trim().trim_end_matches('%').parse().ok())
        .unwrap_or(0);
    let muted = output(&["pactl", "get-sink-mute", "@DEFAULT_SINK@"]).is_some_and(|m| m.contains("yes"));
    Volume { available: true, percent, muted }
}

pub fn volume() -> Rc<Watch<Volume>> {
    let w = Watch::new(read_volume());
    let w2 = w.clone();
    let (tx, rx) = async_channel::unbounded::<()>();
    std::thread::spawn(move || {
        use std::io::BufRead;
        use std::os::unix::process::CommandExt;
        let mut cmd = Command::new("pactl");
        cmd.arg("subscribe").stdout(std::process::Stdio::piped());
        // dies with the bar, even when the bar crashes: otherwise it outlives
        // it in the bar's unit and blocks the next start of that unit
        unsafe {
            cmd.pre_exec(|| {
                libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM);
                Ok(())
            });
        }
        let Ok(mut child) = cmd.spawn() else { return };
        let Some(out) = child.stdout.take() else { return };
        for line in std::io::BufReader::new(out).lines() {
            let Ok(line) = line else { break };
            // "Event 'change' on sink #56" / "... on server" (default sink switched)
            if (line.contains(" sink ") || line.contains(" server")) && tx.send_blocking(()).is_err() {
                break;
            }
        }
        let _ = child.kill();
        let _ = child.wait();
    });
    glib::spawn_future_local(async move {
        while rx.recv().await.is_ok() {
            w2.set(read_volume());
        }
    });
    w
}

pub fn set_volume(percent: u32) {
    let p = format!("{}%", percent.min(150));
    spawn(&["pactl", "set-sink-volume", "@DEFAULT_SINK@", &p]);
}

pub fn step_volume(delta: i32) {
    let p = format!("{}{}%", if delta >= 0 { "+" } else { "-" }, delta.unsigned_abs());
    let _ = Command::new("pactl").args(["set-sink-volume", "@DEFAULT_SINK@", &p]).status();
}

pub fn toggle_mute() {
    let _ = Command::new("pactl").args(["set-sink-mute", "@DEFAULT_SINK@", "toggle"]).status();
}

pub fn sinks() -> Vec<Sink> {
    let default = output(&["pactl", "get-default-sink"]).unwrap_or_default().trim().to_owned();
    let Some(json) = output(&["pactl", "--format=json", "list", "sinks"]) else { return vec![] };
    let Ok(serde_json::Value::Array(list)) = serde_json::from_str(&json) else { return vec![] };
    list.iter()
        .filter_map(|s| {
            let name = s["name"].as_str()?.to_owned();
            Some(Sink {
                description: s["description"].as_str().unwrap_or(&name).to_owned(),
                default: name == default,
                name,
            })
        })
        .collect()
}

pub fn set_default_sink(name: &str) {
    spawn(&["pactl", "set-default-sink", name]);
}

// ---- brightness ----------------------------------------------------------------

/// Percent of the first backlight, None when there is none (desktop monitor).
pub fn brightness() -> Option<u32> {
    // "intel_backlight,backlight,12000,50%,24000"
    let info = output(&["brightnessctl", "-m", "-c", "backlight", "info"])?;
    info.split(',').nth(3)?.trim().trim_end_matches('%').parse().ok()
}

pub fn set_brightness(percent: u32) {
    let p = format!("{}%", percent.clamp(1, 100));
    spawn(&["brightnessctl", "-q", "-c", "backlight", "set", &p]);
}

pub fn step_brightness(delta: i32) {
    let p = format!("{}%{}", delta.unsigned_abs(), if delta >= 0 { "+" } else { "-" });
    let _ = Command::new("brightnessctl").args(["-q", "-c", "backlight", "set", &p]).status();
}

// ---- do not disturb ----------------------------------------------------------------

pub fn dnd() -> Option<bool> {
    output(&["swaync-client", "-D", "-sw"]).map(|s| s.trim() == "true")
}

pub fn set_dnd(on: bool) {
    spawn(&["swaync-client", if on { "-dn" } else { "-df" }, "-sw"]);
}
