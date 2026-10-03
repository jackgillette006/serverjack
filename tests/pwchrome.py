"""Terminal page chrome: the tab strip, the + panel, and the frame's connection.

Chromium, Firefox and WebKit (iPhone emulation -- emulated WebKit is NOT iOS
Safari). What is proven here:

- the terminal reconnects BY ITSELF after serverjack, ttyd or both restart
  (run.sh's fourth instance, driven through tests/restartable.sh), and after
  the frame loaded our own 502 page while ttyd was down;
- a session renamed elsewhere is followed (tab, URL, title; frame not
  reloaded), one that ended sends the tab to the list and closes a pop-out --
  never quietly attaching some other session;
- Back after switching tabs never leaves the frame on a different session
  from the bar;
- the + panel: Escape / + / Cancel / a click in the terminal close it and put
  the keyboard back, aria-expanded, a name is optional for every type, a
  double submit starts one session, no CRT toggle in it;
- the strip: edge fades, the mouse wheel, polls that change nothing touch
  nothing, the active tab and its window badge in view, long names cut with
  an ellipsis, the window list built from fresh data;
- a refit after load (no dead band), no scrollbar strip, no touchCss error.

Sessions it makes are all called pwc-*, and are killed at the end.
"""
import os
import subprocess
import time

from playwright.sync_api import sync_playwright, Error as PlaywrightError

BASE = os.environ.get("SERVERJACK_TEST_BASE", "http://127.0.0.1:7690")
RS_BASE = os.environ.get("SERVERJACK_TEST_RS_BASE", "")
RS_CTL = os.environ.get("SERVERJACK_TEST_RS_CTL", "")
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]
TAG = str(int(time.time()))[-5:]
fails = 0

FOCUSED = ("(() => { const f = document.getElementById('frame'), d = f.contentDocument;"
           " return document.activeElement === f && !!d && !!d.activeElement &&"
           " d.activeElement.className.includes('xterm-helper-textarea'); })()")
# What the frame shows: 'DOWN' (our 502 page), ttyd's overlay text, '' (a
# live terminal) or 'none' (not loaded yet).
OVERLAY = ("(() => { const d = document.getElementById('frame').contentDocument;"
           " if (!d) return 'none'; if (d.getElementById('sj-term-down')) return 'DOWN';"
           " const x = d.querySelector('.xterm'); if (!x) return 'none';"
           " for (const c of x.children) if (!c.className) return c.textContent; return ''; })()")
ARG = "new URLSearchParams(document.getElementById('frame').contentWindow.location.search).get('arg')"


def tmux(*args):
    return subprocess.run(T + list(args), capture_output=True, text=True)


def pane(name):
    return tmux("capture-pane", "-p", "-J", "-t", f"={name}:", "-S", "-200").stdout


def sessions():
    return set(tmux("ls", "-F", "#S").stdout.split())


def new_session(name, windows=1):
    tmux("new-session", "-d", "-s", name, "-x", "120", "-y", "30")
    for _ in range(windows - 1):
        tmux("new-window", "-d", "-t", f"={name}")


def ran(name, marker):
    """The marker came back as output, not just as the typed command."""
    return marker in pane(name).replace("echo " + marker, "")


def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + str(extra)) if extra and not cond else ""))
    return bool(cond)


def wait_for(fn, timeout=10.0, step=0.25):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


def phone(p, name="iPhone 14"):
    d = dict(p.devices[name])
    d.pop("default_browser_type", None)
    return d


def open_term(page, base, name):
    page.goto(f"{base}/s/{name}")
    page.wait_for_selector("#tabs .tab.on")
    page.frame_locator("#frame").locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000)
    time.sleep(1.2)


def type_line(page, text):
    page.keyboard.type(text)
    page.keyboard.press("Enter")


def errors_of(page):
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    return errs


# ---------------------------------------------------------- restart helper --
def rs_state():
    try:
        with open(os.path.join(RS_CTL, "state")) as f:
            return f.read().split()
    except OSError:
        return []


def rs_restart(what, secs):
    """Ask restartable.sh to stop <what> for <secs>; returns once it is down."""
    n = int((rs_state() or ["up", "0"])[1]) + 1
    tmp = os.path.join(RS_CTL, "req.tmp")
    with open(tmp, "w") as f:
        f.write(f"{what} {secs}\n")
    os.rename(tmp, os.path.join(RS_CTL, "req"))
    wait_for(lambda: rs_state() in (["down", str(n)], ["up", str(n)]), 20, 0.05)
    return n


def rs_up(n):
    return wait_for(lambda: rs_state() == ["up", str(n)], 30, 0.1)


def reconnect_rounds(page, sess, label, rounds):
    for i, (what, secs) in enumerate(rounds):
        n = rs_restart(what, secs)
        up = rs_up(n)
        t0 = time.time()
        # No user action at all until the frame is a live terminal again.
        live = wait_for(lambda: page.evaluate(OVERLAY) == "" and page.evaluate(FOCUSED), 15, 0.2)
        marker = f"RS{TAG}{label}{i}"
        if live:
            type_line(page, "echo " + marker)
        got = wait_for(lambda: ran(sess, marker), 5)
        ok(f"{label}: restart {what} ({secs}s down) -> reconnects by itself and typing reaches tmux",
           up and live and got, f"up={up} live={live} overlay={page.evaluate(OVERLAY)!r} "
                                f"after {time.time() - t0:.1f}s")


MADE = [f"pwc-a{TAG}", f"pwc-b{TAG}", f"pwc-c{TAG}", f"pwc-rs{TAG}",
        f"pwc-a-really-long-session-name-for-the-strip-{TAG}"]
FILLERS = [f"pwc-f{i:02d}-{TAG}" for i in range(18)]
A, B, C, RS, LONG = MADE
new_session(A)
new_session(B, windows=3)
new_session(C)
new_session(RS)
new_session(LONG)

try:
    with sync_playwright() as p:
        # ===================================== reconnect after a restart (F09)
        if RS_BASE and RS_CTL and rs_state():
            print("reconnect after a restart (chromium desktop):")
            b = p.chromium.launch()
            page = b.new_context(viewport={"width": 1280, "height": 800}).new_page()
            errs = errors_of(page)
            open_term(page, RS_BASE, RS)
            reconnect_rounds(page, RS, "chromium", [("both", 0.3), ("web", 0), ("ttyd", 0)])

            # ---- the 502 page in the frame comes back on its own (F51)
            n = rs_restart("ttyd", 4)
            page.click(f"#tabs .tab[data-name='{A}']")
            down = wait_for(lambda: page.evaluate(OVERLAY) == "DOWN", 8)
            ok("ttyd down at a tab switch: the frame shows the 502 page", down, page.evaluate(OVERLAY))
            if down:
                fr = page.frame_locator("#frame")
                ok("...compact inside the frame (no second header)", not fr.locator("h1").is_visible())
                ok("...with a Retry button and no 'reload this page'",
                   fr.locator("button:has-text('Retry')").count() == 1
                   and "reload this page" not in fr.locator("body").inner_text())
                ok("...and no 'connecting' sweep over it",
                   not page.evaluate("document.body.classList.contains('conn')"))
            rs_up(n)
            back = wait_for(lambda: page.evaluate(OVERLAY) == "" and page.evaluate(FOCUSED), 15, 0.2)
            ok("...and it is a live terminal again with no tap, once ttyd is back", back,
               page.evaluate(OVERLAY))
            if back:
                type_line(page, f"echo DOWN{TAG}")
                ok("...on the session in the bar", wait_for(lambda: ran(A, f"DOWN{TAG}"), 5)
                   and page.evaluate(ARG) == A, page.evaluate(ARG))
            ok("no page errors", not errs, errs)
            b.close()

            print("reconnect after a restart (webkit iphone, firefox):")
            b = p.webkit.launch()
            page = b.new_context(**phone(p)).new_page()
            open_term(page, RS_BASE, RS)
            reconnect_rounds(page, RS, "webkit", [("both", 0.3), ("ttyd", 0)])
            b.close()
            b = p.firefox.launch()
            page = b.new_context(viewport={"width": 1280, "height": 800}).new_page()
            open_term(page, RS_BASE, RS)
            reconnect_rounds(page, RS, "firefox", [("both", 0.3)])
            b.close()
        else:
            print("  (skipped: reconnect checks -- run.sh's restartable instance is not configured)")

        # ============================================ desktop chrome (chromium)
        print("chromium desktop:")
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        errs = errors_of(page)
        open_term(page, BASE, A)
        ok("current tab is aria-current", page.get_attribute("#tabs .tab.on", "aria-current") == "true")
        ok("the frame has a title naming the session", page.get_attribute("#frame", "title") == f"Terminal: {A}",
           page.get_attribute("#frame", "title"))
        ok("#err is announced (role=alert)", page.get_attribute("#err", "role") == "alert")
        ok("x is there on a desktop", page.locator("#close").is_visible())

        # ---- G03 / G04: the grid fills the frame, no scrollbar strip
        cols = page.evaluate("document.getElementById('frame').contentWindow.term.cols")
        refit = page.evaluate("(() => { const t = document.getElementById('frame').contentWindow.term;"
                              " t.fit(); return t.cols; })()")
        ok("terminal already fits the frame after load (a refit changes nothing)", cols == refit, f"{cols} -> {refit}")

        # ---- F13: Back after switching tabs
        page.goto(f"{BASE}/")
        open_term(page, BASE, A)
        page.click(f"#tabs .tab[data-name='{B}']")
        wait_for(lambda: page.evaluate(ARG) == B)
        page.click(f"#tabs .tab[data-name='{C}']")
        wait_for(lambda: page.evaluate(ARG) == C)
        try:
            page.evaluate("history.back()")
        except PlaywrightError:
            pass                                  # navigated away mid-evaluate: that is the success case
        time.sleep(1.5)
        if "/s/" in page.evaluate("location.pathname"):
            on = page.get_attribute("#tabs .tab.on", "data-name")
            ok("Back: the frame, the bar and the URL agree", page.evaluate(ARG) == on
               and page.evaluate("location.pathname").endswith("/" + on), f"{page.evaluate(ARG)} / {on}")
        else:
            ok("Back leaves the terminal page (no frame-only history entries)", True)
        open_term(page, BASE, A)

        # ---- F38: the + panel
        page.click("#add")
        ok("+ open: aria-expanded and the on state",
           page.get_attribute("#add", "aria-expanded") == "true" and "on" in page.get_attribute("#add", "class"))
        ok("no CRT toggle in the new-session panel", page.locator("#pop #fxt, #pop .fxt").count() == 0)
        page.keyboard.press("Escape")
        ok("Escape closes it and puts the keyboard back in the terminal",
           not page.locator("#pop.open").count() and wait_for(lambda: page.evaluate(FOCUSED), 3)
           and page.get_attribute("#add", "aria-expanded") == "false")
        type_line(page, f"echo ESC{TAG}")
        ok("...typing reaches tmux", wait_for(lambda: ran(A, f"ESC{TAG}"), 5))
        before = sessions()
        page.click("#add")
        page.click("#add")
        ok("+ again closes it, keyboard back in the terminal", wait_for(lambda: page.evaluate(FOCUSED), 3))
        type_line(page, f"echo PLUS{TAG} x")
        ok("...typing reaches tmux and starts no stray session",
           wait_for(lambda: ran(A, f"PLUS{TAG} x"), 5) and sessions() == before, sessions() - before)
        page.click("#add")
        box = page.locator("#frame").bounding_box()
        page.mouse.click(box["x"] + 200, box["y"] + 300)
        ok("a click in the terminal closes it", wait_for(lambda: not page.locator("#pop.open").count(), 3))
        page.click("#add")
        page.click("#pop-cancel")
        ok("Cancel closes it, keyboard back in the terminal",
           not page.locator("#pop.open").count() and wait_for(lambda: page.evaluate(FOCUSED), 3))

        # ---- F39: a name is optional for every type, and stays so
        before = sessions()
        page.click("#add")
        page.click("#pop .kinds label:has(input[value=fake])")
        page.click("#pop .btn[type=submit]")
        made = wait_for(lambda: sessions() - before, 8)
        MADE.extend(made)
        ok("an agent starts with the name left blank (auto-named)", len(made) == 1, made)
        wait_for(lambda: page.evaluate(ARG) in made, 5)
        page.click("#add")
        ok("...and after that the name is still optional",
           not page.evaluate("document.querySelector('#pop [name=name]').required")
           and page.evaluate("document.querySelector('#pop input[name=kind]:checked').value") == "shell")
        before = sessions()
        page.click("#pop .btn[type=submit]")
        made = wait_for(lambda: sessions() - before, 8)
        MADE.extend(made)
        ok("...a blank-named Shell starts too", len(made) == 1, made)
        ok("the button says Start", page.locator("#pop .btn[type=submit]").inner_text().strip() == "Start")

        # ---- F86: a double submit starts one session
        open_term(page, BASE, A)
        # A slow link: hold every /api/new for a second, inside the page.
        page.evaluate("(() => { const f = window.fetch; window.fetch = function (u, o) {"
                      " if (String(u).indexOf('/api/new') < 0) return f(u, o);"
                      " return new Promise(function (r) { setTimeout(r, 1000); }).then(function () {"
                      " return f(u, o); }); }; })()")
        before = sessions()
        page.click("#add")
        page.click("#pop .btn[type=submit]")
        ok("the Start button is disabled while it starts",
           page.locator("#pop .btn[type=submit]").is_disabled()
           and "Starting" in page.locator("#pop .btn[type=submit]").inner_text())
        page.locator("#pop .btn[type=submit]").click(force=True)     # the impatient second tap
        made = wait_for(lambda: sessions() - before, 6)
        time.sleep(1.5)
        made = sessions() - before
        MADE.extend(made)
        ok("a double submit starts exactly one session", len(made) == 1, made)

        # ---- G21 / F95: the window list is fresh, and one numbering scheme
        open_term(page, BASE, B)
        wait_for(lambda: page.locator("#tabs .tab.on .wb").count() == 1, 5)
        ok("badge is the window count with a caret",
           page.locator("#tabs .tab.on .wb").inner_text().strip() == "\u00b7 3"
           and page.locator("#tabs .tab.on .wb svg").count() == 1,
           page.locator("#tabs .tab.on .wb").inner_text())
        tmux("select-window", "-t", f"={B}:2")
        page.click("#tabs .tab.on")
        ok("a window picked elsewhere is current in the list as soon as it opens",
           wait_for(lambda: page.locator("#winmenu button.on .wi").inner_text().strip() == "\u25b82", 2),
           page.locator("#winmenu button.on .wi").inner_text())
        page.keyboard.press("ArrowDown")
        page.evaluate("document.activeElement.__sj = 1")
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        time.sleep(1)
        ok("a refresh that changes nothing keeps the list's focused row",
           page.evaluate("document.activeElement.__sj === 1"))
        page.keyboard.press("Escape")
        ok("Escape closes the list and puts the keyboard back",
           wait_for(lambda: page.evaluate(FOCUSED), 3) and page.locator("#winmenu[hidden]").count() == 1)
        tmux("select-window", "-t", f"={B}:0")
        open_term(page, BASE, C)
        tmux("new-window", "-d", "-t", f"={C}")
        page.click("#tabs .tab.on")
        ok("a window made elsewhere: the tab opens the list without a reload",
           wait_for(lambda: page.locator("#winmenu:not([hidden])").count() == 1, 3))
        page.keyboard.press("Escape")
        tmux("kill-window", "-t", f"={C}:1")

        # ---- F12: renamed elsewhere -> followed
        open_term(page, BASE, A)
        page.evaluate("document.getElementById('frame').contentWindow.__sj = 1")
        renamed = A + "-renamed"
        tmux("rename-session", "-t", f"={A}", renamed)
        MADE.append(renamed)
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        ok("renamed elsewhere: the tab, URL and title follow",
           wait_for(lambda: page.get_attribute("#tabs .tab.on", "data-name") == renamed, 5)
           and page.evaluate("location.pathname") == f"/s/{renamed}" and page.title().startswith(renamed),
           page.evaluate("location.pathname"))
        ok("...without reloading the terminal",
           page.evaluate("document.getElementById('frame').contentWindow.__sj === 1"))
        type_line(page, f"echo REN{TAG}")
        ok("...and typing still reaches it", wait_for(lambda: ran(renamed, f"REN{TAG}"), 5))
        tmux("rename-session", "-t", f"={renamed}", A)

        # ---- F12: ended -> the list, with a note; never another session
        gone = f"pwc-gone{TAG}"
        new_session(gone)
        MADE.append(gone)
        open_term(page, BASE, gone)
        wait_for(lambda: "1" in tmux("display", "-p", "-t", f"={gone}:", "#{session_attached}").stdout, 10)
        tmux("kill-session", "-t", f"={gone}")
        try:
            page.wait_for_url("**/?ended=*", timeout=8000)
            landed = True
        except PlaywrightError:
            landed = False
        ok("killed elsewhere: the tab goes to the list at once, not to another session", landed, page.url)
        if landed:
            ok("...which says it ended", f"“{gone}” has ended" in page.locator(".flash").inner_text())
        ok("no page errors", not errs, errs)

        # ---- F12: a pop-out on a session that ends closes
        page.goto(f"{BASE}/")
        gone2 = f"pwc-gone2{TAG}"
        new_session(gone2)
        MADE.append(gone2)
        pop = ctx.new_page()
        pop.goto(f"{BASE}/")
        with pop.expect_popup() as pi:
            pop.evaluate(f"window.open('/s/{gone2}?popout=1', 'x', 'popup=yes,width=900,height=600')")
        w = pi.value
        w.wait_for_selector("#tabs .tab.on", state="attached")
        wait_for(lambda: w.evaluate(OVERLAY) == "" and "1" in tmux(
            "display", "-p", "-t", f"={gone2}:", "#{session_attached}").stdout, 15)
        tmux("kill-session", "-t", f"={gone2}")
        try:                                       # (a wait that lets Playwright see the close)
            w.wait_for_event("close", timeout=8000)
        except PlaywrightError:
            pass
        ok("a pop-out whose session ended closes", w.is_closed(), "" if w.is_closed() else w.url)
        b.close()

        # ======================================= strip: many sessions (desktop)
        for s in FILLERS:
            new_session(s)
        for engine in ("chromium", "firefox"):
            print(f"{engine} desktop, many sessions:")
            b = getattr(p, engine).launch()
            page = b.new_context(viewport={"width": 1280, "height": 800}).new_page()
            errs = errors_of(page)
            open_term(page, BASE, A)
            strip = "document.getElementById('tabs')"
            page.evaluate(f"{strip}.scrollLeft = 0")
            time.sleep(0.2)
            ok("an overflowing strip fades the edge with more tabs past it",
               page.evaluate(f"{strip}.classList.contains('fr') && !{strip}.classList.contains('fl')"),
               page.get_attribute("#tabs", "class"))
            box = page.locator("#tabs").bounding_box()
            page.mouse.move(box["x"] + 300, box["y"] + 20)
            for _ in range(3):
                page.mouse.wheel(0, 120)
            ok("a plain mouse wheel scrolls the strip sideways",
               wait_for(lambda: page.evaluate(f"{strip}.scrollLeft") > 0, 2))
            ok("...and Ctrl+wheel is left to the browser (zoom)", not page.evaluate(
                f"(() => {{ const e = new WheelEvent('wheel', {{deltaY: 100, ctrlKey: true, bubbles: true,"
                f" cancelable: true}}); {strip}.dispatchEvent(e); return e.defaultPrevented; }})()"))
            page.evaluate(f"(() => {{ const t = {strip}; t.children[2].__sj = 1; t.scrollLeft = 150; }})()")
            page.focus("#tabs .tab:nth-child(3)")
            focused = page.evaluate("document.activeElement.getAttribute('data-name')")
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            time.sleep(1)
            ok("a poll that changes nothing keeps the tabs, the scroll and the focus",
               page.evaluate(f"{strip}.children[2].__sj === 1 && {strip}.scrollLeft === 150"
                             f" && document.activeElement === {strip}.children[2]"))
            extra = f"pwc-zz{TAG}"
            new_session(extra)
            MADE.append(extra)
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            ok("a poll that adds a tab keeps the scroll and the focused tab",
               wait_for(lambda: page.evaluate(f"!!{strip}.querySelector('[data-name=\"{extra}\"]')"), 3)
               and page.evaluate(f"{strip}.scrollLeft") == 150
               and page.evaluate("document.activeElement.getAttribute('data-name')") == focused)
            ok("no page errors", not errs, errs)
            b.close()

        # ================================================ phones (webkit)
        print("webkit iphone 14:")
        b = p.webkit.launch()
        ctx = b.new_context(**phone(p))
        page = ctx.new_page()
        errs = errors_of(page)
        open_term(page, BASE, B)
        wait_for(lambda: page.locator("#tabs .tab.on .wb").count() == 1, 5)
        time.sleep(0.5)
        g = page.evaluate("(() => { const s = document.getElementById('tabs').getBoundingClientRect(),"
                          " t = document.querySelector('#tabs .tab.on').getBoundingClientRect();"
                          " return [s.left, s.right, t.left, t.right]; })()")
        ok("the active tab, badge and all, is fully in view", g[2] >= g[0] - 0.5 and g[3] <= g[1] + 0.5, g)
        ok("x is hidden on touch (the logo is the way back)", not page.locator("#close").is_visible())
        page.tap("#add")
        ok("the + sheet is opaque over the key row", page.evaluate(
            "getComputedStyle(document.getElementById('pop')).backgroundColor") ==
            page.evaluate("getComputedStyle(document.getElementById('bar')).backgroundColor"))
        page.tap("#pop-cancel")
        ok("Cancel closes the sheet", not page.locator("#pop.open").count())
        open_term(page, BASE, LONG)
        t = page.locator("#tabs .tab.on")
        ok("a long name is cut with an ellipsis, the full name in the tooltip",
           t.bounding_box()["width"] <= 0.4 * 390 + 1
           and page.evaluate("getComputedStyle(document.querySelector('#tabs .tab.on .tn')).textOverflow")
           == "ellipsis" and LONG in t.get_attribute("title"), t.bounding_box())
        ok("no page errors", not errs, errs)
        b.close()

        print("webkit iphone 14 landscape:")
        b = p.webkit.launch()
        page = b.new_context(**phone(p, "iPhone 14 landscape")).new_page()
        open_term(page, BASE, A)
        h = page.evaluate("document.getElementById('bar').getBoundingClientRect().height")
        ok("short landscape: a denser bar", h < 44, h)
        b.close()

        # ================================== F85: touch loads, no init error
        print("chromium touch reloads:")
        b = p.chromium.launch()
        for dev in ("iPhone SE", "Pixel 7"):
            page = b.new_context(**phone(p, dev)).new_page()
            errs = errors_of(page)
            for _ in range(6):
                page.goto(f"{BASE}/s/{A}")
                page.wait_for_selector("#tabs .tab.on")
                time.sleep(0.4)
            page.frame_locator("#frame").locator("#sj-touch").wait_for(state="attached", timeout=10000)
            ok(f"{dev}: six loads, no page error, touch CSS in the frame", not errs, errs)
        b.close()

        # ============ G04: classic (space-taking) scrollbars, as on Windows
        print("chromium with classic scrollbars:")
        b = p.chromium.launch(ignore_default_args=["--hide-scrollbars"])
        page = b.new_context(viewport={"width": 1280, "height": 800}).new_page()
        open_term(page, BASE, A)
        sb = page.evaluate("(() => { const v = document.getElementById('frame').contentDocument"
                           ".querySelector('.xterm-viewport'); return v.offsetWidth - v.clientWidth; })()")
        ok("no scrollbar strip down the terminal", sb == 0, f"{sb}px")
        b.close()
finally:
    for s in MADE + FILLERS:
        tmux("kill-session", "-t", f"={s}")

print("  " + ("all chrome checks passed" if not fails else f"{fails} chrome check(s) FAILED"))
if fails:
    raise SystemExit(1)
