//! One bar window per monitor.

use crate::config::Config;
use crate::services::{procs, sway, tray, Services};
use crate::ui::{icons, quick::QuickSettings};
use crate::watch::Subs;
use gtk::prelude::*;
use gtk::{gdk, glib};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use adw::prelude::*;
use std::cell::{Cell, RefCell};
use std::rc::Rc;

pub const NAMESPACE: &str = "swayctl-bar";

pub fn build(app: &adw::Application, monitor: &gdk::Monitor, cfg: &Config, svc: &Rc<Services>,
             quick: &Rc<QuickSettings>, subs: &Subs) -> gtk::ApplicationWindow {
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
            if let Some(w) = module(name, cfg, svc, quick, &output, monitor, subs) {
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
        subs.follow(&svc.sway.state, move |_| {
            let r = r.clone();
            // after the workspace buttons have been laid out again
            glib::timeout_add_local_once(std::time::Duration::from_millis(100), move || r(true));
        });
        // and on a slow timer: the wallpaper (or a page scrolling under a
        // fullscreen-adjacent bar) can change without any sway event. Probe
        // only, and not often: each read stalls the compositor's frame (it
        // was once a second — a visible cursor hitch every second at 120 Hz)
        let r = retag.clone();
        let alive = win.downgrade();
        glib::timeout_add_seconds_local(10, move || {
            if alive.upgrade().is_none() {
                return glib::ControlFlow::Break; // this bar was rebuilt
            }
            r(false);
            glib::ControlFlow::Continue
        });
    }
    win
}

fn module(name: &str, cfg: &Config, svc: &Rc<Services>, quick: &Rc<QuickSettings>, output: &str,
          monitor: &gdk::Monitor, subs: &Subs) -> Option<gtk::Widget> {
    Some(match name {
        "workspaces" => workspaces(svc, output, subs).upcast(),
        "mode" => {
            let l = gtk::Label::builder().css_classes(["mode"]).visible(false).build();
            let l2 = l.clone();
            subs.follow(&svc.sway.state, move |s| {
                l2.set_label(&s.mode);
                l2.set_visible(!s.mode.is_empty());
            });
            l.upcast()
        }
        "window" => {
            let l = gtk::Label::builder().css_classes(["window-title"]).ellipsize(gtk::pango::EllipsizeMode::End)
                .max_width_chars(60).build();
            let l2 = l.clone();
            subs.follow(&svc.sway.state, move |s| l2.set_label(&s.title));
            l.upcast()
        }
        "clock" => clock(cfg).upcast(),
        "status" => status(svc, quick, monitor, subs).upcast(),
        "tray" => tray(svc, subs)?.upcast(),
        _ => {
            eprintln!("swayctl-bar: unknown module {name}");
            return None;
        }
    })
}

/// The focused workspace's "drop": one blob behind the buttons that slides to
/// the new workspace. Its leading edge springs ahead of the trailing one, so
/// it stretches on the way (and flattens a little) and then settles back, like
/// a drop of water. The buttons only carry the text (the one it's over wears
/// the accent text, `.under-drop`); the blob is the `.focused` fill.
struct WsDrop {
    fixed: gtk::Fixed,
    blob: gtk::Box,
    row: gtk::Box,
    left: Cell<f64>,
    right: Cell<f64>,
    /// where the blob is heading
    goal: Cell<(f64, f64)>,
    /// (width, y, height) of the focused button: the blob at rest
    rest: Cell<(f64, f64, f64)>,
    placed: Cell<bool>,
    /// each button's span along the fixed, as of the last layout
    spans: RefCell<Vec<(gtk::Widget, f64, f64)>>,
    /// the springs of the left and the right edge
    anims: RefCell<Vec<adw::SpringAnimation>>,
}

impl WsDrop {
    fn focused_button(&self) -> Option<gtk::Widget> {
        let mut c = self.row.first_child();
        while let Some(w) = c {
            if w.has_css_class("current") {
                return Some(w);
            }
            c = w.next_sibling();
        }
        None
    }

    fn stop(&self) {
        for a in self.anims.take() {
            a.pause();
        }
    }

    /// Head for the focused button; snap there instead when `animate` is off
    /// or the blob isn't on screen yet.
    fn retarget(self: &Rc<Self>, animate: bool) {
        let Some(btn) = self.focused_button() else {
            // the focused workspace is on another output
            self.stop();
            self.blob.set_visible(false);
            self.placed.set(false);
            self.measure();
            self.wear(None);
            return;
        };
        let Some(b) = btn.compute_bounds(&self.fixed) else { return };
        let (x, w, y, h) = (b.x() as f64, b.width() as f64, b.y() as f64, b.height() as f64);
        if w < 1.0 {
            return;
        }
        self.rest.set((w, y, h));
        self.measure();
        let (l, r) = (x, x + w);
        if !self.placed.get() || !animate || !self.blob.is_mapped() {
            self.stop();
            self.goal.set((l, r));
            self.left.set(l);
            self.right.set(r);
            self.placed.set(true);
            self.blob.set_visible(true);
            self.paint();
            return;
        }
        if self.goal.get() == (l, r) {
            return;
        }
        self.goal.set((l, r));
        // the edge on the side it's moving to leads: quick, a touch of
        // overshoot; the other trails: slow and soft
        let right_leads = l + r >= self.left.get() + self.right.get();
        let lead = adw::SpringParams::new(0.7, 1.0, 380.0);
        let trail = adw::SpringParams::new(0.95, 1.0, 130.0);
        let (pl, pr) = if right_leads { (trail, lead) } else { (lead, trail) };
        // a move interrupted midway carries its speed into the next
        let old = self.anims.take();
        let (mut vl, mut vr) = (0.0, 0.0);
        if old.len() == 2 {
            vl = old[0].velocity();
            vr = old[1].velocity();
        }
        for a in &old {
            a.pause();
        }
        let edge = |from: f64, to: f64, v0: f64, params: adw::SpringParams, right: bool| {
            let weak = Rc::downgrade(self);
            let target = adw::CallbackAnimationTarget::new(move |v| {
                let Some(me) = weak.upgrade() else { return };
                if right { me.right.set(v) } else { me.left.set(v) }
                me.paint();
            });
            let a = adw::SpringAnimation::new(&self.fixed, from, to, params, target);
            a.set_initial_velocity(v0);
            a.set_epsilon(0.05);
            a.play();
            a
        };
        let al = edge(self.left.get(), l, vl, pl, false);
        let ar = edge(self.right.get(), r, vr, pr, true);
        *self.anims.borrow_mut() = vec![al, ar];
    }

    /// Two frames on, when the buttons have been laid out again.
    fn retarget_later(self: &Rc<Self>, animate: bool) {
        let weak = Rc::downgrade(self);
        let ticks = Cell::new(0u8);
        self.fixed.add_tick_callback(move |_, _| {
            ticks.set(ticks.get() + 1);
            if ticks.get() < 2 {
                return glib::ControlFlow::Continue;
            }
            if let Some(me) = weak.upgrade() {
                me.retarget(animate);
            }
            glib::ControlFlow::Break
        });
    }

    fn measure(&self) {
        let mut spans = Vec::new();
        let mut c = self.row.first_child();
        while let Some(w) = c {
            if let Some(b) = w.compute_bounds(&self.fixed) {
                spans.push((w.clone(), b.x() as f64, b.x() as f64 + b.width() as f64));
            }
            c = w.next_sibling();
        }
        *self.spans.borrow_mut() = spans;
    }

    /// The numbers the drop covers (by their middle) wear the accent text.
    fn wear(&self, over: Option<(f64, f64)>) {
        for (w, x0, x1) in self.spans.borrow().iter() {
            let mid = (x0 + x1) / 2.0;
            let on = over.is_some_and(|(l, r)| mid >= l && mid <= r);
            if on != w.has_css_class("under-drop") {
                if on { w.add_css_class("under-drop") } else { w.remove_css_class("under-drop") }
            }
        }
    }

    fn paint(&self) {
        let (rest_w, y, h) = self.rest.get();
        let total = self.fixed.width() as f64;
        let (mut l, mut r) = (self.left.get(), self.right.get());
        if total > 0.0 {
            // never wider than the row: the fixed's own size must not grow
            l = l.clamp(0.0, total);
            r = r.clamp(0.0, total);
        }
        let w = (r - l).max(4.0);
        // longer than at rest = flatter, as a stretched drop is
        let stretch = (w / rest_w.max(1.0) - 1.0).clamp(0.0, 1.5);
        let hh = h * (1.0 - 0.08 * stretch);
        self.blob.set_size_request(w.round() as i32, hh.round() as i32);
        self.fixed.move_(&self.blob, l, y + (h - hh) / 2.0);
        self.wear(Some((l, r)));
    }
}

fn set_ws_state(btn: &gtk::Widget, ws: &sway::Workspace) {
    for (class, on) in [("current", ws.focused), ("visible", !ws.focused && ws.visible), ("urgent", ws.urgent)] {
        if on { btn.add_css_class(class) } else { btn.remove_css_class(class) }
    }
}

fn workspaces(svc: &Rc<Services>, output: &str, subs: &Subs) -> gtk::Overlay {
    let row = gtk::Box::builder().css_classes(["workspace-row"]).spacing(2).build();
    let fixed = gtk::Fixed::builder().can_target(false).build();
    let blob = gtk::Box::builder().css_classes(["workspace", "focused", "ws-blob"])
        .can_target(false).visible(false).build();
    fixed.put(&blob, 0.0, 0.0);
    // the drop layer is the main child (lowest), the buttons overlay it and
    // give the overlay its size
    let root = gtk::Overlay::builder().css_classes(["workspaces"]).child(&fixed).build();
    root.add_overlay(&row);
    root.set_measure_overlay(&row, true);
    let drop = Rc::new(WsDrop {
        fixed, blob, row: row.clone(), left: Cell::new(0.0), right: Cell::new(0.0), goal: Cell::new((0.0, 0.0)),
        rest: Cell::new((1.0, 0.0, 0.0)), placed: Cell::new(false), spans: RefCell::new(Vec::new()), anims: RefCell::new(Vec::new()),
    });
    let output = output.to_owned();
    let names: RefCell<Vec<String>> = RefCell::new(Vec::new());
    let d = drop.clone();
    subs.follow(&svc.sway.state, move |s| {
        let list: Vec<&sway::Workspace> = s.workspaces.iter().filter(|w| output.is_empty() || w.output == output).collect();
        let now: Vec<String> = list.iter().map(|w| w.name.clone()).collect();
        // buttons are only rebuilt when workspaces come or go; a plain focus
        // change keeps them (and so the blob has something to slide between)
        let rebuilt = *names.borrow() != now;
        if rebuilt {
            while let Some(c) = row.first_child() {
                row.remove(&c);
            }
            for ws in &list {
                let btn = gtk::Button::builder().label(&ws.name).css_classes(["workspace", "flat"]).build();
                let target = if ws.num >= 0 { format!("workspace number {}", ws.num) } else {
                    format!("workspace \"{}\"", ws.name.replace('"', "\\\""))
                };
                btn.connect_clicked(move |_| sway::command(&target));
                row.append(&btn);
            }
            *names.borrow_mut() = now;
        }
        let mut child = row.first_child();
        for ws in &list {
            let Some(btn) = child else { break };
            set_ws_state(&btn, ws);
            child = btn.next_sibling();
        }
        if rebuilt { d.retarget_later(true) } else { d.retarget(true) }
    });
    // placed once the bar is on screen
    let d = drop.clone();
    root.connect_map(move |_| d.retarget_later(false));
    // scroll through workspaces like most bars
    let scroll = gtk::EventControllerScroll::new(gtk::EventControllerScrollFlags::VERTICAL | gtk::EventControllerScrollFlags::DISCRETE);
    scroll.connect_scroll(|_, _dx, dy| {
        sway::command(if dy > 0.0 { "workspace next_on_output" } else { "workspace prev_on_output" });
        glib::Propagation::Stop
    });
    root.add_controller(scroll);
    root
}

fn clock(cfg: &Config) -> gtk::Button {
    let label = gtk::Label::new(None);
    let btn = gtk::Button::builder().child(&label).css_classes(["clock", "flat"]).build();
    let (fmt, alt) = (cfg.clock_format.clone(), cfg.clock_format_alt.clone());
    let seconds = fmt.contains("%S") || fmt.contains("%T") || fmt.contains("%r");
    let tick = {
        // weak: the timer below stops once the clock is gone
        let (label, btn) = (label.downgrade(), btn.downgrade());
        move || {
            let (Some(label), Some(btn)) = (label.upgrade(), btn.upgrade()) else { return };
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
fn status(svc: &Rc<Services>, quick: &Rc<QuickSettings>, monitor: &gdk::Monitor, subs: &Subs) -> gtk::Button {
    // spacing from CSS (border-spacing on .status-row), so bar.padding can set it
    let row = gtk::Box::builder().css_classes(["status-row"]).build();
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
        subs.follow(&svc.network, move |n| {
            net.set_icon_name(Some(icons::network(n)));
            btn.set_tooltip_text(Some(if n.name.is_empty() { "Offline" } else { &n.name }));
        });
    }
    {
        let bt = bt.clone();
        subs.follow(&svc.bluetooth, move |b| bt.set_visible(b.available && b.powered));
    }
    {
        let vol = vol.clone();
        subs.follow(&svc.volume, move |v| vol.set_icon_name(Some(icons::volume(v))));
    }
    {
        let (bat, pct) = (bat.clone(), pct.clone());
        subs.follow(&svc.battery, move |b| {
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

/// The nth (from 1) tray icon's button in a bar window, if it has that many.
pub fn tray_button_at(win: &gtk::Window, n: usize) -> Option<gtk::Button> {
    fn find(w: &gtk::Widget) -> Option<gtk::Widget> {
        if w.has_css_class("tray") {
            return Some(w.clone());
        }
        let mut c = w.first_child();
        while let Some(x) = c {
            if let Some(f) = find(&x) {
                return Some(f);
            }
            c = x.next_sibling();
        }
        None
    }
    let tray = find(win.upcast_ref())?;
    let mut c = tray.first_child();
    for _ in 1..n {
        c = c?.next_sibling();
    }
    c.and_downcast::<gtk::Button>()
}

fn tray(svc: &Rc<Services>, subs: &Subs) -> Option<gtk::Box> {
    let tray = svc.tray.clone()?;
    let b = gtk::Box::builder().css_classes(["tray"]).spacing(2).build();
    let (b2, t2) = (b.clone(), tray.clone());
    subs.follow(&tray.items, move |items| {
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
        crate::ui::traymenu::show(&tray, &item, &root, anchor.upcast_ref());
    });
}

