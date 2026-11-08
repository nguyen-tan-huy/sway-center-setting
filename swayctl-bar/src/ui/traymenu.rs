//! A tray item's menu as a pane of liquid glass: a layer-shell surface of its
//! own under the icon (a GTK popover is an xdg_popup, which the compositor's
//! layer glass never reaches). Submenus open in place with a back row; a click
//! outside (the catcher) or Escape closes it.

use crate::services::tray::{self, MenuNode};
use crate::ui::catcher;
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
    // margins from the screen's edge, not from under the bar's reserved strip
    win.set_exclusive_zone(-1);

    // next to the icon, on the side the bar leaves free: below a top bar, above a
    // bottom one, beside a left or right one. Margins count from the screen's
    // edge (exclusive zone -1), so the bar's own reserved strip isn't added.
    let geo = monitor.geometry();
    let (bx, by) = bar_origin(&bar, &monitor);
    let (ix, iy, iw, ih) = match anchor.compute_bounds(&bar) {
        Some(b) => (bx + b.x() as i32, by + b.y() as i32, b.width() as i32, b.height() as i32),
        None => (geo.width() / 2, by, 0, bar.height()),
    };
    let vertical = bar.is_anchor(Edge::Top) && bar.is_anchor(Edge::Bottom);
    const GAP: i32 = 6;
    if vertical {
        if bar.is_anchor(Edge::Left) && !bar.is_anchor(Edge::Right) {
            win.set_anchor(Edge::Left, true);
            win.set_margin(Edge::Left, ix + iw + GAP);
        } else {
            win.set_anchor(Edge::Right, true);
            win.set_margin(Edge::Right, (geo.width() - ix + GAP).max(8));
        }
        // level with the icon; from the bottom edge when it sits in the lower half
        if iy + ih / 2 > geo.height() / 2 {
            win.set_anchor(Edge::Bottom, true);
            win.set_margin(Edge::Bottom, (geo.height() - (iy + ih)).max(8));
        } else {
            win.set_anchor(Edge::Top, true);
            win.set_margin(Edge::Top, iy.max(8));
        }
    } else {
        if bar.is_anchor(Edge::Bottom) && !bar.is_anchor(Edge::Top) {
            win.set_anchor(Edge::Bottom, true);
            win.set_margin(Edge::Bottom, geo.height() - iy + GAP);
        } else {
            win.set_anchor(Edge::Top, true);
            win.set_margin(Edge::Top, iy + ih + GAP);
        }
        // the icon's half of the screen keeps the menu on screen
        if ix + iw / 2 > geo.width() / 2 {
            win.set_anchor(Edge::Right, true);
            win.set_margin(Edge::Right, (geo.width() - (ix + iw)).max(8));
        } else {
            win.set_anchor(Edge::Left, true);
            win.set_margin(Edge::Left, ix.max(8));
        }
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
    let left = if bar.is_anchor(Edge::Left) {
        bar.margin(Edge::Left)
    } else if bar.is_anchor(Edge::Right) {
        geo.width() - bar.width() - bar.margin(Edge::Right)
    } else {
        (geo.width() - bar.width()) / 2
    };
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
