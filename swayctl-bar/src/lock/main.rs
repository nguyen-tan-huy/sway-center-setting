//! swayctl-lock: the lock screen. Locks with ext-session-lock (if this
//! process dies the session stays locked) and asks the password field and
//! the fingerprint reader (fprintd) at the same time, each in its own PAM
//! thread; the first that succeeds unlocks.
//!
//!   swayctl-lock [--fingerprint] [--style FILE] [--daemonize]
//!                [--service-prefix swayctl-lock-]
//!
//! --daemonize returns once the screen is locked (for swayidle before-sleep).

mod auth;

use adw::prelude::*;
use auth::{Event, Method};
use gtk::{gdk, glib};
use std::cell::{Cell, RefCell};
use std::rc::Rc;

const DEFAULT_CSS: &str = include_str!("lock.css");

// ---- gtk4-session-lock (C API; part of the gtk4-layer-shell library) -----------

mod ffi {
    use gtk::glib::ffi::gboolean;
    use gtk::glib::gobject_ffi::GObject;
    #[link(name = "gtk4-layer-shell")]
    unsafe extern "C" {
        pub fn gtk_session_lock_is_supported() -> gboolean;
        pub fn gtk_session_lock_instance_new() -> *mut GObject;
        pub fn gtk_session_lock_instance_lock(i: *mut GObject) -> gboolean;
        pub fn gtk_session_lock_instance_unlock(i: *mut GObject);
        pub fn gtk_session_lock_instance_assign_window_to_monitor(
            i: *mut GObject, window: *mut gtk::ffi::GtkWindow, monitor: *mut gtk::gdk::ffi::GdkMonitor);
    }
}

struct Lock(glib::Object);

impl Lock {
    fn new() -> Option<Self> {
        use glib::translate::FromGlibPtrFull;
        unsafe {
            if ffi::gtk_session_lock_is_supported() == 0 {
                return None;
            }
            Some(Lock(glib::Object::from_glib_full(ffi::gtk_session_lock_instance_new())))
        }
    }
    fn ptr(&self) -> *mut glib::gobject_ffi::GObject {
        use glib::translate::ToGlibPtr;
        self.0.to_glib_none().0
    }
    fn lock(&self) -> bool {
        unsafe { ffi::gtk_session_lock_instance_lock(self.ptr()) != 0 }
    }
    fn unlock(&self) {
        unsafe { ffi::gtk_session_lock_instance_unlock(self.ptr()) }
    }
    fn assign(&self, win: &gtk::Window, monitor: &gdk::Monitor) {
        use glib::translate::ToGlibPtr;
        unsafe {
            ffi::gtk_session_lock_instance_assign_window_to_monitor(self.ptr(), win.to_glib_none().0, monitor.to_glib_none().0)
        }
    }
}

// ---- options ------------------------------------------------------------------

struct Opts {
    fingerprint: bool,
    style: Option<String>,
    daemonize: bool,
    prefix: String,
}

fn opts() -> Opts {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let value = |flag: &str| args.iter().position(|a| a == flag).and_then(|i| args.get(i + 1)).cloned();
    Opts {
        fingerprint: args.iter().any(|a| a == "--fingerprint"),
        style: value("--style"),
        daemonize: args.iter().any(|a| a == "--daemonize"),
        prefix: value("--service-prefix").unwrap_or_else(|| "swayctl-lock-".into()),
    }
}

/// Fork; the parent exits once the child reports "locked" on a pipe (or
/// failure / timeout), so callers can wait for the screen to be locked.
fn daemonize() -> Option<std::fs::File> {
    use std::io::Read;
    use std::os::fd::FromRawFd;
    let mut fds = [0; 2];
    unsafe {
        if libc::pipe(fds.as_mut_ptr()) != 0 {
            return None;
        }
        match libc::fork() {
            -1 => None,
            0 => {
                libc::close(fds[0]);
                libc::setsid();
                Some(std::fs::File::from_raw_fd(fds[1]))
            }
            _ => {
                libc::close(fds[1]);
                let mut r = std::fs::File::from_raw_fd(fds[0]);
                let mut b = [0u8; 1];
                let ok = r.read(&mut b).map(|n| n == 1 && b[0] == b'L').unwrap_or(false);
                std::process::exit(if ok { 0 } else { 1 });
            }
        }
    }
}

// ---- UI ------------------------------------------------------------------------

struct Ui {
    entries: RefCell<Vec<gtk::PasswordEntry>>,
    statuses: RefCell<Vec<gtk::Label>>,
    cards: RefCell<Vec<gtk::Box>>,
    busy: Cell<bool>,
}

impl Ui {
    fn status(&self, text: &str) {
        for l in self.statuses.borrow().iter() {
            l.set_label(text);
        }
    }

    fn set_busy(&self, busy: bool) {
        self.busy.set(busy);
        for e in self.entries.borrow().iter() {
            e.set_sensitive(!busy);
            if !busy {
                e.set_text("");
            }
        }
    }

    /// Wrong password: a short horizontal shake.
    fn shake(&self) {
        for card in self.cards.borrow().iter() {
            let c = card.clone();
            let target = adw::CallbackAnimationTarget::new(move |t| {
                let dx = ((t * std::f64::consts::PI * 6.0).sin() * 12.0 * (1.0 - t)) as i32;
                c.set_margin_start(dx.max(0) * 2);
                c.set_margin_end((-dx).max(0) * 2);
            });
            adw::TimedAnimation::new(card, 0.0, 1.0, 420, target).play();
        }
    }
}

fn hints(o: &Opts) -> &'static str {
    if o.fingerprint { "Enter your password or touch the fingerprint reader" } else { "Enter your password" }
}

fn build_window(app: &adw::Application, ui: &Rc<Ui>, user: &str, o: &Opts,
                on_password: Rc<dyn Fn(String)>) -> gtk::Window {
    let win = gtk::Window::builder().application(app).css_classes(["lock-window"]).build();
    let col = gtk::Box::builder().orientation(gtk::Orientation::Vertical).spacing(10)
        .halign(gtk::Align::Center).valign(gtk::Align::Center).css_classes(["lock-card"]).build();
    let time = gtk::Label::builder().css_classes(["lock-time"]).build();
    let date = gtk::Label::builder().css_classes(["lock-date"]).build();
    let tick = {
        let (time, date) = (time.clone(), date.clone());
        move || {
            if let Ok(now) = glib::DateTime::now_local() {
                time.set_label(&now.format("%H:%M").map(|s| s.to_string()).unwrap_or_default());
                date.set_label(&now.format("%A, %d %B").map(|s| s.to_string()).unwrap_or_default());
            }
        }
    };
    tick();
    let t2 = tick.clone();
    glib::timeout_add_seconds_local(5, move || { t2(); glib::ControlFlow::Continue });
    let avatar = adw::Avatar::builder().size(72).text(user).show_initials(true).css_classes(["lock-avatar"]).build();
    let name = gtk::Label::builder().label(user).css_classes(["lock-user"]).build();
    let entry = gtk::PasswordEntry::builder().show_peek_icon(true).width_request(280)
        .placeholder_text("Password").css_classes(["lock-entry"]).build();
    let status = gtk::Label::builder().label(hints(o)).css_classes(["lock-status"]).wrap(true)
        .max_width_chars(40).justify(gtk::Justification::Center).build();
    let methods = gtk::Box::builder().spacing(14).halign(gtk::Align::Center).css_classes(["lock-methods"]).build();
    if o.fingerprint {
        methods.append(&gtk::Image::from_icon_name("auth-fingerprint-symbolic"));
    }
    for w in [time.upcast_ref::<gtk::Widget>(), date.upcast_ref(), avatar.upcast_ref(), name.upcast_ref(),
              entry.upcast_ref(), status.upcast_ref(), methods.upcast_ref()] {
        col.append(w);
    }
    entry.connect_activate(move |e| {
        let text = e.text().to_string();
        if !text.is_empty() {
            on_password(text);
        }
    });
    win.set_child(Some(&col));
    // fade the card in
    col.set_opacity(0.0);
    let c2 = col.clone();
    let anim = adw::TimedAnimation::new(&col, 0.0, 1.0, 260, adw::CallbackAnimationTarget::new(move |v| c2.set_opacity(v)));
    anim.set_easing(adw::Easing::EaseOutCubic);
    win.connect_map(move |_| anim.play());
    ui.entries.borrow_mut().push(entry.clone());
    ui.statuses.borrow_mut().push(status);
    ui.cards.borrow_mut().push(col);
    win
}

fn main() -> glib::ExitCode {
    let o = opts();
    let notify = if o.daemonize { daemonize() } else { None };
    let notify = Rc::new(RefCell::new(notify));
    let user = std::env::var("USER").unwrap_or_default();
    let app = adw::Application::builder()
        .application_id("io.github.huyhappy.SwayctlLock")
        .flags(gtk::gio::ApplicationFlags::NON_UNIQUE)
        .build();
    let o = Rc::new(o);
    app.connect_activate(move |app| {
        let display = gdk::Display::default().expect("no display");
        let css = gtk::CssProvider::new();
        css.load_from_string(DEFAULT_CSS);
        gtk::style_context_add_provider_for_display(&display, &css, gtk::STYLE_PROVIDER_PRIORITY_APPLICATION);
        if let Some(path) = &o.style {
            // the theme's colors (the bar's generated style.css)
            if std::path::Path::new(path).exists() {
                let theme = gtk::CssProvider::new();
                theme.load_from_path(path);
                gtk::style_context_add_provider_for_display(&display, &theme, gtk::STYLE_PROVIDER_PRIORITY_APPLICATION - 1);
            }
        }
        let Some(lock) = Lock::new() else {
            eprintln!("swayctl-lock: the compositor doesn't support ext-session-lock");
            app.quit();
            return;
        };
        let lock = Rc::new(lock);
        let ui = Rc::new(Ui { entries: RefCell::default(), statuses: RefCell::default(), cards: RefCell::default(),
                              busy: Cell::new(false) });
        let (tx, rx) = async_channel::unbounded::<Event>();

        // password: one attempt per Enter
        let on_password: Rc<dyn Fn(String)> = {
            let (ui, tx, o, user) = (ui.clone(), tx.clone(), o.clone(), user.clone());
            Rc::new(move |pw: String| {
                if ui.busy.get() {
                    return;
                }
                ui.set_busy(true);
                ui.status("Checking…");
                let (tx, user) = (tx.clone(), user.clone());
                let service = auth::service(&o.prefix, Method::Password).unwrap_or_default();
                std::thread::spawn(move || {
                    let r = auth::attempt(&service, &user, Method::Password, Some(pw), &tx);
                    let _ = tx.send_blocking(r);
                });
            })
        };

        // fingerprint: keep asking in the background (pam_fprintd waits for a finger)
        if let Some(service) = o.fingerprint.then(|| auth::service(&o.prefix, Method::Fingerprint)).flatten() {
            let (tx, user) = (tx.clone(), user.clone());
            std::thread::spawn(move || loop {
                let r = auth::attempt(&service, &user, Method::Fingerprint, None, &tx);
                let stop = matches!(r, Event::Success(_) | Event::Failed(_, true));
                let _ = tx.send_blocking(r);
                if stop {
                    break;
                }
                std::thread::sleep(std::time::Duration::from_millis(500));
            });
        }

        // one window per monitor, now and when plugged in
        {
            let (app, ui, o, user, lock2, on_password) = (app.clone(), ui.clone(), o.clone(), user.clone(), lock.clone(), on_password.clone());
            lock.0.connect_local("monitor", false, move |args| {
                let monitor = args[1].get::<gdk::Monitor>().ok()?;
                let win = build_window(&app, &ui, &user, &o, on_password.clone());
                lock2.assign(&win, &monitor);
                None
            });
        }
        {
            let notify = notify.clone();
            lock.0.connect_local("locked", false, move |_| {
                if let Some(mut f) = notify.borrow_mut().take() {
                    use std::io::Write;
                    let _ = f.write_all(b"L");
                }
                None
            });
        }
        {
            let a = app.clone();
            lock.0.connect_local("failed", false, move |_| {
                eprintln!("swayctl-lock: could not lock (another locker running?)");
                a.quit();
                None
            });
            let a = app.clone();
            lock.0.connect_local("unlocked", false, move |_| {
                a.quit();
                None
            });
        }

        // results
        let (ui2, lock2) = (ui.clone(), lock.clone());
        glib::spawn_future_local(async move {
            while let Ok(ev) = rx.recv().await {
                match ev {
                    Event::Success(m) => {
                        eprintln!("swayctl-lock: unlocked with {}", m.name());
                        lock2.unlock();
                        break;
                    }
                    Event::Failed(Method::Password, _) => {
                        ui2.set_busy(false);
                        ui2.status("Wrong password");
                        ui2.shake();
                    }
                    Event::Failed(Method::Fingerprint, false) => ui2.status("Fingerprint not recognised - try again"),
                    Event::Failed(_, _) => {}
                    // module messages ("Place your finger…"); the password's own are noise here
                    Event::Info(m, text) if m != Method::Password && !ui2.busy.get() => ui2.status(&text),
                    Event::Info(_, _) => {}
                }
            }
        });

        let hold = app.hold();
        std::mem::forget(hold);
        if !lock.lock() {
            eprintln!("swayctl-lock: lock request refused");
            app.quit();
        }
    });
    app.run_with_args::<&str>(&[])
}
