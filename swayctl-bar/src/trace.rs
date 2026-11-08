//! Timing for the paths that must never stutter (opening Quick Settings, the
//! notification list). Off unless SWAYCTL_BAR_TRACE is set; then each span
//! prints how long it took when it ends, e.g. `trace quick.open: 12.4 ms`.

use std::sync::OnceLock;
use std::time::Instant;

fn enabled() -> bool {
    static ON: OnceLock<bool> = OnceLock::new();
    *ON.get_or_init(|| std::env::var_os("SWAYCTL_BAR_TRACE").is_some())
}

pub struct Span(&'static str, Option<Instant>);

pub fn span(name: &'static str) -> Span {
    Span(name, enabled().then(Instant::now))
}

impl Drop for Span {
    fn drop(&mut self) {
        if let Some(t) = self.1 {
            eprintln!("trace {}: {:.1} ms", self.0, t.elapsed().as_secs_f64() * 1000.0);
        }
    }
}
