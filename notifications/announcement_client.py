"""Safe local client for sending a spoken announcement to Jarvis."""

from __future__ import annotations

import argparse
import base64
import json
import socket

from config import settings


def enqueue(text: str) -> None:
    """Place one validated announcement in the local service queue."""
    payload = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")

    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as client:
        client.sendto(payload, str(settings.ANNOUNCEMENT_SOCKET_PATH))


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
