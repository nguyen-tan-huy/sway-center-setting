//! Notification server: org.freedesktop.Notifications on the session bus.
//!
//! zbus answers calls on its own thread; each call is turned into a plain
//! `Event` and handed to the GLib main loop, where the Notifier keeps the
//! history and tells the popups. Replies and signals (NotificationClosed,
//! ActionInvoked) go out from the main loop.

use crate::watch::Watch;
use std::cell::RefCell;
use std::collections::HashMap;
use std::rc::Rc;
use std::sync::Arc;
use std::sync::atomic::{AtomicU32, Ordering};
use zbus::Connection;
use zbus::zvariant::{OwnedValue, Value};

pub const NAME: &str = "org.freedesktop.Notifications";
const PATH: &str = "/org/freedesktop/Notifications";
const HISTORY: usize = 50;

/// Why a notification went away (the spec's reason codes).
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Reason {
    Expired = 1,
    Dismissed = 2,
    Closed = 3,
}

#[derive(Clone, PartialEq, Debug)]
pub enum Image {
    Name(String),
    Path(String),
    /// width, height, rowstride, has_alpha, pixels (RGB(A), 8 bits per sample)
    Data(i32, i32, i32, bool, Vec<u8>),
}

#[derive(Clone, PartialEq, Debug)]
pub struct Notification {
    pub id: u32,
    pub app_name: String,
    pub summary: String,
    pub body: String,
    /// (key, label); "default" is clicking the notification itself
    pub actions: Vec<(String, String)>,
    /// 0 low, 1 normal, 2 critical
    pub urgency: u8,
    /// ms as the app asked: -1 = server default, 0 = never
    pub expire_timeout: i32,
    pub image: Option<Image>,
    pub transient: bool,
    pub resident: bool,
    /// seconds since the epoch
    pub time: i64,
}

impl Notification {
    pub fn default_action(&self) -> bool {
        self.actions.iter().any(|(k, _)| k == "default")
    }
}

enum Event {
    Notify(Notification, bool),
    Close(u32),
}

struct Server {
    tx: async_channel::Sender<Event>,
    next: Arc<AtomicU32>,
}

fn hint<T: TryFrom<OwnedValue>>(h: &HashMap<String, OwnedValue>, k: &str) -> Option<T> {
    h.get(k).and_then(|v| v.try_clone().ok()).and_then(|v| T::try_from(v).ok())
}

fn image_data(h: &HashMap<String, OwnedValue>) -> Option<Image> {
    // image-data (1.2), image_data (1.1), icon_data (1.0): (iiibiiay)
    let v = ["image-data", "image_data", "icon_data"].iter().find_map(|k| h.get(*k))?;
    let Value::Structure(s) = &**v else { return None };
    let f = s.fields();
    if f.len() != 7 {
        return None;
    }
    let int = |i: usize| match &f[i] { Value::I32(n) => Some(*n), _ => None };
    let alpha = match &f[3] { Value::Bool(b) => *b, _ => return None };
    let bytes: Vec<u8> = match &f[6] {
        Value::Array(a) => a.iter().filter_map(|x| if let Value::U8(b) = x { Some(*b) } else { None }).collect(),
        _ => return None,
    };
    let (w, ht, stride) = (int(0)?, int(1)?, int(2)?);
    (w > 0 && ht > 0 && bytes.len() >= (stride * (ht - 1) + w * if alpha { 4 } else { 3 }) as usize)
        .then(|| Image::Data(w, ht, stride, alpha, bytes))
}

#[zbus::interface(name = "org.freedesktop.Notifications")]
impl Server {
    fn get_capabilities(&self) -> Vec<&str> {
        vec!["body", "body-markup", "actions", "icon-static", "persistence"]
    }

    #[allow(clippy::too_many_arguments)]
    async fn notify(&self, app_name: String, replaces_id: u32, app_icon: String, summary: String, body: String,
                    actions: Vec<String>, hints: HashMap<String, OwnedValue>, expire_timeout: i32) -> u32 {
        let id = if replaces_id != 0 { replaces_id } else { self.next.fetch_add(1, Ordering::Relaxed) };
        let image = image_data(&hints)
            .or_else(|| hint::<String>(&hints, "image-path").or_else(|| hint(&hints, "image_path"))
                .filter(|s| !s.is_empty()).map(|s| icon_or_path(&s)))
            .or_else(|| (!app_icon.is_empty()).then(|| icon_or_path(&app_icon)));
        let n = Notification {
            id,
            app_name: hint::<String>(&hints, "x-swayctl-app").unwrap_or(app_name),
            summary,
            body,
            actions: actions.chunks(2).filter(|c| c.len() == 2).map(|c| (c[0].clone(), c[1].clone())).collect(),
            urgency: hint::<u8>(&hints, "urgency").unwrap_or(1).min(2),
            expire_timeout,
            image,
            transient: hint::<bool>(&hints, "transient").unwrap_or(false),
            resident: hint::<bool>(&hints, "resident").unwrap_or(false),
            time: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0),
        };
        let _ = self.tx.send(Event::Notify(n, replaces_id != 0)).await;
        id
    }

    async fn close_notification(&self, id: u32) {
        let _ = self.tx.send(Event::Close(id)).await;
    }

    fn get_server_information(&self) -> (&str, &str, &str, &str) {
        ("swayctl-bar", "swayctl", env!("CARGO_PKG_VERSION"), "1.2")
    }
}

fn icon_or_path(s: &str) -> Image {
    match s.strip_prefix("file://") {
        Some(p) => Image::Path(p.to_owned()),
        None if s.starts_with('/') => Image::Path(s.to_owned()),
        None => Image::Name(s.to_owned()),
    }
}

type Handler = Box<dyn Fn(&Notification, bool)>;
type CloseHandler = Box<dyn Fn(u32)>;

/// The notifications on the main thread: history, do-not-disturb, and who
/// to tell when one arrives or goes away.
pub struct Notifier {
    conn: Connection,
    history: RefCell<Vec<Notification>>,
    /// bumped on every history change (widgets subscribe to it)
    pub changed: Rc<Watch<u64>>,
    pub dnd: Rc<Watch<bool>>,
    /// whether we own the bus name (false while swaync or another server holds it)
    pub active: Rc<Watch<bool>>,
    on_show: RefCell<Vec<Handler>>,
    on_close: RefCell<Vec<CloseHandler>>,
}

impl Notifier {
    pub fn new(conn: Connection) -> Rc<Self> {
        Rc::new(Self {
            conn,
            history: RefCell::new(Vec::new()),
            changed: Watch::new(0),
            dnd: Watch::new(false),
            active: Watch::new(false),
            on_show: RefCell::new(Vec::new()),
            on_close: RefCell::new(Vec::new()),
        })
    }

    /// Serve on the bus and take the name; gives up (with a message) if
    /// another server already has it.
    pub fn start(self: &Rc<Self>) {
        if self.active.get() {
            return;
        }
        let (tx, rx) = async_channel::unbounded();
        let conn = self.conn.clone();
        let me = Rc::downgrade(self);
        gtk::glib::spawn_future_local(async move {
            let server = Server { tx, next: Arc::new(AtomicU32::new(1)) };
            if let Err(e) = conn.object_server().at(PATH, server).await {
                eprintln!("swayctl-bar: notifications: {e}");
                return;
            }
            let flags = zbus::fdo::RequestNameFlags::DoNotQueue.into();
            match conn.request_name_with_flags(NAME, flags).await {
                Ok(zbus::fdo::RequestNameReply::PrimaryOwner | zbus::fdo::RequestNameReply::AlreadyOwner) => {}
                other => {
                    eprintln!("swayctl-bar: another notification server is running ({other:?}); not showing notifications");
                    let _ = conn.object_server().remove::<Server, _>(PATH).await;
                    return;
                }
            }
            if let Some(me) = me.upgrade() {
                me.active.set(true);
            }
            while let Ok(ev) = rx.recv().await {
                let Some(me) = me.upgrade() else { break };
                match ev {
                    Event::Notify(n, replaced) => me.add(n, replaced),
                    Event::Close(id) => me.close(id, Reason::Closed),
                }
            }
        });
    }

    /// Give the name back (notifications turned off in settings).
    pub fn stop(self: &Rc<Self>) {
        if !self.active.get() {
            return;
        }
        self.active.set(false);
        let conn = self.conn.clone();
        gtk::glib::spawn_future_local(async move {
            let _ = conn.release_name(NAME).await;
            // drops the Server and so its sender: the receive loop above ends
            let _ = conn.object_server().remove::<Server, _>(PATH).await;
        });
    }

    pub fn connect_show(&self, f: impl Fn(&Notification, bool) + 'static) {
        self.on_show.borrow_mut().push(Box::new(f));
    }

    pub fn connect_close(&self, f: impl Fn(u32) + 'static) {
        self.on_close.borrow_mut().push(Box::new(f));
    }

    pub fn history(&self) -> Vec<Notification> {
        self.history.borrow().clone()
    }

    fn bump(&self) {
        self.changed.set(self.changed.get().wrapping_add(1));
    }

    fn add(&self, n: Notification, replaced: bool) {
        {
            let mut h = self.history.borrow_mut();
            h.retain(|o| o.id != n.id);
            if !n.transient {
                h.insert(0, n.clone());
                h.truncate(HISTORY);
            }
        }
        self.bump();
        // do not disturb: only critical ones pop up
        if !self.dnd.get() || n.urgency == 2 {
            for f in self.on_show.borrow().iter() {
                f(&n, replaced);
            }
        }
    }

    /// Remove a notification everywhere and tell its app why.
    pub fn close(&self, id: u32, reason: Reason) {
        let had = {
            let mut h = self.history.borrow_mut();
            let before = h.len();
            h.retain(|o| o.id != id);
            before != h.len()
        };
        if had {
            self.bump();
        }
        for f in self.on_close.borrow().iter() {
            f(id);
        }
        self.emit("NotificationClosed", (id, reason as u32));
    }

    /// A popup timed out: it leaves the screen but stays in the list.
    pub fn expired(&self, id: u32) {
        let transient = !self.history.borrow().iter().any(|n| n.id == id);
        if transient {
            self.emit("NotificationClosed", (id, Reason::Expired as u32));
        }
    }

    pub fn invoke(&self, id: u32, action: &str) {
        self.emit("ActionInvoked", (id, action.to_owned()));
        let resident = self.history.borrow().iter().any(|n| n.id == id && n.resident);
        if !resident {
            self.close(id, Reason::Dismissed);
        }
    }

    pub fn clear(&self) {
        let ids: Vec<u32> = self.history.borrow().iter().map(|n| n.id).collect();
        for id in ids {
            self.close(id, Reason::Dismissed);
        }
    }

    fn emit<B>(&self, signal: &'static str, body: B)
    where B: serde::Serialize + zbus::zvariant::DynamicType + 'static {
        if !self.active.get() {
            return;
        }
        let conn = self.conn.clone();
        gtk::glib::spawn_future_local(async move {
            if let Err(e) = conn.emit_signal(None::<()>, PATH, NAME, signal, &body).await {
                eprintln!("swayctl-bar: {signal}: {e}");
            }
        });
    }
}
