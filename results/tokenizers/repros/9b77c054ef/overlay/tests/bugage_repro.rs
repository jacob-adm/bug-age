// bug-age repro for 9b77c054ef "Fix off-by-one error in tokenizer::normalizer::Range::len".
use tokenizers::tokenizer::normalizer::Range;

#[test]
fn range_len_counts_inclusive_and_exclusive_bounds() {
    assert_eq!(Range::Original(3..=7).len(), Some(5));
    assert_eq!(Range::Original(3..7).len(), Some(4));
}
