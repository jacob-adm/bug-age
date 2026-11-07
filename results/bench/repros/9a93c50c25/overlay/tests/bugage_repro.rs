// bug-age repro for 9a93c50c25 "Fix stride condition".
// with_truncation rejected stride == effective max length (<= instead of <).
use std::collections::HashMap;
use tokenizers::models::wordlevel::WordLevel;
use tokenizers::{Tokenizer, TruncationParams};

#[test]
fn stride_equal_to_max_length_is_accepted() {
    let mut vocab = HashMap::new();
    vocab.insert("<unk>".to_string(), 0u32);
    let model = WordLevel::builder().vocab(vocab).unk_token("<unk>".to_string()).build().unwrap();
    let mut tokenizer = Tokenizer::new(model);
    let params = TruncationParams { max_length: 2, stride: 2, ..Default::default() };
    assert!(tokenizer.with_truncation(Some(params)).is_ok());
}
