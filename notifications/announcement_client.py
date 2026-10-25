"""Safe local client for sending a spoken announcement to Jarvis."""

from __future__ import annotations

import argparse
import base64

from config import settings
from jarvis.infrastructure.ipc.announcer import SocketAnnouncer


def enqueue(text: str) -> None:
    """Place one announcement in the local service queue (logs a warning if nobody listens)."""
    SocketAnnouncer(settings.ANNOUNCEMENT_SOCKET_PATH).announce(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue a spoken Jarvis alert.")
    parser.add_argument("--base64", required=True, dest="encoded_text")
    arguments = parser.parse_args()

    try:
        text = base64.b64decode(arguments.encoded_text, validate=True).decode(
            "utf-8"
        )
    except (ValueError, UnicodeDecodeError) as error:
        raise SystemExit("Invalid announcement payload.") from error

    enqueue(text)


if __name__ == "__main__":
    main()
