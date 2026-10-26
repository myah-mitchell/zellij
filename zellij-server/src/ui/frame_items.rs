//! Text that plugins place on pane frames (see `set_pane_frame_items` and
//! `set_default_frame_items` in zellij-tile), kept on the screen and shared with every tab so
//! frames can look up their items while rendering.

use crate::panes::PaneId;
use std::cell::RefCell;
use std::collections::{BTreeMap, HashMap};
use std::rc::Rc;
use zellij_utils::attention::sanitize_display_text;
use zellij_utils::data::FrameItem;

pub type SharedFrameItems = Rc<RefCell<FrameItems>>;

/// The items one plugin shows on one pane frame. They are laid out together and shown only
/// when all of them fit.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FrameItemGroup {
    pub plugin_id: u32,
    pub items: Vec<FrameItem>,
}

#[derive(Debug, Default)]
pub struct FrameItems {
    // plugin ids are ordered so that groups always appear in the same order
    per_pane: HashMap<PaneId, BTreeMap<u32, Vec<FrameItem>>>,
    defaults: BTreeMap<u32, Vec<FrameItem>>,
}

impl FrameItems {
    /// Returns whether anything changed, so callers only re-render when they have to.
    pub fn set_for_pane(&mut self, plugin_id: u32, pane_id: PaneId, items: Vec<FrameItem>) -> bool {
        let items = sanitize(items);
        let plugin_items = self.per_pane.entry(pane_id).or_default();
        let changed = if items.is_empty() {
            plugin_items.remove(&plugin_id).is_some()
        } else {
            plugin_items.insert(plugin_id, items.clone()) != Some(items)
        };
        if plugin_items.is_empty() {
            self.per_pane.remove(&pane_id);
        }
        changed
    }
    /// Returns whether anything changed, so callers only re-render when they have to.
    pub fn set_defaults(&mut self, plugin_id: u32, items: Vec<FrameItem>) -> bool {
        let items = sanitize(items);
        if items.is_empty() {
            self.defaults.remove(&plugin_id).is_some()
        } else {
            self.defaults.insert(plugin_id, items.clone()) != Some(items)
        }
    }
    /// Drops everything a plugin placed, eg. once it unloads. Returns whether it had any items.
    pub fn forget_plugin(&mut self, plugin_id: u32) -> bool {
        let mut changed = self.defaults.remove(&plugin_id).is_some();
        self.per_pane.retain(|_, plugin_items| {
            changed |= plugin_items.remove(&plugin_id).is_some();
            !plugin_items.is_empty()
        });
        changed
    }
    /// Drops the items placed on a pane that closed.
    pub fn forget_pane(&mut self, pane_id: PaneId) {
        self.per_pane.remove(&pane_id);
    }
    /// One group per plugin with items for this pane: the items it placed on the pane, or
    /// otherwise its default items. Ordered by plugin id.
    pub fn groups_for_pane(&self, pane_id: PaneId) -> Vec<FrameItemGroup> {
        // this runs for every pane on every render, so the common case of no items is kept cheap
        let pane_items = self.per_pane.get(&pane_id);
        if self.defaults.is_empty() && pane_items.is_none() {
            return vec![];
        }
        let mut groups: BTreeMap<u32, &Vec<FrameItem>> = self
            .defaults
            .iter()
            .map(|(plugin_id, items)| (*plugin_id, items))
            .collect();
        if let Some(pane_items) = pane_items {
            for (plugin_id, items) in pane_items {
                groups.insert(*plugin_id, items);
            }
        }
        groups
            .into_iter()
            .map(|(plugin_id, items)| FrameItemGroup {
                plugin_id,
                items: items.clone(),
            })
            .collect()
    }
}

// item text ends up in the terminal output, so control characters (and with them escape
// sequences) are removed, as are items left with no text
fn sanitize(items: Vec<FrameItem>) -> Vec<FrameItem> {
    items
        .into_iter()
        .map(|item| FrameItem {
            text: sanitize_display_text(&item.text),
            ..item
        })
        .filter(|item| !item.text.is_empty())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn group(plugin_id: u32, items: &[FrameItem]) -> FrameItemGroup {
        FrameItemGroup {
            plugin_id,
            items: items.to_vec(),
        }
    }

    #[test]
    fn items_placed_on_a_pane_take_the_place_of_the_same_plugins_defaults() {
        let mut frame_items = FrameItems::default();
        let default_item = FrameItem::new("close", "[X]").clickable();
        let pane_item = FrameItem::new("minimize", "[-]").clickable();
        frame_items.set_defaults(1, vec![default_item.clone()]);
        frame_items.set_for_pane(1, PaneId::Terminal(2), vec![pane_item.clone()]);
        assert_eq!(
            frame_items.groups_for_pane(PaneId::Terminal(2)),
            vec![group(1, &[pane_item])]
        );
        assert_eq!(
            frame_items.groups_for_pane(PaneId::Terminal(3)),
            vec![group(1, &[default_item])]
        );
    }

    #[test]
    fn each_plugin_gets_its_own_group_in_plugin_id_order() {
        let mut frame_items = FrameItems::default();
        let first = FrameItem::new("a", "a");
        let second = FrameItem::new("b", "b");
        frame_items.set_for_pane(7, PaneId::Plugin(1), vec![second.clone()]);
        frame_items.set_defaults(3, vec![first.clone()]);
        assert_eq!(
            frame_items.groups_for_pane(PaneId::Plugin(1)),
            vec![group(3, &[first]), group(7, &[second])]
        );
    }

    #[test]
    fn an_empty_list_removes_the_items_and_brings_back_the_defaults() {
        let mut frame_items = FrameItems::default();
        let default_item = FrameItem::new("close", "[X]");
        frame_items.set_defaults(1, vec![default_item.clone()]);
        frame_items.set_for_pane(1, PaneId::Terminal(2), vec![FrameItem::new("a", "a")]);
        assert!(frame_items.set_for_pane(1, PaneId::Terminal(2), vec![]));
        assert_eq!(
            frame_items.groups_for_pane(PaneId::Terminal(2)),
            vec![group(1, &[default_item])]
        );
        assert!(frame_items.set_defaults(1, vec![]));
        assert!(frame_items.groups_for_pane(PaneId::Terminal(2)).is_empty());
    }

    #[test]
    fn setting_the_same_items_again_reports_no_change() {
        let mut frame_items = FrameItems::default();
        let items = vec![FrameItem::new("a", "a")];
        assert!(frame_items.set_for_pane(1, PaneId::Terminal(2), items.clone()));
        assert!(!frame_items.set_for_pane(1, PaneId::Terminal(2), items.clone()));
        assert!(frame_items.set_defaults(1, items.clone()));
        assert!(!frame_items.set_defaults(1, items));
        assert!(!frame_items.set_for_pane(1, PaneId::Terminal(9), vec![]));
    }

    #[test]
    fn control_characters_are_removed_and_items_left_empty_are_dropped() {
        let mut frame_items = FrameItems::default();
        frame_items.set_for_pane(
            1,
            PaneId::Terminal(2),
            vec![
                FrameItem::new("styled", "\u{1b}[31mred\u{1b}[0m"),
                FrameItem::new("empty", "\u{7}\n"),
            ],
        );
        assert_eq!(
            frame_items.groups_for_pane(PaneId::Terminal(2)),
            vec![group(1, &[FrameItem::new("styled", "[31mred[0m")])]
        );
    }

    #[test]
    fn forgetting_a_plugin_drops_its_defaults_and_pane_items_only() {
        let mut frame_items = FrameItems::default();
        let other = FrameItem::new("b", "b");
        frame_items.set_defaults(1, vec![FrameItem::new("a", "a")]);
        frame_items.set_for_pane(1, PaneId::Terminal(2), vec![FrameItem::new("a", "a")]);
        frame_items.set_for_pane(2, PaneId::Terminal(2), vec![other.clone()]);
        assert!(frame_items.forget_plugin(1));
        assert!(!frame_items.forget_plugin(1));
        assert_eq!(
            frame_items.groups_for_pane(PaneId::Terminal(2)),
            vec![group(2, &[other])]
        );
    }

    #[test]
    fn forgetting_a_pane_keeps_the_defaults() {
        let mut frame_items = FrameItems::default();
        let default_item = FrameItem::new("close", "[X]");
        frame_items.set_defaults(1, vec![default_item.clone()]);
        frame_items.set_for_pane(1, PaneId::Terminal(2), vec![FrameItem::new("a", "a")]);
        frame_items.forget_pane(PaneId::Terminal(2));
        assert_eq!(
            frame_items.groups_for_pane(PaneId::Terminal(2)),
            vec![group(1, &[default_item])]
        );
    }
}
