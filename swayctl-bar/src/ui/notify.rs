//! Notification popups: a stack of cards in one layer-shell surface, in the
//! corner chosen in settings. Each card slides in (revealer + fade), waits
//! (paused while the pointer is on it) and slides out. The surface is resized
//! to the cards after every change: an oversized transparent surface would
//! still catch clicks, and the compositor's glass follows the cards' shape.

use crate::config;
use crate::services::notify::{Image, Notification, Notifier, Reason};
use adw::prelude::*;
use gtk::{gdk, glib};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use std::cell::RefCell;
use std::rc::Rc;
use std::time::Duration;

pub const NAMESPACE: &str = "swayctl-notifications";
const SLIDE_MS: u32 = 220;

struct Card {
    id: u32,
    revealer: gtk::Revealer,
    n: RefCell<Notification>,
    timer: RefCell<Option<glib::SourceId>>,
}

pub struct Popups {
    app: adw::Application,
    notifier: Rc<Notifier>,
    cfg: RefCell<config::Notifications>,
    win: RefCell<Option<gtk::Window>>,
    stack: gtk::Box,
    cards: RefCell<Vec<Rc<Card>>>,
    /// what's behind the column of cards (taken as the first one comes)
    backdrop: RefCell<Option<(Rc<crate::ui::backdrop::Grid>, gdk::Monitor)>>,
}

impl Popups {
    pub fn new(app: &adw::Application, notifier: &Rc<Notifier>, cfg: &config::Notifications) -> Rc<Self> {
        let me = Rc::new(Self {
            app: app.clone(),
            notifier: notifier.clone(),
            cfg: RefCell::new(cfg.clone()),
            win: RefCell::new(None),
            stack: gtk::Box::builder().orientation(gtk::Orientation::Vertical).css_classes(["notification-stack"]).build(),
            cards: RefCell::new(Vec::new()),
            backdrop: RefCell::new(None),
        });
        let w = Rc::downgrade(&me);
        notifier.connect_show(move |n, replaced| if let Some(me) = w.upgrade() { me.show(n, replaced) });
        let w = Rc::downgrade(&me);
        notifier.connect_close(move |id| if let Some(me) = w.upgrade() { me.remove(id) });
        // turning do-not-disturb on clears what's on screen
        let w = Rc::downgrade(&me);
        notifier.dnd.subscribe(move |on| {
            if let (true, Some(me)) = (*on, w.upgrade()) {
                me.clear_screen();
            }
        });
        me
    }

    /// Take every card off the screen (Quick Settings lists them instead).
    pub fn clear_screen(self: &Rc<Self>) {
        let ids: Vec<u32> = self.cards.borrow().iter().map(|c| c.id).collect();
        ids.into_iter().for_each(|id| self.remove(id));
    }

    pub fn set_config(&self, cfg: &config::Notifications) {
        if *self.cfg.borrow() == *cfg {
            return;
        }
        *self.cfg.borrow_mut() = cfg.clone();
        // placed again on the next notification
        if let Some(w) = self.win.take() {
            w.set_child(None::<&gtk::Widget>);
            w.close();
        }
    }

    fn window(&self) -> gtk::Window {
        if let Some(w) = self.win.borrow().clone() {
            return w;
        }
        let cfg = self.cfg.borrow().clone();
        let win = gtk::Window::builder().application(&self.app).css_classes(["notification-window"]).build();
        win.init_layer_shell();
        win.set_namespace(Some(NAMESPACE));
        win.set_layer(Layer::Overlay);
        win.set_keyboard_mode(KeyboardMode::None);
        if !cfg.output.is_empty() {
            if let Some(m) = monitor(&cfg.output) {
                win.set_monitor(Some(&m));
            }
        }
        match cfg.position_y.as_str() {
            "bottom" => win.set_anchor(Edge::Bottom, true),
            "center" => {}
            _ => win.set_anchor(Edge::Top, true),
        }
        match cfg.position_x.as_str() {
            "left" => win.set_anchor(Edge::Left, true),
            "center" => {}
            _ => win.set_anchor(Edge::Right, true),
        }
        for e in [Edge::Top, Edge::Bottom, Edge::Left, Edge::Right] {
            win.set_margin(e, 8);
        }
        self.stack.set_spacing(0);
        if let Some(p) = self.stack.parent() {
            if let Ok(old) = p.downcast::<gtk::Window>() {
                old.set_child(None::<&gtk::Widget>);
            }
        }
        win.set_child(Some(&self.stack));
        self.win.replace(Some(win.clone()));
        win
    }

    fn show(self: &Rc<Self>, n: &Notification, replaced: bool) {
        let cfg = self.cfg.borrow().clone();
        // an update to one already on screen replaces it in place
        if replaced {
            if let Some(c) = self.cards.borrow().iter().find(|c| c.id == n.id).cloned() {
                c.revealer.set_child(Some(&self.card(n, &cfg)));
                *c.n.borrow_mut() = n.clone();
                self.arm(&c);
                return;
            }
        }
        let bottom = cfg.position_y == "bottom";
        let revealer = gtk::Revealer::builder()
            .transition_type(if bottom { gtk::RevealerTransitionType::SlideUp } else { gtk::RevealerTransitionType::SlideDown })
            .transition_duration(SLIDE_MS)
            .child(&self.card(n, &cfg))
            .build();
        let c = Rc::new(Card { id: n.id, revealer: revealer.clone(), n: RefCell::new(n.clone()), timer: RefCell::new(None) });
        // the pointer on a card pauses its timeout
        let motion = gtk::EventControllerMotion::new();
        let card = Rc::downgrade(&c);
        motion.connect_enter(move |_, _, _| {
            if let Some(t) = card.upgrade().and_then(|c| c.timer.take()) {
                t.remove();
            }
        });
        let (me, card) = (Rc::downgrade(self), Rc::downgrade(&c));
        motion.connect_leave(move |_| {
            if let (Some(me), Some(c)) = (me.upgrade(), card.upgrade()) {
                me.arm(&c);
            }
        });
        revealer.add_controller(motion);
        // newest nearest the screen edge
        if bottom { self.stack.append(&revealer) } else { self.stack.prepend(&revealer) }
        self.cards.borrow_mut().push(c.clone());
        let win = self.window();
        if !win.is_visible() {
            // nothing of ours on screen yet: what's there will be behind the cards
            let m = if cfg.output.is_empty() { crate::ui::backdrop::focused_monitor() } else { monitor(&cfg.output) };
            self.backdrop.replace(m.and_then(|m| crate::ui::backdrop::Grid::capture(&m).map(|g| (Rc::new(g), m))));
        }
        win.present();
        glib::idle_add_local_once(move || revealer.set_reveal_child(true));
        // once it has slid in: light or dark text per card
        let me = Rc::downgrade(self);
        glib::timeout_add_local_once(Duration::from_millis(SLIDE_MS as u64 + 60), move || {
            if let Some(me) = me.upgrade() { me.retag() }
        });
        self.arm(&c);
        // too many: the oldest leave the screen (they stay in Quick Settings)
        let extra: Vec<u32> = {
            let cards = self.cards.borrow();
            let n = cards.len().saturating_sub(cfg.max_visible.max(1));
            cards.iter().take(n).map(|c| c.id).collect()
        };
        for id in extra {
            self.remove(id);
        }
    }

    /// (Re)start the card's timeout.
    fn arm(self: &Rc<Self>, c: &Rc<Card>) {
        if let Some(t) = c.timer.take() {
            t.remove();
        }
        if !self.cards.borrow().iter().any(|o| Rc::ptr_eq(o, c)) {
            return; // already leaving
        }
        let (expire, urgency) = { let n = c.n.borrow(); (n.expire_timeout, n.urgency) };
        let cfg = self.cfg.borrow();
        let secs = match expire {
            0 => 0,
            ms if ms > 0 => (ms as u32).div_ceil(1000),
            _ => match urgency { 0 => cfg.timeout_low, 2 => cfg.timeout_critical, _ => cfg.timeout },
        };
        if secs == 0 {
            return;
        }
        let (me, id) = (Rc::downgrade(self), c.id);
        *c.timer.borrow_mut() = Some(glib::timeout_add_local_once(Duration::from_secs(secs as u64), move || {
            if let Some(me) = me.upgrade() {
                if let Some(c) = me.cards.borrow().iter().find(|c| c.id == id) {
                    c.timer.take();
                }
                me.remove(id);
                me.notifier.expired(id);
            }
        }));
    }

    /// Slide a card out (no signal: the caller says why it went).
    fn remove(self: &Rc<Self>, id: u32) {
        let c = {
            let mut cards = self.cards.borrow_mut();
            let Some(i) = cards.iter().position(|c| c.id == id) else { return };
            cards.remove(i)
        };
        if let Some(t) = c.timer.take() {
            t.remove();
        }
        let me = Rc::downgrade(self);
        c.revealer.connect_child_revealed_notify(move |r| {
            if r.reveals_child() || r.is_child_revealed() {
                return;
            }
            let Some(me) = me.upgrade() else { return };
            me.stack.remove(r);
            me.fit();
        });
        c.revealer.set_reveal_child(false);
    }

    fn retag(&self) {
        let Some((grid, m)) = self.backdrop.borrow().clone() else { return };
        let Some(win) = self.win.borrow().clone() else { return };
        if let Some(origin) = crate::ui::backdrop::layer_origin(&m, NAMESPACE) {
            crate::ui::backdrop::tag_panes(self.stack.upcast_ref(), &win, &grid, origin);
        }
    }

    /// Shrink the surface to the cards, or hide it when there are none.
    fn fit(&self) {
        let Some(win) = self.win.borrow().clone() else { return };
        if self.stack.first_child().is_none() {
            win.set_visible(false);
            self.backdrop.replace(None);
            return;
        }
        let w = self.cfg.borrow().width;
        let (_, h, _, _) = self.stack.measure(gtk::Orientation::Vertical, w);
        win.set_default_size(w, h);
    }

    fn card(self: &Rc<Self>, n: &Notification, cfg: &config::Notifications) -> gtk::Widget {
        let id = n.id;
        let card = build_card(n, cfg.width, true);
        // spacing lives inside the revealer, so it collapses with the card
        let pad = gtk::Box::builder().margin_bottom(8).build();
        if cfg.position_y == "bottom" {
            pad.set_margin_bottom(0);
            pad.set_margin_top(8);
        }
        pad.append(&card.root);
        let (me, has_default) = (Rc::downgrade(self), n.default_action());
        let click = gtk::GestureClick::new();
        click.connect_released(move |g, _, _, _| {
            let Some(me) = me.upgrade() else { return };
            g.set_state(gtk::EventSequenceState::Claimed);
            if has_default {
                me.notifier.invoke(id, "default");
            } else {
                me.remove(id);
            }
        });
        card.root.add_controller(click);
        let me = Rc::downgrade(self);
        card.close.connect_clicked(move |_| if let Some(me) = me.upgrade() { me.notifier.close(id, Reason::Dismissed) });
        for (b, key) in card.actions {
            let me = Rc::downgrade(self);
            b.connect_clicked(move |_| if let Some(me) = me.upgrade() { me.notifier.invoke(id, &key) });
        }
        pad.upcast()
    }
}

pub struct CardWidgets {
    pub root: gtk::Box,
    pub close: gtk::Button,
    pub actions: Vec<(gtk::Button, String)>,
}

/// One notification card; also used (compact, without actions) in Quick Settings.
pub fn build_card(n: &Notification, width: i32, full: bool) -> CardWidgets {
    let root = gtk::Box::builder().orientation(gtk::Orientation::Vertical).spacing(6).width_request(width)
        .css_classes(["notification-card"]).build();
    match n.urgency {
        0 => root.add_css_class("low"),
        2 => root.add_css_class("critical"),
        _ => {}
    }
    let head = gtk::Box::builder().spacing(10).build();
    if let Some(img) = n.image.as_ref().and_then(image_widget) {
        head.append(&img);
    }
    let text = gtk::Box::builder().orientation(gtk::Orientation::Vertical).spacing(2).hexpand(true).build();
    let top = gtk::Box::builder().spacing(6).build();
    let app = gtk::Label::builder().label(&n.app_name).xalign(0.0).hexpand(true)
        .ellipsize(gtk::pango::EllipsizeMode::End).width_chars(1).css_classes(["caption", "notification-app"]).build();
    top.append(&app);
    let when = glib::DateTime::from_unix_local(n.time).ok().and_then(|t| t.format("%H:%M").ok());
    if let Some(when) = when {
        top.append(&gtk::Label::builder().label(when.as_str()).css_classes(["caption", "dim-label", "numeric"]).build());
    }
    text.append(&top);
    let summary = gtk::Label::builder().label(&n.summary).xalign(0.0).wrap(true)
        .wrap_mode(gtk::pango::WrapMode::WordChar).width_chars(1).css_classes(["notification-summary"]).build();
    if !full {
        summary.set_wrap(false);
        summary.set_ellipsize(gtk::pango::EllipsizeMode::End);
    }
    text.append(&summary);
    if !n.body.is_empty() {
        let body = gtk::Label::builder().xalign(0.0).wrap(true).wrap_mode(gtk::pango::WrapMode::WordChar)
            .width_chars(1).lines(if full { 6 } else { 2 }).ellipsize(gtk::pango::EllipsizeMode::End)
            .css_classes(["notification-body"]).build();
        set_body(&body, &n.body);
        text.append(&body);
    }
    head.append(&text);
    let close = gtk::Button::builder().icon_name("window-close-symbolic").valign(gtk::Align::Start)
        .css_classes(["flat", "circular", "notification-close"]).build();
    head.append(&close);
    root.append(&head);
    let mut actions = Vec::new();
    let buttons: Vec<_> = n.actions.iter().filter(|(k, _)| k != "default").collect();
    if full && !buttons.is_empty() {
        let row = gtk::Box::builder().spacing(6).homogeneous(true).css_classes(["notification-actions"]).build();
        for (key, label) in buttons {
            let b = gtk::Button::builder().label(label).css_classes(["notification-action"]).build();
            row.append(&b);
            actions.push((b, key.clone()));
        }
        root.append(&row);
    }
    CardWidgets { root, close, actions }
}

/// Body markup is a small subset of Pango's (b, i, u, a, img); anything that
/// doesn't parse is shown as plain text.
fn set_body(label: &gtk::Label, body: &str) {
    let cleaned = body.replace("<br>", "\n").replace("<br/>", "\n");
    if gtk::pango::parse_markup(&cleaned, '\0').is_ok() {
        label.set_markup(&cleaned);
    } else {
        label.set_text(body);
    }
}

fn image_widget(img: &Image) -> Option<gtk::Image> {
    let w = match img {
        Image::Name(name) => gtk::Image::from_icon_name(name),
        Image::Path(p) => {
            let tex = gdk::Texture::from_filename(p).ok()?;
            gtk::Image::from_paintable(Some(&tex))
        }
        Image::Data(w, h, stride, alpha, bytes) => {
            let fmt = if *alpha { gdk::MemoryFormat::R8g8b8a8 } else { gdk::MemoryFormat::R8g8b8 };
            let tex = gdk::MemoryTexture::new(*w, *h, fmt, &glib::Bytes::from(bytes), *stride as usize);
            gtk::Image::from_paintable(Some(&tex))
        }
    };
    w.set_pixel_size(40);
    w.set_valign(gtk::Align::Start);
    w.add_css_class("notification-image");
    Some(w)
}

fn monitor(connector: &str) -> Option<gdk::Monitor> {
    let monitors = gdk::Display::default()?.monitors();
    (0..monitors.n_items())
        .filter_map(|i| monitors.item(i).and_downcast::<gdk::Monitor>())
        .find(|m| m.connector().as_deref() == Some(connector))
}
