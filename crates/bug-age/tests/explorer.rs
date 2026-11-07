use bug_age::explorer::{assemble, Target, GATE_BYTES, MARKER};
use serde_json::json;

fn target(name: &str, filler: usize) -> Target {
    Target { name: name.into(), bundle: json!({"commits": {}, "pad": "x".repeat(filler)}), receipt: json!({"blameless_gate": "PASS"}) }
}

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

#[test]
fn escapes_closing_tags_inside_data() {
    let mut t = target("a", 0);
    t.bundle = json!({"subject": "</script><img src=x>"});
    let out = assemble(MARKER, &[t]).unwrap();
    assert!(!out.files[0].1.contains("</script>"));
}

#[test]
fn rejects_oversize_bad_names_duplicates_and_missing_marker() {
    assert!(assemble(MARKER, &[target("big", GATE_BYTES)]).unwrap_err().contains("size gate failed"));
    assert!(assemble(MARKER, &[target("../x", 0)]).is_err());
    assert!(assemble(MARKER, &[target("a", 0), target("a", 0)]).unwrap_err().contains("twice"));
    assert!(assemble("<p>no marker</p>", &[target("a", 0)]).is_err());
    assert!(assemble(MARKER, &[]).is_err());
}
