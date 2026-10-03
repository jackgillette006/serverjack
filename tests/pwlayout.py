"""Landing-page layout and live behaviour: what the list looks like on a phone
and a desktop, and that it keeps itself current.

Chromium desktop plus emulated WebKit iPhones (390 and 320 wide). Emulated
WebKit is not iOS Safari: these checks prove CSS geometry and page script,
not iOS-only behaviour (focus zoom, the standalone status bar, Dynamic Type),
which docs/MANUAL-TESTS.md covers on a real phone.

Uses run.sh's instance and tmux server. Sessions it needs (a long name, one
with a client attached) are made with tmux directly and killed at the end;
the two shortcuts it adds are removed again.
"""
import os
import re
import subprocess
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("SERVERJACK_TEST_BASE", "http://127.0.0.1:7690")
TAG = str(int(time.time()))[-6:]
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]
SAME = {"Sec-Fetch-Site": "same-origin"}
MADE = []
fails = 0


def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + extra) if extra and not cond else ""))
    return bool(cond)


def tmux(*args):
    return subprocess.run(T + list(args), capture_output=True, text=True)


def exists(name):
    return tmux("has-session", "-t", f"={name}").returncode == 0


def make(name):
    tmux("new-session", "-d", "-s", name, "-x", "100", "-y", "30", "sleep 900")
    MADE.append(name)
    return name


def wait_for(fn, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.25)
    return fn()


def phone(p, browser, width=None, height=None):
    d = dict(p.devices["iPhone 14"])
    d.pop("default_browser_type", None)
    if width:
        d["viewport"] = {"width": width, "height": height or 640}
    return browser.new_context(**d)


with sync_playwright() as p:
    # ------------------------------------------------------------ chrome --
    print("chromium desktop:")
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.on("pageerror", lambda e: print("   [pageerror]", e))
    page.goto(f"{BASE}/")
    ok("the page declares a dark color-scheme (dark scrollbars and checkboxes)",
       page.evaluate("getComputedStyle(document.documentElement).colorScheme") == "dark",
       page.evaluate("getComputedStyle(document.documentElement).colorScheme"))
    r = page.request.get(f"{BASE}/favicon.ico")
    ok("/favicon.ico answers with the PNG icon instead of a 404",
       r.status == 200 and r.headers.get("content-type") == "image/png"
       and r.body()[:8] == b"\x89PNG\r\n\x1a\n", f"{r.status} {r.headers.get('content-type')}")
    ctx.close()

    # ------------------------------------------- status-bar strip (iPhone) --
    print("webkit iphone 14:")
    wk = p.webkit.launch()
    ictx = phone(p, wk)
    ipage = ictx.new_page()
    ipage.on("pageerror", lambda e: print("   [pageerror]", e))
    ipage.goto(f"{BASE}/")
    # Emulated WebKit reports no safe-area inset, so stand in for the
    # home-screen app's 47px one, then scroll content under it.
    ipage.add_style_tag(content="#sbbg{height:47px!important}")
    ipage.evaluate("window.scrollTo(0, 300)")
    ipage.wait_for_timeout(300)
    strip = ipage.evaluate("""() => { const e = document.getElementById('sbbg');
      if (!e) return null; const s = getComputedStyle(e);
      return [s.position, s.backgroundColor, +s.zIndex]; }""")
    ok("a fixed, opaque strip sits behind the status bar above menus",
       bool(strip) and strip[0] == "fixed" and strip[1] == "rgb(8, 15, 14)" and strip[2] > 6, str(strip))
    ipage.screenshot(path="shots/layout-statusbar.png", clip={"x": 0, "y": 0, "width": 390, "height": 60})
    from PIL import Image
    img = Image.open("shots/layout-statusbar.png").convert("RGB")
    sx = img.width / 390.0
    band = {img.getpixel((int(x * sx), int(y * sx))) for x in range(0, 390, 13) for y in range(2, 45, 7)}
    ok("...and scrolled content no longer shows through under the clock",
       all(max(abs(c - e) for c, e in zip(px, (8, 15, 14))) <= 6 for px in band), str(sorted(band)[:6]))
    ictx.close()
    wk.close()
    b.close()

for name in MADE:
    if exists(name):
        tmux("kill-session", "-t", f"={name}")

if fails:
    raise SystemExit(1)
