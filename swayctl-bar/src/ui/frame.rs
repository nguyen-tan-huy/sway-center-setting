//! The frame style as glass: one layer surface under the windows that covers the whole output,
//! with a rounded cut-out for every window. What is drawn here is only its shape (a thin white
//! body); the compositor's shaped glass bends the wallpaper behind it along the edges of the
//! cut-outs, so the bar, the screen edges and the gaps between windows are one pane of glass.
//! The bar itself sits above, transparent, and draws only its text.

use crate::config::Config;
use crate::services::{sway::WinRect, Services};
use crate::watch::Subs;
use gtk::cairo;
use gtk::{gdk, prelude::*};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use std::cell::RefCell;
use std::f64::consts::{FRAC_PI_2, PI};
use std::rc::Rc;

pub const NAMESPACE: &str = "swayctl-frame";

/// A rounded rectangle as a sub-path.
fn rounded_rect(cr: &cairo::Context, x: f64, y: f64, w: f64, h: f64, r: f64) {
    let r = r.min(w / 2.0).min(h / 2.0).max(0.0);
    cr.new_sub_path();
    cr.arc(x + w - r, y + r, r, -FRAC_PI_2, 0.0);
    cr.arc(x + w - r, y + h - r, r, 0.0, FRAC_PI_2);
    cr.arc(x + r, y + h - r, r, FRAC_PI_2, PI);
    cr.arc(x + r, y + r, r, PI, PI + FRAC_PI_2);
    cr.close_path();
}

/// The whole output minus the windows (even-odd), as the pane's body.
pub fn paint(cr: &cairo::Context, width: f64, height: f64, windows: &[WinRect], radius: f64, tint: f64) {
    cr.set_fill_rule(cairo::FillRule::EvenOdd);
    cr.rectangle(0.0, 0.0, width, height);
    for r in windows {
        rounded_rect(cr, r.x as f64, r.y as f64, r.w as f64, r.h as f64, radius);
    }
    cr.set_source_rgba(1.0, 1.0, 1.0, tint);
    let _ = cr.fill();
}

pub fn build(app: &adw::Application, monitor: &gdk::Monitor, cfg: &Config, svc: &Rc<Services>, subs: &Subs) -> gtk::Window {
    let win = gtk::Window::builder().application(app).css_classes(["frame-window"]).build();
    win.init_layer_shell();
    win.set_namespace(Some(NAMESPACE));
    win.set_monitor(Some(monitor));
    // under the windows (and the bar), over the wallpaper
    win.set_layer(Layer::Bottom);
    for e in [Edge::Top, Edge::Bottom, Edge::Left, Edge::Right] {
        win.set_anchor(e, true);
    }
    // -1: the whole output, whatever the bar or anything else reserves
    win.set_exclusive_zone(-1);
    win.set_keyboard_mode(KeyboardMode::None);

    let windows: Rc<RefCell<Vec<WinRect>>> = Rc::default();
    let area = gtk::DrawingArea::builder().hexpand(true).vexpand(true).build();
    let (radius, tint) = (cfg.frame.radius, cfg.frame.tint);
    {
        let windows = windows.clone();
        area.set_draw_func(move |_, cr, w, h| paint(cr, w as f64, h as f64, &windows.borrow(), radius, tint));
    }
    win.set_child(Some(&area));
    // clicks go straight through to the desktop
    win.connect_realize(|w| {
        if let Some(s) = w.surface() {
            s.set_input_region(Some(&cairo::Region::create()));
        }
    });

    let connector = monitor.connector().map(|c| c.to_string()).unwrap_or_default();
    let area2 = area.clone();
    subs.follow(&svc.sway.state, move |st| {
        let mine: Vec<WinRect> = st.windows.iter().filter(|r| r.output == connector).cloned().collect();
        if *windows.borrow() != mine {
            *windows.borrow_mut() = mine;
            area2.queue_draw();
        }
    });
    win
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rect(x: i32, y: i32, w: i32, h: i32) -> WinRect {
        WinRect { output: "A".into(), x, y, w, h }
    }

    fn alpha_at(surface: &mut cairo::ImageSurface, x: usize, y: usize) -> u8 {
        let stride = surface.stride() as usize;
        let data = surface.data().unwrap();
        data[y * stride + x * 4 + 3] // A of ARGB32 (little endian: B G R A)
    }

    #[test]
    fn the_frame_is_everything_but_the_windows() {
        let mut s = cairo::ImageSurface::create(cairo::Format::ARgb32, 200, 100).unwrap();
        {
            let cr = cairo::Context::new(&s).unwrap();
            paint(&cr, 200.0, 100.0, &[rect(20, 30, 60, 50), rect(100, 30, 80, 50)], 8.0, 0.5);
        }
        assert!(alpha_at(&mut s, 5, 5) > 100, "the bar's strip is body");
        assert!(alpha_at(&mut s, 90, 50) > 100, "the gap between the windows is body");
        assert_eq!(alpha_at(&mut s, 50, 50), 0, "inside a window is cut out");
        assert_eq!(alpha_at(&mut s, 140, 60), 0);
    }

    #[test]
    fn no_windows_means_one_pane() {
        let mut s = cairo::ImageSurface::create(cairo::Format::ARgb32, 40, 40).unwrap();
        {
            let cr = cairo::Context::new(&s).unwrap();
            paint(&cr, 40.0, 40.0, &[], 8.0, 0.5);
        }
        assert!(alpha_at(&mut s, 20, 20) > 100);
    }

    #[test]
    fn the_cut_out_corners_are_rounded() {
        let mut s = cairo::ImageSurface::create(cairo::Format::ARgb32, 100, 100).unwrap();
        {
            let cr = cairo::Context::new(&s).unwrap();
            paint(&cr, 100.0, 100.0, &[rect(10, 10, 80, 80)], 20.0, 0.5);
        }
        assert!(alpha_at(&mut s, 11, 11) > 100, "the very corner is still frame");
        assert_eq!(alpha_at(&mut s, 50, 11), 0, "the straight edge is cut out");
    }
}
