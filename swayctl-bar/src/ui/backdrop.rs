//! What's behind the bar: the wallpaper (the bar keeps windows off its strip).
//! A small luminance grid of it, laid out on the monitor like sway's
//! `output bg <image> <mode>`, tells each module whether light or dark text
//! stands out over the glass there.

use crate::config::Backdrop;
use gtk::gdk_pixbuf::Pixbuf;
use gtk::prelude::*;
use gtk::gdk;

const GW: usize = 96;
const GH: usize = 54;

pub struct Grid {
    lum: Vec<f32>,   // gw x gh, relative luminance 0..1 (mean of the cell)
    lmin: Vec<f32>,  // gw x gh, darkest source pixel in the cell (true floor)
    lmax: Vec<f32>,  // gw x gh, brightest source pixel in the cell (true peak)
    gw: usize,
    gh: usize,
    width: f32,    // monitor, logical px
    height: f32,
    /// covers one surface (a probe), not the monitor: origins don't apply
    local: bool,
}

thread_local! {
    /// The bar's current backdrop settings (tints, on/off), for the popups.
    static CURRENT: std::cell::RefCell<Backdrop> = std::cell::RefCell::new(Backdrop::default());
}

pub fn set_current(b: &Backdrop) {
    CURRENT.with(|c| *c.borrow_mut() = b.clone());
}

pub fn current() -> Backdrop {
    CURRENT.with(|c| c.borrow().clone())
}

fn srgb_to_linear(c: f32) -> f32 {
    if c <= 0.04045 { c / 12.92 } else { ((c + 0.055) / 1.055).powf(2.4) }
}

fn luminance(r: u8, g: u8, b: u8) -> f32 {
    let (r, g, b) = (srgb_to_linear(r as f32 / 255.0), srgb_to_linear(g as f32 / 255.0), srgb_to_linear(b as f32 / 255.0));
    0.2126 * r + 0.7152 * g + 0.0722 * b
}

fn parse_color(s: &str) -> f32 {
    gdk::RGBA::parse(s).map(|c| luminance((c.red() * 255.0) as u8, (c.green() * 255.0) as u8, (c.blue() * 255.0) as u8))
        .unwrap_or(0.0)
}

impl Grid {
    /// The grid for a monitor of `width` x `height` (logical px); None when
    /// adaptive text is off.
    pub fn new(b: &Backdrop, width: i32, height: i32) -> Option<Grid> {
        if !b.adaptive || width <= 0 || height <= 0 {
            return None;
        }
        let (w, h) = (width as f32, height as f32);
        let fill = parse_color(&b.color);
        let mut lum = vec![fill; GW * GH];
        let mut lmin = vec![fill; GW * GH];
        let mut lmax = vec![fill; GW * GH];
        // original size for the layout, a small copy for the pixels
        let image = (!b.image.is_empty()).then(|| {
            let (_, iw, ih) = Pixbuf::file_info(&b.image)?;
            let small = Pixbuf::from_file_at_scale(&b.image, 320, 320, true).ok()?;
            Some((iw as f32, ih as f32, small))
        }).flatten();
        if let Some((iw, ih, px)) = image {
            let (pw, ph) = (px.width() as f32, px.height() as f32);
            let (stride, n) = (px.rowstride() as usize, px.n_channels() as usize);
            let bytes = px.read_pixel_bytes();
            let data: &[u8] = &bytes;
            for gy in 0..GH {
                for gx in 0..GW {
                    // 2x2 samples per cell: mean for the side pick, min/max
                    // so the envelope still catches detail the mean would hide
                    let mut sum = 0.0f32;
                    let (mut lo, mut hi) = (2.0f32, -1.0f32);
                    let mut got = 0u32;
                    for oy in [0.25f32, 0.75] {
                        for ox in [0.25f32, 0.75] {
                            let (mx, my) = ((gx as f32 + ox) * w / GW as f32,
                                            (gy as f32 + oy) * h / GH as f32);
                            // monitor point -> point in the original image (None: not covered)
                            let at = match b.mode.as_str() {
                                "stretch" => Some((mx * iw / w, my * ih / h)),
                                "fit" => {
                                    let s = (w / iw).min(h / ih);
                                    Some(((mx - (w - iw * s) / 2.0) / s, (my - (h - ih * s) / 2.0) / s))
                                }
                                "center" => Some((mx - (w - iw) / 2.0, my - (h - ih) / 2.0)),
                                "tile" => Some((mx % iw, my % ih)),
                                _ => {
                                    let s = (w / iw).max(h / ih); // fill
                                    Some(((mx - (w - iw * s) / 2.0) / s, (my - (h - ih * s) / 2.0) / s))
                                }
                            };
                            let Some((ix, iy)) = at else { continue };
                            if ix < 0.0 || iy < 0.0 || ix >= iw || iy >= ih {
                                continue; // the background color shows there
                            }
                            let (sx, sy) = (((ix / iw) * pw) as usize, ((iy / ih) * ph) as usize);
                            let o = sy.min(px.height() as usize - 1) * stride + sx.min(px.width() as usize - 1) * n;
                            if o + 2 < data.len() {
                                let y = luminance(data[o], data[o + 1], data[o + 2]);
                                sum += y;
                                lo = lo.min(y);
                                hi = hi.max(y);
                                got += 1;
                            }
                        }
                    }
                    if got > 0 {
                        lum[gy * GW + gx] = sum / got as f32;
                        lmin[gy * GW + gx] = lo;
                        lmax[gy * GW + gx] = hi;
                    }
                }
            }
        }
        Some(Grid { lum, lmin, lmax, gw: GW, gh: GH, width: w, height: h, local: false })
    }

    /// What's on a monitor right now (taken just before a popup shows, so
    /// it's what will be behind it): the compositor's own backdrop sample
    /// over IPC, falling back to a grim screenshot on stock sway.
    pub fn capture(monitor: &gdk::Monitor) -> Option<Grid> {
        if !current().adaptive {
            return None;
        }
        let connector = monitor.connector()?;
        let geo = monitor.geometry();
        if let Some(g) = Self::capture_ipc(&connector, geo.width(), geo.height()) {
            return Some(g);
        }
        Self::capture_grim(&connector, geo.width(), geo.height())
    }

    /// What is *behind* one of our layer surfaces right now (swayctl fork:
    /// the glass probe, grabbed as the compositor draws the glass, so the
    /// surface's own text isn't in it). Each call re-arms the probe, so
    /// polling follows what scrolls underneath. None: not drawn since the
    /// last call, no glass on the surface, or stock sway.
    pub fn probe(monitor: &gdk::Monitor, namespace: &str, size: (i32, i32)) -> Option<Grid> {
        if !current().adaptive {
            return None;
        }
        let connector = monitor.connector()?;
        // ~1 cell per 6 px of the surface (it's small: a bar, a popup)
        let payload = format!("{{\"output\":\"{connector}\",\"namespace\":\"{namespace}\",\"cols\":{},\"rows\":{}}}",
                              (size.0 / 6).clamp(4, 320), (size.1 / 6).clamp(2, 160));
        let v = crate::services::sway::request(crate::services::sway::GET_BACKDROP, &payload).ok()?;
        if v.get("success").and_then(|s| s.as_bool()) != Some(true) {
            return None;
        }
        let (w, h) = (v.get("w")?.as_f64()? as f32, v.get("h")?.as_f64()? as f32);
        let (gw, gh) = (v.get("cols")?.as_u64()? as usize, v.get("rows")?.as_u64()? as usize);
        let cells = v.get("cells")?.as_array()?;
        if gw == 0 || gh == 0 || cells.len() != gw * gh * 3 || w < 1.0 || h < 1.0 {
            return None;
        }
        let mut lum = Vec::with_capacity(gw * gh);
        for c in cells.chunks_exact(3) {
            lum.push(luminance(c[0].as_u64()? as u8, c[1].as_u64()? as u8, c[2].as_u64()? as u8));
        }
        let env = |key: &str| -> Option<Vec<f32>> {
            let a = v.get(key)?.as_array()?;
            if a.len() != gw * gh { return None; }
            a.iter().map(|n| n.as_u64().map(|y| y.min(255) as f32 / 255.0)).collect()
        };
        let lmin = env("lmin")?;
        let lmax = env("lmax")?;
        Some(Grid { lum, lmin, lmax, gw, gh, width: w, height: h, local: true })
    }

    /// Where a surface at `origin` on the monitor sits in this grid.
    pub fn origin(&self, origin: (f32, f32)) -> (f32, f32) {
        if self.local { (0.0, 0.0) } else { origin }
    }

    /// The compositor's own sample of `connector` (swayctl fork IPC): a
    /// GW x GH RGB grid of the last frame, as luminance. None when the
    /// compositor doesn't know the type (stock sway) or the reply is off-size.
    fn capture_ipc(connector: &str, width: i32, height: i32) -> Option<Grid> {
        let payload = format!("{{\"output\":\"{connector}\",\"cols\":{GW},\"rows\":{GH}}}");
        let v = crate::services::sway::request(crate::services::sway::GET_BACKDROP, &payload).ok()?;
        if v.get("success").and_then(|s| s.as_bool()) != Some(true) {
            return None;
        }
        let cells = v.get("cells")?.as_array()?;
        if cells.len() != GW * GH * 3 {
            return None;
        }
        let mut lum = Vec::with_capacity(GW * GH);
        for c in cells.chunks_exact(3) {
            lum.push(luminance(c[0].as_u64()? as u8, c[1].as_u64()? as u8, c[2].as_u64()? as u8));
        }
        // the per-cell envelope (older compositors don't send it: the mean
        // stands in for both, the pre-envelope behavior)
        let env = |key: &str| -> Option<Vec<f32>> {
            let a = v.get(key)?.as_array()?;
            if a.len() != GW * GH { return None; }
            a.iter().map(|n| n.as_u64().map(|y| y.min(255) as f32 / 255.0)).collect()
        };
        let (lmin, lmax) = match (env("lmin"), env("lmax")) {
            (Some(a), Some(b)) => (a, b),
            _ => (lum.clone(), lum.clone()),
        };
        Some(Grid { lum, lmin, lmax, gw: GW, gh: GH, width: width as f32, height: height as f32, local: false })
    }

    /// Stock-sway fallback: a full screenshot from grim, pooled into the same
    /// GW x GH grid with the true per-cell min/max (as the fork's IPC gives).
    fn capture_grim(connector: &str, width: i32, height: i32) -> Option<Grid> {
        let out = std::process::Command::new("grim")
            .args(["-o", connector, "-t", "ppm", "-"])
            .stderr(std::process::Stdio::null()).output().ok()?;
        if !out.status.success() {
            return None;
        }
        // binary PPM: "P6\n<w> <h>\n<max>\n" then RGB bytes
        let data = &out.stdout;
        let mut fields = Vec::new();
        let mut i = 0;
        while fields.len() < 4 && i < data.len() {
            while i < data.len() && data[i].is_ascii_whitespace() { i += 1; }
            let start = i;
            while i < data.len() && !data[i].is_ascii_whitespace() { i += 1; }
            fields.push(String::from_utf8_lossy(&data[start..i]).into_owned());
        }
        i += 1; // the single whitespace after maxval
        if fields.len() < 4 || fields[0] != "P6" {
            return None;
        }
        let (pw, ph): (usize, usize) = (fields[1].parse().ok()?, fields[2].parse().ok()?);
        if pw == 0 || ph == 0 {
            return None;
        }
        let px = data.get(i..i + pw * ph * 3)?;
        let mut lum = vec![0.0f32; GW * GH];
        let mut lmin = vec![1.0f32; GW * GH];
        let mut lmax = vec![0.0f32; GW * GH];
        let mut cnt = vec![0u32; GW * GH];
        for (p, c) in px.chunks_exact(3).enumerate() {
            let k = (p / pw) * GH / ph.max(1) * GW + (p % pw) * GW / pw.max(1);
            let y = luminance(c[0], c[1], c[2]);
            lum[k] += y;
            lmin[k] = lmin[k].min(y);
            lmax[k] = lmax[k].max(y);
            cnt[k] += 1;
        }
        for k in 0..GW * GH {
            if cnt[k] > 0 {
                lum[k] /= cnt[k] as f32;
            }
        }
        Some(Grid { lum, lmin, lmax, gw: GW, gh: GH, width: width as f32, height: height as f32, local: false })
    }

    /// (mean, darkest, brightest) luminance under a rectangle of the monitor.
    /// The floor/peak come from the per-cell envelope: a cell's average can
    /// hide a bright glyph or a dark hole the text would sit on.
    pub fn stats(&self, x: f32, y: f32, rw: f32, rh: f32) -> (f32, f32, f32) {
        let (gw, gh) = (self.gw, self.gh);
        let cx = |v: f32| ((v / self.width * gw as f32).floor().max(0.0) as usize).min(gw - 1);
        let cy = |v: f32| ((v / self.height * gh as f32).floor().max(0.0) as usize).min(gh - 1);
        let (mut sum, mut n, mut lo, mut hi) = (0.0, 0.0, 1.0f32, 0.0f32);
        for gy in cy(y)..=cy(y + rh) {
            for gx in cx(x)..=cx(x + rw) {
                let k = gy * gw + gx;
                sum += self.lum[k];
                n += 1.0;
                lo = lo.min(self.lmin[k]);
                hi = hi.max(self.lmax[k]);
            }
        }
        if n > 0.0 { (sum / n, lo, hi) } else { (0.0, 0.0, 0.0) }
    }

    /// Mean luminance under a rectangle of the monitor (logical px).
    #[allow(dead_code)]
    pub fn mean(&self, x: f32, y: f32, rw: f32, rh: f32) -> f32 {
        let (gw, gh) = (self.gw, self.gh);
        let cx = |v: f32| ((v / self.width * gw as f32).floor().max(0.0) as usize).min(gw - 1);
        let cy = |v: f32| ((v / self.height * gh as f32).floor().max(0.0) as usize).min(gh - 1);
        let (x0, x1, y0, y1) = (cx(x), cx(x + rw), cy(y), cy(y + rh));
        let (mut sum, mut count) = (0.0, 0.0);
        for gy in y0..=y1 {
            for gx in x0..=x1 {
                sum += self.lum[gy * self.gw + gx];
                count += 1.0;
            }
        }
        if count > 0.0 { sum / count } else { 0.0 }
    }
}

/// Over a wallpaper of luminance `l`: is milky glass with dark text (#1d1d1f)
/// easier to read than smoked glass with light text (#f5f5f7)? Each tint
/// mixes into what's behind before the text sees it.
#[cfg(test)]
pub fn wants_dark_text(l: f32, tint_dark: f32, tint_light: f32) -> bool {
    const SMOKE: f32 = 0.0116; // #1c1c1e
    const MILK: f32 = 0.913;   // #f5f5f7
    let under_light_text = l * (1.0 - tint_dark) + SMOKE * tint_dark;
    let under_dark_text = l * (1.0 - tint_light) + MILK * tint_light;
    let light = (0.913 + 0.05) / (under_light_text + 0.05);
    let dark = (under_dark_text + 0.05) / (0.012 + 0.05);
    dark > light
}

/// (dark text?, tint step 0-10): the text by the mean, and glass thick enough
/// that it reads (4.5:1) even over the hardest pixel behind the pane — any
/// color, any detail, because `lo`/`hi` are the true envelope (min/max), not
/// cell averages. The tint-N gradient's bottom is alpha x 0.9, so the needed
/// alpha is divided by 0.9 before rounding up to a step.
#[cfg(test)]
pub fn choose(stats: (f32, f32, f32), tint_dark: f32, tint_light: f32) -> (bool, u32) {
    choose_side(stats, wants_dark_text(stats.0, tint_dark, tint_light), tint_dark, tint_light)
}

/// The tint step that keeps `dark` (the chosen side) at 4.5:1 over the
/// hardest pixel behind the pane.
fn choose_side(stats: (f32, f32, f32), dark: bool, tint_dark: f32, tint_light: f32) -> (bool, u32) {
    const SMOKE: f32 = 0.0116;
    const MILK: f32 = 0.913;
    let (_, lo, hi) = stats;
    let tint = if dark {
        // milky: lift the darkest pixel to >= 0.229
        tint_light.max((0.229 - lo) / (MILK - lo).max(1e-3) / 0.9)
    } else {
        // smoked: bring the brightest pixel down to <= 0.164
        tint_dark.max((hi - 0.164) / (hi - SMOKE).max(1e-3) / 0.9)
    };
    (dark, ((tint * 10.0 + 0.999) as i32).clamp(0, 10) as u32)
}

/// The text side the way tools/liquid-demo.html settled it: pure dark or
/// pure light ink only (a grey in between reads on neither side), with the
/// cut above the 0.179 contrast midpoint — over busy mid-tones light ink with
/// a dark halo reads better — and a hysteresis band so a pane near the cut
/// doesn't flip back and forth on every retag. `was_dark`: the pane's current
/// side (None when untagged).
pub fn ink_dark(mean: f32, was_dark: Option<bool>) -> bool {
    match was_dark {
        Some(true) => mean > 0.255,
        Some(false) => mean > 0.32,
        None => mean > 0.287,
    }
}

/// Halo step 0-4 under the text: stronger the nearer the mean sits to the
/// cut (neither ink stands out much there) and the busier the backdrop (the
/// envelope spread: detail running through the glyphs).
pub fn halo(stats: (f32, f32, f32), frost: f32) -> u32 {
    let (mean, lo, hi) = stats;
    let near = 1.0 - (((mean + 0.05) / 0.337).ln().abs() / 1.2).min(1.0);
    // frost blurs the detail away: less of the spread reaches the glyphs
    let spread = (hi - lo).max(0.0) * (1.0 - 0.7 * frost.clamp(0.0, 1.0));
    let h = (0.25 + near * 0.6 + spread * 0.75).min(1.0);
    (h * 4.0).round() as u32
}

/// What the text sees through a capsule whose white body has alpha `tint`
/// (the demo: L * (1 - t) + t), for the mean and the envelope alike.
pub fn through_glass(stats: (f32, f32, f32), tint: f32) -> (f32, f32, f32) {
    let t = tint.clamp(0.0, 1.0);
    let f = |l: f32| l * (1.0 - t) + t;
    (f(stats.0), f(stats.1), f(stats.2))
}

/// (dark text?, tint step, halo step) for a pane over `stats`, keeping its
/// side when it's in the hysteresis band. With liquid glass the settings'
/// body tint and frost go in (the demo's math); the tint step still covers
/// the plain-milk look when glass is off.
pub fn choose_ink(stats: (f32, f32, f32), was_dark: Option<bool>, b: &Backdrop) -> (bool, u32, u32) {
    let seen = if b.lens { through_glass(stats, b.lens_tint) } else { stats };
    let dark = ink_dark(seen.0, was_dark);
    let (_, step) = choose_side(stats, dark, b.tint_dark, b.tint_light);
    (dark, step, halo(seen, if b.lens { b.frost } else { 0.0 }))
}

fn was_dark(w: &gtk::Widget) -> Option<bool> {
    if w.has_css_class("on-light") {
        Some(true)
    } else if w.has_css_class("on-dark") {
        Some(false)
    } else {
        None
    }
}

fn tag(w: &gtk::Widget, dark: bool, step: u32, halo: u32) {
    for c in w.css_classes() {
        if c.starts_with("tint-") || c.starts_with("halo-") {
            w.remove_css_class(&c);
        }
    }
    w.remove_css_class(if dark { "on-dark" } else { "on-light" });
    w.add_css_class(if dark { "on-light" } else { "on-dark" });
    w.add_css_class(&format!("tint-{step}"));
    w.add_css_class(&format!("halo-{halo}"));
}

/// The compositor inks the text itself (swayctl-fx "glass-ink", the bar's
/// `glass_text auto`) and the glass is on: draw text in the key colour
/// (`.ink-key`, see swayctl-center's adaptive CSS) and ask nothing - no
/// probe, no capture, no tagging. Asked of sway at most every 30 s.
pub fn compositor_ink() -> bool {
    use std::cell::Cell;
    use std::time::{Duration, Instant};
    thread_local! {
        static KNOWN: Cell<Option<(Instant, bool)>> = const { Cell::new(None) };
    }
    if !current().lens {
        return false;
    }
    if let Some((at, ink)) = KNOWN.with(|k| k.get()) {
        if at.elapsed() < Duration::from_secs(30) {
            return ink;
        }
    }
    let ink = crate::services::sway::request(7 /* GET_VERSION */, "")
        .ok()
        .and_then(|v| v.get("swayctl_features")?.as_array().cloned())
        .is_some_and(|f| f.iter().any(|x| x.as_str() == Some("glass-ink")));
    KNOWN.with(|k| k.set(Some((Instant::now(), ink))));
    ink
}

/// Key ink on (`compositor_ink`): mark the window; any adaptive tags go.
pub fn set_key_ink(win: &impl IsA<gtk::Widget>, on: bool) {
    let win = win.as_ref();
    if !on {
        win.remove_css_class("ink-key");
        return;
    }
    if win.has_css_class("ink-key") {
        return;
    }
    win.add_css_class("ink-key");
    // tags from before (adaptive ink) would keep their smoke and halos
    let mut stack = vec![win.clone()];
    while let Some(w) = stack.pop() {
        for c in w.css_classes() {
            if c == "on-dark" || c == "on-light" || c.starts_with("tint-") || c.starts_with("halo-") {
                w.remove_css_class(&c);
            }
        }
        let mut child = w.first_child();
        while let Some(ch) = child {
            child = ch.next_sibling();
            stack.push(ch);
        }
    }
}

/// Tag each module of a bar window `on-light` / `on-dark` by what's behind it.
/// `origin` is the window's top left on its monitor.
pub fn tag_modules(win: &gtk::ApplicationWindow, grid: &Grid, origin: (f32, f32), backdrop: &Backdrop) {
    let mut child = win.first_child();
    let mut stack = Vec::new();
    while let Some(w) = child {
        if w.has_css_class("module") {
            if let Some(b) = w.compute_bounds(win) {
                let o = grid.origin(origin);
                let st = grid.stats(o.0 + b.x(), o.1 + b.y(), b.width(), b.height());
                let (dark, step, halo) = choose_ink(st, was_dark(&w), backdrop);
                tag(&w, dark, step, halo);
            }
        } else if let Some(first) = w.first_child() {
            stack.push(first);
        }
        child = w.next_sibling().or_else(|| stack.pop());
    }
}

/// Where a layer surface (by namespace) is on its monitor, from sway.
pub fn layer_origin(monitor: &gdk::Monitor, namespace: &str) -> Option<(f32, f32)> {
    let connector = monitor.connector()?;
    let outputs = crate::services::sway::request(3 /* GET_OUTPUTS */, "").ok()?;
    let out = outputs.as_array()?.iter().find(|o| o["name"] == connector.as_str())?;
    let l = out["layer_shell_surfaces"].as_array()?.iter().find(|l| l["namespace"] == namespace)?;
    Some((l["extent"]["x"].as_f64()? as f32, l["extent"]["y"].as_f64()? as f32))
}

/// A pane of glass in a popup: tagged as a whole (its contents follow).
fn is_pane(w: &gtk::Widget) -> bool {
    const PANES: [&str; 9] = ["tile", "slider-row", "media", "notification-card", "calendar-panel",
                              "circular", "pane", "notification-action", "osd"];
    if PANES.iter().any(|c| w.has_css_class(c)) || w.css_name() == "headerbar" {
        return true;
    }
    // sub-page rows: each is its own pill
    w.css_name() == "row" && w.parent().is_some_and(|p| p.has_css_class("boxed-list"))
}

/// Tag every pane of glass under `root` (in `win`, at `origin` on the
/// monitor) light or dark by what's behind it.
pub fn tag_panes(root: &gtk::Widget, win: &impl IsA<gtk::Widget>, grid: &Grid, origin: (f32, f32)) {
    let b = current();
    let mut stack = vec![root.clone()];
    while let Some(w) = stack.pop() {
        if is_pane(&w) {
            if let Some(r) = w.compute_bounds(win) {
                let o = grid.origin(origin);
                let st = grid.stats(o.0 + r.x(), o.1 + r.y(), r.width(), r.height());
                let (dark, step, halo) = choose_ink(st, was_dark(&w), &b);
                tag(&w, dark, step, halo);
            }
            continue;
        }
        let mut c = w.first_child();
        while let Some(ch) = c {
            c = ch.next_sibling();
            stack.push(ch);
        }
    }
}

/// The monitor of the focused workspace (where sway puts a popup with no output set).
pub fn focused_monitor() -> Option<gdk::Monitor> {
    let ws = crate::services::sway::request(crate::services::sway::GET_WORKSPACES, "").ok()?;
    let name = ws.as_array()?.iter().find(|w| w["focused"] == true)?["output"].as_str()?.to_owned();
    let monitors = gdk::Display::default()?.monitors();
    (0..monitors.n_items())
        .filter_map(|i| monitors.item(i).and_downcast::<gdk::Monitor>())
        .find(|m| m.connector().as_deref() == Some(name.as_str()))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The contrast the chosen side must clear, in CSS reality: the tint-N
    /// gradient's weakest row is alpha x 0.9, over the region's true floor/peak.
    fn worst_contrast(dark: bool, step: u32, lo: f32, hi: f32) -> f32 {
        let a = 0.9 * step as f32 / 10.0;
        if dark {
            let under = a * 0.913 + (1.0 - a) * lo;
            (under + 0.05) / (0.012 + 0.05)
        } else {
            let under = a * 0.0116 + (1.0 - a) * hi;
            (0.913 + 0.05) / (under + 0.05)
        }
    }

    #[test]
    fn readable_over_every_color_and_detail() {
        // luminances of wallpaper colors (black, blues/greens/reds, greys,
        // white) plus mixed envelopes: bright glyph on dark, hole in light
        let pal = [0.0, 0.0116, 0.0722, 0.1, 0.184, 0.2126, 0.3, 0.5,
                   0.7152, 0.8, 0.913, 1.0];
        for &m in &pal {
            for &lo in &pal {
                for &hi in &pal {
                    if lo > m || hi < m {
                        continue; // the envelope contains the mean
                    }
                    for &(td, tl) in &[(0.0, 0.0), (0.5, 0.1), (0.9, 0.02)] {
                        let (dark, step) = choose((m, lo, hi), td, tl);
                        assert!(step <= 10);
                        let c = worst_contrast(dark, step, lo, hi);
                        assert!(c >= 4.5 - 1e-3,
                                "mean={m} lo={lo} hi={hi} tints=({td},{tl}): \
                                 dark={dark} step={step} contrast={c:.2}");
                    }
                }
            }
        }
    }

    #[test]
    fn ink_is_never_grey_and_holds_its_side_near_the_cut() {
        // white page: dark ink; deep forest: light ink
        assert!(ink_dark(0.9, None));
        assert!(!ink_dark(0.05, None));
        // a mid-tone (the demo's busy forest, ~0.2) goes light, not dark
        assert!(!ink_dark(0.2, None));
        // inside the band each side keeps what it had
        assert!(ink_dark(0.28, Some(true)));
        assert!(!ink_dark(0.28, Some(false)));
        // still readable whatever side: the tint step covers the envelope
        let plain = Backdrop::default();
        for &(m, lo, hi) in &[(0.2f32, 0.0f32, 1.0f32), (0.3, 0.1, 0.8), (0.9, 0.0, 1.0)] {
            for prev in [None, Some(true), Some(false)] {
                let (dark, step, h) = choose_ink((m, lo, hi), prev, &plain);
                assert!(worst_contrast(dark, step, lo, hi) >= 4.5 - 1e-3);
                assert!(h <= 4);
            }
        }
    }

    #[test]
    fn halo_grows_near_the_cut_and_on_busy_backdrops() {
        assert!(halo((0.287, 0.287, 0.287), 0.0) > halo((0.95, 0.95, 0.95), 0.0));
        assert!(halo((0.05, 0.0, 0.9), 0.0) > halo((0.05, 0.05, 0.05), 0.0));
    }

    #[test]
    fn settings_glass_opacity_and_frost_reach_the_ink() {
        // a mid-tone: clear capsule -> light ink; a thick milky body (high
        // glass_opacity) lifts it -> dark ink, like the demo's tint slider
        let mid = (0.22f32, 0.1f32, 0.4f32);
        let clear = Backdrop { lens: true, lens_tint: 0.04, ..Default::default() };
        let milky = Backdrop { lens: true, lens_tint: 0.30, ..Default::default() };
        assert!(!choose_ink(mid, None, &clear).0);
        assert!(choose_ink(mid, None, &milky).0);
        // frost wipes the detail: a busy backdrop needs less halo
        let busy = (0.05f32, 0.0f32, 0.9f32);
        let sharp = Backdrop { lens: true, lens_tint: 0.04, frost: 0.0, ..Default::default() };
        let frosted = Backdrop { lens: true, lens_tint: 0.04, frost: 1.0, ..Default::default() };
        assert!(choose_ink(busy, None, &frosted).2 < choose_ink(busy, None, &sharp).2);
    }

    #[test]
    fn stats_use_the_envelope_not_the_average() {
        let mut g = Grid {
            lum: vec![0.5, 0.3, 0.3, 0.3],
            lmin: vec![0.0, 0.3, 0.3, 0.3],
            lmax: vec![1.0, 0.3, 0.3, 0.3],
            gw: 2, gh: 2, width: 2.0, height: 2.0, local: false,
        };
        let (mean, lo, hi) = g.stats(0.0, 0.0, 2.0, 2.0);
        assert!((mean - 0.35).abs() < 1e-6);
        assert_eq!(lo, 0.0);
        assert_eq!(hi, 1.0);
        g.lum = vec![0.0; 4];
        g.lmin = vec![0.0; 4];
        g.lmax = vec![0.0; 4];
        let (_, lo, hi) = g.stats(0.0, 0.0, 2.0, 2.0);
        assert_eq!((lo, hi), (0.0, 0.0));
    }
}
