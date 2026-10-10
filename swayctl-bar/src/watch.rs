//! A value on the main thread that widgets follow: every subscriber runs once
//! right away and again on each change. Services own the Watch, widgets only
//! subscribe, so there is no polling anywhere. A subscriber lives as long as
//! the Watch unless it's dropped with `unsubscribe` (widgets built per open,
//! like the Quick Settings panel, must: the closure holds them alive).

use std::cell::{Cell, RefCell};
use std::rc::{Rc, Weak};

type Sub<T> = Rc<dyn Fn(&T)>;

pub struct Watch<T> {
    value: RefCell<T>,
    subs: RefCell<Vec<(u64, Sub<T>)>>,
    next: Cell<u64>,
}

impl<T: PartialEq + Clone + 'static> Watch<T> {
    pub fn new(value: T) -> Rc<Self> {
        Rc::new(Self { value: RefCell::new(value), subs: RefCell::new(Vec::new()), next: Cell::new(0) })
    }

    pub fn get(&self) -> T {
        self.value.borrow().clone()
    }

    /// Store and notify, unless nothing changed.
    pub fn set(&self, value: T) {
        if *self.value.borrow() == value {
            return;
        }
        *self.value.borrow_mut() = value;
        let v = self.value.borrow().clone();
        // a snapshot: a subscriber may (un)subscribe while it runs
        let subs: Vec<Sub<T>> = self.subs.borrow().iter().map(|(_, f)| f.clone()).collect();
        for f in subs {
            f(&v);
        }
    }

    /// Follow the value; the id is for `unsubscribe`.
    pub fn subscribe(&self, f: impl Fn(&T) + 'static) -> u64 {
        f(&self.value.borrow());
        let id = self.next.get();
        self.next.set(id + 1);
        self.subs.borrow_mut().push((id, Rc::new(f)));
        id
    }

    pub fn unsubscribe(&self, id: u64) {
        self.subs.borrow_mut().retain(|(i, _)| *i != id);
    }

    #[cfg(test)]
    fn count(&self) -> usize {
        self.subs.borrow().len()
    }
}

/// Subscriptions that end together (dropped, or `clear`ed): for widgets
/// that come and go while the services stay.
#[derive(Default)]
pub struct Subs(RefCell<Vec<Box<dyn FnOnce()>>>);

impl Subs {
    pub fn follow<T: PartialEq + Clone + 'static>(&self, w: &Rc<Watch<T>>, f: impl Fn(&T) + 'static) {
        let id = w.subscribe(f);
        let w: Weak<Watch<T>> = Rc::downgrade(w);
        self.0.borrow_mut().push(Box::new(move || {
            if let Some(w) = w.upgrade() {
                w.unsubscribe(id);
            }
        }));
    }

    pub fn clear(&self) {
        let ends = std::mem::take(&mut *self.0.borrow_mut());
        for end in ends {
            end();
        }
    }
}

impl Drop for Subs {
    fn drop(&mut self) {
        self.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cleared_subscribers_stop_and_free_what_they_hold() {
        let w = Watch::new(0);
        let held = Rc::new(());
        let seen = Rc::new(Cell::new(0));
        let subs = Subs::default();
        let (h, s) = (held.clone(), seen.clone());
        subs.follow(&w, move |v| { let _ = &h; s.set(*v) });
        w.set(1);
        assert_eq!(seen.get(), 1);
        subs.clear();
        assert_eq!(w.count(), 0);
        assert_eq!(Rc::strong_count(&held), 1);
        w.set(2);
        assert_eq!(seen.get(), 1);
    }

    #[test]
    fn a_subscriber_may_unsubscribe_while_notified() {
        let w = Watch::new(0);
        let subs = Rc::new(Subs::default());
        let s2 = subs.clone();
        subs.follow(&w, move |v| if *v == 1 { s2.clear() });
        w.set(1);
        assert_eq!(w.count(), 0);
    }
}
