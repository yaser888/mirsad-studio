"""Entry point for Mirsad Studio."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .. import __version__

LOGGER = logging.getLogger("mirsad.studio")


def _friendly_qt_error(error: Exception) -> str:
    return (
        "Mirsad Studio needs the desktop runtime.\n\n"
        "Install it with:\n"
        '  pip install "mirsad-agent[desktop]"\n\n'
        f"Details: {error}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mirsad-studio",
        description="Mirsad Studio - a local-first desktop shell for the Mirsad agent.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Mirsad Studio {__version__}",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Open the interface with local preview data (no runtime calls).",
    )
    parser.add_argument(
        "--view",
        choices=["home", "chat", "activity", "settings"],
        default="home",
        help="Open a specific surface. Defaults to the overview.",
    )
    parser.add_argument(
        "--screenshot",
        metavar="PATH",
        help="Render the window to a PNG file and exit (useful for documentation).",
    )
    parser.add_argument(
        "--scroll",
        metavar="ANCHOR",
        default="",
        help="Initial transcript anchor: top, mid, bottom, or a pixel offset.",
    )
    parser.add_argument("--width", type=int, default=1440, help="Initial window width.")
    parser.add_argument(
        "--height", type=int, default=900, help="Initial window height."
    )
    parser.add_argument(
        "--no-gpu",
        action="store_true",
        help="Ask Chromium to use software rendering (for constrained machines).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show runtime and web console diagnostics.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    try:
        from PySide6.QtCore import QCoreApplication, Qt, QTimer
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError as exc:  # pragma: no cover - depends on the environment
        print(_friendly_qt_error(exc), file=sys.stderr)
        return 2

    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    if args.no_gpu and "--disable-gpu" not in flags:
        flags = f"{flags} --disable-gpu".strip()
    if "--lang=en-US" not in flags:
        flags = f"{flags} --lang=en-US".strip()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = flags

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    from PySide6.QtCore import QLocale

    QLocale.setDefault(QLocale("en_US"))
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:  # noqa: BLE001 - older Qt builds
        pass

    app = QApplication([sys.argv[0]])
    app.setApplicationName("Mirsad Studio")
    app.setApplicationDisplayName("Mirsad Studio")
    app.setOrganizationName("Mirsad")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(True)

    from .window import StudioWindow, apply_application_style

    apply_application_style(app)

    def excepthook(exc_type, exc_value, exc_tb):  # pragma: no cover - UI safety net
        LOGGER.exception(
            "Unhandled Studio error", exc_info=(exc_type, exc_value, exc_tb)
        )
        try:
            QMessageBox.critical(
                None,
                "Mirsad Studio",
                f"An unexpected error occurred.\n\n{exc_type.__name__}: {exc_value}",
            )
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = excepthook

    window = StudioWindow(demo=args.demo, view=args.view, scroll=args.scroll)
    window.resize(max(720, args.width), max(520, args.height))
    window.show()

    if args.screenshot:
        destination = Path(args.screenshot).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)

        def capture() -> None:
            pixmap = window.grab()
            if pixmap.isNull():
                LOGGER.error("Could not capture the Studio window.")
            else:
                if pixmap.save(str(destination), "PNG"):
                    print(destination)
                else:
                    LOGGER.error("Could not write the screenshot to %s", destination)
            window.close()
            app.quit()

        # Give Chromium time to paint the interface and settle the boot animation.
        QTimer.singleShot(2800, capture)

    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
