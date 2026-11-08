//! Popups that the compositor opens and closes itself (swayctl-fx's `layer-animate`): the bar draws
//! the surface once, at its final size, and the compositor's spring scales, moves and fades it.
//! Nothing runs in this process while it moves, so the motion cannot be late because the bar is
//! busy (a client redrawing a scaled card cost 3-12 ms of a 8.3 ms frame at 120 Hz).
//!
//! Without the fork's `layer-animate` a popup simply appears and goes: this bar has no animation of its own.

use crate::services::sway;
use std::cell::Cell;
use std::time::{Duration, Instant};

/// How a popup looks while it moves. Pace and curve are not here: they are the compositor's own
/// animation settings (`animation_curve`, `animation_spring`, `animation_duration_ms`), the ones
/// windows follow, and `animations popups enable|disable` switches them.
#[derive(Clone, Copy)]
pub struct Motion {
    /// pivot: px from the surface's right edge (None = centred) and from its top edge
    pub right: Option<i32>,
    pub top: i32,
    /// start size (0 = out of a point), px above its place at the start, stretch with speed,
    /// and how fast it fades in (opaque at 1/fade)
    pub min_scale: f64,
    pub drop: f64,
    pub stretch: f64,
    pub fade: f64,
}

impl Motion {
    fn rule(&self) -> String {
        format!("animate {} {} {} {} {} {}", self.right.unwrap_or(-1), self.top, self.min_scale, self.drop,
                self.stretch, self.fade)
    }
}

/// Does the compositor do this? Asked of sway at most every 30 s.
pub fn supported() -> bool {
    thread_local! {
        static KNOWN: Cell<Option<(Instant, bool)>> = const { Cell::new(None) };
    }
    if let Some((at, yes)) = KNOWN.with(|k| k.get()) {
        if at.elapsed() < Duration::from_secs(30) {
            return yes;
        }
    }
    let yes = sway::request(7 /* GET_VERSION */, "")
        .ok()
        .and_then(|v| v.get("swayctl_features")?.as_array().cloned())
        .is_some_and(|f| f.iter().any(|x| x.as_str() == Some("layer-animate")));
    KNOWN.with(|k| k.set(Some((Instant::now(), yes))));
    yes
}

/// Tell the compositor how `namespace` looks while it moves (before its surface is shown). The look
/// belongs to the popup that owns the geometry, so it is sent from here, not configured.
pub fn set(namespace: &str, motion: &Motion) {
    sway::command(&format!("layer_effects \"{namespace}\" \"{}\"", motion.rule()));
}

/// Spring it open again (it was on its way out).
pub fn open(namespace: &str) {
    sway::command(&format!("layer_animate {namespace} open"));
}

/// Start the motion toward closed. Returns how long until it is at rest (the window may go then),
/// or None when nothing moves (animations are off): close at once. The compositor says how long
/// it takes, since the pace is its own setting.
pub fn close(namespace: &str) -> Option<Duration> {
    let reply = sway::request(sway::RUN_COMMAND, &format!("layer_animate {namespace} close")).ok()?;
    let first = reply.get(0)?;
    if !first.get("success")?.as_bool()? {
        return None;
    }
    let ms = first.get("error").and_then(|e| e.as_str()).and_then(|e| e.trim().parse::<u64>().ok())
        .unwrap_or(400);
    Some(Duration::from_millis(ms + 50))
}
