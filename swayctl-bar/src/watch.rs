//! A value on the main thread that widgets follow: every subscriber runs once
//! right away and again on each change. Services own the Watch, widgets only
//! subscribe, so there is no polling anywhere.

use std::cell::RefCell;
use std::rc::Rc;

type Sub<T> = Box<dyn Fn(&T)>;

pub struct Watch<T> {
    value: RefCell<T>,
    subs: RefCell<Vec<Sub<T>>>,
}

impl<T: PartialEq + Clone + 'static> Watch<T> {
    pub fn new(value: T) -> Rc<Self> {
        Rc::new(Self { value: RefCell::new(value), subs: RefCell::new(Vec::new()) })
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
        for f in self.subs.borrow().iter() {
            f(&v);
        }
    }

    pub fn subscribe(&self, f: impl Fn(&T) + 'static) {
        f(&self.value.borrow());
        self.subs.borrow_mut().push(Box::new(f));
    }
}
