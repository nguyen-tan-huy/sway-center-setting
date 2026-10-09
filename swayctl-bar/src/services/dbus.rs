//! System services over D-Bus. Each one fills a Watch from the service's
//! properties and keeps it current from PropertiesChanged; a missing service
//! (no UPower, no BlueZ...) just leaves the default "not available" value.

use crate::watch::Watch;
use futures_util::StreamExt;
use std::collections::HashMap;
use std::rc::Rc;
use zbus::zvariant::{OwnedObjectPath, OwnedValue};
use zbus::{Connection, Proxy};

type Props = HashMap<String, OwnedValue>;

pub async fn proxy(conn: &Connection, dest: &str, path: &str, iface: &str) -> zbus::Result<Proxy<'static>> {
    Proxy::new(conn, dest.to_owned(), path.to_owned(), iface.to_owned()).await
}

pub async fn get_all(conn: &Connection, dest: &str, path: &str, iface: &str) -> zbus::Result<Props> {
    let p = proxy(conn, dest, path, "org.freedesktop.DBus.Properties").await?;
    p.call("GetAll", &(iface,)).await
}

/// Calls `on_change` now and after every PropertiesChanged on (path, iface).
pub fn follow(conn: Connection, dest: &'static str, path: String, iface: &'static str, on_change: impl Fn(Props) + 'static) {
    gtk::glib::spawn_future_local(async move {
        let Ok(p) = proxy(&conn, dest, &path, "org.freedesktop.DBus.Properties").await else { return };
        let Ok(mut stream) = p.receive_signal("PropertiesChanged").await else { return };
        if let Ok(all) = get_all(&conn, dest, &path, iface).await {
            on_change(all);
        }
        while let Some(msg) = stream.next().await {
            let Ok((changed_iface, _changed, _inval)) = msg.body().deserialize::<(String, Props, Vec<String>)>() else {
                continue;
            };
            if changed_iface == iface {
                if let Ok(all) = get_all(&conn, dest, &path, iface).await {
                    on_change(all);
                }
            }
        }
    });
}

fn val<T: TryFrom<OwnedValue>>(p: &Props, k: &str) -> Option<T> {
    p.get(k).and_then(|v| v.try_clone().ok()).and_then(|v| T::try_from(v).ok())
}

async fn set_prop(conn: &Connection, dest: &str, path: &str, iface: &str, name: &str, value: zbus::zvariant::Value<'_>) {
    if let Ok(p) = proxy(conn, dest, path, "org.freedesktop.DBus.Properties").await {
        let r: zbus::Result<()> = p.call("Set", &(iface, name, value)).await;
        if let Err(e) = r {
            eprintln!("swayctl-bar: setting {iface}.{name}: {e}");
        }
    }
}

// ---- battery (UPower) ------------------------------------------------------

#[derive(Clone, PartialEq, Default)]
pub struct Battery {
    pub present: bool,
    pub percent: f64,
    pub charging: bool,
    pub full: bool,
}

pub fn battery(system: Connection) -> Rc<Watch<Battery>> {
    let w = Watch::new(Battery::default());
    let w2 = w.clone();
    follow(system, "org.freedesktop.UPower", "/org/freedesktop/UPower/devices/DisplayDevice".into(),
           "org.freedesktop.UPower.Device", move |p| {
        // State: 1 charging, 2 discharging, 4 fully charged, 5 pending charge
        let state: u32 = val(&p, "State").unwrap_or(0);
        w2.set(Battery {
            present: val::<bool>(&p, "IsPresent").unwrap_or(false),
            percent: val(&p, "Percentage").unwrap_or(0.0),
            charging: state == 1 || state == 5,
            full: state == 4,
        });
    });
    w
}

// ---- power profiles ----------------------------------------------------------

pub const PROFILES: &str = "org.freedesktop.UPower.PowerProfiles";
const PROFILES_PATH: &str = "/org/freedesktop/UPower/PowerProfiles";

pub fn power_profile(system: Connection) -> Rc<Watch<String>> {
    let w = Watch::new(String::new());
    let w2 = w.clone();
    follow(system, PROFILES, PROFILES_PATH.into(), PROFILES, move |p| {
        w2.set(val::<String>(&p, "ActiveProfile").unwrap_or_default());
    });
    w
}

pub fn set_power_profile(system: Connection, name: String) {
    gtk::glib::spawn_future_local(async move {
        set_prop(&system, PROFILES, PROFILES_PATH, PROFILES, "ActiveProfile", name.as_str().into()).await;
    });
}

// ---- network (NetworkManager) -----------------------------------------------

const NM: &str = "org.freedesktop.NetworkManager";
const NM_PATH: &str = "/org/freedesktop/NetworkManager";

#[derive(Clone, PartialEq, Default)]
pub struct Network {
    pub available: bool,
    pub wifi_enabled: bool,
    /// "wifi" | "ethernet" | "vpn" | "" (offline)
    pub kind: String,
    pub name: String,
    pub strength: u8,
}

#[derive(Clone, PartialEq, Debug)]
pub struct AccessPoint {
    pub ssid: String,
    pub strength: u8,
    pub secure: bool,
    pub active: bool,
    pub path: OwnedObjectPath,
    pub device: OwnedObjectPath,
}

pub fn network(system: Connection) -> Rc<Watch<Network>> {
    let w = Watch::new(Network::default());
    let (w2, conn) = (w.clone(), system.clone());
    // any NetworkManager object, not just the root: the access point's
    // strength, a connection coming up, a device going away
    on_any_change(system, NM, move || {
        let (w3, conn) = (w2.clone(), conn.clone());
        gtk::glib::spawn_future_local(async move {
            if let Some(net) = read_network(&conn).await {
                w3.set(net);
            }
        });
        true
    });
    w
}

async fn read_network(conn: &Connection) -> Option<Network> {
    let p = get_all(conn, NM, NM_PATH, NM).await.ok()?;
    let wifi_enabled = val::<bool>(&p, "WirelessEnabled").unwrap_or(false);
    let primary: Option<OwnedObjectPath> = val(&p, "PrimaryConnection");
    let mut net = Network { available: true, wifi_enabled, ..Default::default() };
    if let Some(path) = primary.filter(|p| p.as_str() != "/") {
        if let Ok(a) = get_all(conn, NM, path.as_str(), "org.freedesktop.NetworkManager.Connection.Active").await {
            net.name = val(&a, "Id").unwrap_or_default();
            let t: String = val(&a, "Type").unwrap_or_default();
            net.kind = match t.as_str() {
                "802-11-wireless" => "wifi",
                "802-3-ethernet" => "ethernet",
                "vpn" | "wireguard" => "vpn",
                _ => "ethernet",
            }
            .into();
            if net.kind == "wifi" {
                if let Some(ap) = val::<OwnedObjectPath>(&a, "SpecificObject") {
                    if let Ok(ap) = get_all(conn, NM, ap.as_str(), "org.freedesktop.NetworkManager.AccessPoint").await {
                        net.strength = val(&ap, "Strength").unwrap_or(0);
                    }
                }
            }
        }
    }
    Some(net)
}

/// Calls `on_change` now and after each burst of PropertiesChanged /
/// InterfacesAdded / InterfacesRemoved from any object of `dest`, until it
/// returns false. A burst (a scan updates every access point) is one call.
pub fn on_any_change(conn: Connection, dest: &'static str, on_change: impl Fn() -> bool + 'static) {
    use futures_util::FutureExt;
    gtk::glib::spawn_future_local(async move {
        if !on_change() {
            return;
        }
        let mut streams = Vec::new();
        for (iface, member) in [("org.freedesktop.DBus.Properties", "PropertiesChanged"),
                                ("org.freedesktop.DBus.ObjectManager", "InterfacesAdded"),
                                ("org.freedesktop.DBus.ObjectManager", "InterfacesRemoved")] {
            let rule = zbus::MatchRule::builder()
                .msg_type(zbus::message::Type::Signal)
                .sender(dest).and_then(|b| b.interface(iface)).and_then(|b| b.member(member))
                .map(|b| b.build());
            let Ok(rule) = rule else { continue };
            if let Ok(s) = zbus::MessageStream::for_match_rule(rule, &conn, None).await {
                streams.push(s);
            }
        }
        if streams.is_empty() {
            return;
        }
        let mut all = futures_util::stream::select_all(streams);
        while all.next().await.is_some() {
            gtk::glib::timeout_future(std::time::Duration::from_millis(400)).await;
            while let Some(Some(_)) = all.next().now_or_never() {}
            if !on_change() {
                return;
            }
        }
    });
}

pub fn set_wifi(system: Connection, on: bool) {
    gtk::glib::spawn_future_local(async move {
        set_prop(&system, NM, NM_PATH, NM, "WirelessEnabled", on.into()).await;
    });
}

pub async fn access_points(system: &Connection) -> Vec<AccessPoint> {
    let mut out: Vec<AccessPoint> = Vec::new();
    let Ok(nm) = proxy(system, NM, NM_PATH, NM).await else { return out };
    let Ok(devices): zbus::Result<Vec<OwnedObjectPath>> = nm.call("GetDevices", &()).await else { return out };
    for dev in devices {
        let Ok(d) = get_all(system, NM, dev.as_str(), "org.freedesktop.NetworkManager.Device").await else { continue };
        if val::<u32>(&d, "DeviceType") != Some(2) {
            continue; // not Wi-Fi
        }
        let Ok(wd) = get_all(system, NM, dev.as_str(), "org.freedesktop.NetworkManager.Device.Wireless").await else { continue };
        let active: Option<OwnedObjectPath> = val(&wd, "ActiveAccessPoint");
        let aps: Vec<OwnedObjectPath> = val(&wd, "AccessPoints").unwrap_or_default();
        for ap in aps {
            let Ok(a) = get_all(system, NM, ap.as_str(), "org.freedesktop.NetworkManager.AccessPoint").await else { continue };
            let ssid: Vec<u8> = val(&a, "Ssid").unwrap_or_default();
            let ssid = String::from_utf8_lossy(&ssid).into_owned();
            if ssid.is_empty() {
                continue;
            }
            let secure = val::<u32>(&a, "WpaFlags").unwrap_or(0) != 0 || val::<u32>(&a, "RsnFlags").unwrap_or(0) != 0;
            let strength: u8 = val(&a, "Strength").unwrap_or(0);
            let is_active = active.as_ref().map(|p| p == &ap).unwrap_or(false);
            match out.iter_mut().find(|x| x.ssid == ssid) {
                Some(x) if x.strength >= strength && !is_active => {}
                Some(x) => *x = AccessPoint { ssid, strength, secure, active: is_active, path: ap, device: dev.clone() },
                None => out.push(AccessPoint { ssid, strength, secure, active: is_active, path: ap, device: dev.clone() }),
            }
        }
    }
    out.sort_by(|a, b| b.active.cmp(&a.active).then(b.strength.cmp(&a.strength)));
    out
}

/// Connect to an access point. Saved and open networks connect directly;
/// returns false when NetworkManager needs a password we can't ask for here.
pub async fn activate(system: &Connection, ap: &AccessPoint) -> bool {
    let Ok(nm) = proxy(system, NM, NM_PATH, NM).await else { return false };
    let root = OwnedObjectPath::try_from("/").unwrap();
    let empty: HashMap<String, HashMap<String, OwnedValue>> = HashMap::new();
    let r: zbus::Result<(OwnedObjectPath, OwnedObjectPath)> =
        nm.call("AddAndActivateConnection", &(empty, &ap.device, &ap.path)).await;
    if r.is_ok() {
        return true;
    }
    // already known: plain activation with "/" lets NM pick the saved profile
    let r: zbus::Result<OwnedObjectPath> = nm.call("ActivateConnection", &(&root, &ap.device, &ap.path)).await;
    r.is_ok() || !ap.secure
}

// ---- bluetooth (BlueZ) --------------------------------------------------------

#[derive(Clone, PartialEq, Default)]
pub struct Bluetooth {
    pub available: bool,
    pub powered: bool,
}

pub fn bluetooth(system: Connection) -> Rc<Watch<Bluetooth>> {
    let w = Watch::new(Bluetooth::default());
    let w2 = w.clone();
    // any BlueZ object: the adapter also comes and goes (bluetoothd restart, rfkill)
    let conn = system.clone();
    on_any_change(system, "org.bluez", move || {
        let (w3, conn) = (w2.clone(), conn.clone());
        gtk::glib::spawn_future_local(async move {
            w3.set(match get_all(&conn, "org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1").await {
                Ok(p) => Bluetooth { available: true, powered: val(&p, "Powered").unwrap_or(false) },
                Err(_) => Bluetooth::default(),
            });
        });
        true
    });
    w
}

pub fn set_bluetooth(system: Connection, on: bool) {
    gtk::glib::spawn_future_local(async move {
        set_prop(&system, "org.bluez", "/org/bluez/hci0", "org.bluez.Adapter1", "Powered", on.into()).await;
    });
}

// ---- media (MPRIS) ---------------------------------------------------------------

#[derive(Clone, PartialEq, Default)]
pub struct Media {
    pub player: String,
    pub title: String,
    pub artist: String,
    pub playing: bool,
}

pub fn media(session: Connection) -> Rc<Watch<Media>> {
    let w = Watch::new(Media::default());
    let w2 = w.clone();
    gtk::glib::spawn_future_local(async move {
        let Ok(bus) = zbus::fdo::DBusProxy::new(&session).await else { return };
        let Ok(mut owners) = bus.receive_name_owner_changed().await else { return };
        let follow_player = |name: String| {
            let w3 = w2.clone();
            let n = name.clone();
            // MPRIS names are dynamic; leak a &'static once per player name seen
            let dest: &'static str = Box::leak(name.into_boxed_str());
            follow(session.clone(), dest, "/org/mpris/MediaPlayer2".into(), "org.mpris.MediaPlayer2.Player", move |p| {
                let meta: HashMap<String, OwnedValue> = val(&p, "Metadata").unwrap_or_default();
                let title: String = val(&meta, "xesam:title").unwrap_or_default();
                let artist: Vec<String> = val(&meta, "xesam:artist").unwrap_or_default();
                let status: String = val(&p, "PlaybackStatus").unwrap_or_default();
                let cur = w3.get();
                if status == "Stopped" && cur.player == n {
                    w3.set(Media::default());
                } else if status != "Stopped" && (status == "Playing" || cur.player.is_empty() || cur.player == n) {
                    w3.set(Media { player: n.clone(), title, artist: artist.join(", "), playing: status == "Playing" });
                }
            });
        };
        if let Ok(names) = bus.list_names().await {
            for n in names.iter().map(|n| n.to_string()).filter(|n| n.starts_with("org.mpris.MediaPlayer2.")) {
                follow_player(n);
            }
        }
        while let Some(sig) = owners.next().await {
            let Ok(args) = sig.args() else { continue };
            let name = args.name().to_string();
            if !name.starts_with("org.mpris.MediaPlayer2.") {
                continue;
            }
            if args.new_owner().is_some() {
                follow_player(name);
            } else if w2.get().player == name {
                w2.set(Media::default());
            }
        }
    });
    w
}

pub fn media_call(session: Connection, player: String, method: &'static str) {
    gtk::glib::spawn_future_local(async move {
        if let Ok(p) = proxy(&session, &player, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player").await {
            let _: zbus::Result<()> = p.call(method, &()).await;
        }
    });
}

// ---- swayctl-center daemon -------------------------------------------------------

const CENTER: &str = "io.github.huyhappy.SwayctlCenter";
const CENTER_PATH: &str = "/io/github/huyhappy/SwayctlCenter";

pub async fn center_get(session: &Connection, path: &str) -> Option<serde_json::Value> {
    let p = proxy(session, CENTER, CENTER_PATH, CENTER).await.ok()?;
    let s: String = p.call("Get", &(path,)).await.ok()?;
    serde_json::from_str(&s).ok()
}

pub fn center_action(session: Connection, name: &'static str) {
    gtk::glib::spawn_future_local(async move {
        if let Ok(p) = proxy(&session, CENTER, CENTER_PATH, CENTER).await {
            let r: zbus::Result<()> = p.call("Action", &(name,)).await;
            if let Err(e) = r {
                eprintln!("swayctl-bar: action {name}: {e}");
            }
        }
    });
}

/// Night light on/off, following the daemon's Changed signal.
pub fn night_light(session: Connection) -> Rc<Watch<Option<bool>>> {
    let w = Watch::new(None);
    let w2 = w.clone();
    gtk::glib::spawn_future_local(async move {
        let read = |s: Connection, w: Rc<Watch<Option<bool>>>| async move {
            let mode = center_get(&s, "night_light.mode").await;
            w.set(mode.and_then(|m| m.as_str().map(|m| m != "off")));
        };
        read(session.clone(), w2.clone()).await;
        let Ok(p) = proxy(&session, CENTER, CENTER_PATH, CENTER).await else { return };
        let Ok(mut changed) = p.receive_signal("Changed").await else { return };
        while let Some(msg) = changed.next().await {
            if let Ok((section, _keys)) = msg.body().deserialize::<(String, Vec<String>)>() {
                if section == "night_light" {
                    read(session.clone(), w2.clone()).await;
                }
            }
        }
    });
    w
}
