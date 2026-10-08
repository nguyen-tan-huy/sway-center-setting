//! A tray item's menu as a pane of liquid glass: a layer-shell surface of its
//! own under the icon (a GTK popover is an xdg_popup, which the compositor's
//! layer glass never reaches). Submenus open in place with a back row; a click
//! outside (the catcher) or Escape closes it.

use crate::services::tray::{self, MenuNode};
use crate::ui::{backdrop, catcher};
use gtk::prelude::*;
use gtk::{gdk, glib};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use std::cell::RefCell;
use std::rc::Rc;

pub const NAMESPACE: &str = "swayctl-traymenu";

struct Open {
    win: gtk::Window,
    catcher: gtk::Window,
}

thread_local! {
    static OPEN: RefCell<Option<Open>> = const { RefCell::new(None) };
}

pub fn close() {
    if let Some(o) = OPEN.with(|o| o.take()) {
        o.win.close();
        o.catcher.close();
    }
}

/// Show `root` (the item's dbusmenu) under `anchor`, a tray button on the bar.
pub fn show(tray: &Rc<tray::Tray>, item: &tray::Item, root: &MenuNode, anchor: &gtk::Widget) {
    close();
    let Some(bar) = anchor.root().and_downcast::<gtk::Window>() else { return };
    let Some(app) = bar.application().and_downcast::<adw::Application>() else { return };
    let display = WidgetExt::display(&bar);
    let Some(monitor) = bar.surface().and_then(|s| display.monitor_at_surface(&s)) else { return };

    let win = gtk::Window::builder().application(&app).css_classes(["quick-window", "traymenu-window"]).build();
    win.init_layer_shell();
    win.set_namespace(Some(NAMESPACE));
    win.set_monitor(Some(&monitor));
    win.set_layer(Layer::Overlay);
    win.set_keyboard_mode(KeyboardMode::Exclusive);
    backdrop::set_key_ink(&win, backdrop::compositor_ink());

    // under the icon: the bar's top-left corner (its layer margins) plus the
    // icon's place in the bar; the side the icon is on keeps the menu on screen
    let geo = monitor.geometry();
    let bounds = anchor.compute_bounds(&bar);
    let (bx, by) = bar_origin(&bar, &monitor);
    let (x, w, bottom_y) = match bounds {
        Some(b) => (bx + b.x() as i32, b.width() as i32, by + (b.y() + b.height()) as i32),
        None => (geo.width() / 2, 0, by + bar.height()),
    };
    win.set_anchor(Edge::Top, true);
    win.set_margin(Edge::Top, bottom_y + 6);
    if x + w / 2 > geo.width() / 2 {
        win.set_anchor(Edge::Right, true);
        win.set_margin(Edge::Right, (geo.width() - (x + w)).max(8));
    } else {
        win.set_anchor(Edge::Left, true);
        win.set_margin(Edge::Left, x.max(8));
    }

    let pane = gtk::Box::builder()
        .orientation(gtk::Orientation::Vertical)
        .spacing(2)
        .width_request(220)
        .css_classes(["tray-menu"])
        .build();
    win.set_child(Some(&pane));
    let stack: Rc<RefCell<Vec<MenuNode>>> = Rc::new(RefCell::new(vec![root.clone()]));
    fill(&pane, tray, item, &stack);

    let keys = gtk::EventControllerKey::new();
    {
        let (pane, tray, item, stack) = (pane.clone(), tray.clone(), item.clone(), stack.clone());
        keys.connect_key_pressed(move |_, key, _, _| {
            if key != gdk::Key::Escape {
                return glib::Propagation::Proceed;
            }
            // first Escape leaves a submenu, the next closes
            if stack.borrow().len() > 1 {
                stack.borrow_mut().pop();
                fill(&pane, &tray, &item, &stack);
            } else {
                close();
            }
            glib::Propagation::Stop
        });
    }
    win.add_controller(keys);

    let catcher = catcher::open(&app, &monitor, close);
    win.present();
    OPEN.with(|o| *o.borrow_mut() = Some(Open { win, catcher }));
}

/// Where the bar's surface sits on the monitor, logical px.
fn bar_origin(bar: &gtk::Window, monitor: &gdk::Monitor) -> (i32, i32) {
    let geo = monitor.geometry();
    let left = if bar.is_anchor(Edge::Left) { bar.margin(Edge::Left) } else { (geo.width() - bar.width()) / 2 };
    let top = if bar.is_anchor(Edge::Top) {
        bar.margin(Edge::Top)
    } else {
        geo.height() - bar.height() - bar.margin(Edge::Bottom)
    };
    (left, top)
}

/// Rows for the menu on top of `stack` (a back row first in a submenu).
fn fill(pane: &gtk::Box, tray: &Rc<tray::Tray>, item: &tray::Item, stack: &Rc<RefCell<Vec<MenuNode>>>) {
    while let Some(c) = pane.first_child() {
        pane.remove(&c);
    }
    let node = stack.borrow().last().cloned().unwrap_or_default();
    if stack.borrow().len() > 1 {
        let back = row("go-previous-symbolic", &node.label, None);
        back.add_css_class("tray-menu-back");
        let (p, t, it, s) = (pane.clone(), tray.clone(), item.clone(), stack.clone());
        back.connect_clicked(move |_| {
            s.borrow_mut().pop();
            fill(&p, &t, &it, &s);
        });
        pane.append(&back);
        pane.append(&gtk::Separator::new(gtk::Orientation::Horizontal));
    }
    let mut last_sep = true; // no separator first, none twice
    for child in &node.children {
        if child.separator {
            if !last_sep {
                pane.append(&gtk::Separator::new(gtk::Orientation::Horizontal));
                last_sep = true;
            }
            continue;
        }
        last_sep = false;
        let icon = match child.toggle {
            Some(true) => Some("object-select-symbolic"),
            _ => None,
        };
        let sub = !child.children.is_empty();
        let b = row(icon.unwrap_or(""), &child.label, sub.then_some("go-next-symbolic"));
        b.set_sensitive(child.enabled);
        if sub {
            let (p, t, it, s, c) = (pane.clone(), tray.clone(), item.clone(), stack.clone(), child.clone());
            b.connect_clicked(move |_| {
                s.borrow_mut().push(c.clone());
                fill(&p, &t, &it, &s);
            });
        } else {
            let (t, it, id) = (tray.clone(), item.clone(), child.id);
            b.connect_clicked(move |_| {
                t.menu_event(&it, id);
                close();
            });
        }
        pane.append(&b);
    }
    if let Some(w) = pane.root().and_downcast::<gtk::Window>() {
        // the surface follows the pane's size (shrinks back from a long submenu)
        w.set_default_size(-1, -1);
    }
}

/// One menu row: an optional leading icon (a check, back), the label, an
/// optional trailing icon (a submenu's arrow).
fn row(lead: &str, label: &str, trail: Option<&str>) -> gtk::Button {
    let line = gtk::Box::builder().spacing(10).build();
    let lead_img = gtk::Image::builder().pixel_size(16).build();
    if !lead.is_empty() {
        lead_img.set_icon_name(Some(lead));
    }
    line.append(&lead_img);
    // dbusmenu labels mark their mnemonic with '_'
    let text = gtk::Label::builder()
        .label(label.replace("__", "\u{0}").replace('_', "").replace('\u{0}', "_"))
        .xalign(0.0)
        .hexpand(true)
        .ellipsize(gtk::pango::EllipsizeMode::End)
        .max_width_chars(40)
        .build();
    line.append(&text);
    if let Some(t) = trail {
        line.append(&gtk::Image::builder().icon_name(t).pixel_size(16).build());
    }
    gtk::Button::builder().child(&line).css_classes(["flat", "tray-menu-item"]).build()
}
