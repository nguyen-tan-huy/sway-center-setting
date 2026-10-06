//! Symbolic icon names (Adwaita) for the current state of each service.

use crate::services::dbus::{Battery, Network};
use crate::services::procs::Volume;

pub fn volume(v: &Volume) -> &'static str {
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
    let mut name = format!("battery-level-{level}");
    if b.full {
        name.push_str("-charged");
    } else if b.charging {
        name.push_str("-charging");
    }
    name + "-symbolic"
}

pub fn brightness(_p: u32) -> &'static str {
    "display-brightness-symbolic"
}
