// bug-age repro for fb837b4adb "Fix wordlevel encode `<unk>`".
// An unknown word got the unk id but kept its own text as the token value.
use std::collections::HashMap;
use tokenizers::models::wordlevel::WordLevel;
use tokenizers::Model;

#[test]
fn unknown_word_becomes_unk_token() {
    let mut vocab = HashMap::new();
    vocab.insert("<unk>".to_string(), 0u32);
    vocab.insert("a".to_string(), 1u32);
    let model = WordLevel::builder().vocab(vocab).unk_token("<unk>".to_string()).build().unwrap();
    let tokens = model.tokenize("c").unwrap();
    assert_eq!(tokens.len(), 1);
    assert_eq!(tokens[0].id, 0);
    assert_eq!(tokens[0].value, "<unk>");
}
