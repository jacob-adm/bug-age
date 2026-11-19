"""A test client session must work with an IPv6 host in base_url."""
import flask


def test_session_transaction_ipv6():
    app = flask.Flask(__name__)
    app.secret_key = "test"
    base_url = "http://[::1]:8000/"

    @app.route("/")
    def index():
        return str(flask.session.get("value"))

    client = app.test_client()
    with client.session_transaction(base_url=base_url) as sess:
        sess["value"] = 42
    assert client.get("/", base_url=base_url).get_data(as_text=True) == "42"
