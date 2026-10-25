"""Command line to queue one spoken announcement: ``python -m jarvis.cli.announce --base64 ...``."""

from __future__ import annotations

import argparse
import base64
from collections.abc import Sequence

from jarvis.config.settings import load_settings
from jarvis.infrastructure.ipc.announcer import SocketAnnouncer


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Queue a spoken Jarvis alert.")
    parser.add_argument("--base64", required=True, dest="encoded_text")
    arguments = parser.parse_args(argv)

    try:
        text = base64.b64decode(arguments.encoded_text, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise SystemExit("Invalid announcement payload.") from error

    SocketAnnouncer(load_settings().announcements.socket_path).announce(text)


if __name__ == "__main__":
    main()
