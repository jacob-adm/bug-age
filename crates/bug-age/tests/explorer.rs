//! Explorer assembly: data scripts are linked in order, data cannot break out of its script,
//! and the size gate and name checks hold.

use bug_age::explorer::{assemble, Target, GATE_BYTES, MARKER};
use serde_json::json;

/// A target with an empty bundle padded to `filler` bytes, for size-gate tests.
fn target(name: &str, filler: usize) -> Target {
    Target { name: name.into(), bundle: json!({"commits": {}, "pad": "x".repeat(filler)}), receipt: json!({"blameless_gate": "PASS"}) }
}

/// Each target gets one data script, linked in order and before the page's own script.
#[test]
fn links_one_data_script_per_target_in_order() {
    let page = format!("<title>t</title>{MARKER}<script>boot()</script>");
    let out = assemble(&page, &[target("tokenizers", 0), target("rust-sdk", 0)]).unwrap();
    let a = out.page.find("data/tokenizers.js").unwrap();
    let b = out.page.find("data/rust-sdk.js").unwrap();
    assert!(a < b && b < out.page.find("boot()").unwrap());
    assert!(!out.page.contains(MARKER));
    assert_eq!(out.files.len(), 2);
    assert!(out.files[1].1.starts_with("(window.BUG_AGE = window.BUG_AGE || []).push({"));
}

/// `</script>` inside bundle text cannot end the data script early.
#[test]
fn escapes_closing_tags_inside_data() {
    let mut t = target("a", 0);
    t.bundle = json!({"subject": "</script><img src=x>"});
    let out = assemble(MARKER, &[t]).unwrap();
    assert!(!out.files[0].1.contains("</script>"));
}

/// Assembly fails over the size gate, on unsafe or repeated names, without the marker, and with no targets.
#[test]
fn rejects_oversize_bad_names_duplicates_and_missing_marker() {
    assert!(assemble(MARKER, &[target("big", GATE_BYTES)]).unwrap_err().contains("size gate failed"));
    assert!(assemble(MARKER, &[target("../x", 0)]).is_err());
    assert!(assemble(MARKER, &[target("a", 0), target("a", 0)]).unwrap_err().contains("twice"));
    assert!(assemble("<p>no marker</p>", &[target("a", 0)]).is_err());
    assert!(assemble(MARKER, &[]).is_err());
}
