//! PAM, one thread per method. Each method has its own PAM service so they
//! can run side by side: <prefix>password, <prefix>fingerprint.

use pam_client::{ConversationHandler, ErrorCode, Flag};
use std::ffi::{CStr, CString};
use std::path::Path;

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Method {
    Password,
    Fingerprint,
}

impl Method {
    pub fn name(self) -> &'static str {
        match self {
            Method::Password => "password",
            Method::Fingerprint => "fingerprint",
        }
    }
}

#[derive(Debug)]
pub enum Event {
    /// a message from the PAM module ("Place your finger on the reader"...)
    Info(Method, String),
    Success(Method),
    /// wrong password, finger not matched...; `fatal` = don't retry (no reader)
    Failed(Method, bool),
}

/// The PAM service for a method; the password falls back to swaylock's
/// service (always there) until swayctl-center has written ours.
pub fn service(prefix: &str, m: Method) -> Option<String> {
    let name = format!("{prefix}{}", m.name());
    if Path::new("/etc/pam.d").join(&name).exists() || Path::new("/usr/lib/pam.d").join(&name).exists() {
        Some(name)
    } else if m == Method::Password {
        Some("swaylock".to_owned())
    } else {
        None
    }
}

struct Conv {
    method: Method,
    password: Option<String>,
    tx: async_channel::Sender<Event>,
}

impl ConversationHandler for Conv {
    fn prompt_echo_on(&mut self, _prompt: &CStr) -> Result<CString, ErrorCode> {
        Err(ErrorCode::CONV_ERR)
    }

    fn prompt_echo_off(&mut self, _prompt: &CStr) -> Result<CString, ErrorCode> {
        // only the password method answers, and only once
        match self.password.take() {
            Some(p) => CString::new(p).map_err(|_| ErrorCode::CONV_ERR),
            None => Err(ErrorCode::CONV_ERR),
        }
    }

    fn text_info(&mut self, msg: &CStr) {
        let _ = self.tx.send_blocking(Event::Info(self.method, msg.to_string_lossy().into_owned()));
    }

    fn error_msg(&mut self, msg: &CStr) {
        let _ = self.tx.send_blocking(Event::Info(self.method, msg.to_string_lossy().into_owned()));
    }
}

/// Blocking: one authentication attempt.
pub fn attempt(service: &str, user: &str, method: Method, password: Option<String>,
               tx: &async_channel::Sender<Event>) -> Event {
    let conv = Conv { method, password, tx: tx.clone() };
    let mut ctx = match pam_client::Context::new(service, Some(user), conv) {
        Ok(c) => c,
        Err(_) => return Event::Failed(method, true),
    };
    // authenticate only, like swaylock: unlocking needs no account check, and
    // swaylock's PAM file (our fallback) has no "account" section at all, so
    // pam_acct_mgmt there always fails, even after the right password
    match ctx.authenticate(Flag::NONE) {
        Ok(()) => Event::Success(method),
        Err(e) => {
            // no reader / module missing: stop asking this method
            let fatal = matches!(e.code(), ErrorCode::AUTHINFO_UNAVAIL | ErrorCode::MODULE_UNKNOWN
                                 | ErrorCode::OPEN_ERR | ErrorCode::SYMBOL_ERR | ErrorCode::SERVICE_ERR);
            Event::Failed(method, fatal)
        }
    }
}
