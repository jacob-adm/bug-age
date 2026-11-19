"""A Content-Type parameter without a value ("charset" alone) must not break encoding detection."""
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers


def test_charset_without_value_falls_back_to_latin1():
    headers = CaseInsensitiveDict({"content-type": "text/html; charset"})
    assert get_encoding_from_headers(headers) == "ISO-8859-1"
