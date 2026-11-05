from __future__ import annotations

import pytest

from mirsad.tools.web import (
    WebError,
    _clean_ddg_url,
    _html_to_text,
    _validate_public_url,
    web_fetch,
)


def test_html_to_text_strips_markup_and_scripts():
    raw = """
    <html><head><title>T</title><script>alert('x')</script></head>
    <body><h1>Title</h1><p>Hello&nbsp;<b>world</b></p><ul><li>One</li></ul></body></html>
    """
    text = _html_to_text(raw)
    assert "Title" in text
    assert "Hello world" in text
    assert "One" in text
    assert "alert" not in text
    assert "<" not in text


def test_clean_duckduckgo_redirect():
    raw = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=abc"
    assert _clean_ddg_url(raw) == "https://example.com/page"


def test_block_private_urls():
    with pytest.raises(WebError):
        _validate_public_url("http://127.0.0.1:8000")
    with pytest.raises(WebError):
        _validate_public_url("http://localhost:11434")
    with pytest.raises(WebError):
        _validate_public_url("file:///etc/passwd")


def test_web_fetch_rejects_private_before_request():
    with pytest.raises(WebError):
        web_fetch("http://127.0.0.1:9")
