//! The clock's calendar: its own layer-shell surface under the clock (not a
//! GTK popover, which the compositor can't turn into glass), opened with a
//! short fade + slide, closed by a click outside (catcher), Escape or the clock.

use crate::config::Config;
use crate::ui::{backdrop, catcher};
use adw::prelude::*;
use gtk::{gdk, glib};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use std::cell::RefCell;
use std::rc::Rc;

pub const NAMESPACE: &str = "swayctl-calendar";
const GAP: i32 = 8;

pub struct CalendarPopup {
    app: adw::Application,
    win: RefCell<Option<gtk::Window>>,
    catcher: RefCell<Option<gtk::Window>>,
}

impl CalendarPopup {
    pub fn new(app: &adw::Application) -> Rc<Self> {
        Rc::new(Self { app: app.clone(), win: RefCell::new(None), catcher: RefCell::new(None) })
    }

    /// Open under (or over) `anchor`, the clock in a bar, or close if open.
    pub fn toggle(self: &Rc<Self>, monitor: &gdk::Monitor, anchor: &gtk::Widget, cfg: &Config) {
        if self.win.borrow().is_some() {
            self.close();
        } else {
            self.open(monitor, anchor, cfg);
        }
    }

    pub fn close(&self) {
        if let Some(c) = self.catcher.take() {
            c.close();
        }
        let Some(win) = self.win.take() else { return };
        let Some(panel) = win.child() else { win.close(); return };
        let target = adw::CallbackAnimationTarget::new({
            let panel = panel.clone();
            move |v| panel.set_opacity(v)
        });
        let anim = adw::TimedAnimation::new(&panel, 1.0, 0.0, 120, target);
        anim.set_easing(adw::Easing::EaseInCubic);
        anim.connect_done(move |_| win.close());
        anim.play();
    }

    fn open(self: &Rc<Self>, monitor: &gdk::Monitor, anchor: &gtk::Widget, cfg: &Config) {
        // what will be behind it, before it shows
        let grid = backdrop::Grid::capture(monitor);
        let win = gtk::Window::builder().application(&self.app).css_classes(["calendar-window"]).build();
        win.init_layer_shell();
        win.set_namespace(Some(NAMESPACE));
        win.set_monitor(Some(monitor));
        win.set_layer(Layer::Overlay);
        win.set_keyboard_mode(KeyboardMode::Exclusive);
        let bottom = cfg.position == "bottom";
        win.set_anchor(if bottom { Edge::Bottom } else { Edge::Top }, true);
        win.set_anchor(Edge::Left, true);
        win.set_margin(if bottom { Edge::Bottom } else { Edge::Top }, GAP);

        let cal = gtk::Calendar::new();
        if let Ok(now) = glib::DateTime::now_local() {
            cal.select_day(&now);
        }
        let panel = gtk::Box::builder().orientation(gtk::Orientation::Vertical).css_classes(["calendar-panel"]).build();
        if let Ok(now) = glib::DateTime::now_local() {
            // today in words above the grid, like the macOS/GNOME clock popups
            let day = gtk::Label::builder().label(now.format("%A").map(|s| s.to_string()).unwrap_or_default())
                .xalign(0.0).css_classes(["calendar-weekday"]).build();
            let date = gtk::Label::builder().label(now.format("%e %B %Y").map(|s| s.trim().to_string()).unwrap_or_default())
                .xalign(0.0).css_classes(["calendar-date"]).build();
            panel.append(&day);
            panel.append(&date);
        }
        panel.append(&cal);
        win.set_child(Some(&panel));

        // centred under the clock, kept on screen
        let (_, w, _, _) = panel.measure(gtk::Orientation::Horizontal, -1);
        let bar_left = cfg.margins[3];
        let x = anchor.root().and_then(|r| anchor.compute_bounds(&r))
            .map(|b| bar_left + (b.x() + b.width() / 2.0) as i32 - w / 2).unwrap_or(GAP);
        let screen = monitor.geometry().width();
        win.set_margin(Edge::Left, x.clamp(GAP, (screen - w - GAP).max(GAP)));

        let keys = gtk::EventControllerKey::new();
        let me = Rc::downgrade(self);
        keys.connect_key_pressed(move |_, key, _, _| {
            if key == gdk::Key::Escape {
                if let Some(me) = me.upgrade() {
                    me.close();
                }
                return glib::Propagation::Stop;
            }
            glib::Propagation::Proceed
        });
        win.add_controller(keys);

        let me = Rc::downgrade(self);
        let c = catcher::open(&self.app, monitor, move || if let Some(me) = me.upgrade() { me.close() });
        self.catcher.replace(Some(c));

        panel.set_opacity(0.0);
        win.present();
        let target = adw::CallbackAnimationTarget::new({
            let panel = panel.clone();
            move |v| panel.set_opacity(v)
        });
        let anim = adw::TimedAnimation::new(&panel, 0.0, 1.0, 160, target);
        anim.set_easing(adw::Easing::EaseOutCubic);
        if let Some(grid) = grid {
            let (w, m) = (win.downgrade(), monitor.clone());
            anim.connect_done(move |_| {
                let Some(w) = w.upgrade() else { return };
                if let (Some(root), Some(origin)) = (w.child(), backdrop::layer_origin(&m, NAMESPACE)) {
                    backdrop::tag_panes(&root, &w, &grid, origin);
                }
            });
        }
        anim.play();
        self.win.replace(Some(win));
    }
}
