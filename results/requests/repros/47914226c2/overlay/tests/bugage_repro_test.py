"""An empty `default` entry in .netrc must not yield credentials."""
from requests.utils import get_netrc_auth


def test_empty_default_entry_gives_no_credentials(tmp_path, monkeypatch):
    netrc = tmp_path / ".netrc"
    netrc.write_text("machine example.com login user password pass\ndefault\n")
    netrc.chmod(0o600)
    # Older versions read only ~/.netrc, newer ones $NETRC first: point both at the file.
    monkeypatch.setenv("NETRC", str(netrc))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert get_netrc_auth("http://example.com/") == ("user", "pass")  # the file is read at all
    assert get_netrc_auth("http://other.example/") is None
