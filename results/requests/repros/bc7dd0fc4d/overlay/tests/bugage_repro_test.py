"""Header values ending in a newline are invalid and must be refused when the request is prepared."""
import pytest
import requests
from requests.exceptions import InvalidHeader


@pytest.mark.parametrize("headers", [{"foo": "bar\n"}, {"foo": "bar\r\n"}, {"foo": "\n"}])
def test_trailing_newline_in_header_value_is_refused(headers):
    with pytest.raises(InvalidHeader):
        requests.Request("GET", "http://example.invalid/", headers=headers).prepare()
