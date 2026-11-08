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

/// A window on screen: its output and its rectangle inside that output (logical pixels).
#[derive(Clone, PartialEq, Debug)]
pub struct WinRect {
    pub output: String,
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

#[derive(Clone, PartialEq, Default)]
pub struct SwayState {
    pub workspaces: Vec<Workspace>,
    pub mode: String,
    pub title: String,
    /// the windows of each output's visible workspace (the frame's cut-outs); empty for an output
    /// with a fullscreen window
    pub windows: Vec<WinRect>,
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

/// The windows of every output's visible workspace, from a GET_TREE reply. An output showing a
/// fullscreen window has none (nothing of the frame is seen there).
pub fn window_rects(tree: &Value) -> Vec<WinRect> {
    fn leaves(n: &Value, fullscreen: &mut bool, out: &mut Vec<[i64; 4]>) {
        let kids = || n["nodes"].as_array().into_iter().chain(n["floating_nodes"].as_array()).flatten();
        if n["type"] == "con" && kids().next().is_none() && (n["pid"].is_number() || n["app_id"].is_string()) {
            if n["fullscreen_mode"].as_i64().unwrap_or(0) != 0 {
                *fullscreen = true;
            }
            let r = &n["rect"];
            out.push([r["x"].as_i64().unwrap_or(0), r["y"].as_i64().unwrap_or(0), r["width"].as_i64().unwrap_or(0), r["height"].as_i64().unwrap_or(0)]);
            return;
        }
        for k in kids() {
            leaves(k, fullscreen, out);
        }
    }
    let mut rects = Vec::new();
    for output in tree["nodes"].as_array().into_iter().flatten() {
        if output["type"] != "output" {
            continue;
        }
        let name = output["name"].as_str().unwrap_or_default();
        let (ox, oy) = (output["rect"]["x"].as_i64().unwrap_or(0), output["rect"]["y"].as_i64().unwrap_or(0));
        let current = output["current_workspace"].as_str().unwrap_or_default();
        let mut wins = Vec::new();
        let mut fullscreen = false;
        for ws in output["nodes"].as_array().into_iter().flatten() {
            if ws["type"] == "workspace" && ws["name"].as_str() == Some(current) {
                leaves(ws, &mut fullscreen, &mut wins);
            }
        }
        if fullscreen {
            continue;
        }
        rects.extend(wins.into_iter().filter(|r| r[2] > 0 && r[3] > 0).map(|r| WinRect {
            output: name.to_owned(),
            x: (r[0] - ox) as i32,
            y: (r[1] - oy) as i32,
            w: r[2] as i32,
            h: r[3] as i32,
        }));
    }
    rects
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
            let tree = request(GET_TREE, "").ok();
            st.title = tree.as_ref().and_then(focused_title).unwrap_or_default();
            if let Some(t) = &tree {
                st.windows = window_rects(t);
            }
        }
        self.state.set(st);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn tree() -> Value {
        json!({"type": "root", "nodes": [
            {"type": "output", "name": "eDP-1", "rect": {"x": 0, "y": 0}, "current_workspace": "2", "nodes": [
                {"type": "workspace", "name": "1", "nodes": [{"type": "con", "pid": 9, "rect": {"x": 8, "y": 8, "width": 100, "height": 100}, "nodes": []}]},
                {"type": "workspace", "name": "2", "nodes": [
                    {"type": "con", "nodes": [
                        {"type": "con", "pid": 1, "rect": {"x": 8, "y": 43, "width": 700, "height": 900}, "nodes": []},
                        {"type": "con", "app_id": "foot", "rect": {"x": 716, "y": 43, "width": 800, "height": 900}, "nodes": []}]}],
                 "floating_nodes": [{"type": "floating_con", "pid": 5, "rect": {"x": 300, "y": 200, "width": 400, "height": 300}, "nodes": []}]}]},
            {"type": "output", "name": "HDMI-A-1", "rect": {"x": 1536, "y": 0}, "current_workspace": "3", "nodes": [
                {"type": "workspace", "name": "3", "nodes": [{"type": "con", "pid": 7, "fullscreen_mode": 1, "rect": {"x": 1536, "y": 0, "width": 1920, "height": 1080}, "nodes": []}]}]}]})
    }

    #[test]
    fn only_the_visible_workspace_of_each_output_counts() {
        let r = window_rects(&tree());
        assert_eq!(r.len(), 2, "{r:?}");   // the two tiled windows of workspace 2; 1 is hidden, 3 is fullscreen
        assert_eq!(r[0], WinRect { output: "eDP-1".into(), x: 8, y: 43, w: 700, h: 900 });
        assert_eq!(r[1].x, 716);
    }

    #[test]
    fn rectangles_are_relative_to_their_output() {
        let mut t = tree();
        t["nodes"][0]["rect"] = json!({"x": 100, "y": 50});
        let r = window_rects(&t);
        assert_eq!((r[0].x, r[0].y), (8 - 100, 43 - 50));
    }

    #[test]
    fn a_fullscreen_window_hides_the_frame_on_its_output_only() {
        let r = window_rects(&tree());
        assert!(r.iter().all(|w| w.output == "eDP-1"));
    }

    #[test]
    fn empty_boxes_are_not_windows() {
        let t = json!({"nodes": [{"type": "output", "name": "A", "rect": {"x": 0, "y": 0}, "current_workspace": "1",
            "nodes": [{"type": "workspace", "name": "1", "nodes": [{"type": "con", "nodes": []}]}]}]});
        assert!(window_rects(&t).is_empty());
    }
}
