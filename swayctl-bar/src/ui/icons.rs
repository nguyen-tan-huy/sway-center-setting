//! Symbolic icon names for the current state of each service: the iPadOS-style set drawn for the
//! bar (ipad_icons.rs, written out as a private icon path at start) or the system theme's.

use crate::services::dbus::{Battery, Network};
use crate::services::procs::Volume;
use std::sync::atomic::{AtomicBool, Ordering};

static IPAD: AtomicBool = AtomicBool::new(true);

/// `bar.icon_style`: "ipados" (our set) or anything else (the system's).
pub fn set_style(style: &str) {
    IPAD.store(style == "ipados", Ordering::Relaxed);
}

fn ipad() -> bool {
    IPAD.load(Ordering::Relaxed)
}

/// Make the embedded icons known to GTK: written under a private directory (a `hicolor/scalable/status`
/// tree, which every icon theme falls back to) that is added to the icon search path. Once.
pub fn install() {
    use std::sync::Once;
    static ONCE: Once = Once::new();
    ONCE.call_once(|| {
        let base = std::path::PathBuf::from(std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".into()))
            .join(format!("swayctl-bar-icons-{}", env!("CARGO_PKG_VERSION")));
        let dir = base.join("hicolor/scalable/status");
        if std::fs::create_dir_all(&dir).is_err() {
            return;
        }
        for (name, svg) in crate::ui::ipad_icons::ICONS {
            let path = dir.join(format!("{name}.svg"));
            if std::fs::read_to_string(&path).map(|old| old != *svg).unwrap_or(true) {
                let _ = std::fs::write(&path, svg);
            }
        }
        if let Some(display) = gtk::gdk::Display::default() {
            gtk::IconTheme::for_display(&display).add_search_path(&base);
        }
    });
}

pub fn bluetooth() -> &'static str {
    if ipad() { "swayctl-bluetooth-symbolic" } else { "bluetooth-active-symbolic" }
}

pub fn volume(v: &Volume) -> &'static str {
    if ipad() {
        return if !v.available || v.muted {
            "swayctl-volume-muted-symbolic"
        } else if v.percent == 0 {
            "swayctl-volume-0-symbolic"
        } else if v.percent < 34 {
            "swayctl-volume-1-symbolic"
        } else if v.percent < 67 {
            "swayctl-volume-2-symbolic"
        } else {
            "swayctl-volume-3-symbolic"
        };
    }
    if !v.available {
        "audio-volume-muted-symbolic"
    } else if v.muted || v.percent == 0 {
        "audio-volume-muted-symbolic"
    } else if v.percent < 34 {
        "audio-volume-low-symbolic"
    } else if v.percent < 67 {
        "audio-volume-medium-symbolic"
    } else {
        "audio-volume-high-symbolic"
    }
}

pub fn network(n: &Network) -> &'static str {
    if ipad() {
        match n.kind.as_str() {
            "wifi" => return match n.strength {
                0..=24 => "swayctl-wifi-1-symbolic",
                25..=49 => "swayctl-wifi-2-symbolic",
                _ => "swayctl-wifi-3-symbolic",
            },
            "ethernet" => return "swayctl-ethernet-symbolic",
            "vpn" => {} // no drawing for it: the system's
            _ => return "swayctl-wifi-off-symbolic",
        }
    }
    match n.kind.as_str() {
        "wifi" => match n.strength {
            0..=24 => "network-wireless-signal-weak-symbolic",
            25..=49 => "network-wireless-signal-ok-symbolic",
            50..=74 => "network-wireless-signal-good-symbolic",
            _ => "network-wireless-signal-excellent-symbolic",
        },
        "ethernet" => "network-wired-symbolic",
        "vpn" => "network-vpn-symbolic",
        _ if !n.available => "network-offline-symbolic",
        _ if !n.wifi_enabled => "network-wireless-disabled-symbolic",
        _ => "network-wireless-offline-symbolic",
    }
}

pub fn wifi_strength(s: u8) -> &'static str {
    network(&Network { kind: "wifi".into(), strength: s, available: true, ..Default::default() })
}

pub fn battery(b: &Battery) -> String {
    let level = ((b.percent / 10.0).round() as u32 * 10).min(100);
    if ipad() {
        return format!("swayctl-battery-{level}{}-symbolic", if b.full || b.charging { "-charging" } else { "" });
    }
    let mut name = format!("battery-level-{level}");
    if b.full {
        name.push_str("-charged");
    } else if b.charging {
        name.push_str("-charging");
    }
    name + "-symbolic"
}

pub fn brightness(_p: u32) -> &'static str {
    if ipad() { "swayctl-sun-symbolic" } else { "display-brightness-symbolic" }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_name_the_ipad_set_asks_for_is_drawn() {
        let have: std::collections::HashSet<&str> = crate::ui::ipad_icons::ICONS.iter().map(|(n, _)| *n).collect();
        set_style("ipados");
        let mut asked = vec![bluetooth().to_string(), brightness(50).to_string()];
        for (muted, available, percent) in [(true, true, 50), (false, false, 50), (false, true, 0), (false, true, 20), (false, true, 50), (false, true, 90)] {
            asked.push(volume(&Volume { available, muted, percent, ..Default::default() }).to_string());
        }
        for kind in ["wifi", "ethernet", "", "other"] {
            for strength in [0u8, 30, 60, 100] {
                asked.push(network(&Network { kind: kind.into(), strength, available: true, wifi_enabled: true, ..Default::default() }).to_string());
            }
        }
        for percent in [0.0, 4.0, 5.0, 33.0, 50.0, 99.0, 100.0] {
            for (charging, full) in [(false, false), (true, false), (false, true)] {
                asked.push(battery(&Battery { percent, charging, full, ..Default::default() }));
            }
        }
        for name in asked {
            assert!(have.contains(name.as_str()) || !name.starts_with("swayctl-"), "no drawing for {name}");
        }
    }

    #[test]
    fn the_system_set_is_still_there() {
        set_style("system");
        assert_eq!(bluetooth(), "bluetooth-active-symbolic");
        assert_eq!(battery(&Battery { percent: 50.0, ..Default::default() }), "battery-level-50-symbolic");
        set_style("ipados");
    }
}
