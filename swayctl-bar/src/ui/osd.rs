//! On-screen display for volume and brightness keys: `swayctl-bar osd
//! volume-up` (sent to the running bar) changes the value and shows a small
//! fading panel near the bottom of the focused monitor.

use crate::services::procs;
use crate::ui::{backdrop, icons};
use adw::prelude::*;
use gtk::{gdk, glib};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use std::cell::RefCell;
use std::rc::Rc;

pub const NAMESPACE: &str = "swayctl-osd";

pub struct Osd {
    win: gtk::Window,
    icon: gtk::Image,
    level: gtk::LevelBar,
    value: gtk::Label,
    row: gtk::Box,
    hide: RefCell<Option<glib::SourceId>>,
    anim: adw::TimedAnimation,
    /// the live-backdrop timer while the OSD is up
    follow: RefCell<Option<glib::SourceId>>,
}

impl Osd {
    pub fn new(app: &adw::Application) -> Rc<Self> {
        let win = gtk::Window::builder().application(app).css_classes(["osd-window"]).build();
        win.init_layer_shell();
        win.set_namespace(Some(NAMESPACE));
        win.set_layer(Layer::Overlay);
        win.set_keyboard_mode(KeyboardMode::None);
        win.set_anchor(Edge::Bottom, true);
        win.set_margin(Edge::Bottom, 96);
        win.set_exclusive_zone(-1);
        win.set_can_target(false);
        // macOS-style pill: wide and short — icon, accent bar, percent
        let row = gtk::Box::builder().spacing(14).css_classes(["osd"]).width_request(360).build();
        let icon = gtk::Image::builder().pixel_size(22).css_classes(["osd-icon"]).build();
        let level = gtk::LevelBar::builder()
            .min_value(0.0).max_value(100.0)
            .hexpand(true).valign(gtk::Align::Center)
            .css_classes(["osd-level"])
            .build();
        let value = gtk::Label::builder()
            .width_chars(5).xalign(1.0)
            .css_classes(["numeric", "osd-value"])
            .build();
        row.append(&icon);
        row.append(&level);
        row.append(&value);
        win.set_child(Some(&row));
        let row2 = row.clone();
        let row = row.clone();
        let target = adw::CallbackAnimationTarget::new(move |v| row2.set_opacity(v));
        let anim = adw::TimedAnimation::new(&row, 0.0, 1.0, 150, target);
        anim.set_easing(adw::Easing::EaseOutCubic);
        let win2 = win.clone();
        anim.connect_done(move |a| {
            if a.is_reverse() {
                win2.set_visible(false);
            }
        });
        Rc::new(Self { win, icon, level, value, row, hide: RefCell::new(None), anim, follow: RefCell::new(None) })
    }

    /// Runs one of: volume-up, volume-down, volume-mute, brightness-up, brightness-down.
    pub fn run(self: &Rc<Self>, what: &str) {
        let (icon, percent) = match what {
            "volume-up" | "volume-down" | "volume-mute" => {
                match what {
                    "volume-up" => procs::step_volume(5),
                    "volume-down" => procs::step_volume(-5),
                    _ => procs::toggle_mute(),
                }
                let v = procs::read_volume();
                (icons::volume(&v), if v.muted { 0 } else { v.percent })
            }
            "brightness-up" | "brightness-down" => {
                procs::step_brightness(if what == "brightness-up" { 5 } else { -5 });
                let p = procs::brightness().unwrap_or(0);
                (icons::brightness(p), p)
            }
            other => {
                eprintln!("swayctl-bar: unknown osd {other}");
                return;
            }
        };
        self.show(icon, percent);
    }

    fn show(self: &Rc<Self>, icon: &str, percent: u32) {
        self.icon.set_icon_name(Some(icon));
        self.level.set_value(percent.min(100) as f64);
        self.value.set_label(&format!("{percent}%"));
        if !self.win.is_visible() {
            // not on screen yet: the whole frame there is what will be behind it
            if let Some(m) = backdrop::focused_monitor() {
                if let Some(grid) = backdrop::Grid::capture(&m) {
                    self.tag(&grid, &m);
                }
            }
            self.win.present();
            self.follow_backdrop();
            self.anim.set_reverse(false);
            self.anim.play();
        } else if self.anim.is_reverse() {
            // was fading out: come back
            self.anim.set_reverse(false);
            self.anim.play();
        }
        if let Some(id) = self.hide.take() {
            id.remove();
        }
        let me = Rc::downgrade(self);
        *self.hide.borrow_mut() = Some(glib::timeout_add_local_once(std::time::Duration::from_millis(1300), move || {
            let Some(me) = me.upgrade() else { return };
            me.hide.take();
            if let Some(id) = me.follow.take() {
                id.remove();
            }
            me.anim.set_reverse(true);
            me.anim.play();
        }));
    }

    /// Light or dark text on the pill by what's behind it. The OSD sits
    /// bottom-centre, 96 px up: its origin on the monitor follows from that
    /// (only used for a whole-frame grid; a probe is already local).
    fn tag(&self, grid: &backdrop::Grid, monitor: &gdk::Monitor) {
        let geo = monitor.geometry();
        let (w, h) = (self.row.width().max(360) as f32, self.row.height().max(44) as f32);
        let origin = ((geo.width() as f32 - w) / 2.0, geo.height() as f32 - 96.0 - h);
        backdrop::tag_panes(self.row.upcast_ref(), &self.win, grid, origin);
    }

    /// While shown: follow what's behind (the compositor's glass probe,
    /// without the pill's own text), like Quick Settings — a video or a page
    /// scrolling under it while the keys are held.
    fn follow_backdrop(self: &Rc<Self>) {
        if let Some(id) = self.follow.take() {
            id.remove();
        }
        let me = Rc::downgrade(self);
        let id = glib::timeout_add_local(std::time::Duration::from_millis(150), move || {
            let Some(me) = me.upgrade() else { return glib::ControlFlow::Break };
            let Some(m) = backdrop::focused_monitor() else { return glib::ControlFlow::Continue };
            if let Some(grid) = backdrop::Grid::probe(&m, NAMESPACE, (me.win.width(), me.win.height())) {
                me.tag(&grid, &m);
            }
            glib::ControlFlow::Continue
        });
        *self.follow.borrow_mut() = Some(id);
    }
}
