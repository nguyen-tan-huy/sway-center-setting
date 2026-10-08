//! One bar window per monitor.

use crate::config::Config;
use crate::services::{procs, sway, tray, Services};
use crate::ui::{calendar::CalendarPopup, icons, quick::QuickSettings};
use gtk::prelude::*;
use gtk::{gdk, gio, glib};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use std::cell::Cell;
use std::rc::Rc;

pub const NAMESPACE: &str = "swayctl-bar";

pub fn build(app: &adw::Application, monitor: &gdk::Monitor, cfg: &Config, svc: &Rc<Services>,
             quick: &Rc<QuickSettings>, calendar: &Rc<CalendarPopup>) -> gtk::ApplicationWindow {
    let win = gtk::ApplicationWindow::builder().application(app).css_classes(["bar"]).build();
    win.init_layer_shell();
    win.set_namespace(Some(NAMESPACE));
    win.set_monitor(Some(monitor));
    win.set_layer(match cfg.layer.as_str() {
        "bottom" => Layer::Bottom,
        "overlay" => Layer::Overlay,
        _ => Layer::Top,
    });
    win.set_keyboard_mode(KeyboardMode::None);
    let vertical = matches!(cfg.position.as_str(), "left" | "right");
    let edge = match cfg.position.as_str() {
        "bottom" => Edge::Bottom,
        "left" => Edge::Left,
        "right" => Edge::Right,
        _ => Edge::Top,
    };
    for e in [Edge::Top, Edge::Bottom, Edge::Left, Edge::Right] {
        let along = if vertical { matches!(e, Edge::Top | Edge::Bottom) } else { matches!(e, Edge::Left | Edge::Right) };
        win.set_anchor(e, e == edge || along);
    }
    for (e, m) in [Edge::Top, Edge::Right, Edge::Bottom, Edge::Left].into_iter().zip(cfg.margins) {
        win.set_margin(e, m);
    }
    if cfg.exclusive {
        win.auto_exclusive_zone_enable();
    }
    let orientation = if vertical { gtk::Orientation::Vertical } else { gtk::Orientation::Horizontal };
    if cfg.height > 0 {
        if vertical {
            win.set_default_size(cfg.height, -1);
        } else {
            win.set_default_size(-1, cfg.height);
        }
    }

    let output = monitor.connector().map(|c| c.to_string()).unwrap_or_default();
    let center = gtk::CenterBox::builder().orientation(orientation).css_classes(["bar-box"]).build();
    let side = |names: &[String], class: &str| {
        let b = gtk::Box::builder().orientation(orientation).spacing(cfg.spacing).css_classes([class]).build();
        for name in names {
            if let Some(w) = module(name, cfg, svc, quick, calendar, &output, monitor) {
                w.add_css_class("module");
                b.append(&w);
            }
        }
        b
    };
    center.set_start_widget(Some(&side(&cfg.modules_left, "modules-left")));
    center.set_center_widget(Some(&side(&cfg.modules_center, "modules-center")));
    center.set_end_widget(Some(&side(&cfg.modules_right, "modules-right")));
    win.set_child(Some(&center));

    // Text that stands out on what's actually behind each module: a live
    // compositor sample (fallback: the config's wallpaper), retagged on
    // layout changes and every couple of seconds so a wallpaper change is
    // picked up too
    let geo = monitor.geometry();
    if cfg.backdrop.adaptive {
        let (pos, m, bd, mon) = (cfg.position.clone(), cfg.margins, cfg.backdrop.clone(), monitor.clone());
        // `full`: when the probe has nothing yet, fall back to capturing the
        // whole frame (and then the wallpaper). Only on events: every
        // backdrop read makes the compositor read pixels back synchronously
        // and a full capture is a whole 3K frame — on a 1 s timer that was a
        // 10–20 ms hitch of the cursor every second.
        let retag = {
            let (win, geo) = (win.downgrade(), geo);
            move |full: bool| {
                let Some(win) = win.upgrade() else { return };
                // the compositor inks the text: nothing to sample or tag
                let ink = crate::ui::backdrop::compositor_ink();
                crate::ui::backdrop::set_key_ink(&win, ink);
                if ink {
                    return;
                }
                let (w, h) = (win.width() as f32, win.height() as f32);
                let (mw, mh) = (geo.width() as f32, geo.height() as f32);
                let origin = match pos.as_str() {
                    "bottom" => (m[3] as f32, mh - h - m[2] as f32),
                    "right" => (mw - w - m[1] as f32, m[0] as f32),
                    _ => (m[3] as f32, m[0] as f32),
                };
                // what's behind the bar itself (glass probe: its own text left
                // out), else the whole frame, else the wallpaper
                let probed = crate::ui::backdrop::Grid::probe(&mon, "swayctl-bar", (win.width(), win.height()));
                let grid = if full {
                    probed.or_else(|| crate::ui::backdrop::Grid::capture(&mon)).or_else(|| {
                        crate::ui::backdrop::Grid::new(&bd, geo.width(), geo.height())
                    })
                } else {
                    probed
                };
                if let Some(grid) = grid {
                    crate::ui::backdrop::tag_modules(&win, &grid, origin, &bd);
                }
            }
        };
        let retag = std::rc::Rc::new(retag);
        // once laid out, and again when the workspaces (and so the layout) change
        let r = retag.clone();
        win.connect_map(move |_| {
            let r = r.clone();
            glib::timeout_add_local_once(std::time::Duration::from_millis(250), move || r(true));
        });
        let r = retag.clone();
        svc.sway.state.subscribe(move |_| {
            let r = r.clone();
            // after the workspace buttons have been laid out again
            glib::timeout_add_local_once(std::time::Duration::from_millis(100), move || r(true));
        });
        // and on a slow timer: the wallpaper (or a page scrolling under a
        // fullscreen-adjacent bar) can change without any sway event. Probe
        // only, and not often: each read stalls the compositor's frame (it
        // was once a second — a visible cursor hitch every second at 120 Hz)
        let r = retag.clone();
        glib::timeout_add_seconds_local(10, move || {
            r(false);
            glib::ControlFlow::Continue
        });
    }
    win
}

fn module(name: &str, cfg: &Config, svc: &Rc<Services>, quick: &Rc<QuickSettings>, calendar: &Rc<CalendarPopup>, output: &str,
          monitor: &gdk::Monitor) -> Option<gtk::Widget> {
    Some(match name {
        "workspaces" => workspaces(svc, output).upcast(),
        "mode" => {
            let l = gtk::Label::builder().css_classes(["mode"]).visible(false).build();
            let l2 = l.clone();
            svc.sway.state.subscribe(move |s| {
                l2.set_label(&s.mode);
                l2.set_visible(!s.mode.is_empty());
            });
            l.upcast()
        }
        "window" => {
            let l = gtk::Label::builder().css_classes(["window-title"]).ellipsize(gtk::pango::EllipsizeMode::End)
                .max_width_chars(60).build();
            let l2 = l.clone();
            svc.sway.state.subscribe(move |s| l2.set_label(&s.title));
            l.upcast()
        }
        "clock" => clock(cfg, calendar, monitor).upcast(),
        "status" => status(svc, quick, monitor).upcast(),
        "tray" => tray(svc)?.upcast(),
        _ => {
            eprintln!("swayctl-bar: unknown module {name}");
            return None;
        }
    })
}

fn workspaces(svc: &Rc<Services>, output: &str) -> gtk::Box {
    let b = gtk::Box::builder().css_classes(["workspaces"]).spacing(2).build();
    let (b2, output) = (b.clone(), output.to_owned());
    svc.sway.state.subscribe(move |s| {
        while let Some(c) = b2.first_child() {
            b2.remove(&c);
        }
        for ws in s.workspaces.iter().filter(|w| output.is_empty() || w.output == output) {
            let btn = gtk::Button::builder().label(&ws.name).css_classes(["workspace", "flat"]).build();
            if ws.focused {
                btn.add_css_class("focused");
            } else if ws.visible {
                btn.add_css_class("visible");
            }
            if ws.urgent {
                btn.add_css_class("urgent");
            }
            let target = if ws.num >= 0 { format!("workspace number {}", ws.num) } else {
                format!("workspace \"{}\"", ws.name.replace('"', "\\\""))
            };
            btn.connect_clicked(move |_| sway::command(&target));
            b2.append(&btn);
        }
    });
    // scroll through workspaces like most bars
    let scroll = gtk::EventControllerScroll::new(gtk::EventControllerScrollFlags::VERTICAL | gtk::EventControllerScrollFlags::DISCRETE);
    scroll.connect_scroll(|_, _dx, dy| {
        sway::command(if dy > 0.0 { "workspace next_on_output" } else { "workspace prev_on_output" });
        glib::Propagation::Stop
    });
    b.add_controller(scroll);
    b
}

fn clock(cfg: &Config, calendar: &Rc<CalendarPopup>, monitor: &gdk::Monitor) -> gtk::Button {
    let label = gtk::Label::new(None);
    let btn = gtk::Button::builder().child(&label).css_classes(["clock", "flat"]).build();
    // the calendar is a glass popup of its own (see ui/calendar.rs)
    let (cal, m, c) = (calendar.clone(), monitor.clone(), cfg.clone());
    btn.connect_clicked(move |b| cal.toggle(&m, b.upcast_ref(), &c));
    let (fmt, alt) = (cfg.clock_format.clone(), cfg.clock_format_alt.clone());
    let seconds = fmt.contains("%S") || fmt.contains("%T") || fmt.contains("%r");
    let tick = {
        let (label, btn) = (label.clone(), btn.clone());
        move || {
            if let Ok(now) = glib::DateTime::now_local() {
                label.set_label(&now.format(&fmt).map(|s| s.to_string()).unwrap_or_default());
                btn.set_tooltip_text(now.format(&alt).ok().as_deref());
            }
        }
    };
    tick();
    // wake exactly on the next minute (or second), then keep that rhythm
    let tick = Rc::new(tick);
    fn schedule(tick: Rc<dyn Fn()>, seconds: bool, alive: glib::WeakRef<gtk::Label>) {
        let now = glib::DateTime::now_local().ok();
        let ms_into = now.map(|n| (n.second() as u64 % if seconds { 1 } else { 60 }) * 1000 + n.microsecond() as u64 / 1000).unwrap_or(0);
        let period = if seconds { 1000 } else { 60_000 };
        glib::timeout_add_local_once(std::time::Duration::from_millis(period - ms_into % period + 5), move || {
            if alive.upgrade().is_some() {
                tick();
                schedule(tick, seconds, alive);
            }
        });
    }
    schedule(tick, seconds, label.downgrade());
    btn
}

/// The cluster of status icons on the right; one click opens Quick Settings.
fn status(svc: &Rc<Services>, quick: &Rc<QuickSettings>, monitor: &gdk::Monitor) -> gtk::Button {
    let row = gtk::Box::builder().spacing(10).build();
    let net = gtk::Image::new();
    let bt = gtk::Image::from_icon_name("bluetooth-active-symbolic");
    let vol = gtk::Image::new();
    let bat = gtk::Image::new();
    let pct = gtk::Label::builder().css_classes(["battery-percent"]).build();
    for w in [net.upcast_ref::<gtk::Widget>(), bt.upcast_ref(), vol.upcast_ref(), bat.upcast_ref(), pct.upcast_ref()] {
        row.append(w);
    }
    let btn = gtk::Button::builder().child(&row).css_classes(["status", "flat"]).build();
    {
        let (net, btn) = (net.clone(), btn.clone());
        svc.network.subscribe(move |n| {
            net.set_icon_name(Some(icons::network(n)));
            btn.set_tooltip_text(Some(if n.name.is_empty() { "Offline" } else { &n.name }));
        });
    }
    {
        let bt = bt.clone();
        svc.bluetooth.subscribe(move |b| bt.set_visible(b.available && b.powered));
    }
    {
        let vol = vol.clone();
        svc.volume.subscribe(move |v| vol.set_icon_name(Some(icons::volume(v))));
    }
    {
        let (bat, pct) = (bat.clone(), pct.clone());
        svc.battery.subscribe(move |b| {
            bat.set_visible(b.present);
            pct.set_visible(b.present);
            bat.set_icon_name(Some(&icons::battery(b)));
            pct.set_label(&format!("{:.0}%", b.percent));
            pct.set_css_classes(if b.present && !b.charging && b.percent <= 10.0 { &["battery-percent", "critical"] }
                                else if b.present && !b.charging && b.percent <= 20.0 { &["battery-percent", "warning"] }
                                else { &["battery-percent"] });
        });
    }
    let (q, m) = (quick.clone(), monitor.clone());
    btn.connect_clicked(move |_| q.toggle(&m));
    let scroll = gtk::EventControllerScroll::new(gtk::EventControllerScrollFlags::VERTICAL | gtk::EventControllerScrollFlags::DISCRETE);
    let busy = Rc::new(Cell::new(false));
    scroll.connect_scroll(move |_, _dx, dy| {
        if !busy.replace(true) {
            procs::step_volume(if dy > 0.0 { -5 } else { 5 });
            busy.set(false);
        }
        glib::Propagation::Stop
    });
    btn.add_controller(scroll);
    btn
}

fn tray(svc: &Rc<Services>) -> Option<gtk::Box> {
    let tray = svc.tray.clone()?;
    let b = gtk::Box::builder().css_classes(["tray"]).spacing(2).build();
    let (b2, t2) = (b.clone(), tray.clone());
    tray.items.subscribe(move |items| {
        while let Some(c) = b2.first_child() {
            b2.remove(&c);
        }
        b2.set_visible(!items.is_empty());
        for item in items.iter().filter(|i| i.status != "Passive") {
            b2.append(&tray_button(&t2, item));
        }
    });
    Some(b)
}

fn tray_icon(item: &tray::Item) -> gtk::Image {
    let image = gtk::Image::builder().pixel_size(16).build();
    if !item.icon_theme_path.is_empty() {
        if let Some(display) = gdk::Display::default() {
            let theme = gtk::IconTheme::for_display(&display);
            if !theme.search_path().iter().any(|p| p.to_str() == Some(item.icon_theme_path.as_str())) {
                theme.add_search_path(&item.icon_theme_path);
            }
        }
    }
    let named = !item.icon_name.is_empty()
        && (item.icon_name.starts_with('/') || gdk::Display::default()
            .map(|d| gtk::IconTheme::for_display(&d).has_icon(&item.icon_name)).unwrap_or(false));
    if named && item.icon_name.starts_with('/') {
        image.set_from_file(Some(&item.icon_name));
    } else if named {
        image.set_icon_name(Some(&item.icon_name));
    } else if let Some(px) = &item.pixmap {
        let bytes = glib::Bytes::from(&px.data[..]);
        let tex = gdk::MemoryTexture::new(px.width, px.height, gdk::MemoryFormat::A8r8g8b8, &bytes, px.width as usize * 4);
        image.set_paintable(Some(&tex));
    } else {
        image.set_icon_name(Some("application-x-executable-symbolic"));
    }
    image
}

fn tray_button(tray: &Rc<tray::Tray>, item: &tray::Item) -> gtk::Button {
    let btn = gtk::Button::builder().child(&tray_icon(item)).css_classes(["tray-item", "flat"]).build();
    let tip = if item.tooltip.is_empty() { &item.title } else { &item.tooltip };
    if !tip.is_empty() {
        btn.set_tooltip_text(Some(tip));
    }
    // left click: the button's own "clicked" (its gesture takes button 1)
    let (t, it) = (tray.clone(), item.clone());
    btn.connect_clicked(move |b| {
        if it.item_is_menu { show_tray_menu(&t, &it, b) } else { t.call(&it, "Activate") }
    });
    let click = gtk::GestureClick::builder().button(0).build();
    let (t, it, b) = (tray.clone(), item.clone(), btn.clone());
    click.connect_released(move |g, _, _, _| match g.current_button() {
        2 => t.call(&it, "SecondaryActivate"),
        3 => show_tray_menu(&t, &it, &b),
        _ => {}
    });
    btn.add_controller(click);
    btn
}

fn show_tray_menu(tray: &Rc<tray::Tray>, item: &tray::Item, anchor: &gtk::Button) {
    let (tray, item, anchor) = (tray.clone(), item.clone(), anchor.clone());
    glib::spawn_future_local(async move {
        let Some(root) = tray.menu(&item).await else {
            tray.call(&item, "ContextMenu"); // no dbusmenu: let the app show its own
            return;
        };
        let actions = gio::SimpleActionGroup::new();
        let act = gio::SimpleAction::new("item", Some(glib::VariantTy::INT32));
        let (t2, it2) = (tray.clone(), item.clone());
        act.connect_activate(move |_, v| {
            if let Some(id) = v.and_then(|v| v.get::<i32>()) {
                t2.menu_event(&it2, id);
            }
        });
        actions.add_action(&act);
        let pop = gtk::PopoverMenu::from_model(Some(&menu_model(&root)));
        pop.insert_action_group("tray", Some(&actions));
        pop.set_parent(&anchor);
        pop.set_has_arrow(false);
        pop.connect_closed(|p| {
            let p = p.clone();
            glib::idle_add_local_once(move || p.unparent());
        });
        pop.popup();
    });
}

fn menu_model(node: &tray::MenuNode) -> gio::Menu {
    let menu = gio::Menu::new();
    let mut section = gio::Menu::new();
    for child in &node.children {
        if child.separator {
            if section.n_items() > 0 {
                menu.append_section(None, &section);
                section = gio::Menu::new();
            }
            continue;
        }
        let label = match child.toggle {
            Some(true) => format!("✓ {}", child.label),
            Some(false) => format!("   {}", child.label),
            None => child.label.clone(),
        };
        if !child.children.is_empty() {
            section.append_submenu(Some(&label), &menu_model(child));
        } else {
            let mi = gio::MenuItem::new(Some(&label), None);
            if child.enabled {
                mi.set_action_and_target_value(Some("tray.item"), Some(&child.id.to_variant()));
            } else {
                mi.set_action_and_target_value(Some("tray.disabled"), None); // no such action: greyed out
            }
            section.append_item(&mi);
        }
    }
    if section.n_items() > 0 {
        menu.append_section(None, &section);
    }
    menu
}
