// bug-age repro for c046da7679 "Fix stripping strings containing Unicode characters".
// strip() compared char indices against the byte length, so trailing whitespace after
// multi-byte characters was not removed.
use tokenizers::NormalizedString;

#[test]
fn strip_removes_whitespace_around_unicode() {
    let mut n = NormalizedString::from("  你好asa \n");
    n.strip();
    assert_eq!(n.get(), "你好asa");
}
