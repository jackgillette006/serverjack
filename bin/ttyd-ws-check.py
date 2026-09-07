#!/usr/bin/env python3
"""Probe ttyd's WebSocket handshake: same-origin must be accepted (101),
a foreign Origin must be refused (ttyd -O). Usage:
    ttyd-ws-check.py https://<machine>.<tailnet>.ts.net/term/
Exit 0 only if both hold."""
import base64, os, sys, http.client, ssl
from urllib.parse import urlparse

u = urlparse(sys.argv[1])
def handshake(origin):
    C = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    kw = {"context": ssl.create_default_context()} if u.scheme == "https" else {}
    c = C(u.hostname, u.port, timeout=15, **kw)
    c.request("GET", u.path.rstrip("/") + "/ws", headers={
        "Host": u.netloc, "Origin": origin, "Upgrade": "websocket", "Connection": "Upgrade",
        "Sec-WebSocket-Version": "13", "Sec-WebSocket-Protocol": "tty",
        "Sec-WebSocket-Key": base64.b64encode(os.urandom(16)).decode()})
    try:
        r = c.getresponse(); return r.status
    except (http.client.HTTPException, OSError):
        return "closed"          # ttyd -O drops bad-origin sockets without a reply
    finally:
        c.close()

same = handshake(f"{u.scheme}://{u.netloc}")
evil = handshake("https://evil.example")
print(f"  same-origin websocket: {same} ({'ok' if same == 101 else 'BROKEN'})")
print(f"  foreign-origin websocket: {evil} ({'refused, ok' if evil != 101 else 'ACCEPTED - origin check not working'})")
sys.exit(0 if same == 101 and evil != 101 else 1)
