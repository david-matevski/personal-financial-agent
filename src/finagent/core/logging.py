"""Minimal stdlib logging setup.

Never log raw statement text, card numbers, or amounts tied to a merchant
at INFO or above (see AGENTS.md §3).
"""

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with a simple stream handler."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
