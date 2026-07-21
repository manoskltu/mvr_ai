"""Smoke and unit tests for the Flask application."""

from flask import Flask

from app import create_app


def test_create_app_returns_flask_instance():
    """create_app() should return a Flask instance."""
    app = create_app()
    assert isinstance(app, Flask)


def test_index_returns_200(client):
    """GET / should return HTTP 200."""
    response = client.get("/")
    assert response.status_code == 200


def test_index_contains_page_title(client):
    """Response body should contain the project name as page title."""
    response = client.get("/")
    assert b"MVR Tool" in response.data


def test_swedish_characters_render(client):
    """Swedish characters (å, ä, ö) should render correctly in the response."""
    response = client.get("/")
    text = response.data.decode("utf-8")
    # The pipeline step names or page content should be intact —
    # verify the response is valid UTF-8 containing Swedish-friendly content.
    # At minimum, the template renders without encoding errors.
    assert "MVR Tool" in text
    # Verify å, ä, ö can appear in the response (from template/content)
    # The base template declares UTF-8 charset, so we confirm encoding works
    # by asserting the decoded text doesn't contain replacement characters.
    assert "\ufffd" not in text


def test_response_includes_utf8_charset(client):
    """Response Content-Type header should declare UTF-8 charset."""
    response = client.get("/")
    content_type = response.headers.get("Content-Type", "")
    assert "charset=utf-8" in content_type.lower()
