//! Quick Settings: a layer-shell popup under the bar with toggles, sliders,
//! media and power, opened with a spring (fade + slide + slight scale) and
//! closed with a short ease-in. Sub-pages (Wi-Fi, sound output, power mode,
//! power) slide in with AdwNavigationView.

use crate::config::Config;
use crate::services::{dbus, procs, sway, Services};
use crate::ui::{backdrop, catcher, icons};
use adw::prelude::*;
use gtk::{gdk, glib, graphene, gsk};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use std::cell::{Cell, RefCell};
use std::rc::Rc;

pub const NAMESPACE: &str = "swayctl-quick";
const SLIDE: f32 = 12.0;
const PANEL_WIDTH: i32 = 360;

pub struct QuickSettings {
    app: adw::Application,
    svc: Rc<Services>,
    cfg: RefCell<Config>,
    win: RefCell<Option<gtk::Window>>,
    /// transparent full-screen surface under the popup: a click on it (anywhere
    /// outside the popup) closes it; scrolling passes through to the windows
    catcher: RefCell<Option<gtk::Window>>,
    closing: Cell<bool>,
    /// the notification list's scroller and list, and how tall it may get on
    /// this monitor (the rest of the popup must stay on screen)
    notif: RefCell<Option<(gtk::ScrolledWindow, gtk::Box)>>,
    notif_max: Cell<i32>,
    main_col: RefCell<Option<gtk::Box>>,
    /// what's behind the popup (taken as it opens), for light/dark text per pane
    backdrop: RefCell<Option<(Rc<backdrop::Grid>, gdk::Monitor)>>,
    /// bumped on every open: the live-backdrop timer of an older popup stops
    opened: Cell<u32>,
    /// run as it opens (notification pop-ups make way)
    pub on_open: RefCell<Option<Box<dyn Fn()>>>,
    /// the open panel's service subscriptions, ended as it closes (they
    /// hold its widgets: a panel per open would otherwise never be freed)
    subs: crate::watch::Subs,
}

impl QuickSettings {
    pub fn new(app: &adw::Application, svc: &Rc<Services>, cfg: &Config) -> Rc<Self> {
        Rc::new(Self { app: app.clone(), svc: svc.clone(), cfg: RefCell::new(cfg.clone()), win: RefCell::new(None),
                       catcher: RefCell::new(None), closing: Cell::new(false),
                       on_open: RefCell::new(None), notif: RefCell::new(None), notif_max: Cell::new(320),
                       main_col: RefCell::new(None), backdrop: RefCell::new(None),
                       opened: Cell::new(0), subs: Default::default() })
    }

    pub fn set_config(&self, cfg: &Config) {
        *self.cfg.borrow_mut() = cfg.clone();
    }

    pub fn toggle(self: &Rc<Self>, monitor: &gdk::Monitor) {
        if self.win.borrow().is_some() {
            self.close();
        } else {
            self.open(monitor);
        }
    }

    pub fn close(self: &Rc<Self>) {
        let Some(win) = self.win.borrow().clone() else { return };
        if self.closing.replace(true) {
            return;
        }
        // the panel stops following the services now; freed once closed
        self.subs.clear();
        if let Some(c) = self.catcher.take() {
            c.close();
        }
        let stage = win.child().and_downcast::<gtk::Fixed>().unwrap();
        let card = stage.first_child().unwrap();
        freeze_size(&stage, &card);
        let target = adw::CallbackAnimationTarget::new(move |v| place(&stage, &card, v));
        let anim = adw::TimedAnimation::new(&win, 1.0, 0.0, 140, target);
        anim.set_easing(adw::Easing::EaseInCubic);
        let me = Rc::downgrade(self);
        let win2 = win.clone();
        anim.connect_done(move |_| {
            win2.close();
            if let Some(me) = me.upgrade() {
                me.win.replace(None);
                me.closing.set(false);
            }
        });
        anim.play();
    }

    fn open(self: &Rc<Self>, monitor: &gdk::Monitor) {
        if let Some(f) = self.on_open.borrow().as_ref() {
            f();
        }
        self.opened.set(self.opened.get().wrapping_add(1));
        // before anything of ours is on screen: that's what will be behind it
        // (unless the compositor inks the text itself: then nothing is read)
        let ink = backdrop::compositor_ink();
        self.backdrop.replace(if ink {
            None
        } else {
            backdrop::Grid::capture(monitor).map(|g| (Rc::new(g), monitor.clone()))
        });
        let cfg = self.cfg.borrow().clone();
        let win = gtk::Window::builder().application(&self.app).css_classes(["quick-window"]).build();
        backdrop::set_key_ink(&win, ink);
        win.init_layer_shell();
        win.set_namespace(Some(NAMESPACE));
        win.set_monitor(Some(monitor));
        win.set_layer(Layer::Overlay);
        win.set_keyboard_mode(KeyboardMode::Exclusive);
        let gap = 8;
        let bottom = cfg.position == "bottom";
        win.set_anchor(if bottom { Edge::Bottom } else { Edge::Top }, true);
        win.set_anchor(if cfg.position == "left" { Edge::Left } else { Edge::Right }, true);
        for e in [Edge::Top, Edge::Bottom, Edge::Left, Edge::Right] {
            win.set_margin(e, gap + if e == Edge::Right { cfg.margins[1] } else { 0 });
        }

        let nav = adw::NavigationView::new();
        nav.add(&self.main_page(&nav));
        let card = gtk::Box::builder().css_classes(["quick-panel"]).width_request(PANEL_WIDTH).build();
        card.append(&nav);
        // A clamp caps the *natural* width too: an ellipsized label (a long song
        // title) still asks for its full text width, which would widen the layer
        // surface - and the compositor paints glass over all of it.
        let clamp = adw::Clamp::builder().maximum_size(PANEL_WIDTH).tightening_threshold(PANEL_WIDTH)
            .child(&card).build();
        let stage = gtk::Fixed::new();
        stage.put(&clamp, 0.0, 0.0);
        win.set_child(Some(&stage));

        let keys = gtk::EventControllerKey::new();
        let me = Rc::downgrade(self);
        let nav2 = nav.clone();
        keys.connect_key_pressed(move |_, key, _, _| {
            if key == gdk::Key::Escape {
                // first Escape leaves a sub-page, the next closes
                if nav2.navigation_stack().n_items() > 1 {
                    nav2.pop();
                } else if let Some(me) = me.upgrade() {
                    me.close();
                }
                return glib::Propagation::Stop;
            }
            glib::Propagation::Proceed
        });
        win.add_controller(keys);
        // Not closed on focus loss: with focus_follows_mouse the pointer
        // crossing a window on its way to the popup would take focus and shut
        // it (and sway drops an on-demand layer's focus anyway). A click
        // outside lands on the catcher instead.
        self.open_catcher(monitor);

        // everything below works on the stage's child: the clamp, not the card in it
        let pane: gtk::Widget = clamp.clone().upcast();
        // A GTK window grows with its content but never shrinks back by itself:
        // after each page change (once the slide is over), size it to the page,
        // or the compositor keeps painting glass over the old, larger surface.
        {
            let (win2, pane2) = (win.clone(), pane.clone());
            let me = Rc::downgrade(self);
            nav.connect_visible_page_notify(move |_| {
                let (win3, pane3, me) = (win2.clone(), pane2.clone(), me.clone());
                glib::timeout_add_local_once(std::time::Duration::from_millis(320), move || {
                    fit(&win3, &pane3);
                    if let Some(me) = me.upgrade() { me.retag() }
                });
            });
        }
        self.limit_notifications(monitor, &cfg);
        place(&stage, &pane, 0.0);
        freeze_size(&stage, &pane);
        win.present();
        let target = {
            let (stage, pane) = (stage.clone(), pane.clone());
            adw::CallbackAnimationTarget::new(move |v| place(&stage, &pane, v))
        };
        let anim = adw::SpringAnimation::new(&win, 0.0, 1.0, adw::SpringParams::new(0.62, 1.0, 380.0), target);
        let (stage2, card2, me) = (stage.clone(), pane.clone(), Rc::downgrade(self));
        anim.connect_done(move |_| {
            // let sub-pages resize the popup from now on
            stage2.set_size_request(-1, -1);
            stage2.set_child_transform(&card2, None);
            // in place now: light or dark text per pane, by what's behind it
            if let Some(me) = me.upgrade() {
                me.retag();
                me.follow_backdrop();
            }
        });
        anim.play();
        self.win.replace(Some(win));
    }

    fn open_catcher(self: &Rc<Self>, monitor: &gdk::Monitor) {
        let me = Rc::downgrade(self);
        let c = catcher::open(&self.app, monitor, move || if let Some(me) = me.upgrade() { me.close() });
        if let Some(old) = self.catcher.replace(Some(c)) {
            old.close();
        }
    }

    fn settings(self: &Rc<Self>, page: &str) {
        procs::shell(&self.cfg.borrow().settings_command.replace("{page}", page));
        self.close();
    }

    fn main_page(self: &Rc<Self>, nav: &adw::NavigationView) -> adw::NavigationPage {
        let svc = &self.svc;
        let col = gtk::Box::builder().orientation(gtk::Orientation::Vertical).spacing(12).css_classes(["quick-main"]).build();
        self.main_col.replace(Some(col.clone()));

        // ---- tiles
        let grid = gtk::Grid::builder().column_spacing(8).row_spacing(8).column_homogeneous(true).build();
        let mut n = 0;
        let mut add = |w: &gtk::Widget| {
            grid.attach(w, n % 2, n / 2, 1, 1);
            n += 1;
        };
        if let Some(sys) = svc.system.clone() {
            let wifi_page = {
                let me = Rc::downgrade(self);
                let nav = nav.clone();
                move || if let Some(me) = me.upgrade() { nav.push(&me.wifi_page()) }
            };
            let t = Tile::new("network-wireless-symbolic", "Wi-Fi", Some(Box::new(wifi_page)));
            let (t2, s2) = (t.clone(), sys.clone());
            self.subs.follow(&svc.network, move |net| {
                t2.root.set_visible(net.available);
                t2.set(net.wifi_enabled, if !net.wifi_enabled { "Off" } else if net.kind == "wifi" { &net.name } else { "Not connected" });
                t2.icon.set_icon_name(Some(if net.kind == "wifi" { icons::network(net) } else if net.wifi_enabled {
                    "network-wireless-symbolic" } else { "network-wireless-disabled-symbolic" }));
            });
            let net = svc.network.clone();
            t.button.connect_clicked(move |_| dbus::set_wifi(s2.clone(), !net.get().wifi_enabled));
            add(t.root.upcast_ref());

            let me = Rc::downgrade(self);
            let t = Tile::new("bluetooth-active-symbolic", "Bluetooth", Some(Box::new(move || {
                if let Some(me) = me.upgrade() { me.settings("system:bluetooth") }
            })));
            let t2 = t.clone();
            self.subs.follow(&svc.bluetooth, move |b| {
                t2.root.set_visible(b.available);
                t2.set(b.powered, if b.powered { "On" } else { "Off" });
                t2.icon.set_icon_name(Some(if b.powered { "bluetooth-active-symbolic" } else { "bluetooth-disabled-symbolic" }));
            });
            let (bt, s3) = (svc.bluetooth.clone(), sys.clone());
            t.button.connect_clicked(move |_| dbus::set_bluetooth(s3.clone(), !bt.get().powered));
            add(t.root.upcast_ref());
        }
        if let Some(ses) = svc.session.clone() {
            let t = Tile::new("night-light-symbolic", "Night Light", None);
            let t2 = t.clone();
            self.subs.follow(&svc.night_light, move |on| {
                t2.root.set_visible(on.is_some());
                t2.set(on.unwrap_or(false), if on.unwrap_or(false) { "On" } else { "Off" });
            });
            t.button.connect_clicked(move |_| dbus::center_action(ses.clone(), "night_light.toggle"));
            add(t.root.upcast_ref());
        }
        if let Some(n) = svc.notifier.clone().filter(|n| n.active.get()) {
            let t = Tile::new("notifications-disabled-symbolic", "Do Not Disturb", None);
            let t2 = t.clone();
            self.subs.follow(&n.dnd, move |on| t2.set(*on, if *on { "On" } else { "Off" }));
            t.button.connect_clicked(move |_| n.dnd.set(!n.dnd.get()));
            add(t.root.upcast_ref());
        } else if let Some(dnd) = procs::dnd() {
            // another server (swaync) shows notifications
            let t = Tile::new("notifications-disabled-symbolic", "Do Not Disturb", None);
            t.set(dnd, if dnd { "On" } else { "Off" });
            let t2 = t.clone();
            t.button.connect_clicked(move |_| {
                let on = !t2.active.get();
                procs::set_dnd(on);
                t2.set(on, if on { "On" } else { "Off" });
            });
            add(t.root.upcast_ref());
        }
        if svc.system.is_some() && !svc.profile.get().is_empty() {
            let me = Rc::downgrade(self);
            let nav2 = nav.clone();
            let t = Tile::new("power-profile-balanced-symbolic", "Power Mode", Some(Box::new(move || {
                if let Some(me) = me.upgrade() { nav2.push(&me.profile_page()) }
            })));
            let t2 = t.clone();
            self.subs.follow(&svc.profile, move |p| {
                t2.set(p != "balanced", &profile_label(p));
                t2.icon.set_icon_name(Some(&format!("power-profile-{p}-symbolic")));
            });
            let nav3 = nav.clone();
            let me = Rc::downgrade(self);
            t.button.connect_clicked(move |_| if let Some(me) = me.upgrade() { nav3.push(&me.profile_page()) });
            add(t.root.upcast_ref());
        }
        col.append(&grid);

        // ---- sliders
        if let Some(b) = procs::brightness() {
            let (row, scale, icon) = slider_row(icons::brightness(b), b as f64, 100.0);
            scale.connect_value_changed(move |s| {
                let v = s.value() as u32;
                icon.set_icon_name(Some(icons::brightness(v)));
                procs::set_brightness(v);
            });
            col.append(&row);
        }
        {
            let v = svc.volume.get();
            let (row, scale, icon) = slider_row(icons::volume(&v), v.percent as f64, 100.0);
            let mute = gtk::Button::builder().css_classes(["flat", "circular"]).build();
            row.remove(&icon);
            mute.set_child(Some(&icon));
            row.prepend(&mute);
            mute.connect_clicked(|_| procs::toggle_mute());
            let me = Rc::downgrade(self);
            let nav2 = nav.clone();
            let out = gtk::Button::builder().icon_name("go-next-symbolic").css_classes(["flat", "circular"])
                .tooltip_text("Sound output").build();
            out.connect_clicked(move |_| if let Some(me) = me.upgrade() { nav2.push(&me.sink_page()) });
            row.append(&out);
            let updating = Rc::new(Cell::new(false));
            let (s2, u2) = (scale.clone(), updating.clone());
            self.subs.follow(&svc.volume, move |v| {
                icon.set_icon_name(Some(icons::volume(v)));
                if (s2.value() as u32) != v.percent.min(100) {
                    u2.set(true);
                    s2.set_value(v.percent as f64);
                    u2.set(false);
                }
            });
            scale.connect_value_changed(move |s| if !updating.get() { procs::set_volume(s.value() as u32) });
            row.set_visible(v.available);
            col.append(&row);
        }

        // ---- media
        if let Some(ses) = svc.session.clone() {
            let card = gtk::Box::builder().spacing(8).css_classes(["media"]).build();
            let text = gtk::Box::builder().orientation(gtk::Orientation::Vertical).hexpand(true).valign(gtk::Align::Center).build();
            let title = gtk::Label::builder().xalign(0.0).ellipsize(gtk::pango::EllipsizeMode::End).max_width_chars(24)
                .width_chars(1).css_classes(["media-title"]).build();
            let artist = gtk::Label::builder().xalign(0.0).ellipsize(gtk::pango::EllipsizeMode::End).max_width_chars(28)
                .width_chars(1).css_classes(["dim-label", "caption"]).build();
            text.append(&title);
            text.append(&artist);
            card.append(&text);
            let mk = |icon: &str, method: &'static str| {
                let b = gtk::Button::builder().icon_name(icon).css_classes(["flat", "circular"]).build();
                let (ses, media) = (ses.clone(), self.svc.media.clone());
                b.connect_clicked(move |_| dbus::media_call(ses.clone(), media.get().player, method));
                card.append(&b);
                b
            };
            mk("media-skip-backward-symbolic", "Previous");
            let play = mk("media-playback-start-symbolic", "PlayPause");
            mk("media-skip-forward-symbolic", "Next");
            let card2 = card.clone();
            self.subs.follow(&svc.media, move |m| {
                card2.set_visible(!m.player.is_empty());
                title.set_label(if m.title.is_empty() { "Playing" } else { &m.title });
                artist.set_label(&m.artist);
                artist.set_visible(!m.artist.is_empty());
                play.set_icon_name(if m.playing { "media-playback-pause-symbolic" } else { "media-playback-start-symbolic" });
            });
            col.append(&card);
        }

        // ---- notifications
        if let Some(n) = svc.notifier.clone().filter(|n| n.active.get()) {
            col.append(&self.notification_list(&n));
        }

        // ---- footer
        // just the buttons, on the right (the battery is already on the bar)
        let foot = gtk::Box::builder().spacing(6).halign(gtk::Align::End).css_classes(["quick-footer"]).build();
        let me = Rc::downgrade(self);
        let gear = gtk::Button::builder().icon_name("emblem-system-symbolic").css_classes(["circular"]).tooltip_text("Settings").build();
        gear.connect_clicked(move |_| if let Some(me) = me.upgrade() { me.settings("appearance") });
        let lock = gtk::Button::builder().icon_name("system-lock-screen-symbolic").css_classes(["circular"]).tooltip_text("Lock").build();
        let me = Rc::downgrade(self);
        lock.connect_clicked(move |_| if let Some(me) = me.upgrade() { me.lock() });
        let power = gtk::Button::builder().icon_name("system-shutdown-symbolic").css_classes(["circular"]).tooltip_text("Power").build();
        let me = Rc::downgrade(self);
        let nav2 = nav.clone();
        power.connect_clicked(move |_| if let Some(me) = me.upgrade() { nav2.push(&me.power_page()) });
        foot.append(&gear);
        foot.append(&lock);
        foot.append(&power);
        col.append(&foot);

        adw::NavigationPage::builder().title("Quick Settings").tag("main").child(&col).build()
    }

    /// The latest notifications, newest first, with "Clear all".
    fn notification_list(self: &Rc<Self>, n: &Rc<crate::services::notify::Notifier>) -> gtk::Widget {
        use crate::services::notify::Reason;
        let section = gtk::Box::builder().orientation(gtk::Orientation::Vertical).spacing(6)
            .css_classes(["quick-notifications"]).build();
        let head = gtk::Box::builder().spacing(6).build();
        head.append(&gtk::Label::builder().label("Notifications").xalign(0.0).hexpand(true)
            .css_classes(["heading"]).build());
        let clear = gtk::Button::builder().label("Clear").css_classes(["flat", "pill-button"]).build();
        let n2 = n.clone();
        clear.connect_clicked(move |_| n2.clear());
        head.append(&clear);
        head.add_css_class("pane");
        section.append(&head);
        let list = gtk::Box::builder().orientation(gtk::Orientation::Vertical).spacing(6).build();
        // A scrolled window doesn't report a useful natural height, so its height
        // is set by hand (size_notifications): the list's own, up to what fits.
        let scroller = gtk::ScrolledWindow::builder().hscrollbar_policy(gtk::PolicyType::Never)
            .vscrollbar_policy(gtk::PolicyType::Automatic).child(&list).build();
        section.append(&scroller);
        self.notif.replace(Some((scroller, list.clone())));
        let (n2, sec2, me) = (n.clone(), section.clone(), Rc::downgrade(self));
        self.subs.follow(&n.changed, move |_| {
            while let Some(c) = list.first_child() {
                list.remove(&c);
            }
            let items = n2.history();
            sec2.set_visible(!items.is_empty());
            for item in items.iter().take(30) {
                let card = crate::ui::notify::build_card(item, -1, false);
                card.root.add_css_class("compact");
                let (id, nn) = (item.id, n2.clone());
                card.close.connect_clicked(move |_| nn.close(id, Reason::Dismissed));
                if item.default_action() {
                    let (nn, me) = (n2.clone(), me.clone());
                    let click = gtk::GestureClick::new();
                    click.connect_released(move |_, _, _, _| {
                        nn.invoke(id, "default");
                        if let Some(me) = me.upgrade() { me.close() }
                    });
                    card.root.add_controller(click);
                }
                list.append(&card.root);
            }
            if let Some(me) = me.upgrade() {
                me.size_notifications();
            }
        });
        section.upcast()
    }

    /// How tall the notification list may be on `monitor`: the screen less the
    /// bar, the gaps and the rest of the popup.
    fn limit_notifications(&self, monitor: &gdk::Monitor, cfg: &Config) {
        let (Some((scroller, _)), Some(col)) = (self.notif.borrow().clone(), self.main_col.borrow().clone()) else { return };
        scroller.set_min_content_height(0);
        scroller.set_max_content_height(0);
        let (_, rest, _, _) = col.measure(gtk::Orientation::Vertical, PANEL_WIDTH - 28);
        let bar = cfg.height.max(30) + cfg.margins[0] + cfg.margins[2];
        // 8 px gaps above/below, the panel's own padding (~28) and a little air
        let room = monitor.geometry().height() - bar - rest - 16 - 28 - 24;
        self.notif_max.set(room.max(120));
        self.size_notifications();
    }

    /// While open: keep sampling what's behind the popup (the compositor's
    /// glass probe — the popup's own text isn't in it), so the text follows a
    /// page scrolling underneath, like the demo's draggable pane. Stock sway
    /// has no probe: the snapshot from opening stays.
    fn follow_backdrop(self: &Rc<Self>) {
        if backdrop::compositor_ink() {
            return; // the compositor inks the text: nothing to follow
        }
        let generation = self.opened.get();
        let me = Rc::downgrade(self);
        glib::timeout_add_local(std::time::Duration::from_millis(250), move || {
            let Some(me) = me.upgrade() else { return glib::ControlFlow::Break };
            if me.opened.get() != generation || me.closing.get() {
                return glib::ControlFlow::Break;
            }
            let Some(win) = me.win.borrow().clone() else { return glib::ControlFlow::Break };
            let monitor = me.backdrop.borrow().as_ref().map(|(_, m)| m.clone())
                .or_else(backdrop::focused_monitor);
            let Some(monitor) = monitor else { return glib::ControlFlow::Continue };
            match backdrop::Grid::probe(&monitor, NAMESPACE, (win.width(), win.height())) {
                Some(grid) => {
                    me.backdrop.replace(Some((Rc::new(grid), monitor)));
                    me.retag();
                    glib::ControlFlow::Continue
                }
                None => glib::ControlFlow::Continue,
            }
        });
    }

    /// Tag each pane light or dark by what was behind the popup as it opened.
    fn retag(&self) {
        let Some((grid, monitor)) = self.backdrop.borrow().clone() else { return };
        let Some(win) = self.win.borrow().clone() else { return };
        let Some(root) = win.child() else { return };
        if let Some(origin) = backdrop::layer_origin(&monitor, NAMESPACE) {
            backdrop::tag_panes(&root, &win, &grid, origin);
        }
    }

    /// The list's natural height, capped: scrolls beyond that.
    fn size_notifications(&self) {
        let Some((scroller, list)) = self.notif.borrow().clone() else { return };
        let (_, natural, _, _) = list.measure(gtk::Orientation::Vertical, PANEL_WIDTH - 28);
        let h = natural.min(self.notif_max.get()).max(0);
        // max first: GTK refuses a min above the current max
        scroller.set_max_content_height(h.max(scroller.min_content_height()));
        scroller.set_min_content_height(h);
        scroller.set_max_content_height(h);
        // already open: let the surface follow (a GTK window never shrinks by itself)
        if let Some(win) = self.win.borrow().as_ref() {
            if let Some(pane) = win.child().and_downcast::<gtk::Fixed>().and_then(|f| f.first_child()) {
                if !self.closing.get() {
                    fit(win, &pane);
                }
            }
        }
        // the list changed: its cards need their light/dark too
        self.retag();
    }

    fn lock(self: &Rc<Self>) {
        match &self.svc.session {
            Some(s) => dbus::center_action(s.clone(), "lock"),
            None => procs::spawn(&["swaylock", "-f"]),
        }
        self.close();
    }

    fn sub_page(&self, title: &str, body: &gtk::Widget) -> adw::NavigationPage {
        let view = adw::ToolbarView::new();
        let header = adw::HeaderBar::builder().show_end_title_buttons(false).show_start_title_buttons(false).build();
        header.add_css_class("flat");
        view.add_top_bar(&header);
        view.set_content(Some(body));
        adw::NavigationPage::builder().title(title).child(&view).build()
    }

    fn list() -> gtk::ListBox {
        gtk::ListBox::builder().selection_mode(gtk::SelectionMode::None).css_classes(["boxed-list"]).build()
    }

    fn wifi_page(self: &Rc<Self>) -> adw::NavigationPage {
        let body = gtk::Box::builder().orientation(gtk::Orientation::Vertical).spacing(10).build();
        let list = Self::list();
        let spinner = adw::Spinner::new();
        body.append(&spinner);
        let scroller = gtk::ScrolledWindow::builder().hscrollbar_policy(gtk::PolicyType::Never)
            .propagate_natural_height(true).max_content_height(320).child(&list).build();
        body.append(&scroller);
        let me = Rc::downgrade(self);
        let more = gtk::Button::builder().label("Wi-Fi Settings…").css_classes(["flat", "pane"]).build();
        more.connect_clicked(move |_| if let Some(me) = me.upgrade() { me.settings("system:network") });
        body.append(&more);
        if let Some(sys) = self.svc.system.clone() {
            let me = Rc::downgrade(self);
            // rebuilt whenever NetworkManager changes something, while the page lives
            let (weak_list, weak_spinner) = (list.downgrade(), spinner.downgrade());
            let busy = Rc::new(std::cell::Cell::new(false));
            dbus::on_any_change(sys.clone(), "org.freedesktop.NetworkManager", move || {
                let (Some(list), Some(spinner)) = (weak_list.upgrade(), weak_spinner.upgrade()) else { return false };
                if busy.replace(true) {
                    return true;
                }
                let (sys, me, busy) = (sys.clone(), me.clone(), busy.clone());
                glib::spawn_future_local(async move {
                    let aps = dbus::access_points(&sys).await;
                    busy.set(false);
                    spinner.set_visible(false);
                    while let Some(c) = list.first_child() {
                        list.remove(&c);
                    }
                    Self::fill_wifi(&list, aps, &sys, &me);
                });
                true
            });
        }
        self.sub_page("Wi-Fi", body.upcast_ref())
    }

    fn fill_wifi(list: &gtk::ListBox, aps: Vec<dbus::AccessPoint>, sys: &zbus::Connection, me: &std::rc::Weak<Self>) {
        if aps.is_empty() {
            list.append(&gtk::Label::builder().label("No networks found").css_classes(["dim-label"]).margin_top(12).margin_bottom(12).build());
        }
        for ap in aps {
            let row = adw::ActionRow::builder().title(glib::markup_escape_text(&ap.ssid)).activatable(true).build();
            row.add_prefix(&gtk::Image::from_icon_name(icons::wifi_strength(ap.strength)));
            if ap.secure {
                row.add_suffix(&gtk::Image::from_icon_name("system-lock-screen-symbolic"));
            }
            if ap.active {
                row.add_suffix(&gtk::Image::from_icon_name("object-select-symbolic"));
            }
            let (sys, me) = (sys.clone(), me.clone());
            row.connect_activated(move |_| {
                let (sys, ap, me) = (sys.clone(), ap.clone(), me.clone());
                glib::spawn_future_local(async move {
                    if !dbus::activate(&sys, &ap).await {
                        // needs a password: the full settings page asks for it
                        if let Some(me) = me.upgrade() { me.settings("system:network") }
                    }
                });
            });
            list.append(&row);
        }
    }

    fn sink_page(self: &Rc<Self>) -> adw::NavigationPage {
        let list = Self::list();
        let mut first: Option<gtk::CheckButton> = None;
        for sink in procs::sinks() {
            let check = gtk::CheckButton::builder().active(sink.default).build();
            if let Some(f) = &first { check.set_group(Some(f)); } else { first = Some(check.clone()); }
            let row = adw::ActionRow::builder().title(glib::markup_escape_text(&sink.description)).activatable_widget(&check).build();
            row.add_prefix(&check);
            let name = sink.name.clone();
            check.connect_toggled(move |c| if c.is_active() { procs::set_default_sink(&name) });
            list.append(&row);
        }
        self.sub_page("Sound Output", list.upcast_ref())
    }

    fn profile_page(self: &Rc<Self>) -> adw::NavigationPage {
        let list = Self::list();
        let current = self.svc.profile.get();
        let mut first: Option<gtk::CheckButton> = None;
        for p in ["power-saver", "balanced", "performance"] {
            let check = gtk::CheckButton::builder().active(p == current).build();
            if let Some(f) = &first { check.set_group(Some(f)); } else { first = Some(check.clone()); }
            let row = adw::ActionRow::builder().title(profile_label(p)).activatable_widget(&check).build();
            row.add_prefix(&gtk::Image::from_icon_name(&format!("power-profile-{p}-symbolic")));
            row.add_suffix(&check);
            let sys = self.svc.system.clone();
            check.connect_toggled(move |c| {
                if let (true, Some(sys)) = (c.is_active(), sys.clone()) {
                    dbus::set_power_profile(sys, p.to_owned());
                }
            });
            list.append(&row);
        }
        self.sub_page("Power Mode", list.upcast_ref())
    }

    fn power_page(self: &Rc<Self>) -> adw::NavigationPage {
        let list = Self::list();
        let items: [(&str, &str, Box<dyn Fn()>); 4] = [
            ("weather-clear-night-symbolic", "Suspend", Box::new(|| procs::spawn(&["systemctl", "suspend"]))),
            ("system-log-out-symbolic", "Log Out", Box::new(|| sway::command("exit"))),
            ("system-reboot-symbolic", "Restart", Box::new(|| procs::spawn(&["systemctl", "reboot"]))),
            ("system-shutdown-symbolic", "Shut Down", Box::new(|| procs::spawn(&["systemctl", "poweroff"]))),
        ];
        for (icon, title, act) in items {
            let row = adw::ActionRow::builder().title(title).activatable(true).build();
            row.add_prefix(&gtk::Image::from_icon_name(icon));
            let me = Rc::downgrade(self);
            row.connect_activated(move |_| {
                if let Some(me) = me.upgrade() { me.close() }
                act();
            });
            list.append(&row);
        }
        self.sub_page("Power", list.upcast_ref())
    }
}

fn profile_label(p: &str) -> String {
    match p {
        "power-saver" => "Power Saver",
        "performance" => "Performance",
        "balanced" => "Balanced",
        other => other,
    }
    .to_owned()
}

/// Size the popup window to its pane exactly (shrinking it if needed).
fn fit(win: &gtk::Window, pane: &gtk::Widget) {
    let (min_w, nat_w, _, _) = pane.measure(gtk::Orientation::Horizontal, -1);
    let w = nat_w.min(PANEL_WIDTH).max(min_w);
    let (_, h, _, _) = pane.measure(gtk::Orientation::Vertical, w);
    win.set_default_size(w, h);
}

/// Keep the stage at the card's size while it animates, so the layer surface
/// doesn't resize every frame. Exactly the card's size: the compositor draws
/// the shadow and glass for the whole surface, so no slack around it (the
/// slide in from the bar is clipped at the top instead).
fn freeze_size(stage: &gtk::Fixed, card: &gtk::Widget) {
    let (min_w, nat_w, _, _) = card.measure(gtk::Orientation::Horizontal, -1);
    let w = nat_w.min(PANEL_WIDTH).max(min_w);
    let (_, h, _, _) = card.measure(gtk::Orientation::Vertical, w);
    stage.set_size_request(w, h);
}

/// Progress 0 (hidden) .. 1 (open): fade, slide from the bar, scale 0.96 -> 1
/// around the top edge.
fn place(stage: &gtk::Fixed, card: &gtk::Widget, v: f64) {
    let v = v as f32;
    card.set_opacity(v.clamp(0.0, 1.0) as f64);
    let w = card.width().max(stage.width_request()) as f32;
    // "liquid" open: grows out of the status button (top right) taller-than-
    // wide, and the spring's overshoot makes it bulge a little and settle,
    // like a drop of glass finding its shape
    // never larger than the card: an overshoot that grew it would grow the
    // layer surface too, and it doesn't shrink back (a second, empty pane of
    // glass behind it). The bounce shows as a quick squash-and-settle instead.
    let k = (1.0 - v).abs();
    let sx = 1.0 - 0.10 * k;
    let sy = 1.0 - 0.24 * k;
    let origin = graphene::Point::new(w - 48.0, 0.0);
    let t = gsk::Transform::new()
        .translate(&graphene::Point::new(origin.x(), origin.y() - (1.0 - v).max(0.0) * SLIDE))
        .scale(sx, sy)
        .translate(&graphene::Point::new(-origin.x(), -origin.y()));
    stage.set_child_transform(card, Some(&t));
}

/// A rounded toggle with an icon, a title, a state line and an optional arrow
/// that opens more.
#[derive(Clone)]
struct Tile {
    root: gtk::Box,
    button: gtk::Button,
    icon: gtk::Image,
    sub: gtk::Label,
    active: Rc<Cell<bool>>,
}

impl Tile {
    fn new(icon: &str, title: &str, more: Option<Box<dyn Fn()>>) -> Self {
        let root = gtk::Box::builder().css_classes(["tile"]).build();
        let inner = gtk::Box::builder().spacing(10).build();
        let icon = gtk::Image::from_icon_name(icon);
        let text = gtk::Box::builder().orientation(gtk::Orientation::Vertical).valign(gtk::Align::Center).build();
        text.append(&gtk::Label::builder().label(title).xalign(0.0).css_classes(["tile-title"]).build());
        let sub = gtk::Label::builder().xalign(0.0).ellipsize(gtk::pango::EllipsizeMode::End).max_width_chars(12)
            .css_classes(["tile-sub"]).build();
        text.append(&sub);
        inner.append(&icon);
        inner.append(&text);
        let button = gtk::Button::builder().child(&inner).hexpand(true).css_classes(["tile-main"]).build();
        root.append(&button);
        if let Some(more) = more {
            let arrow = gtk::Button::builder().icon_name("go-next-symbolic").css_classes(["tile-more"]).build();
            arrow.connect_clicked(move |_| more());
            root.append(&arrow);
        }
        Self { root, button, icon, sub, active: Rc::new(Cell::new(false)) }
    }

    fn set(&self, active: bool, sub: &str) {
        self.active.set(active);
        self.sub.set_label(sub);
        if active { self.root.add_css_class("active") } else { self.root.remove_css_class("active") }
    }
}

fn slider_row(icon: &str, value: f64, max: f64) -> (gtk::Box, gtk::Scale, gtk::Image) {
    let row = gtk::Box::builder().spacing(8).css_classes(["slider-row"]).build();
    let image = gtk::Image::from_icon_name(icon);
    let scale = gtk::Scale::with_range(gtk::Orientation::Horizontal, 0.0, max, 1.0);
    scale.set_value(value);
    scale.set_hexpand(true);
    row.append(&image);
    row.append(&scale);
    (row, scale, image)
}
