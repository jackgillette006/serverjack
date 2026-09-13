"""HTTP parser and restricted-route security regressions against run.sh servers."""
import http.client
import os
import socket
from urllib.parse import urlsplit

BASE = os.environ["SERVERJACK_TEST_BASE"]
AUTH = os.environ["SERVERJACK_TEST_AUTH_BASE"]
fails = 0


def ok(label, condition, extra=""):
    global fails
    if not condition:
        fails += 1
    print(("  PASS " if condition else "  FAIL ") + label
          + (("  -- " + extra) if extra and not condition else ""))


def request_status(base, method, path, headers=None):
    target = urlsplit(base)
    conn = http.client.HTTPConnection(target.hostname, target.port, timeout=5)
    try:
        conn.request(method, path, headers=headers or {})
        return conn.getresponse().status
    finally:
        conn.close()


def raw_content_length(value):
    target = urlsplit(BASE)
    request = (f"POST /run HTTP/1.1\r\nHost: {target.netloc}\r\n"
               "Sec-Fetch-Site: same-origin\r\n"
               f"Content-Length: {value}\r\nConnection: close\r\n\r\n")
    with socket.create_connection((target.hostname, target.port), timeout=5) as conn:
        conn.settimeout(5)
        conn.sendall(request.encode("ascii"))
        first_line = conn.recv(4096).split(b"\r\n", 1)[0]
    try:
        return int(first_line.split()[1])
    except (IndexError, ValueError):
        return 0


headers = {"Sec-Fetch-Site": "same-origin", "Content-Length": "0"}
for path in ("/healthz", "/api/status"):
    status = request_status(AUTH, "POST", path, headers)
    ok(f"restricted POST {path} requires identity", status == 403, str(status))

for value, expected in (("invalid", 400), ("-1", 400), ("65537", 413)):
    status = raw_content_length(value)
    ok(f"Content-Length {value!r} is rejected", status == expected,
       f"{status}, wanted {expected}")

status = request_status(BASE, "GET", "/healthz")
ok("server stays healthy after malformed body headers", status == 200, str(status))

if fails:
    raise SystemExit(1)
