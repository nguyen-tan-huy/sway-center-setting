//! System tray: StatusNotifierItem host, plus the StatusNotifierWatcher when no
//! one else provides it (waybar did, and it isn't running beside us). Menus
//! come from com.canonical.dbusmenu.

use crate::watch::Watch;
use futures_util::StreamExt;
use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;
use zbus::message::Header;
use zbus::object_server::SignalEmitter;
use zbus::zvariant::{OwnedObjectPath, OwnedValue, Structure, Value};
use zbus::{interface, Connection};

const WATCHER: &str = "org.kde.StatusNotifierWatcher";
const WATCHER_PATH: &str = "/StatusNotifierWatcher";
const ITEM: &str = "org.kde.StatusNotifierItem";

#[derive(Clone, PartialEq, Debug, Default)]
pub struct Pixmap {
    pub width: i32,
    pub height: i32,
    /// ARGB32, network byte order (as on the bus)
    pub data: Vec<u8>,
}

#[derive(Clone, PartialEq, Debug, Default)]
pub struct Item {
    /// "bus.name/object/path"
    pub id: String,
    pub bus: String,
    pub path: String,
    pub title: String,
    pub tooltip: String,
    pub icon_name: String,
    pub icon_theme_path: String,
    pub pixmap: Option<Pixmap>,
    pub status: String,
    pub menu: Option<String>,
    pub item_is_menu: bool,
}

#[derive(Clone, Debug, Default)]
pub struct MenuNode {
    pub id: i32,
    pub label: String,
    pub enabled: bool,
    pub separator: bool,
    /// Some(checked) for checkmark and radio items
    pub toggle: Option<bool>,
    pub children: Vec<MenuNode>,
}

// ---- watcher (served when the name is free) ------------------------------------

struct Watcher {
    items: Vec<String>,
    hosts: Vec<String>,
}

#[interface(name = "org.kde.StatusNotifierWatcher")]
impl Watcher {
    async fn register_status_notifier_item(&mut self, service: &str, #[zbus(header)] hdr: Header<'_>,
                                           #[zbus(signal_emitter)] emitter: SignalEmitter<'_>) {
        let sender = hdr.sender().map(|s| s.to_string()).unwrap_or_default();
        // apps pass a bus name (path is the default) or just an object path
        let id = if service.starts_with('/') { format!("{sender}{service}") } else { format!("{service}/StatusNotifierItem") };
        if !self.items.contains(&id) {
            self.items.push(id.clone());
            let _ = Self::status_notifier_item_registered(&emitter, &id).await;
        }
    }

    async fn register_status_notifier_host(&mut self, service: &str, #[zbus(signal_emitter)] emitter: SignalEmitter<'_>) {
        self.hosts.push(service.to_owned());
        let _ = Self::status_notifier_host_registered(&emitter).await;
    }

    #[zbus(property)]
    fn registered_status_notifier_items(&self) -> Vec<String> {
        self.items.clone()
    }

    #[zbus(property)]
    fn is_status_notifier_host_registered(&self) -> bool {
        true
    }

    #[zbus(property)]
    fn protocol_version(&self) -> i32 {
        0
    }

    #[zbus(signal)]
    async fn status_notifier_item_registered(emitter: &SignalEmitter<'_>, service: &str) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn status_notifier_item_unregistered(emitter: &SignalEmitter<'_>, service: &str) -> zbus::Result<()>;

    #[zbus(signal)]
    async fn status_notifier_host_registered(emitter: &SignalEmitter<'_>) -> zbus::Result<()>;
}

impl Watcher {
    /// Drop items whose owner left the bus; returns the removed ids.
    fn forget_bus(&mut self, bus: &str) -> Vec<String> {
        let (gone, kept): (Vec<_>, Vec<_>) = self.items.drain(..).partition(|i| i.split('/').next() == Some(bus));
        self.items = kept;
        gone
    }
}

// ---- host ------------------------------------------------------------------------

pub struct Tray {
    pub items: Rc<Watch<Vec<Item>>>,
    session: Connection,
}

fn split_id(id: &str) -> (String, String) {
    match id.find('/') {
        Some(i) => (id[..i].to_owned(), id[i..].to_owned()),
        None => (id.to_owned(), "/StatusNotifierItem".to_owned()),
    }
}

fn get<T: TryFrom<OwnedValue>>(p: &HashMap<String, OwnedValue>, k: &str) -> Option<T> {
    p.get(k).and_then(|v| v.try_clone().ok()).and_then(|v| T::try_from(v).ok())
}

/// The pixmap closest to 22 px from an a(iiay).
fn best_pixmap(list: Vec<(i32, i32, Vec<u8>)>) -> Option<Pixmap> {
    list.into_iter()
        .filter(|(w, h, d)| *w > 0 && *h > 0 && d.len() >= (*w * *h * 4) as usize)
        .min_by_key(|(w, _, _)| (w - 22).abs())
        .map(|(width, height, data)| Pixmap { width, height, data })
}

async fn read_item(conn: &Connection, id: &str) -> Option<Item> {
    let (bus, path) = split_id(id);
    let props = crate::services::dbus::get_all(conn, &bus, &path, ITEM).await.ok()?;
    let tooltip = props.get("ToolTip").and_then(|v| v.try_clone().ok())
        .and_then(|v| <(String, Vec<(i32, i32, Vec<u8>)>, String, String)>::try_from(v).ok())
        .map(|(_, _, title, body)| if body.is_empty() { title } else { format!("{title}\n{body}") })
        .unwrap_or_default();
    let status: String = get(&props, "Status").unwrap_or_default();
    let attention = status == "NeedsAttention";
    let icon_name: String = (if attention { get(&props, "AttentionIconName") } else { None })
        .filter(|s: &String| !s.is_empty())
        .or_else(|| get(&props, "IconName"))
        .unwrap_or_default();
    let pixmaps: Vec<(i32, i32, Vec<u8>)> = (if attention { get(&props, "AttentionIconPixmap") } else { None })
        .or_else(|| get(&props, "IconPixmap"))
        .unwrap_or_default();
    Some(Item {
        id: id.to_owned(),
        title: get(&props, "Title").unwrap_or_default(),
        tooltip,
        icon_name,
        icon_theme_path: get(&props, "IconThemePath").unwrap_or_default(),
        pixmap: best_pixmap(pixmaps),
        status,
        menu: get::<OwnedObjectPath>(&props, "Menu").map(|p| p.to_string()).filter(|p| p != "/"),
        item_is_menu: get(&props, "ItemIsMenu").unwrap_or(false),
        bus,
        path,
    })
}

impl Tray {
    pub fn start(session: Connection) -> Rc<Self> {
        let me = Rc::new(Self { items: Watch::new(Vec::new()), session: session.clone() });
        let weak = Rc::downgrade(&me);
        gtk::glib::spawn_future_local(async move {
            let watcher = Rc::new(RefCell::new(false));
            // be the watcher if nobody is; otherwise follow the existing one
            let served = session.object_server().at(WATCHER_PATH, Watcher { items: vec![], hosts: vec![] }).await.is_ok()
                && session.request_name(WATCHER).await.is_ok();
            *watcher.borrow_mut() = served;
            let host = format!("org.kde.StatusNotifierHost-{}", std::process::id());
            let _ = session.request_name(host.as_str()).await;
            let Ok(w) = crate::services::dbus::proxy(&session, WATCHER, WATCHER_PATH, WATCHER).await else { return };
            let _: zbus::Result<()> = w.call("RegisterStatusNotifierHost", &(host.as_str(),)).await;
            let ids: Vec<String> = w.get_property("RegisteredStatusNotifierItems").await.unwrap_or_default();
            if let Some(me) = weak.upgrade() {
                for id in ids {
                    me.add(id);
                }
            }
            for (signal, adding) in [("StatusNotifierItemRegistered", true), ("StatusNotifierItemUnregistered", false)] {
                let Ok(mut stream) = w.receive_signal(signal).await else { continue };
                let weak = weak.clone();
                gtk::glib::spawn_future_local(async move {
                    while let Some(m) = stream.next().await {
                        let (Ok(id), Some(me)) = (m.body().deserialize::<String>(), weak.upgrade()) else { continue };
                        if adding { me.add(id) } else { me.remove(|i| i.id == id) }
                    }
                });
            }
            // an app quitting without unregistering: drop its items
            let Ok(bus) = zbus::fdo::DBusProxy::new(&session).await else { return };
            let Ok(mut owners) = bus.receive_name_owner_changed().await else { return };
            while let Some(sig) = owners.next().await {
                let Ok(a) = sig.args() else { continue };
                if a.new_owner().is_some() {
                    continue;
                }
                let name = a.name().to_string();
                let Some(me) = weak.upgrade() else { break };
                me.remove(|i| i.bus == name);
                if *watcher.borrow() {
                    if let Ok(iface) = session.object_server().interface::<_, Watcher>(WATCHER_PATH).await {
                        let gone = iface.get_mut().await.forget_bus(&name);
                        for id in gone {
                            let _ = Watcher::status_notifier_item_unregistered(iface.signal_emitter(), &id).await;
                        }
                    }
                }
            }
        });
        me
    }

    fn remove(&self, f: impl Fn(&Item) -> bool) {
        let mut items = self.items.get();
        items.retain(|i| !f(i));
        self.items.set(items);
    }

    fn add(self: &Rc<Self>, id: String) {
        let weak = Rc::downgrade(self);
        let conn = self.session.clone();
        gtk::glib::spawn_future_local(async move {
            let Some(item) = read_item(&conn, &id).await else { return };
            let (bus, path) = (item.bus.clone(), item.path.clone());
            let Some(me) = weak.upgrade() else { return };
            let mut items = me.items.get();
            match items.iter_mut().find(|i| i.id == id) {
                Some(i) => *i = item,
                None => items.push(item),
            }
            me.items.set(items);
            drop(me);
            // NewIcon / NewToolTip / NewStatus / NewTitle: read it again
            let Ok(p) = crate::services::dbus::proxy(&conn, &bus, &path, ITEM).await else { return };
            let Ok(mut changes) = p.receive_all_signals().await else { return };
            while changes.next().await.is_some() {
                let Some(me) = weak.upgrade() else { break };
                if !me.items.get().iter().any(|i| i.id == id) {
                    break; // removed
                }
                if let Some(fresh) = read_item(&conn, &id).await {
                    let mut items = me.items.get();
                    if let Some(i) = items.iter_mut().find(|i| i.id == id) {
                        *i = fresh;
                    }
                    me.items.set(items);
                }
            }
        });
    }

    pub fn call(&self, item: &Item, method: &'static str) {
        let (conn, bus, path) = (self.session.clone(), item.bus.clone(), item.path.clone());
        gtk::glib::spawn_future_local(async move {
            if let Ok(p) = crate::services::dbus::proxy(&conn, &bus, &path, ITEM).await {
                let _: zbus::Result<()> = p.call(method, &(0i32, 0i32)).await;
            }
        });
    }

    pub async fn menu(&self, item: &Item) -> Option<MenuNode> {
        let path = item.menu.as_deref()?;
        let p = crate::services::dbus::proxy(&self.session, &item.bus, path, "com.canonical.dbusmenu").await.ok()?;
        let _: zbus::Result<bool> = p.call("AboutToShow", &(0i32,)).await;
        let msg = p.call_method("GetLayout", &(0i32, -1i32, Vec::<String>::new())).await.ok()?;
        let body = msg.body();
        let layout: Structure = body.deserialize().ok()?;
        Some(parse_node(layout.fields().get(1)?))
    }

    pub fn menu_event(&self, item: &Item, id: i32) {
        let (conn, bus, path) = (self.session.clone(), item.bus.clone(), item.menu.clone());
        gtk::glib::spawn_future_local(async move {
            let Some(path) = path else { return };
            if let Ok(p) = crate::services::dbus::proxy(&conn, &bus, &path, "com.canonical.dbusmenu").await {
                let data = Value::from("");
                let _: zbus::Result<()> = p.call("Event", &(id, "clicked", &data, 0u32)).await;
            }
        });
    }
}

fn parse_node(v: &Value) -> MenuNode {
    let mut node = MenuNode { enabled: true, ..Default::default() };
    let Value::Structure(s) = v else { return node };
    let f = s.fields();
    if let Some(Value::I32(id)) = f.first() {
        node.id = *id;
    }
    let mut visible = true;
    if let Some(Value::Dict(props)) = f.get(1) {
        for (k, val) in props.iter() {
            let (Value::Str(k), Value::Value(val)) = (k, val) else { continue };
            match (k.as_str(), &**val) {
                ("label", Value::Str(s)) => node.label = s.replace('_', ""),
                ("enabled", Value::Bool(b)) => node.enabled = *b,
                ("visible", Value::Bool(b)) => visible = *b,
                ("type", Value::Str(s)) => node.separator = s.as_str() == "separator",
                ("toggle-state", Value::I32(i)) => node.toggle = Some(*i == 1),
                _ => {}
            }
        }
    }
    if let Some(Value::Array(children)) = f.get(2) {
        for c in children.iter() {
            let c = if let Value::Value(inner) = c { &**inner } else { c };
            let child = parse_node(c);
            if child.label.is_empty() && !child.separator && child.children.is_empty() {
                continue;
            }
            node.children.push(child);
        }
    }
    if !visible {
        node.label.clear();
        node.children.clear();
        node.separator = false;
    }
    node
}
