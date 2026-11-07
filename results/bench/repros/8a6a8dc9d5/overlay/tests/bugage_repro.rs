// bug-age repro for 8a6a8dc9d5 "Fixing decoder strip because of char boundaries".
// Strip sliced tokens by byte index, panicking inside multi-byte characters.
use tokenizers::decoders::strip::Strip;
use tokenizers::Decoder;

#[test]
fn strip_respects_char_boundaries() {
    let decoder = Strip::new(1, 0);
    let out = decoder.decode_chain(vec!["▁hello".to_string()]).unwrap();
    assert_eq!(out, vec!["hello".to_string()]);
}
