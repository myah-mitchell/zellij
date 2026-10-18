use std::collections::BTreeMap;
use zellij_utils::data::PluginSettingsEntry;

/// Settings screen entries registered by plugins, kept for the whole session.
#[derive(Debug, Default)]
pub struct SettingsEntries {
    entries: Vec<RegisteredEntry>,
}

#[derive(Debug)]
struct RegisteredEntry {
    registered_by: String,
    entry: PluginSettingsEntry,
}

impl SettingsEntries {
    /// Returns whether the list of entries changed.
    pub fn register(
        &mut self,
        registered_by: &str,
        label: &str,
        plugin_url: Option<String>,
        configuration: BTreeMap<String, String>,
    ) -> bool {
        let label: String = label.chars().filter(|c| !c.is_control()).collect();
        let label = label.trim();
        if label.is_empty() {
            log::warn!(
                "Ignoring settings entry with an empty label from plugin {}",
                registered_by
            );
            return false;
        }
        let entry = PluginSettingsEntry {
            label: label.to_owned(),
            plugin_url: plugin_url.unwrap_or_else(|| registered_by.to_owned()),
            configuration,
        };
        let existing = self.entries.iter_mut().find(|existing| {
            existing.registered_by == registered_by && existing.entry.label == label
        });
        match existing {
            Some(existing) if existing.entry == entry => false,
            Some(existing) => {
                existing.entry = entry;
                true
            },
            None => {
                self.entries.push(RegisteredEntry {
                    registered_by: registered_by.to_owned(),
                    entry,
                });
                true
            },
        }
    }
    pub fn entries(&self) -> Vec<PluginSettingsEntry> {
        self.entries
            .iter()
            .map(|registered| registered.entry.clone())
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const STATUS: &str = "file:/plugins/status.wasm";
    const CLOCK: &str = "file:/plugins/clock.wasm";

    fn register(entries: &mut SettingsEntries, registered_by: &str, label: &str) -> bool {
        entries.register(registered_by, label, None, BTreeMap::new())
    }

    fn labels(entries: &SettingsEntries) -> Vec<String> {
        entries.entries().into_iter().map(|e| e.label).collect()
    }

    #[test]
    fn entries_keep_their_registration_order() {
        let mut entries = SettingsEntries::default();
        assert!(register(&mut entries, STATUS, "Status"));
        assert!(register(&mut entries, CLOCK, "Clock"));
        assert!(register(&mut entries, STATUS, "Status layout"));
        assert_eq!(labels(&entries), vec!["Status", "Clock", "Status layout"]);
    }

    #[test]
    fn an_entry_launches_the_registering_plugin_unless_told_otherwise() {
        let mut entries = SettingsEntries::default();
        register(&mut entries, STATUS, "Own");
        entries.register(
            STATUS,
            "Other",
            Some("file:/plugins/other.wasm".to_owned()),
            BTreeMap::new(),
        );
        let urls: Vec<String> = entries
            .entries()
            .into_iter()
            .map(|e| e.plugin_url)
            .collect();
        assert_eq!(urls, vec![STATUS, "file:/plugins/other.wasm"]);
    }

    #[test]
    fn registering_the_same_label_again_changes_nothing_and_reports_no_change() {
        let mut entries = SettingsEntries::default();
        assert!(register(&mut entries, STATUS, "Status"));
        assert!(!register(&mut entries, STATUS, "Status"));
        assert_eq!(labels(&entries), vec!["Status"]);
    }

    #[test]
    fn registering_the_same_label_with_new_details_replaces_the_entry_in_place() {
        let mut entries = SettingsEntries::default();
        register(&mut entries, STATUS, "Status");
        register(&mut entries, CLOCK, "Clock");
        let mut configuration = BTreeMap::new();
        configuration.insert("page".to_owned(), "advanced".to_owned());
        assert!(entries.register(STATUS, "Status", None, configuration.clone()));
        let all = entries.entries();
        assert_eq!(all.len(), 2);
        assert_eq!(all[0].label, "Status");
        assert_eq!(all[0].configuration, configuration);
    }

    #[test]
    fn two_plugins_can_use_the_same_label() {
        let mut entries = SettingsEntries::default();
        assert!(register(&mut entries, STATUS, "Settings"));
        assert!(register(&mut entries, CLOCK, "Settings"));
        assert_eq!(labels(&entries), vec!["Settings", "Settings"]);
    }

    #[test]
    fn a_blank_label_is_refused_and_a_padded_one_is_trimmed() {
        let mut entries = SettingsEntries::default();
        assert!(!register(&mut entries, STATUS, "   "));
        assert!(entries.entries().is_empty());
        assert!(register(&mut entries, STATUS, "  Status  "));
        assert!(!register(&mut entries, STATUS, "Status"));
        assert_eq!(labels(&entries), vec!["Status"]);
    }

    #[test]
    fn control_characters_are_stripped_from_a_label() {
        let mut entries = SettingsEntries::default();
        assert!(register(
            &mut entries,
            STATUS,
            "\u{1b}[31mStatus\nbar\u{1b}[0m"
        ));
        assert_eq!(labels(&entries), vec!["[31mStatusbar[0m"]);
        assert!(!register(&mut entries, CLOCK, "\u{1b}\n\t\r"));
        assert_eq!(entries.entries().len(), 1);
    }
}
