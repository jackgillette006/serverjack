"""Identity, and the terminal being behind it (Chromium only -- nothing here is
engine-specific).

run.sh brings up two serverjack instances, each with its own ttyd on its own
Unix socket: one with no SERVERJACK_ALLOW and one with
SERVERJACK_ALLOW=alice@example.com. Playwright plays the part of `tailscale
serve` by sending (or withholding) the Tailscale-User-Login header.

There are no terminal tokens any more. serverjack serves /term/ itself, by
proxying to ttyd's socket, so the identity check covers the terminal exactly
as it covers the page -- which is what these assertions are about:
  * no header, or the wrong login  -> 403, and the page does not name the owner
  * the allowed login              -> the page works, and a session really attaches
  * /term/ on the restricted instance with no header -> 403, for the page fetch
    AND for a raw WebSocket handshake to /term/ws (no new tmux client either)
  * /term/ with the allowed header -> attaches end to end
  * /term/ on the unrestricted instance -> attaches
"""
import base64
import http.client
import os
import subprocess
import time

from playwright.sync_api import sync_playwright

OPEN = os.environ.get("SERVERJACK_TEST_BASE", "http://127.0.0.1:7690")
AUTH = os.environ.get("SERVERJACK_TEST_AUTH_BASE", "http://127.0.0.1:7692")
SESS = "pwtest"
TAG = str(int(time.time()))[-6:]
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]

fails = 0


def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + extra) if extra and not cond else ""))


def pane():
    return subprocess.run(T + ["capture-pane", "-p", "-t", f"={SESS}:"], capture_output=True, text=True).stdout


def clients():
    """How many terminals are attached to the scratch session right now."""
    r = subprocess.run(T + ["display", "-p", "-t", f"={SESS}:", "#{session_attached}"],
                       capture_output=True, text=True)
    return int((r.stdout.strip() or "0"))


def ws_status(base, headers=None):
    """Raw WebSocket handshake against <base>/term/ws, bypassing the browser:
    the status serverjack answers with, or "closed" if it hung up. This is the
    route a device turned away by SERVERJACK_ALLOW would try to sneak in on."""
    host = base.split("//", 1)[1]
    h = {"Host": host, "Origin": base, "Upgrade": "websocket", "Connection": "Upgrade",
         "Sec-WebSocket-Version": "13", "Sec-WebSocket-Protocol": "tty",
         "Sec-WebSocket-Key": base64.b64encode(os.urandom(16)).decode()}
    h.update(headers or {})
    hostname, _, port = host.partition(":")
    c = http.client.HTTPConnection(hostname, int(port), timeout=15)
    try:
        c.request("GET", "/term/ws", headers=h)
        return c.getresponse().status
    except (http.client.HTTPException, OSError):
        return "closed"
    finally:
        c.close()


def attaches(ctx, base, label):
    """Open <base>/term/?arg=SESS and prove a real shell is on the other end."""
    before = clients()
    tp = ctx.new_page()
    tp.goto(f"{base}/term/?arg={SESS}")
    tp.locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000)
    time.sleep(2.5)
    ok(f"{label}: the terminal attaches", clients() > before, f"{before} -> {clients()}")
    marker = f"TERM{label.upper().replace(' ', '')}_{TAG}"
    tp.keyboard.type(f"echo {marker}")
    tp.keyboard.press("Enter")
    time.sleep(1.0)
    out = pane()
    ok(f"{label}: ...and it is a real shell", out.count(marker) >= 2, out[-200:])
    tp.close()
    time.sleep(1.0)


with sync_playwright() as p:
    b = p.chromium.launch()
    anon = b.new_context()

    ok("/api/sessions no longer hands out a terminal token",
       all("token" not in s for s in anon.request.get(f"{OPEN}/api/sessions").json()),
       str(anon.request.get(f"{OPEN}/api/sessions").json())[:200])

    print("no header:")
    page = anon.new_page()
    r = page.goto(f"{AUTH}/")
    ok("landing page is 403", r.status == 403, str(r.status))
    body = page.inner_text("body")
    ok("403 page does NOT name the allowed login", "alice@example.com" not in body, body[:200])
    ok("...and says who you are", "nobody" in body, body[:200])
    r = anon.request.get(f"{AUTH}/api/sessions")
    ok("JSON API is 403 too", r.status == 403, str(r.status))
    for asset in ("/manifest.webmanifest", "/icon.svg", "/icon-180.png"):
        r = anon.request.get(f"{AUTH}{asset}")
        ok(f"{asset} does not leak restricted instance branding", r.status == 403,
           str(r.status))
    ok("/healthz needs no tailnet identity (the peer-uid check still applies)",
       anon.request.get(f"{AUTH}/healthz").status == 200)

    print("the terminal is behind the same check:")
    before = clients()
    r = anon.request.get(f"{AUTH}/term/")
    ok("GET /term/ is 403 without the header", r.status == 403, str(r.status))
    st = ws_status(AUTH)
    ok("a raw /term/ws handshake is refused too", st == 403, str(st))
    tp = anon.new_page()
    tp.goto(f"{AUTH}/term/?arg={SESS}")
    time.sleep(3.0)
    ok("no new terminal attaches", clients() == before, f"{before} -> {clients()}")
    tp.close()
    ok("...and the unrestricted instance is not affected",
       ws_status(OPEN) == 101, str(ws_status(OPEN)))

    print("wrong login:")
    mal = b.new_context(extra_http_headers={"Tailscale-User-Login": "mallory@example.com"})
    mp = mal.new_page()
    r = mp.goto(f"{AUTH}/")
    ok("landing page is 403", r.status == 403, str(r.status))
    ok("403 page names them", "mallory@example.com" in mp.inner_text("body"), mp.inner_text("body")[:200])
    ok("POST is refused as well",
       mal.request.post(f"{AUTH}/api/kill", headers={"Sec-Fetch-Site": "same-origin"},
                        form={"name": SESS}).status == 403)
    ok("and so is the terminal", mal.request.get(f"{AUTH}/term/").status == 403)
    st = ws_status(AUTH, {"Tailscale-User-Login": "mallory@example.com"})
    ok("...websocket included", st == 403, str(st))
    mal.close()

    print("allowed login:")
    good = b.new_context(viewport={"width": 1100, "height": 700},
                         extra_http_headers={"Tailscale-User-Login": "alice@example.com"})
    gp = good.new_page()
    gp.on("pageerror", lambda e: print("   [pageerror]", e))
    r = gp.goto(f"{AUTH}/")
    ok("landing page is 200", r.status == 200, str(r.status))
    gp.goto(f"{AUTH}/s/{SESS}")
    gp.wait_for_selector("#tabs .tab.on")
    src = gp.get_attribute("#frame", "src")
    ok("frame url carries the session name and nothing else",
       src == f"/term/?arg={SESS}", src)
    gp.frame_locator("#frame").locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000)
    time.sleep(1.5)
    gp.keyboard.type(f"echo AUTH_{TAG}")
    gp.keyboard.press("Enter")
    time.sleep(1.0)
    out = pane()
    ok("typing reaches the tmux session through the proxied terminal",
       out.count(f"AUTH_{TAG}") >= 2, out[-200:])
    gp.screenshot(path="shots/auth.png")
    st = ws_status(AUTH, {"Tailscale-User-Login": "alice@example.com"})
    ok("a websocket handshake with the header is accepted", st == 101, str(st))
    good.close()
    time.sleep(1.0)

    print("terminal end to end:")
    attaches(anon, OPEN, "unrestricted")
    allowed = b.new_context(extra_http_headers={"Tailscale-User-Login": "alice@example.com"})
    attaches(allowed, AUTH, "allowed")
    allowed.close()

    anon.close()
    b.close()
print("  " + ("all identity checks passed" if not fails else f"{fails} identity check(s) FAILED"))
if fails:
    raise SystemExit(1)
