//! Client for elephant (the launcher data service, github.com/abenz1267/elephant),
//! speaking its socket protocol directly — the `elephant query` CLI panics on
//! a query with no results.
//!
//! Socket: $XDG_RUNTIME_DIR/elephant/elephant.sock. A request is
//! `[type u8][format u8][len u32 BE][payload]` (type 0 = query, 1 = activate;
//! format 1 = JSON, so no protobuf here). Replies are `[type u8][len u32 BE]
//! [payload]`: 0/1 = a result (1 = arrived later, e.g. files), 254 = no
//! results, 255 = done. A new query on the same connection cancels the one
//! before it, which is what typing wants: one connection, one query at a time.

use serde::{Deserialize, Serialize};
use std::cell::RefCell;
use std::io::{Read, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;

const REQ_QUERY: u8 = 0;
const REQ_ACTIVATE: u8 = 1;
const FORMAT_JSON: u8 = 1;
const RES_ITEM: u8 = 0;
const RES_ASYNC_ITEM: u8 = 1;
const RES_NO_RESULTS: u8 = 254;
const RES_DONE: u8 = 255;

#[derive(Deserialize, Clone, Debug, Default)]
#[serde(default)]
pub struct FuzzyInfo {
    pub start: i32,
    pub field: String,
    pub positions: Vec<i32>,
}

#[derive(Deserialize, Clone, Debug, Default)]
#[serde(default)]
pub struct Item {
    pub identifier: String,
    pub text: String,
    pub subtext: String,
    pub icon: String,
    pub provider: String,
    pub score: i32,
    pub fuzzyinfo: Option<FuzzyInfo>,
    pub actions: Vec<String>,
    pub state: Vec<String>,
}

#[derive(Deserialize, Debug, Default)]
#[serde(default)]
struct QueryResponse {
    query: String,
    item: Option<Item>,
}

/// What the reader thread hands to the main loop.
pub enum Msg {
    /// a result for `query` (the text it was asked for)
    Item { query: String, item: Item },
    /// the query sent last has nothing (or nothing more)
    NoResults,
    Done,
    /// the connection is gone (elephant stopped); the next query reconnects
    Closed,
}

#[derive(Serialize)]
struct QueryRequest<'a> {
    providers: &'a [String],
    query: &'a str,
    maxresults: i32,
    exactsearch: bool,
}

#[derive(Serialize)]
struct ActivateRequest<'a> {
    provider: &'a str,
    identifier: &'a str,
    action: &'a str,
    query: &'a str,
    arguments: &'a str,
}

pub fn socket_path() -> PathBuf {
    match std::env::var_os("XDG_RUNTIME_DIR") {
        Some(d) => PathBuf::from(d).join("elephant/elephant.sock"),
        None => std::env::temp_dir().join("elephant/elephant.sock"),
    }
}

fn frame(kind: u8, payload: &[u8]) -> Vec<u8> {
    let mut b = Vec::with_capacity(6 + payload.len());
    b.push(kind);
    b.push(FORMAT_JSON);
    b.extend_from_slice(&(payload.len() as u32).to_be_bytes());
    b.extend_from_slice(payload);
    b
}

pub struct Elephant {
    conn: RefCell<Option<UnixStream>>,
    tx: async_channel::Sender<Msg>,
}

impl Elephant {
    /// The client and the receiving end of its replies (read on the main loop).
    pub fn new() -> (Self, async_channel::Receiver<Msg>) {
        let (tx, rx) = async_channel::unbounded();
        (Self { conn: RefCell::new(None), tx }, rx)
    }

    fn connect(&self) -> std::io::Result<()> {
        let s = UnixStream::connect(socket_path())?;
        let mut r = s.try_clone()?;
        let tx = self.tx.clone();
        std::thread::spawn(move || {
            loop {
                let mut head = [0u8; 5];
                if r.read_exact(&mut head).is_err() {
                    let _ = tx.send_blocking(Msg::Closed);
                    return;
                }
                let len = u32::from_be_bytes([head[1], head[2], head[3], head[4]]) as usize;
                let mut body = vec![0u8; len];
                if len > 0 && r.read_exact(&mut body).is_err() {
                    let _ = tx.send_blocking(Msg::Closed);
                    return;
                }
                let msg = match head[0] {
                    RES_ITEM | RES_ASYNC_ITEM => match serde_json::from_slice::<QueryResponse>(&body) {
                        Ok(QueryResponse { query, item: Some(item) }) => Msg::Item { query, item },
                        _ => continue,
                    },
                    RES_NO_RESULTS => Msg::NoResults,
                    RES_DONE => Msg::Done,
                    _ => continue, // activation finished, provider state, ...
                };
                if tx.send_blocking(msg).is_err() {
                    return;
                }
            }
        });
        *self.conn.borrow_mut() = Some(s);
        Ok(())
    }

    /// Ask `providers` for `query`; results arrive as `Msg`s. Cancels the
    /// query before it (same connection).
    pub fn query(&self, providers: &[String], query: &str, max: i32) -> std::io::Result<()> {
        let body = serde_json::to_vec(&QueryRequest { providers, query, maxresults: max, exactsearch: false })?;
        let msg = frame(REQ_QUERY, &body);
        for attempt in 0..2 {
            if self.conn.borrow().is_none() {
                self.connect()?;
            }
            let ok = self.conn.borrow_mut().as_mut().map(|c| c.write_all(&msg).is_ok()).unwrap_or(false);
            if ok {
                return Ok(());
            }
            *self.conn.borrow_mut() = None; // elephant restarted: once more, fresh
            if attempt == 1 {
                break;
            }
        }
        Err(std::io::Error::other("elephant: write failed"))
    }

    /// Forget the connection (the reader thread saw it close).
    pub fn reset(&self) {
        *self.conn.borrow_mut() = None;
    }

    /// Run `action` on `item` (on a connection of its own: its reply would
    /// only get in the way of the query stream).
    pub fn activate(item: &Item, action: &str, query: &str) -> std::io::Result<()> {
        let body = serde_json::to_vec(&ActivateRequest {
            provider: &item.provider,
            identifier: &item.identifier,
            action,
            query,
            arguments: "",
        })?;
        let mut s = UnixStream::connect(socket_path())?;
        s.write_all(&frame(REQ_ACTIVATE, &body))?;
        // let elephant read it before the socket goes away
        s.set_read_timeout(Some(std::time::Duration::from_millis(300)))?;
        let mut b = [0u8; 5];
        let _ = s.read_exact(&mut b);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frames_like_the_elephant_cli() {
        // [type][format=json][len BE][payload]
        let f = frame(REQ_QUERY, b"{}");
        assert_eq!(f, vec![0, 1, 0, 0, 0, 2, b'{', b'}']);
    }

    #[test]
    fn parses_a_result_as_elephant_sends_it() {
        let j = r#"{"query":"fire","item":{"identifier":"firefox.desktop","text":"Firefox","subtext":"Web Browser",
            "icon":"firefox","provider":"desktopapplications","score":114,
            "fuzzyinfo":{"field":"text","positions":[3,2,1,0]},"state":["unpinned"],"actions":["start","edit","pin"]},"qid":1}"#;
        let r: QueryResponse = serde_json::from_str(j).unwrap();
        let it = r.item.unwrap();
        assert_eq!((r.query.as_str(), it.text.as_str(), it.actions[0].as_str()), ("fire", "Firefox", "start"));
        assert_eq!(it.fuzzyinfo.unwrap().positions, vec![3, 2, 1, 0]);
    }
}
