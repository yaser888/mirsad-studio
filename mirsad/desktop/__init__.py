"""Mirsad Studio desktop application."""

__all__ = ["main"]


def main() -> int:
    from .app import main as run

    return run()
