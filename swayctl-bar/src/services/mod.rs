pub mod clipboard;
pub mod dbus;
pub mod elephant;
pub mod notify;
pub mod procs;
pub mod sway;
pub mod tray;

use crate::watch::Watch;
use std::rc::Rc;
use zbus::Connection;

/// Everything the widgets show, shared by all bars and the popups.
pub struct Services {
    pub system: Option<Connection>,
    pub session: Option<Connection>,
    pub sway: Rc<sway::Sway>,
    pub battery: Rc<Watch<dbus::Battery>>,
    pub network: Rc<Watch<dbus::Network>>,
    pub bluetooth: Rc<Watch<dbus::Bluetooth>>,
    pub profile: Rc<Watch<String>>,
    pub media: Rc<Watch<dbus::Media>>,
    pub night_light: Rc<Watch<Option<bool>>>,
    pub volume: Rc<Watch<procs::Volume>>,
    pub tray: Option<Rc<tray::Tray>>,
    pub notifier: Option<Rc<notify::Notifier>>,
}

impl Services {
    /// Connect to both buses; call before the GLib main loop runs.
    pub fn connect() -> (Option<Connection>, Option<Connection>) {
        let system = zbus::block_on(Connection::system()).map_err(|e| eprintln!("swayctl-bar: system bus: {e}")).ok();
        let session = zbus::block_on(Connection::session()).map_err(|e| eprintln!("swayctl-bar: session bus: {e}")).ok();
        (system, session)
    }

    /// Start following everything; call on the main loop (application startup).
    pub fn start(system: Option<Connection>, session: Option<Connection>) -> Rc<Self> {
        let on_system = |f: fn(Connection) -> Rc<Watch<_>>| system.clone().map(f);
        let battery = system.clone().map(dbus::battery).unwrap_or_else(|| Watch::new(Default::default()));
        let network = system.clone().map(dbus::network).unwrap_or_else(|| Watch::new(Default::default()));
        let bluetooth = system.clone().map(dbus::bluetooth).unwrap_or_else(|| Watch::new(Default::default()));
        let profile = on_system(dbus::power_profile).unwrap_or_else(|| Watch::new(String::new()));
        let media = session.clone().map(dbus::media).unwrap_or_else(|| Watch::new(Default::default()));
        let night_light = session.clone().map(dbus::night_light).unwrap_or_else(|| Watch::new(None));
        Rc::new(Self {
            sway: sway::Sway::start(),
            volume: procs::volume(),
            tray: session.clone().map(tray::Tray::start),
            notifier: session.clone().map(notify::Notifier::new),
            battery,
            network,
            bluetooth,
            profile,
            media,
            night_light,
            system,
            session,
        })
    }
}
