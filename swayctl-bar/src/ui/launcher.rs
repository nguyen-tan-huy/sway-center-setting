//! Spotlight-style launcher (`swayctl-bar launcher`), the look settled in
//! tools/spotlight-demo.html: a search capsule, a results sheet (Top Hit, then
//! grouped by kind) and a key-hint strip — three panes of liquid glass whose
//! text follows what's behind them like Quick Settings. Results come from
//! elephant (services/elephant.rs); a first character can switch to one
//! provider (= calculator, / files, . emoji, ...), as the settings say.
//! ":" is the clipboard history, read from cliphist (services/clipboard.rs).

use crate::config::Launcher as Config;
use crate::services::clipboard;
use crate::services::elephant::{Elephant, Item, Msg};
use crate::ui::{backdrop, catcher};
use adw::prelude::*;
use gtk::{gdk, glib, graphene, gsk};
use gtk4_layer_shell::{Edge, KeyboardMode, Layer, LayerShell};
use std::cell::{Cell, RefCell};
use std::rc::Rc;

pub const NAMESPACE: &str = "swayctl-launcher";
const WIDTH: i32 = 720;
const EMOJI_COLS: usize = 10;
/// provider -> section heading, in the order sections are listed
const SECTIONS: [(&str, &str); 6] = [
    ("desktopapplications", "Applications"),
    ("menus", "Settings"),
    ("files", "Documents"),
    ("windows", "Windows"),
    ("websearch", "Web"),
    ("runner", "Run"),
];

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Suggest,
    List,
    Calc,
    Emoji,
    /// clipboard history (cliphist), newest first, no Top Hit
    Clip,
}
/// clipboard rows shown at most
const CLIP_MAX: usize = 60;

pub struct Launcher {
    app: adw::Application,
    cfg: RefCell<Config>,
    elephant: Elephant,
    win: RefCell<Option<gtk::Window>>,
    catcher: RefCell<Option<gtk::Window>>,
    widgets: RefCell<Option<Widgets>>,
    /// the text the shown results are for, and the one asked last
    shown_for: RefCell<String>,
    asked: RefCell<String>,
    items: RefCell<Vec<Item>>,
    /// results for `asked` arriving: replace `items` on the first one
    fresh: Cell<bool>,
    kind: Cell<Kind>,
    sel: Cell<usize>,
    search_queued: Cell<bool>,
    /// the selectable widgets of the last render, by result index
    cells: RefCell<Vec<gtk::Widget>>,
    /// the results list scrolls past this height (px)
    scroll_max: Cell<i32>,
    /// clipboard image thumbnails by cliphist line
    thumbs: RefCell<std::collections::HashMap<String, gdk::Texture>>,
    monitor: RefCell<Option<gdk::Monitor>>,
    opened: Cell<u32>,
    closing: Cell<bool>,
}

trait EntryOf {
    fn clone_entry(&self) -> Option<gtk::Text>;
}

impl EntryOf for Option<Widgets> {
    fn clone_entry(&self) -> Option<gtk::Text> {
        self.as_ref().map(|w| w.entry.clone())
    }
}

struct Widgets {
    stage: gtk::Fixed,
    card: gtk::Box,
    entry: gtk::Text,
    mode: gtk::Label,
    suggest: gtk::Box,
    /// the rows (inside `scroll`, inside the glass pane `sheet`)
    results: gtk::Box,
    sheet: gtk::Box,
    scroll: gtk::ScrolledWindow,
    keys: gtk::Box,
}

impl Launcher {
    pub fn new(app: &adw::Application, cfg: &Config) -> Rc<Self> {
        let (elephant, rx) = Elephant::new();
        let me = Rc::new(Self {
            app: app.clone(),
            cfg: RefCell::new(cfg.clone()),
            elephant,
            win: RefCell::new(None),
            catcher: RefCell::new(None),
            widgets: RefCell::new(None),
            shown_for: RefCell::new(String::new()),
            asked: RefCell::new(String::new()),
            items: RefCell::new(Vec::new()),
            fresh: Cell::new(false),
            kind: Cell::new(Kind::Suggest),
            sel: Cell::new(0),
            search_queued: Cell::new(false),
            cells: RefCell::new(Vec::new()),
            scroll_max: Cell::new(500),
            thumbs: RefCell::new(std::collections::HashMap::new()),
            monitor: RefCell::new(None),
            opened: Cell::new(0),
            closing: Cell::new(false),
        });
        let weak = Rc::downgrade(&me);
        glib::spawn_future_local(async move {
            while let Ok(msg) = rx.recv().await {
                let Some(me) = weak.upgrade() else { return };
                me.on_msg(msg);
            }
        });
        me
    }

    pub fn set_config(&self, cfg: &Config) {
        *self.cfg.borrow_mut() = cfg.clone();
    }

    /// Open (if it isn't) with `text` in the search field.
    pub fn open_with(self: &Rc<Self>, monitor: &gdk::Monitor, text: &str) {
        if self.win.borrow().is_none() {
            self.open(monitor);
        }
        if let Some(w) = self.widgets.borrow().clone_entry() {
            w.set_text(text);
            w.set_position(-1);
        }
    }

    pub fn toggle(self: &Rc<Self>, monitor: &gdk::Monitor) {
        if self.win.borrow().is_some() {
            self.close();
        } else {
            self.open(monitor);
        }
    }

    // ---- results -----------------------------------------------------------

    /// (providers, query, kind, label) for what's typed: a prefix picks one
    /// provider, else the default list.
    fn route(&self, text: &str) -> (Vec<String>, String, Kind, String) {
        let cfg = self.cfg.borrow();
        for p in &cfg.prefixes {
            if !p.prefix.is_empty() && text.starts_with(&p.prefix) {
                let q = text[p.prefix.len()..].trim_start().to_owned();
                let kind = match p.provider.as_str() {
                    "calc" => Kind::Calc,
                    "symbols" => Kind::Emoji,
                    "clipboard" => Kind::Clip,
                    _ => Kind::List,
                };
                return (vec![p.provider.clone()], q, kind, p.label.clone());
            }
        }
        if text.trim().is_empty() {
            return (vec!["desktopapplications".into()], String::new(), Kind::Suggest, String::new());
        }
        (cfg.providers.clone(), text.trim().to_owned(), Kind::List, String::new())
    }

    /// Search once per main-loop turn: replacing the text is a delete and an
    /// insert (two `changed`), and the empty query in between must not win.
    fn queue_search(&self) {
        if self.search_queued.replace(true) {
            return;
        }
        let weak = self.self_weak();
        glib::idle_add_local_once(move || {
            if let Some(me) = weak.as_ref().and_then(|w| w.upgrade()) {
                me.search_queued.set(false);
                me.search();
            }
        });
    }

    fn search(&self) {
        let Some(text) = self.widgets.borrow().as_ref().map(|w| w.entry.text().to_string()) else { return };
        let (providers, query, kind, label) = self.route(&text);
        if let Some(w) = self.widgets.borrow().as_ref() {
            w.mode.set_label(&label);
            w.mode.set_visible(!label.is_empty());
        }
        if self.kind.replace(kind) != kind {
            // another kind of results (list / calculator / emoji): never
            // show the old ones in the new layout
            self.items.borrow_mut().clear();
            self.render(None);
        }
        self.sel.set(0);
        *self.asked.borrow_mut() = query.clone();
        if kind == Kind::Clip {
            self.search_clipboard(&query);
            return;
        }
        self.fresh.set(true);
        let max = match kind {
            Kind::Suggest => 60, // pinned apps are picked out of these
            Kind::Emoji => 40,
            _ => self.cfg.borrow().max_results,
        };
        if let Err(e) = self.elephant.query(&providers, &query, max) {
            eprintln!("swayctl-bar: launcher: {e}");
            self.items.borrow_mut().clear();
            self.render(Some("Elephant isn't running — the launcher needs it (swayctl-center starts it)."));
        }
    }

    /// The clipboard history matching `q` (no elephant: cliphist directly).
    fn search_clipboard(&self, q: &str) {
        let items: Vec<Item> = clipboard::list().into_iter()
            .filter_map(|e| {
                // one line in the list: newlines shown as ⏎
                let text: String = e.preview.replace('\n', " ⏎ ").chars().take(240).collect();
                let pos = match &e.image {
                    Some(_) => if q.trim().is_empty() || "image".contains(&q.trim().to_lowercase()) { vec![] } else { return None },
                    None => clipboard::matches(&text, q)?,
                };
                Some(Item {
                    identifier: e.line,
                    text: if e.image.is_some() { "Image".into() } else { text },
                    subtext: e.image.clone().unwrap_or_default(),
                    provider: "clipboard".into(),
                    fuzzyinfo: Some(crate::services::elephant::FuzzyInfo { start: 0, field: "text".into(), positions: pos }),
                    actions: vec!["copy".into(), "delete".into()],
                    ..Default::default()
                })
            })
            .take(CLIP_MAX)
            .collect();
        *self.items.borrow_mut() = items;
        *self.shown_for.borrow_mut() = q.to_owned();
        self.render(None);
    }

    /// Remove the selected clipboard entry and show the list again.
    fn delete_clip(&self) {
        let rows = self.ordered();
        let Some((it, _)) = rows.get(self.sel.get()) else { return };
        clipboard::delete(&it.identifier);
        self.thumbs.borrow_mut().remove(&it.identifier);
        let sel = self.sel.get();
        let q = self.asked.borrow().clone();
        self.search_clipboard(&q);
        self.sel.set(sel.min(self.items.borrow().len().saturating_sub(1)));
        self.render(None);
    }

    /// A thumbnail of a clipboard image (decoded once).
    fn thumb(&self, line: &str) -> Option<gdk::Texture> {
        if let Some(t) = self.thumbs.borrow().get(line) {
            return Some(t.clone());
        }
        let bytes = clipboard::decode(line)?;
        let t = gdk::Texture::from_bytes(&glib::Bytes::from_owned(bytes)).ok()?;
        self.thumbs.borrow_mut().insert(line.to_owned(), t.clone());
        Some(t)
    }

    fn on_msg(&self, msg: Msg) {
        match msg {
            Msg::Item { query, item } => {
                if query != *self.asked.borrow() {
                    return; // an older query still trickling in
                }
                if self.fresh.replace(false) {
                    self.items.borrow_mut().clear();
                }
                self.items.borrow_mut().push(item);
                *self.shown_for.borrow_mut() = query;
                self.queue_render();
            }
            Msg::NoResults => {
                if self.fresh.replace(false) {
                    self.items.borrow_mut().clear();
                    *self.shown_for.borrow_mut() = self.asked.borrow().clone();
                    self.queue_render();
                }
            }
            Msg::Done => {}
            Msg::Closed => self.elephant.reset(),
        }
    }

    fn queue_render(&self) {
        // results come in a burst: draw once per frame
        if let Some(w) = self.widgets.borrow().as_ref() {
            let me = w.card.clone();
            if me.has_css_class("render-queued") {
                return;
            }
            me.add_css_class("render-queued");
        }
        let weak = self.self_weak();
        glib::idle_add_local_once(move || {
            if let Some(me) = weak.as_ref().and_then(|w| w.upgrade()) {
                if let Some(w) = me.widgets.borrow().as_ref() {
                    w.card.remove_css_class("render-queued");
                }
                me.render(None);
            }
        });
    }

    fn self_weak(&self) -> Option<std::rc::Weak<Self>> {
        SELF.with(|s| s.borrow().clone())
    }

    /// Results in display order: Top Hit (best score) first, then by section.
    fn ordered(&self) -> Vec<(Item, bool)> {
        let mut items = self.items.borrow().clone();
        if self.kind.get() == Kind::Suggest {
            // Spotlight's row: the apps pinned in the launcher (elephant's
            // "pinned" state), each once; none pinned = just the search field
            let mut seen = std::collections::HashSet::new();
            items.retain(|i| i.state.iter().any(|s| s == "pinned") && seen.insert(i.text.clone()));
            items.truncate(7);
        }
        if self.kind.get() != Kind::List || items.is_empty() {
            return items.into_iter().map(|i| (i, false)).collect();
        }
        items.sort_by(|a, b| b.score.cmp(&a.score));
        let top = items.remove(0);
        let rank = |p: &str| SECTIONS.iter().position(|(k, _)| p.starts_with(k)).unwrap_or(SECTIONS.len());
        items.sort_by(|a, b| rank(&a.provider).cmp(&rank(&b.provider)).then(b.score.cmp(&a.score)));
        std::iter::once((top, true)).chain(items.into_iter().map(|i| (i, false))).collect()
    }

    fn render(&self, error: Option<&str>) {
        let Some(w) = self.widgets.borrow().as_ref().map(|w| (w.suggest.clone(), w.results.clone(), w.keys.clone(), w.sheet.clone())) else { return };
        let (suggest, results, keys, sheet) = w;
        self.cells.borrow_mut().clear();
        clear(&suggest);
        clear(&results);
        clear(&keys);
        let kind = self.kind.get();
        let rows = self.ordered();
        let n = rows.len();
        if self.sel.get() >= n.max(1) {
            self.sel.set(n.saturating_sub(1));
        }
        let sel = self.sel.get();
        suggest.set_visible(kind == Kind::Suggest && error.is_none() && n > 0);
        sheet.set_visible(kind != Kind::Suggest || error.is_some());
        keys.set_visible(kind != Kind::Suggest && error.is_none());

        if let Some(e) = error {
            results.append(&label(e, &["launcher-empty"]));
        } else if kind == Kind::Suggest {
            for (i, (it, _)) in rows.iter().enumerate() {
                let b = gtk::Box::builder().orientation(gtk::Orientation::Vertical).spacing(6)
                    .css_classes(["launcher-app"]).build();
                if i == sel {
                    b.add_css_class("selected");
                }
                b.append(&icon(&it.icon, 52));
                let name = it.text.split_whitespace().next().unwrap_or(&it.text).to_owned();
                b.append(&label(&name, &["launcher-app-name"]));
                self.clickable(&b, i);
                suggest.append(&b);
            }
        } else if n == 0 {
            let q = self.shown_for.borrow().clone();
            results.append(&label(&if q.is_empty() { "Type to search".into() } else { format!("No results for “{q}”") },
                                  &["launcher-empty"]));
        } else if kind == Kind::Calc {
            let it = &rows[0].0;
            results.append(&label("Calculator", &["launcher-section"]));
            results.append(&label(&it.text, &["launcher-calc"]));
            results.append(&self.row(it, false, true, 0));
            keys_line(&keys, &[("↩", "Copy"), ("esc", "Close")]);
        } else if kind == Kind::Clip {
            results.append(&label(&format!("Clipboard · {n}"), &["launcher-section"]));
            for (i, (it, _)) in rows.iter().enumerate() {
                results.append(&self.row(it, false, i == sel, i));
            }
            keys_line(&keys, &[("↑↓", "Choose"), ("↩", "Copy"), ("⇧⌫", "Delete"), ("esc", "Close")]);
        } else if kind == Kind::Emoji {
            results.append(&label("Emoji & Symbols", &["launcher-section"]));
            let grid = gtk::Grid::builder().column_homogeneous(true).row_spacing(4).column_spacing(4)
                .css_classes(["launcher-emoji"]).build();
            for (i, (it, _)) in rows.iter().enumerate() {
                let l = label(&it.icon, &["launcher-emoji-cell"]);
                l.set_tooltip_text(Some(&it.text));
                if i == sel {
                    l.add_css_class("selected");
                }
                self.clickable(&l, i);
                grid.attach(&l, (i % EMOJI_COLS) as i32, (i / EMOJI_COLS) as i32, 1, 1);
            }
            results.append(&grid);
            keys_line(&keys, &[("←→↑↓", "Choose"), ("↩", "Copy"), ("esc", "Close")]);
        } else {
            let mut section = String::new();
            for (i, (it, top)) in rows.iter().enumerate() {
                let name = if *top {
                    "Top Hit".to_owned()
                } else {
                    SECTIONS.iter().find(|(k, _)| it.provider.starts_with(k)).map(|(_, v)| v.to_string())
                        .unwrap_or_else(|| "Results".into())
                };
                if name != section {
                    results.append(&label(&name, &["launcher-section"]));
                    section = name;
                }
                results.append(&self.row(it, *top, i == sel, i));
            }
            list_keys(&keys, rows.get(sel).map(|(it, _)| it));
        }
        self.fit();
        self.retag();
        self.scroll_to(sel);
    }

    /// Move the highlight without rebuilding the list (a rebuild would lose
    /// the scroll position under the pointer).
    fn select(&self, i: usize) {
        let old = self.sel.replace(i);
        let cells = self.cells.borrow();
        for (k, on) in [(old, false), (i, true)] {
            if let Some(c) = cells.get(k) {
                if on { c.add_css_class("selected") } else { c.remove_css_class("selected") }
                // a row's "↩ Open" hint shows on the selected one only
                if let Some(h) = c.last_child().filter(|h| h.has_css_class("launcher-hint")) {
                    h.set_visible(on);
                }
            }
        }
        drop(cells);
        if self.kind.get() == Kind::List {
            if let Some(keys) = self.widgets.borrow().as_ref().map(|w| w.keys.clone()) {
                clear(&keys);
                list_keys(&keys, self.ordered().get(i).map(|(it, _)| it));
            }
        }
        self.scroll_to(i);
    }

    /// Keep result `i` in view (once it's laid out).
    fn scroll_to(&self, i: usize) {
        let Some(cell) = self.cells.borrow().get(i).cloned() else { return };
        let Some((scroll, list)) = self.widgets.borrow().as_ref().map(|w| (w.scroll.clone(), w.results.clone())) else { return };
        glib::idle_add_local_once(move || {
            let Some(b) = cell.compute_bounds(&list) else { return };
            let adj = scroll.vadjustment();
            let (y, h) = (b.y() as f64, b.height() as f64);
            // the first row: all the way up, so its section heading shows too
            if i == 0 {
                adj.set_value(0.0);
            } else if y < adj.value() {
                adj.set_value(y - 8.0);
            } else if y + h > adj.value() + adj.page_size() {
                adj.set_value(y + h - adj.page_size() + 8.0);
            }
        });
    }

    fn row(&self, it: &Item, top: bool, selected: bool, index: usize) -> gtk::Box {
        let row = gtk::Box::builder().spacing(12).css_classes(["launcher-row"]).build();
        if top {
            row.add_css_class("top");
        }
        if selected {
            row.add_css_class("selected");
        }
        let size = if top { 44 } else { 32 };
        if it.provider == "clipboard" {
            let w: gtk::Widget = match it.subtext.is_empty() {
                false => match self.thumb(&it.identifier) {
                    Some(t) => {
                        let img = gtk::Image::from_paintable(Some(&t));
                        img.set_pixel_size(size);
                        img.add_css_class("launcher-thumb");
                        img.upcast()
                    }
                    None => icon("image-x-generic", size),
                },
                true => icon("edit-paste", size),
            };
            row.append(&w);
        } else {
            row.append(&icon(&it.icon, size));
        }
        let txt = gtk::Box::builder().orientation(gtk::Orientation::Vertical).hexpand(true).valign(gtk::Align::Center).build();
        let title = gtk::Label::builder().xalign(0.0).ellipsize(gtk::pango::EllipsizeMode::End)
            .css_classes(["launcher-title"]).build();
        let fi = it.fuzzyinfo.as_ref().filter(|f| f.field == "text" || f.field.is_empty());
        title.set_markup(&highlight(&it.text, fi.map(|f| f.positions.as_slice()).unwrap_or(&[])));
        txt.append(&title);
        if !it.subtext.is_empty() {
            let sub = gtk::Label::builder().label(&it.subtext).xalign(0.0)
                .ellipsize(gtk::pango::EllipsizeMode::End).css_classes(["launcher-sub"]).build();
            txt.append(&sub);
        }
        row.append(&txt);
        let hint = label(&format!("↩ {}", action_label(it.actions.first().map(String::as_str).unwrap_or(""))),
                         &["launcher-hint"]);
        hint.set_visible(selected);
        row.append(&hint);
        self.clickable(&row, index);
        row
    }

    /// Hover selects, click runs.
    fn clickable(&self, w: &impl IsA<gtk::Widget>, index: usize) {
        {
            let mut cells = self.cells.borrow_mut();
            if cells.len() <= index {
                cells.resize(index + 1, w.clone().upcast());
            }
            cells[index] = w.clone().upcast();
        }
        let weak = self.self_weak();
        let motion = gtk::EventControllerMotion::new();
        let w2 = weak.clone();
        motion.connect_enter(move |_, _, _| {
            if let Some(me) = w2.as_ref().and_then(|w| w.upgrade()) {
                if me.sel.get() != index {
                    me.select(index);
                }
            }
        });
        w.add_controller(motion);
        let click = gtk::GestureClick::new();
        click.connect_released(move |_, _, _, _| {
            if let Some(me) = weak.as_ref().and_then(|w| w.upgrade()) {
                me.sel.set(index);
                me.run(0);
            }
        });
        w.add_controller(click);
    }

    /// Run the selected result's action `nth` (0 = default) and close.
    fn run(&self, nth: usize) {
        let rows = self.ordered();
        let Some((it, _)) = rows.get(self.sel.get()) else { return };
        let Some(action) = it.actions.get(nth).or(it.actions.first()) else { return };
        let query = self.asked.borrow().clone();
        if it.provider == "clipboard" {
            if action == "delete" {
                self.delete_clip();
                return;
            }
            clipboard::copy(&it.identifier);
        } else if let Err(e) = Elephant::activate(it, action, &query) {
            eprintln!("swayctl-bar: launcher: activate: {e}");
        }
        if let Some(me) = self.self_weak().and_then(|w| w.upgrade()) {
            me.close();
        }
    }

    fn step(&self, by: i32) {
        let n = self.ordered().len() as i32;
        if n == 0 {
            return;
        }
        let s = (self.sel.get() as i32 + by).clamp(0, n - 1);
        if s as usize != self.sel.get() {
            self.select(s as usize);
        }
    }

    // ---- window -------------------------------------------------------------

    fn open(self: &Rc<Self>, monitor: &gdk::Monitor) {
        SELF.with(|s| *s.borrow_mut() = Some(Rc::downgrade(self)));
        self.opened.set(self.opened.get().wrapping_add(1));
        *self.monitor.borrow_mut() = Some(monitor.clone());
        // before anything of ours is on screen: what will be behind it
        // (unless the compositor inks the text itself: then nothing is read)
        let ink = backdrop::compositor_ink();
        let grid = if ink { None } else { backdrop::Grid::capture(monitor).map(Rc::new) };

        let win = gtk::Window::builder().application(&self.app).css_classes(["launcher-window"]).build();
        backdrop::set_key_ink(&win, ink);
        win.init_layer_shell();
        win.set_namespace(Some(NAMESPACE));
        win.set_monitor(Some(monitor));
        win.set_layer(Layer::Overlay);
        win.set_keyboard_mode(KeyboardMode::Exclusive);
        win.set_anchor(Edge::Top, true);
        win.set_margin(Edge::Top, (monitor.geometry().height() as f32 * 0.18) as i32);
        win.set_exclusive_zone(-1);

        let card = gtk::Box::builder().orientation(gtk::Orientation::Vertical).spacing(10)
            .width_request(WIDTH).css_classes(["launcher"]).build();
        let search = gtk::Box::builder().spacing(14).css_classes(["pane", "launcher-search"]).build();
        let glass = gtk::Image::from_icon_name("system-search-symbolic");
        glass.set_pixel_size(22);
        glass.add_css_class("launcher-glass");
        let entry = gtk::Text::builder().hexpand(true).placeholder_text("Spotlight Search")
            .css_classes(["launcher-entry"]).build();
        let mode = gtk::Label::builder().css_classes(["launcher-mode"]).visible(false).build();
        search.append(&glass);
        search.append(&entry);
        search.append(&mode);
        let suggest = gtk::Box::builder().homogeneous(true).css_classes(["pane", "launcher-suggest"]).build();
        let results = gtk::Box::builder().orientation(gtk::Orientation::Vertical).build();
        // many results scroll inside the sheet (at most ~55 % of the screen)
        let scroll = gtk::ScrolledWindow::builder().hscrollbar_policy(gtk::PolicyType::Never)
            .child(&results).build();
        self.scroll_max.set((monitor.geometry().height() as f32 * 0.55) as i32);
        let sheet = gtk::Box::builder().orientation(gtk::Orientation::Vertical)
            .css_classes(["pane", "launcher-results"]).visible(false).build();
        sheet.append(&scroll);
        let keys = gtk::Box::builder().spacing(16).halign(gtk::Align::Center)
            .css_classes(["pane", "launcher-keys"]).visible(false).build();
        card.append(&search);
        card.append(&suggest);
        card.append(&sheet);
        card.append(&keys);
        let stage = gtk::Fixed::new();
        stage.put(&card, 0.0, 0.0);
        win.set_child(Some(&stage));

        let weak = Rc::downgrade(self);
        entry.connect_changed(move |_| {
            if let Some(me) = weak.upgrade() {
                me.queue_search();
            }
        });
        let weak = Rc::downgrade(self);
        entry.connect_activate(move |_| {
            if let Some(me) = weak.upgrade() {
                me.run(0);
            }
        });
        // capture: the text field would take the arrows otherwise
        let keyc = gtk::EventControllerKey::new();
        keyc.set_propagation_phase(gtk::PropagationPhase::Capture);
        let weak = Rc::downgrade(self);
        keyc.connect_key_pressed(move |_, key, _, state| {
            let Some(me) = weak.upgrade() else { return glib::Propagation::Proceed };
            let grid = me.kind.get() == Kind::Emoji;
            let row = me.kind.get() == Kind::Suggest;
            let ctrl = state.contains(gdk::ModifierType::CONTROL_MASK);
            match key {
                gdk::Key::Escape => {
                    let empty = me.widgets.borrow().as_ref().is_none_or(|w| w.entry.text().is_empty());
                    if empty {
                        me.close();
                    } else if let Some(w) = me.widgets.borrow().as_ref() {
                        w.entry.set_text("");
                    }
                }
                gdk::Key::Down if grid => me.step(EMOJI_COLS as i32),
                gdk::Key::Up if grid => me.step(-(EMOJI_COLS as i32)),
                gdk::Key::Right if grid || row => me.step(1),
                gdk::Key::Left if grid || row => me.step(-1),
                gdk::Key::Down | gdk::Key::Tab if !row => me.step(1),
                gdk::Key::Up | gdk::Key::ISO_Left_Tab if !row => me.step(-1),
                gdk::Key::Return | gdk::Key::KP_Enter => me.run(if ctrl { 1 } else { 0 }),
                gdk::Key::Delete | gdk::Key::KP_Delete
                    if me.kind.get() == Kind::Clip
                        && (ctrl || state.contains(gdk::ModifierType::SHIFT_MASK)) => me.delete_clip(),
                _ => return glib::Propagation::Proceed,
            }
            glib::Propagation::Stop
        });
        win.add_controller(keyc);

        *self.widgets.borrow_mut() = Some(Widgets { stage: stage.clone(), card: card.clone(), entry: entry.clone(),
                                                   mode, suggest, results, sheet, scroll, keys });
        let weak = Rc::downgrade(self);
        *self.catcher.borrow_mut() = Some(catcher::open(&self.app, monitor, move || {
            if let Some(me) = weak.upgrade() {
                me.close();
            }
        }));
        if let Some(g) = grid {
            self.items.borrow_mut().clear();
            BACKDROP.with(|b| *b.borrow_mut() = Some(g));
        }
        self.closing.set(false);
        self.items.borrow_mut().clear();
        self.render(None);
        self.search();
        place(&stage, &card, 0.0);
        win.present();
        entry.grab_focus();
        let target = {
            let (stage, card) = (stage.clone(), card.clone());
            adw::CallbackAnimationTarget::new(move |v| place(&stage, &card, v))
        };
        let anim = adw::SpringAnimation::new(&win, 0.0, 1.0, adw::SpringParams::new(0.72, 1.0, 420.0), target);
        anim.play();
        *self.win.borrow_mut() = Some(win);
        self.follow_backdrop();
    }

    pub fn close(&self) {
        let Some(win) = self.win.borrow().clone() else { return };
        if self.closing.replace(true) {
            return;
        }
        if let Some(c) = self.catcher.take() {
            c.close();
        }
        let Some((stage, card)) = self.widgets.borrow().as_ref().map(|w| (w.stage.clone(), w.card.clone())) else { return };
        let target = adw::CallbackAnimationTarget::new(move |v| place(&stage, &card, v));
        let anim = adw::TimedAnimation::new(&win, 1.0, 0.0, 120, target);
        anim.set_easing(adw::Easing::EaseInCubic);
        let weak = self.self_weak();
        anim.connect_done(move |_| {
            win.close();
            if let Some(me) = weak.as_ref().and_then(|w| w.upgrade()) {
                me.win.replace(None);
                me.widgets.replace(None);
                me.closing.set(false);
                BACKDROP.with(|b| b.borrow_mut().take());
            }
        });
        anim.play();
    }

    /// The scroller at the list's natural height, capped (a ScrolledWindow
    /// doesn't report its child's natural height; same as Quick Settings'
    /// notification list).
    fn size_scroll(&self) {
        let Some((scroll, list)) = self.widgets.borrow().as_ref().map(|w| (w.scroll.clone(), w.results.clone())) else { return };
        let (_, natural, _, _) = list.measure(gtk::Orientation::Vertical, WIDTH - 16);
        let h = natural.min(self.scroll_max.get()).max(0);
        // max first: GTK refuses a min above the current max
        scroll.set_max_content_height(h.max(scroll.min_content_height()));
        scroll.set_min_content_height(h);
        scroll.set_max_content_height(h);
    }

    /// Size the surface to the card (a GTK window never shrinks by itself).
    fn fit(&self) {
        self.size_scroll();
        let (Some(win), Some(card)) = (self.win.borrow().clone(), self.widgets.borrow().as_ref().map(|w| w.card.clone())) else { return };
        let (_, h, _, _) = card.measure(gtk::Orientation::Vertical, WIDTH);
        win.set_default_size(WIDTH, h);
    }

    /// Light or dark ink per pane by what's behind it.
    fn retag(&self) {
        if backdrop::compositor_ink() {
            return; // the compositor inks the text
        }
        let (Some(win), Some(card)) = (self.win.borrow().clone(), self.widgets.borrow().as_ref().map(|w| w.card.clone())) else { return };
        let Some(grid) = BACKDROP.with(|b| b.borrow().clone()) else { return };
        let origin = self.monitor.borrow().as_ref()
            .and_then(|m| backdrop::layer_origin(m, NAMESPACE)).unwrap_or((0.0, 0.0));
        backdrop::tag_panes(card.upcast_ref(), &win, &grid, origin);
    }

    /// While open: what's behind, from the compositor's glass probe (the
    /// launcher's own text left out), like Quick Settings.
    fn follow_backdrop(&self) {
        if backdrop::compositor_ink() {
            return; // the compositor inks the text: nothing to follow
        }
        let generation = self.opened.get();
        let weak = self.self_weak();
        glib::timeout_add_local(std::time::Duration::from_millis(250), move || {
            let Some(me) = weak.as_ref().and_then(|w| w.upgrade()) else { return glib::ControlFlow::Break };
            if me.opened.get() != generation || me.win.borrow().is_none() {
                return glib::ControlFlow::Break;
            }
            let (Some(m), Some(win)) = (me.monitor.borrow().clone(), me.win.borrow().clone()) else {
                return glib::ControlFlow::Continue;
            };
            if let Some(g) = backdrop::Grid::probe(&m, NAMESPACE, (win.width(), win.height())) {
                BACKDROP.with(|b| *b.borrow_mut() = Some(Rc::new(g)));
                me.retag();
            }
            glib::ControlFlow::Continue
        });
    }
}

thread_local! {
    static SELF: RefCell<Option<std::rc::Weak<Launcher>>> = const { RefCell::new(None) };
    static BACKDROP: RefCell<Option<Rc<backdrop::Grid>>> = const { RefCell::new(None) };
}

/// Progress 0 (hidden) .. 1 (open): fade, drop 14 px, scale 0.96 -> 1 about
/// the top centre — the demo's open.
fn place(stage: &gtk::Fixed, card: &impl IsA<gtk::Widget>, v: f64) {
    let v = v as f32;
    card.set_opacity(v.clamp(0.0, 1.0) as f64);
    let k = (1.0 - v).max(0.0);
    let s = 1.0 - 0.04 * k;
    let cx = WIDTH as f32 / 2.0;
    let t = gsk::Transform::new()
        .translate(&graphene::Point::new(cx, -14.0 * k))
        .scale(s, s)
        .translate(&graphene::Point::new(-cx, 0.0));
    stage.set_child_transform(card, Some(&t));
}

fn clear(b: &gtk::Box) {
    while let Some(c) = b.first_child() {
        b.remove(&c);
    }
}

fn label(text: &str, classes: &[&str]) -> gtk::Label {
    gtk::Label::builder().label(text).xalign(0.0).css_classes(classes.to_vec()).build()
}

/// An icon name from the theme, or a glyph (emoji / a symbol) as text.
fn icon(name: &str, size: i32) -> gtk::Widget {
    if !name.is_empty() && name.chars().all(|c| c.is_ascii_alphanumeric() || "-_.".contains(c)) {
        let i = gtk::Image::from_icon_name(name);
        i.set_pixel_size(size);
        i.add_css_class("launcher-icon");
        i.upcast()
    } else if name.starts_with('/') {
        let i = gtk::Image::from_file(name);
        i.set_pixel_size(size);
        i.add_css_class("launcher-icon");
        i.upcast()
    } else {
        let l = gtk::Label::new(Some(if name.is_empty() { "•" } else { name }));
        l.add_css_class("launcher-glyph");
        l.set_size_request(size, size);
        l.upcast()
    }
}

/// The text with the matched characters in bold (elephant's fuzzy positions).
fn highlight(text: &str, positions: &[i32]) -> String {
    let set: std::collections::HashSet<usize> = positions.iter().filter(|p| **p >= 0).map(|p| *p as usize).collect();
    text.chars().enumerate().map(|(i, c)| {
        let e = glib::markup_escape_text(&c.to_string()).to_string();
        if set.contains(&i) { format!("<b>{e}</b>") } else { e }
    }).collect()
}

fn action_label(a: &str) -> String {
    match a {
        "start" | "open" | "activate" => "Open".into(),
        "copy" | "run_cmd" => "Copy".into(),
        "search" => "Search".into(),
        "focus" => "Focus".into(),
        "run" => "Run".into(),
        "" => "Open".into(),
        other => {
            let mut c = other.replace('_', " ");
            if let Some(f) = c.get_mut(0..1) {
                f.make_ascii_uppercase();
            }
            c
        }
    }
}

/// The key hints for a list: Choose, the selected result's own action (and
/// its second one on Ctrl+Enter), Clear.
fn list_keys(keys: &gtk::Box, selected: Option<&Item>) {
    let first = selected.map(|it| action_label(it.actions.first().map(String::as_str).unwrap_or(""))).unwrap_or_default();
    let mut hints = vec![("↑↓", "Choose".to_owned()), ("↩", first)];
    if let Some(s) = selected.and_then(|it| it.actions.get(1)) {
        hints.push(("⌃↩", action_label(s)));
    }
    hints.push(("esc", "Clear".into()));
    let hints: Vec<(&str, &str)> = hints.iter().map(|(k, v)| (*k, v.as_str())).collect();
    keys_line(keys, &hints);
}

fn keys_line(keys: &gtk::Box, items: &[(&str, &str)]) {
    for (k, v) in items {
        let b = gtk::Box::builder().spacing(5).build();
        b.append(&label(k, &["launcher-kbd"]));
        b.append(&label(v, &["launcher-key-label"]));
        keys.append(&b);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn highlight_bolds_the_matched_characters() {
        assert_eq!(highlight("Fire&fox", &[0, 1]), "<b>F</b><b>i</b>re&amp;fox");
    }

    #[test]
    fn actions_read_like_spotlight() {
        assert_eq!(action_label("start"), "Open");
        assert_eq!(action_label("run_cmd"), "Copy");
        assert_eq!(action_label("show_in_folder"), "Show in folder");
    }
}
