"""Run SootAble:  python main.py   then open http://127.0.0.1:8000

Settings (environment variables, all optional):
  SOOTABLE_HOST  address to listen on. 127.0.0.1 (default) is this computer only; 0.0.0.0 also lets a phone on the
                 same Wi-Fi open the app (the address to type is printed).
  SOOTABLE_PORT  port, default 8000.
  SOOTABLE_DB    where the local database lives, default ./data/sootable.db
  SOOTABLE_NO_BROWSER  set to 1 to stop it opening the app in your browser when it starts.
"""
import os
import socket
import threading
import webbrowser

import uvicorn


def lan_address() -> str:
    """This computer's address on the local network (no traffic is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    host = os.environ.get("SOOTABLE_HOST", "127.0.0.1")
    port = int(os.environ.get("SOOTABLE_PORT", "8000"))
    if host == "0.0.0.0":
        print(f"\n  On your phone (same Wi-Fi): http://{lan_address()}:{port}")
    print(f"  On this computer:           http://127.0.0.1:{port}\n")
    if not os.environ.get("SOOTABLE_NO_BROWSER"):
        # open the app a moment after the server is up, so there is nothing to type
        threading.Timer(1.5, webbrowser.open, args=[f"http://127.0.0.1:{port}"]).start()
    uvicorn.run("sootable.server:app", host=host, port=port)
