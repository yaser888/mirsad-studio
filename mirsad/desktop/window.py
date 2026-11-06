"""Native Qt window that hosts the local Studio interface."""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, QUrlQuery
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

from .bridge import StudioBridge

WEB_DIR = Path(__file__).resolve().parent / "web"
INDEX_FILE = WEB_DIR / "index.html"
ASSET_DIR = Path(__file__).resolve().parent / "assets"
ICON_FILE = ASSET_DIR / "icon.svg"

LOGGER = logging.getLogger("mirsad.studio")


class StudioPage(QWebEnginePage):
    """A page that can only stay on the bundled interface."""

    def acceptNavigationRequest(
        self,
        url: QUrl,
        navigation_type: QWebEnginePage.NavigationType,
        is_main_frame: bool,
    ) -> bool:
        if not is_main_frame:
            return True
        if url.scheme() == "qrc":
            return True
        if not url.isLocalFile():
            LOGGER.warning("Blocked navigation to %s", url.toString())
            return False
        try:
            target = Path(url.toLocalFile()).resolve()
            allowed = INDEX_FILE.resolve()
        except OSError:
            return False
        if target == allowed:
            return True
        LOGGER.warning("Blocked navigation outside the Studio shell: %s", target)
        return False

    def createWindow(self, _window_type):  # type: ignore[override]
        return None

    def javaScriptConsoleMessage(self, level, message, line, source):  # type: ignore[override]
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug("web %s:%s %s", source, line, message)


class StudioWindow(QMainWindow):
    def __init__(
        self, *, demo: bool = False, view: str = "home", scroll: str = ""
    ) -> None:
        super().__init__()
        self.setWindowTitle("Mirsad Studio")
        self.setMinimumSize(1080, 700)
        self.resize(1440, 900)
        self.setWindowIcon(self._load_icon())
        self.setStyleSheet("QMainWindow { background: #0a0c0b; }")

        self._bridge = StudioBridge(self)
        self._profile = QWebEngineProfile(self)
        self._profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
        self._profile.setHttpAcceptLanguage("en-US,en;q=0.9")
        self._profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )

        self._view = QWebEngineView(self)
        self._page = StudioPage(self._profile, self._view)
        self._configure_page()
        self._view.setPage(self._page)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self._view.setStyleSheet("background: #0a0c0b;")
        self.setCentralWidget(self._view)

        self._channel = QWebChannel(self._page)
        self._channel.registerObject("bridge", self._bridge)
        self._page.setWebChannel(self._channel)

        self._url = QUrl.fromLocalFile(str(INDEX_FILE))
        query = QUrlQuery()
        query.addQueryItem(
            "view", view if view in {"home", "chat", "activity", "settings"} else "home"
        )
        if demo:
            query.addQueryItem("demo", "1")
        if scroll in {"top", "mid", "bottom"} or scroll.isdigit():
            query.addQueryItem("scroll", scroll)
        self._url.setQuery(query)
        self._view.load(self._url)
        self._page.loadFinished.connect(self._on_load_finished)

    # ── appearance ───────────────────────────────────────────────────────

    def _load_icon(self) -> QIcon:
        if ICON_FILE.is_file():
            return QIcon(str(ICON_FILE))
        return QIcon()

    def _configure_page(self) -> None:
        settings = self._page.settings()
        attributes = {
            QWebEngineSettings.WebAttribute.JavascriptEnabled: True,
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls: True,
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls: False,
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows: False,
            QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard: True,
            QWebEngineSettings.WebAttribute.PluginsEnabled: False,
            QWebEngineSettings.WebAttribute.PdfViewerEnabled: False,
            QWebEngineSettings.WebAttribute.DnsPrefetchEnabled: False,
            QWebEngineSettings.WebAttribute.FullScreenSupportEnabled: False,
            QWebEngineSettings.WebAttribute.AllowRunningInsecureContent: False,
        }
        for attribute, enabled in attributes.items():
            settings.setAttribute(attribute, enabled)

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        QTimer.singleShot(20, self._apply_dark_titlebar)

    def _apply_dark_titlebar(self) -> None:
        if os.name != "nt":
            return
        try:
            hwnd = int(self.winId())
            dwm = ctypes.windll.dwmapi
            enabled = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(enabled), ctypes.sizeof(enabled)
            )
            caption = ctypes.c_int(0x000F110E)  # COLORREF: BGR for #0e110f
            dwm.DwmSetWindowAttribute(
                hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption)
            )
            border = ctypes.c_int(0x00161312)
            dwm.DwmSetWindowAttribute(
                hwnd, 34, ctypes.byref(border), ctypes.sizeof(border)
            )
            text_color = ctypes.c_int(0x00E7EEF0)
            dwm.DwmSetWindowAttribute(
                hwnd, 36, ctypes.byref(text_color), ctypes.sizeof(text_color)
            )
        except Exception:
            LOGGER.debug("Could not apply the dark title bar", exc_info=True)

    # ── lifecycle ────────────────────────────────────────────────────────

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            LOGGER.error("The Studio interface failed to load.")
            return
        LOGGER.debug("Studio interface loaded")

    def closeEvent(self, event):  # type: ignore[override]
        try:
            self._bridge.shutdown()
        except Exception:
            LOGGER.debug("Bridge shutdown failed", exc_info=True)
        LOGGER.info("Mirsad Studio closed")
        super().closeEvent(event)


def apply_application_style(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0a0c0b"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f0eee7"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0e110f"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#121613"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#f0eee7"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#121613"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f0eee7"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#d97757"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1b0f0a"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#161b17"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f0eee7"))
    app.setPalette(palette)
    if ICON_FILE.is_file():
        app.setWindowIcon(QIcon(str(ICON_FILE)))
