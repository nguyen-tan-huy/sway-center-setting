//! A clear full-screen surface under a popup: a click anywhere outside the
//! popup lands on it and closes the popup. Scrolling is for the window under
//! the pointer, popup open or not: on the first scroll event the catcher stops
//! taking input (empty input region), so the rest of the gesture reaches the
//! window; it catches clicks again once the scrolling has stopped.

use crate::services::sway;
use gtk::prelude::*;
use gtk::{gdk, glib};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use std::cell::RefCell;
use std::rc::Rc;
use std::time::Duration;

/// How long after a scroll the catcher takes clicks again. A scroll still
/// going on then loses one event (the catcher lets go again).
const CATCH_AGAIN: Duration = Duration::from_millis(1500);

pub fn open(app: &adw::Application, monitor: &gdk::Monitor, on_click: impl Fn() + 'static) -> gtk::Window {
    let c = gtk::Window::builder().application(app).css_classes(["quick-catcher"]).build();
    c.init_layer_shell();
    c.set_namespace(Some("swayctl-quick-catcher"));
    c.set_monitor(Some(monitor));
    // above windows and the bar (Top, created later), below the popup (Overlay)
    c.set_layer(Layer::Top);
    c.set_keyboard_mode(KeyboardMode::None);
    for e in [Edge::Top, Edge::Bottom, Edge::Left, Edge::Right] {
        c.set_anchor(e, true);
    }
    c.set_exclusive_zone(-1);
    c.set_child(Some(&gtk::Box::new(gtk::Orientation::Vertical, 0)));
    let click = gtk::GestureClick::builder().button(0).build();
    click.connect_pressed(move |_, _, _, _| on_click());
    c.add_controller(click);
    let scroll = gtk::EventControllerScroll::new(gtk::EventControllerScrollFlags::BOTH_AXES);
    let (c2, timer) = (c.downgrade(), Rc::new(RefCell::new(None::<glib::SourceId>)));
    scroll.connect_scroll(move |_, _, _| {
        let Some(c) = c2.upgrade() else { return glib::Propagation::Stop };
        pass_through(&c, true);
        if let Some(t) = timer.take() {
            t.remove();
        }
        let (c3, t2) = (c.downgrade(), timer.clone());
        *timer.borrow_mut() = Some(glib::timeout_add_local_once(CATCH_AGAIN, move || {
            t2.take();
            if let Some(c) = c3.upgrade() {
                pass_through(&c, false);
            }
        }));
        glib::Propagation::Stop
    });
    c.add_controller(scroll);
    c.present();
    c
}

/// Let input through the catcher (empty input region) or catch it again.
fn pass_through(c: &gtk::Window, through: bool) {
    let Some(surface) = c.surface() else { return };
    surface.set_input_region(Some(&if through {
        gtk::cairo::Region::create()
    } else {
        let (w, h) = (surface.width(), surface.height());
        gtk::cairo::Region::create_rectangle(&gtk::cairo::RectangleInt::new(0, 0, w, h))
    }));
    // GDK sends the region with the next frame; sway only picks the surface
    // under the pointer again when it moves, so nudge it (by nothing) after.
    surface.queue_render();
    glib::timeout_add_local_once(Duration::from_millis(30), || {
        let _ = sway::request(sway::RUN_COMMAND, "seat - cursor move 0 0");
    });
}
