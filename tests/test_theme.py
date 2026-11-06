from __future__ import annotations

from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent / "mirsad" / "desktop" / "web"


def test_light_theme_palette_declared():
    css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")
    assert '[data-theme="light"]' in css
    assert "--ink: #f6f4ee" in css
    assert "--paper: #1a1d1b" in css


def test_light_theme_toggle_and_bridge_wired():
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert 'id="theme-toggle"' in html
    assert "applyTheme(currentTheme())" in js
