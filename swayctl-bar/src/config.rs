//! config.json written by swayctl-center (BarModule) next to style.css.

use serde::Deserialize;
use std::path::{Path, PathBuf};

#[derive(Deserialize, Clone, Debug)]
#[serde(default)]
pub struct Config {
    pub position: String,
    pub layer: String,
    pub height: i32,
    pub spacing: i32,
    /// top, right, bottom, left
    pub margins: [i32; 4],
    pub exclusive: bool,
    pub modules_left: Vec<String>,
    pub modules_center: Vec<String>,
    pub modules_right: Vec<String>,
    /// strftime-style, as GLib's DateTime::format takes it
    pub clock_format: String,
    pub clock_format_alt: String,
    /// shell command run by the "open settings" entries; {page} is replaced
    pub settings_command: String,
    pub notifications: Notifications,
    pub backdrop: Backdrop,
    pub launcher: Launcher,
}

/// The Spotlight-style launcher over elephant (`swayctl-bar launcher`).
#[derive(Deserialize, Clone, Debug, PartialEq)]
#[serde(default)]
pub struct Launcher {
    /// elephant providers searched with no prefix
    pub providers: Vec<String>,
    /// a first character that switches to one provider ("=" -> calc, ...)
    pub prefixes: Vec<Prefix>,
    pub max_results: i32,
}

#[derive(Deserialize, Clone, Debug, PartialEq)]
pub struct Prefix {
    pub prefix: String,
    pub provider: String,
    /// shown in the search field while the prefix is on
    pub label: String,
}

impl Default for Launcher {
    fn default() -> Self {
        let p = |prefix: &str, provider: &str, label: &str| Prefix {
            prefix: prefix.into(), provider: provider.into(), label: label.into() };
        Self {
            providers: vec!["desktopapplications".into(), "menus".into(), "calc".into()],
            prefixes: vec![p("=", "calc", "Calculator"), p("/", "files", "Files"), p("@", "websearch", "Web"),
                           p(".", "symbols", "Emoji"), p("$", "windows", "Windows"), p(">", "runner", "Run"),
                           p(";", "providerlist", "Providers")],
            max_results: 9,
        }
    }
}

/// What's behind the bar (the wallpaper), so each module picks the text
/// color that stands out on it (only with liquid glass).
#[derive(Deserialize, Clone, Debug, PartialEq, Default)]
#[serde(default)]
pub struct Backdrop {
    pub adaptive: bool,
    /// "" = no image, just `color`
    pub image: String,
    /// fill, fit, stretch, center, tile (as sway's `output bg`)
    pub mode: String,
    pub color: String,
    /// alpha of the smoked (light text) and milky (dark text) glass
    pub tint_dark: f32,
    pub tint_light: f32,
    /// liquid glass is on: pure ink + halo over clear capsules
    pub lens: bool,
    /// the capsules' white body alpha (effects.glass_opacity, as painted)
    pub lens_tint: f32,
    /// effects.glass_blur 0..1: frost smooths out the detail behind
    pub frost: f32,
}

/// The notification server (org.freedesktop.Notifications), replacing swaync.
#[derive(Deserialize, Clone, Debug, PartialEq)]
#[serde(default)]
pub struct Notifications {
    pub enabled: bool,
    /// left, center, right
    pub position_x: String,
    /// top, bottom
    pub position_y: String,
    /// connector name; empty = the focused monitor
    pub output: String,
    pub width: i32,
    /// seconds; 0 = until dismissed
    pub timeout: u32,
    pub timeout_low: u32,
    pub timeout_critical: u32,
    pub max_visible: usize,
    pub dnd_on_start: bool,
}

impl Default for Notifications {
    fn default() -> Self {
        Self {
            enabled: false,
            position_x: "right".into(),
            position_y: "top".into(),
            output: String::new(),
            width: 380,
            timeout: 8,
            timeout_low: 4,
            timeout_critical: 0,
            max_visible: 4,
            dnd_on_start: false,
        }
    }
}

impl Default for Config {
    fn default() -> Self {
        Self {
            position: "top".into(),
            layer: "top".into(),
            height: 34,
            spacing: 4,
            margins: [0; 4],
            exclusive: true,
            modules_left: vec!["workspaces".into(), "mode".into()],
            modules_center: vec!["clock".into()],
            modules_right: vec!["audio".into(), "network".into(), "battery".into()],
            clock_format: "%H:%M".into(),
            clock_format_alt: "%a %d %b  %H:%M".into(),
            settings_command: "swayctl-center ui --page {page}".into(),
            notifications: Notifications::default(),
            backdrop: Backdrop::default(),
            launcher: Launcher::default(),
        }
    }
}

pub fn dir_from_args(args: &[String]) -> PathBuf {
    if let Some(i) = args.iter().position(|a| a == "--config-dir") {
        if let Some(d) = args.get(i + 1) {
            return PathBuf::from(d);
        }
    }
    let base = std::env::var("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(std::env::var("HOME").unwrap_or_default()).join(".config"));
    base.join("swayctl-center/generated/swayctl-bar")
}

pub fn load(dir: &Path) -> Config {
    match std::fs::read_to_string(dir.join("config.json")) {
        Ok(text) => serde_json::from_str(&text).unwrap_or_else(|e| {
            eprintln!("swayctl-bar: bad config.json ({e}); using defaults");
            Config::default()
        }),
        Err(_) => Config::default(),
    }
}
