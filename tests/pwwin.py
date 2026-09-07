"""tmux windows in the terminal bar (Chromium only -- no engine-specific code).

The bar shows one tab per *session*; windows live inside a session. With more
than one window the active tab grows a "2/3" badge and tapping it opens a
compact list. Selecting a window is a tmux operation, not a browser one, so
the proof is `tmux display -p '#{window_index}'` on the host afterwards.

This suite adds a second window to run.sh's scratch "pwtest" session and takes
it away again, so it must run after the suites that assume one window.
"""
import os
import subprocess
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7690"
SESS = "pwtest"
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]
fails = 0


def tmux(*args):
    return subprocess.run(T + list(args), capture_output=True, text=True)


def active_index():
    return tmux("display", "-p", "-t", f"={SESS}:", "#{window_index}").stdout.strip()


def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + extra) if extra and not cond else ""))
    return bool(cond)


def wait_for(fn, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.25)
    return fn()


tmux("new-window", "-d", "-t", f"={SESS}")          # -d: don't steal the active window
made = tmux("list-windows", "-t", f"={SESS}", "-F", "#{window_index}").stdout.split()
print("windows in %s: %s" % (SESS, " ".join(made)))

try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1100, "height": 700})
        page = ctx.new_page()
        page.on("pageerror", lambda e: print("   [pageerror]", e))
        page.goto(f"{BASE}/s/{SESS}")
        page.wait_for_selector("#tabs .tab.on")

        # ------------------------------------------------------ /api/windows --
        wins = page.request.get(f"{BASE}/api/windows?name={SESS}").json()
        ok("/api/windows lists both windows", len(wins) == 2, str(wins))
        ok("...with index, name, active and cmd",
           all(set(("index", "name", "active", "cmd")) <= set(w) for w in wins), str(wins))
        ok("...exactly one marked active",
           sum(1 for w in wins if w["active"]) == 1, str(wins))
        ok("/api/windows 404s for a session that isn't there",
           page.request.get(f"{BASE}/api/windows?name=nope-{int(time.time())}").status == 404)

        # ------------------------------------------------------------ badge --
        badge = wait_for(lambda: page.locator("#tabs .tab.on .wb").count() == 1)
        ok("active tab grows a window-count badge", badge,
           page.locator("#tabs .tab.on").inner_text())
        if badge:
            txt = page.locator("#tabs .tab.on .wb").inner_text()
            ok("...reading <position>/<count>", txt.strip().endswith("/2"), repr(txt))
        ok("the tab still carries the session name and .on",
           SESS in page.locator("#tabs .tab.on").inner_text(),
           page.locator("#tabs .tab.on").inner_text())

        # ------------------------------------------------------- the menu --
        page.click("#tabs .tab.on")
        page.wait_for_selector("#winmenu:not([hidden])", timeout=5000)
        rows = page.locator("#winmenu button")
        ok("clicking the active tab opens the window list", rows.count() == 2,
           str(rows.count()))
        ok("...marking the active window", page.locator("#winmenu button.on").count() == 1)
        page.screenshot(path="shots/windows-menu.png")

        # select window 0 and check tmux really moved
        tmux("select-window", "-t", f"={SESS}:1")     # start from the other one
        time.sleep(0.3)
        page.reload()
        page.wait_for_selector("#tabs .tab.on")
        page.wait_for_selector("#tabs .tab.on .wb", timeout=5000)
        page.click("#tabs .tab.on")
        page.wait_for_selector("#winmenu:not([hidden])", timeout=5000)
        page.click("#winmenu button:has(.wi:text-matches('^0$'))")
        moved = wait_for(lambda: active_index() == "0")
        ok("tapping a window selects it in tmux", moved, "window index " + active_index())
        ok("...and the menu closes", page.locator("#winmenu[hidden]").count() == 1)

        # Escape closes it
        page.click("#tabs .tab.on")
        page.wait_for_selector("#winmenu:not([hidden])", timeout=5000)
        page.keyboard.press("Escape")
        ok("Escape closes the window list",
           wait_for(lambda: page.locator("#winmenu[hidden]").count() == 1))

        # ------------------------------------ one window: tab click does nothing --
        tmux("kill-window", "-t", f"={SESS}:1")
        time.sleep(0.3)
        page.reload()
        page.wait_for_selector("#tabs .tab.on")
        time.sleep(1)
        ok("badge is gone with one window", page.locator("#tabs .tab.on .wb").count() == 0,
           page.locator("#tabs .tab.on").inner_text())
        page.click("#tabs .tab.on")
        time.sleep(0.4)
        ok("clicking the only tab opens no menu",
           page.locator("#winmenu[hidden]").count() == 1)
        b.close()
finally:
    # leave pwtest exactly as we found it: one window
    for idx in tmux("list-windows", "-t", f"={SESS}", "-F", "#{window_index}").stdout.split()[1:]:
        tmux("kill-window", "-t", f"={SESS}:{idx}")
print("  " + ("all window checks passed" if not fails else f"{fails} window check(s) FAILED"))
