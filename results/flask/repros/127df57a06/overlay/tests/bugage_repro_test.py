"""register_error_handler refuses an exception instance and a class that is not an exception."""
import flask
import pytest


class CustomException(Exception):
    pass


def test_register_error_handler_rejects_bad_arguments():
    app = flask.Flask(__name__)
    with pytest.raises(TypeError):
        app.register_error_handler(CustomException(), None)
    with pytest.raises(ValueError):
        app.register_error_handler(list, None)
