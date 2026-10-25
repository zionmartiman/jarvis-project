#!/usr/bin/env python3
"""Entry point of Jarvis Voice (run by systemd)."""

from jarvis.bootstrap.app import run

if __name__ == "__main__":
    run()
