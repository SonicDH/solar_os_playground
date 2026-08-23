"""Cyberspace: a human-operated social client for SolarOS."""

import sys

import solaros

from cyber_api import Client
from cyber_session import SessionStore
from cyber_ui import Controller


def app_directory():
    path = sys.argv[0] if sys.argv else "main.py"
    separator = path.rfind("/")
    return path[:separator] if separator > 0 else "."


def main():
    http = getattr(solaros, "http", None)
    if http is None or not hasattr(http, "request") or not hasattr(http, "stream_open"):
        raise RuntimeError("Cyberspace needs the SolarOS HTTP client and stream APIs")
    store = SessionStore(app_directory() + "/session.json",
                         getattr(solaros, "storage", None))
    client = Client(http, session_store=store)
    try:
        Controller(client).run()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            client.close()
        except (AttributeError, OSError):
            pass
        try:
            http.stream_close_all()
        except (AttributeError, OSError):
            pass


main()
