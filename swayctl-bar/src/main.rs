//! swayctl-bar: the bar, Quick Settings and OSD for swayctl-center.
//!
//!   swayctl-bar [--config-dir DIR]     run (one bar per monitor)
//!   swayctl-bar osd volume-up|volume-down|volume-mute|brightness-up|brightness-down
//!   swayctl-bar quick                  toggle Quick Settings on the focused monitor
//!   swayctl-bar dnd on|off|toggle      do not disturb (built-in notifications)
//!
//! The second and later invocations are forwarded to the running bar
//! (GApplication), so key bindings can call them cheaply.

mod config;
mod services;
mod ui;
mod watch;

use adw::prelude::*;
use gtk::{gdk, gio, glib};
use std::cell::RefCell;
use std::path::PathBuf;
use std::rc::Rc;

const APP_ID: &str = "io.github.huyhappy.SwayctlBar";
const DEFAULT_CSS: &str = include_str!("default.css");
/// Over the generated theme: the sliding workspace drop is just a fill, no
/// padding or minimum size of a button.
const MOTION_CSS: &str = "
window.bar .workspace.ws-blob { min-width: 0; min-height: 0; padding: 0; margin: 0; }
/* the number under the drop: accent text whatever the generated theme says (it
   used to key on `.focused`, and key-coloured text over the opaque drop isn't inked) */
window.bar .workspace.under-drop, window.bar .workspace.under-drop label { color: @accent_fg_color; text-shadow: none; }
.workspaces:not(.on-dark):not(.on-light) .workspace { transition: color 90ms linear; }
";

struct State {
    dir: PathBuf,
    svc: Rc<services::Services>,
    quick: Rc<ui::quick::QuickSettings>,
    osd: Rc<ui::osd::Osd>,
    launcher: Rc<ui::launcher::Launcher>,
    popups: Option<Rc<ui::notify::Popups>>,
    bars: RefCell<Vec<gtk::ApplicationWindow>>,
    /// the bars' service subscriptions, ended on each rebuild (they hold the
    /// old bars' widgets)
    bar_subs: watch::Subs,
    css: gtk::CssProvider,
    _monitors: RefCell<Vec<gio::FileMonitor>>,
}

impl State {
    fn rebuild(&self, app: &adw::Application) {
        for w in self.bars.take() {
            w.close();
        }
        self.bar_subs.clear();
        let cfg = config::load(&self.dir);
        ui::backdrop::set_current(&cfg.backdrop);
        self.quick.set_config(&cfg);
        self.launcher.set_config(&cfg.launcher);
        self.notifications(&cfg);
        let Some(display) = gdk::Display::default() else { return };
        let monitors = display.monitors();
        let mut bars = Vec::new();
        for i in 0..monitors.n_items() {
            if let Some(m) = monitors.item(i).and_downcast::<gdk::Monitor>() {
                let w = ui::bar::build(app, &m, &cfg, &self.svc, &self.quick, &self.bar_subs);
                w.present();
                bars.push(w);
            }
        }
        *self.bars.borrow_mut() = bars;
    }

    /// Serve notifications or not, as the settings say.
    fn notifications(&self, cfg: &config::Config) {
        let (Some(n), Some(p)) = (&self.svc.notifier, &self.popups) else { return };
        p.set_config(&cfg.notifications);
        if cfg.notifications.enabled { n.start() } else { n.stop() }
    }

    fn load_css(&self) {
        let path = self.dir.join("style.css");
        if path.exists() {
            self.css.load_from_path(&path);
        } else {
            self.css.load_from_string("");
        }
    }

    fn focused_monitor(&self) -> Option<gdk::Monitor> {
        let out = services::sway::request(services::sway::GET_WORKSPACES, "").ok()?;
        let name = out.as_array()?.iter().find(|w| w["focused"] == true)?["output"].as_str()?.to_owned();
        let monitors = gdk::Display::default()?.monitors();
        (0..monitors.n_items())
            .filter_map(|i| monitors.item(i).and_downcast::<gdk::Monitor>())
            .find(|m| m.connector().as_deref() == Some(name.as_str()))
    }
}

fn main() -> glib::ExitCode {
    let (system, session) = services::Services::connect();
    let app = adw::Application::builder()
        .application_id(APP_ID)
        .flags(gio::ApplicationFlags::HANDLES_COMMAND_LINE)
        .build();
    let state: Rc<RefCell<Option<Rc<State>>>> = Rc::new(RefCell::new(None));
    let conns = RefCell::new(Some((system, session)));

    let st = state.clone();
    app.connect_command_line(move |app, cmd| {
        let args: Vec<String> = cmd.arguments().iter().map(|a| a.to_string_lossy().into_owned()).collect();
        if st.borrow().is_none() {
            let (system, session) = conns.borrow_mut().take().unwrap_or((None, None));
            let display = gdk::Display::default().expect("no display");
            let base = gtk::CssProvider::new();
            base.load_from_string(DEFAULT_CSS);
            gtk::style_context_add_provider_for_display(&display, &base, gtk::STYLE_PROVIDER_PRIORITY_APPLICATION);
            let motion = gtk::CssProvider::new();
            motion.load_from_string(MOTION_CSS);
            gtk::style_context_add_provider_for_display(&display, &motion, gtk::STYLE_PROVIDER_PRIORITY_APPLICATION + 2);
            let css = gtk::CssProvider::new();
            // generated theme above our defaults, below the user's own gtk.css
            gtk::style_context_add_provider_for_display(&display, &css, gtk::STYLE_PROVIDER_PRIORITY_APPLICATION + 1);
            let dir = config::dir_from_args(&args);
            let svc = services::Services::start(system, session);
            let cfg = config::load(&dir);
            let popups = svc.notifier.as_ref().map(|n| ui::notify::Popups::new(app, n, &cfg.notifications));
            if let Some(n) = &svc.notifier {
                n.dnd.set(cfg.notifications.dnd_on_start);
            }
            let s = Rc::new(State {
                popups,
                quick: ui::quick::QuickSettings::new(app, &svc, &cfg),
                osd: ui::osd::Osd::new(app),
                launcher: ui::launcher::Launcher::new(app, &cfg.launcher),
                dir,
                svc,
                bars: RefCell::new(Vec::new()), bar_subs: Default::default(),
                css,
                _monitors: RefCell::new(Vec::new()),
            });
            if let Some(p) = &s.popups {
                let p = Rc::downgrade(p);
                *s.quick.on_open.borrow_mut() = Some(Box::new(move || if let Some(p) = p.upgrade() { p.clear_screen() }));
            }
            s.load_css();
            s.rebuild(app);
            // follow monitors being plugged in or out
            let (s2, app2) = (Rc::downgrade(&s), app.clone());
            display.monitors().connect_items_changed(move |_, _, _, _| {
                if let Some(s) = s2.upgrade() {
                    s.rebuild(&app2);
                }
            });
            // swayctl-center rewrites these when settings or the theme change
            if let Ok(mon) = gio::File::for_path(&s.dir).monitor_directory(gio::FileMonitorFlags::NONE, gio::Cancellable::NONE) {
                let (s2, app2) = (Rc::downgrade(&s), app.clone());
                mon.connect_changed(move |_, file, _, event| {
                    if !matches!(event, gio::FileMonitorEvent::ChangesDoneHint | gio::FileMonitorEvent::Created) {
                        return;
                    }
                    let Some(s) = s2.upgrade() else { return };
                    match file.basename().and_then(|b| b.to_str().map(str::to_owned)).as_deref() {
                        Some("style.css") => s.load_css(),
                        Some("config.json") => s.rebuild(&app2),
                        _ => {}
                    }
                });
                s._monitors.borrow_mut().push(mon);
            }
            *st.borrow_mut() = Some(s);
            // stay alive with no windows (e.g. no monitors for a moment)
            std::mem::forget(app.hold());
        }
        let s = st.borrow().clone().unwrap();
        let rest: Vec<&str> = args.iter().skip(1).map(String::as_str).filter(|a| !a.starts_with("--config-dir")).collect();
        match rest.as_slice() {
            ["osd", what, ..] => s.osd.run(what),
            ["quick", ..] => {
                if let Some(m) = s.focused_monitor() {
                    s.quick.toggle(&m);
                }
            }
            // `launcher` toggles; `launcher <text>` opens with that typed
            // (e.g. "." = the emoji picker, "=" = the calculator)
            ["launcher"] => {
                if let Some(m) = s.focused_monitor() {
                    s.launcher.toggle(&m);
                }
            }
            ["launcher", text @ ..] => {
                if let Some(m) = s.focused_monitor() {
                    s.launcher.open_with(&m, &text.join(" "));
                }
            }
            // `tray-menu [n]`: the menu of the nth tray icon (from 1) on the
            // focused output's bar, as a click on it would open it
            ["tray-menu", n @ ..] => {
                let n: usize = n.first().and_then(|n| n.parse().ok()).unwrap_or(1).max(1);
                let out = s.focused_monitor().and_then(|m| m.connector()).map(|c| c.to_string());
                for w in app.windows() {
                    let on = w.surface().and_then(|sf| WidgetExt::display(&w).monitor_at_surface(&sf))
                        .and_then(|m| m.connector()).map(|c| c.to_string());
                    if out.is_some() && on != out {
                        continue;
                    }
                    if let Some(b) = ui::bar::tray_button_at(&w, n) {
                        b.emit_clicked();
                        break;
                    }
                }
            }
            ["dnd", what, ..] => {
                if let Some(n) = &s.svc.notifier {
                    let on = match *what { "on" => true, "off" => false, _ => !n.dnd.get() };
                    n.dnd.set(on);
                }
            }
            _ => {}
        }
        glib::ExitCode::SUCCESS
    });
    app.run()
}
