//! Sway IPC: a reader thread for subscribed events, plain request/reply on the
//! main thread (a local socket round trip is microseconds).

use crate::watch::Watch;
use serde::Deserialize;
use serde_json::Value;
use std::io::{Read, Write};
use std::os::unix::net::UnixStream;
use std::rc::Rc;

const MAGIC: &[u8; 6] = b"i3-ipc";
pub const RUN_COMMAND: u32 = 0;
pub const GET_WORKSPACES: u32 = 1;
pub const SUBSCRIBE: u32 = 2;
pub const GET_TREE: u32 = 4;
/// swayctl fork: RGB grid of what is on an output right now (B3)
pub const GET_BACKDROP: u32 = 102;

fn socket() -> std::io::Result<UnixStream> {
    let path = std::env::var("SWAYSOCK").map_err(|_| std::io::Error::other("SWAYSOCK not set"))?;
    UnixStream::connect(path)
}

fn send(s: &mut UnixStream, kind: u32, payload: &str) -> std::io::Result<()> {
    let mut msg = Vec::with_capacity(14 + payload.len());
    msg.extend_from_slice(MAGIC);
    msg.extend_from_slice(&(payload.len() as u32).to_ne_bytes());
    msg.extend_from_slice(&kind.to_ne_bytes());
    msg.extend_from_slice(payload.as_bytes());
    s.write_all(&msg)
}

fn recv(s: &mut UnixStream) -> std::io::Result<(u32, Value)> {
    let mut head = [0u8; 14];
    s.read_exact(&mut head)?;
    let len = u32::from_ne_bytes(head[6..10].try_into().unwrap()) as usize;
    let kind = u32::from_ne_bytes(head[10..14].try_into().unwrap());
    let mut body = vec![0u8; len];
    s.read_exact(&mut body)?;
    Ok((kind, serde_json::from_slice(&body).unwrap_or(Value::Null)))
}

pub fn request(kind: u32, payload: &str) -> std::io::Result<Value> {
    let mut s = socket()?;
    send(&mut s, kind, payload)?;
    Ok(recv(&mut s)?.1)
}

pub fn command(cmd: &str) {
    if let Err(e) = request(RUN_COMMAND, cmd) {
        eprintln!("swayctl-bar: sway command failed: {e}");
    }
}

#[derive(Deserialize, Clone, PartialEq, Debug)]
pub struct Workspace {
    pub num: i32,
    pub name: String,
    pub focused: bool,
    pub visible: bool,
    pub urgent: bool,
    pub output: String,
}

#[derive(Clone, PartialEq, Default)]
pub struct SwayState {
    pub workspaces: Vec<Workspace>,
    pub mode: String,
    pub title: String,
}

pub struct Sway {
    pub state: Rc<Watch<SwayState>>,
}

fn focused_title(tree: &Value) -> Option<String> {
    if tree["focused"].as_bool() == Some(true) && tree["type"] == "con" {
        return tree["name"].as_str().map(str::to_owned);
    }
    for key in ["nodes", "floating_nodes"] {
        for n in tree[key].as_array().into_iter().flatten() {
            if let Some(t) = focused_title(n) {
                return Some(t);
            }
        }
    }
    None
}

impl Sway {
    pub fn start() -> Rc<Self> {
        let me = Rc::new(Self { state: Watch::new(SwayState::default()) });
        me.refresh(true, true);
        let (tx, rx) = async_channel::unbounded::<(u32, Value)>();
        std::thread::spawn(move || {
            let run = || -> std::io::Result<()> {
                let mut s = socket()?;
                send(&mut s, SUBSCRIBE, r#"["workspace","mode","window"]"#)?;
                recv(&mut s)?; // {"success": true}
                loop {
                    let ev = recv(&mut s)?;
                    if tx.send_blocking(ev).is_err() {
                        return Ok(());
                    }
                }
            };
            if let Err(e) = run() {
                eprintln!("swayctl-bar: sway event stream ended: {e}");
            }
        });
        let weak = Rc::downgrade(&me);
        gtk::glib::spawn_future_local(async move {
            while let Ok((kind, ev)) = rx.recv().await {
                let Some(me) = weak.upgrade() else { break };
                match kind & 0x7fff_ffff {
                    0 => me.refresh(true, true), // workspace (focus moves too)
                    2 => {
                        // mode
                        let mut st = me.state.get();
                        st.mode = ev["change"].as_str().unwrap_or("default").to_owned();
                        if st.mode == "default" {
                            st.mode.clear();
                        }
                        me.state.set(st);
                    }
                    3 => me.refresh(false, true), // window
                    _ => {}
                }
            }
        });
        me
    }

    fn refresh(&self, workspaces: bool, title: bool) {
        let mut st = self.state.get();
        if workspaces {
            if let Ok(v) = request(GET_WORKSPACES, "") {
                st.workspaces = serde_json::from_value(v).unwrap_or_default();
            }
        }
        if title {
            st.title = request(GET_TREE, "").ok().and_then(|t| focused_title(&t)).unwrap_or_default();
        }
        self.state.set(st);
    }
}
