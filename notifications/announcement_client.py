"""Deprecated: kept until the Raspberry Pi units and the Vento alert caller
use the jarvis.* modules.
"""

from jarvis.cli.announce import main
from jarvis.config.settings import load_settings
from jarvis.infrastructure.ipc.announcer import SocketAnnouncer


def enqueue(text: str) -> None:
    SocketAnnouncer(load_settings().announcements.socket_path).announce(text)


if __name__ == "__main__":
    main()
