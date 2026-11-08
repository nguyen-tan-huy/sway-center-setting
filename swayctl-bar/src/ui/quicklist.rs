//! Which cards the Quick Settings notification list has to build, remove or
//! keep when the history changes. Building a card (Pango layout, textures) is
//! the expensive part of opening the popup, so the list keeps the cards it has,
//! builds only what is new or changed, and only as many as the screen shows
//! (more as you scroll): opening costs the same with 5 notifications or 50.

use crate::services::notify::Notification;

/// Cards built before the popup shows (enough for a screen on most monitors;
/// the list fills up by itself when its cards are small).
pub const FIRST: usize = 8;
/// Cards added each time the scroll nears the end of what is built.
pub const MORE: usize = 8;

#[derive(Debug, PartialEq, Default)]
pub struct Plan {
    /// cards to take out: gone from the history, changed, or beyond the target
    pub remove: Vec<u32>,
    /// cards to make, in list order (new notifications, and changed ones again)
    pub build: Vec<u32>,
}

/// `existing`: the cards there are now, as the notification each was built
/// from. `wanted`: the history, newest first. `target`: how many of its first
/// items should have a card.
pub fn plan(existing: &[(u32, &Notification)], wanted: &[Notification], target: usize) -> Plan {
    let want = &wanted[..target.min(wanted.len())];
    let mut out = Plan::default();
    for (id, built_from) in existing {
        if !want.iter().any(|n| n.id == *id && n == *built_from) {
            out.remove.push(*id);
        }
    }
    for n in want {
        if !existing.iter().any(|(id, b)| *id == n.id && *b == n) {
            out.build.push(n.id);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn n(id: u32, summary: &str) -> Notification {
        Notification {
            id, app_name: "app".into(), summary: summary.into(), body: String::new(), actions: vec![],
            urgency: 1, expire_timeout: -1, image: None, transient: false, resident: false, time: 0,
        }
    }

    fn existing(items: &[Notification]) -> Vec<(u32, &Notification)> {
        items.iter().map(|n| (n.id, n)).collect()
    }

    #[test]
    fn nothing_changed_nothing_to_do() {
        let h = vec![n(3, "c"), n(2, "b"), n(1, "a")];
        assert_eq!(plan(&existing(&h), &h, 8), Plan::default());
    }

    #[test]
    fn a_new_notification_builds_one_card() {
        let old = vec![n(2, "b"), n(1, "a")];
        let new = vec![n(3, "c"), n(2, "b"), n(1, "a")];
        assert_eq!(plan(&existing(&old), &new, 8), Plan { remove: vec![], build: vec![3] });
    }

    #[test]
    fn a_closed_notification_removes_one_card() {
        let old = vec![n(3, "c"), n(2, "b"), n(1, "a")];
        let new = vec![n(3, "c"), n(1, "a")];
        assert_eq!(plan(&existing(&old), &new, 8), Plan { remove: vec![2], build: vec![] });
    }

    #[test]
    fn a_replaced_notification_is_built_again() {
        let old = vec![n(2, "b"), n(1, "a")];
        let new = vec![n(2, "b changed"), n(1, "a")];
        assert_eq!(plan(&existing(&old), &new, 8), Plan { remove: vec![2], build: vec![2] });
    }

    #[test]
    fn only_the_target_has_cards_and_growing_it_builds_the_next_ones() {
        let history: Vec<_> = (1..=20).rev().map(|i| n(i, "x")).collect(); // 20 newest first
        let first = plan(&[], &history, 8);
        assert_eq!(first.build, (13..=20).rev().collect::<Vec<_>>());
        let have = &history[..8];
        let more = plan(&existing(have), &history, 16);
        assert_eq!(more, Plan { remove: vec![], build: (5..=12).rev().collect() });
        // shrinking the target (fewer notifications than before) drops the extra cards
        let few = &history[..3];
        let after = plan(&existing(&history[..8]), few, 8);
        assert_eq!(after.remove, vec![17, 16, 15, 14, 13]);
        assert!(after.build.is_empty());
    }

    #[test]
    fn target_larger_than_the_history_is_fine() {
        let h = vec![n(1, "a")];
        assert_eq!(plan(&[], &h, 100).build, vec![1]);
    }
}
