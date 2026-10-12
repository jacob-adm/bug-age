// bug-age repro for a350ec3e72 "Fix a bug in the Metaspace PreTokenizer".
// With add_prefix_space, the prefix was added before spaces were replaced, so an input
// starting with a space got a doubled "▁".
use tokenizers::pre_tokenizers::metaspace::Metaspace;
use tokenizers::{OffsetReferential, OffsetType, PreTokenizedString, PreTokenizer};

#[test]
fn leading_space_is_not_doubled() {
    let pretok = Metaspace::new('▁', true);
    let mut s = PreTokenizedString::from(" Hey friend!");
    pretok.pre_tokenize(&mut s).unwrap();
    let toks: Vec<String> = s
        .get_splits(OffsetReferential::Normalized, OffsetType::Byte)
        .into_iter()
        .map(|split| split.0.to_string())
        .collect();
    assert_eq!(toks, vec!["▁Hey".to_string(), "▁friend!".to_string()]);
}
