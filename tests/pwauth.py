"""Identity + terminal tokens (Chromium only -- nothing here is engine-specific).

run.sh brings up a second serverjack/ttyd pair with
SERVERJACK_ALLOW=alice@example.com behind nginx on 7698, alongside the
unrestricted pair on 7699. Playwright plays the part of `tailscale serve` by
sending (or withholding) the Tailscale-User-Login header.

What must hold:
  * no header, or the wrong login  -> 403, and the page names who it belongs to
  * the allowed login              -> the page works, and a session really attaches
  * /term/ with no token, or a wrong one -> refused on BOTH instances: no new
    tmux client, and the terminal says to open it from the page. The token is
    not tied to SERVERJACK_ALLOW; ttyd cannot tell who is calling, so it is
    always the thing that says "the page sent you".
  * /term/ with the right token -> attaches, on either instance
"""
import os
import subprocess
import time

from playwright.sync_api import sync_playwright

OPEN = "http://127.0.0.1:7699"          # no SERVERJACK_ALLOW
AUTH = "http://127.0.0.1:7698"          # SERVERJACK_ALLOW=alice@example.com
SESS = "pwtest"
TAG = str(int(time.time()))[-6:]
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]
BAD = "0" * 32

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


def term_text(page):
    """What the terminal is showing. xterm.js paints to a canvas, so run.sh
    starts this instance's ttyd with -t screenReaderMode=true, which mirrors
    the screen into .xterm-accessibility."""
    try:
        return page.evaluate(
            "() => (document.querySelector('.xterm-accessibility')"
            "       || document.body).innerText || ''")
    except Exception:
        return ""


with sync_playwright() as p:
    b = p.chromium.launch()

    # ---- the token this page would hand out, straight from the JSON API
    anon = b.new_context()
    tok = next(s["token"] for s in anon.request.get(f"{OPEN}/api/sessions").json() if s["name"] == SESS)
    ok("/api/sessions carries a per-session token", len(tok) == 32 and tok != BAD, tok)

    print("no header:")
    page = anon.new_page()
    r = page.goto(f"{AUTH}/")
    ok("landing page is 403", r.status == 403, str(r.status))
    body = page.inner_text("body")
    ok("403 page names the allowed login", "alice@example.com" in body, body[:200])
    ok("...and says who you are", "nobody" in body, body[:200])
    r = anon.request.get(f"{AUTH}/api/sessions")
    ok("JSON API is 403 too", r.status == 403, str(r.status))
    ok("/healthz needs no tailnet identity (the peer-uid check still applies)",
       anon.request.get(f"{AUTH}/healthz").status == 200)

    print("wrong login:")
    mal = b.new_context(extra_http_headers={"Tailscale-User-Login": "mallory@example.com"})
    mp = mal.new_page()
    r = mp.goto(f"{AUTH}/")
    ok("landing page is 403", r.status == 403, str(r.status))
    ok("403 page names them", "mallory@example.com" in mp.inner_text("body"), mp.inner_text("body")[:200])
    ok("POST is refused as well",
       mal.request.post(f"{AUTH}/api/kill", form={"name": SESS}).status == 403)
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
    ok("frame url carries the token", f"arg={tok}" in gp.get_attribute("#frame", "src"),
       gp.get_attribute("#frame", "src"))
    gp.frame_locator("#frame").locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000)
    time.sleep(1.5)
    gp.keyboard.type(f"echo AUTH_{TAG}")
    gp.keyboard.press("Enter")
    time.sleep(1.0)
    out = pane()
    ok("typing reaches the tmux session", out.count(f"AUTH_{TAG}") >= 2, out[-200:])
    gp.screenshot(path="shots/auth.png")
    good.close()
    time.sleep(1.0)

    print("terminal without a valid token (restricted instance):")
    for label, url in (("no token", f"{AUTH}/term/?arg={SESS}"),
                       ("wrong token", f"{AUTH}/term/?arg={SESS}&arg={BAD}")):
        before = clients()
        tp = anon.new_page()
        tp.goto(url)
        time.sleep(3.0)
        txt = term_text(tp)
        ok(f"{label}: no new terminal attaches", clients() == before, f"{before} -> {clients()}")
        msg = "Open this session from the serverjack page."
        ok(f"{label}: the terminal says {msg!r}", msg in txt, repr(" ".join(txt.split())[:200]))
        tp.close()
        time.sleep(0.5)

    print("terminal on the unrestricted instance (tokens are not tied to ALLOW):")
    for label, url in (("no token", f"{OPEN}/term/?arg={SESS}"),
                       ("wrong token", f"{OPEN}/term/?arg={SESS}&arg={BAD}")):
        time.sleep(1.0)
        before = clients()
        tp = anon.new_page()
        tp.goto(url)
        time.sleep(3.0)
        ok(f"{label}: refused even with no ALLOW list", clients() == before,
           f"{before} -> {clients()}")
        tp.close()

    time.sleep(1.0)
    before = clients()
    tp = anon.new_page()
    tp.goto(f"{OPEN}/term/?arg={SESS}&arg={tok}")
    tp.locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000)
    time.sleep(2.5)
    ok("the right token attaches", clients() > before, f"{before} -> {clients()}")
    tp.keyboard.type(f"echo TOKOK_{TAG}")
    tp.keyboard.press("Enter")
    time.sleep(1.0)
    out = pane()
    ok("...and it is a real shell", out.count(f"TOKOK_{TAG}") >= 2, out[-200:])
    tp.close()

    anon.close()
    b.close()
print("  " + ("all identity checks passed" if not fails else f"{fails} identity check(s) FAILED"))
