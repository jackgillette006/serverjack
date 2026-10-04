"""Terminal page chrome: the tab strip, the + panel, and the frame's connection.

Chromium, Firefox and WebKit (iPhone emulation -- emulated WebKit is NOT iOS
Safari). What is proven here:

- the terminal reconnects BY ITSELF after serverjack, ttyd or both restart
  (run.sh's fourth instance, driven through tests/restartable.sh), and after
  the frame loaded our own 502 page while ttyd was down;
- a terminal whose WebSocket is slow to open (held back in ttyd's page) is
  not offered before it is open -- no keyboard in it, 'reconnecting' kept
  over it after a restart -- and a line typed the moment it looks ready
  reaches tmux (it used to be focused, and typed into, while the keys still
  went nowhere);
- a session renamed elsewhere is followed (tab, URL, title, and the frame
  re-pointed at the new name), one that ended sends the tab to the list and
  closes a pop-out -- never quietly attaching some other session; a tab for
  a session that ended since the strip was drawn keeps the page where it
  was, and a list asked for before a switch doesn't undo the switch;
- serverjack down when a tab is tapped (the browser's own error page in the
  frame) and ttyd down mid-session both recover by themselves, saying
  "reconnecting" meanwhile;
- Back after switching tabs never leaves the frame on a different session
  from the bar;
- the + panel: Escape / + / Cancel / a click in the terminal close it and put
  the keyboard back, aria-expanded, a name is optional for every type, a
  double submit starts one session, no CRT toggle in it;
- the strip: edge fades, the mouse wheel, polls that change nothing touch
  nothing, the active tab and its window badge in view, long names cut with
  an ellipsis, the window list built from fresh data;
- a refit after load (no dead band), no scrollbar strip, no touchCss error;
- the pop-out window (all three engines): the handle has its own band and
  covers no terminal cell, the bar lies over the terminal (a toggle never
  resizes the session) and leaves the keyboard in it, Escape (which then
  goes no further) / a click in the terminal / a pick put it away, x is
  reachable, the current tab is in view
  on every reveal (the first one included), the window is named after the
  session it shows, and Open on it focuses it without a reload;
- a popped-out session is not attached a second time from this browser by
  Back after Pop out or its tab in another tab's strip (a note says where it
  is, and goes once the tab is switched there after all), and a blocked
  pop-up says so and opens an ordinary tab;
- a touchscreen laptop (touch events, mouse pointer) keeps the desktop UI,
  and a finger swipe on its terminal still scrolls tmux's history; an iPad
  that reports a fine pointer (a trackpad attached) stays a tablet;
- a notched iPhone (safe-area insets patched in, as WebKit here reports 0):
  bar, terminal, key row, + sheet and Copy view stay inside the side insets in
  landscape, the terminal clears the home indicator with the key row off, and
  nothing pays that inset while the soft keyboard is up (a faked
  visualViewport drives fit()).

Sessions it makes are all called pwc-*, and are killed at the end.
"""
import os
import subprocess
import time
from urllib.parse import urlparse

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
# The same, null while the frame holds another origin's document (the
# browser's own error page), where reading its location throws.
ARG_OR_NULL = "(() => { try { return " + ARG + "; } catch (e) { return null; } })()"
RETRY = ("(() => { const d = document.getElementById('frame').contentDocument, x = d && d.querySelector('.xterm');"
         " let v = 'none'; if (x) for (const c of x.children) if (!c.className) v = getComputedStyle(c).visibility;"
         " return {retry: document.body.classList.contains('retry'),"
         " cap: document.querySelector('#conn .cap').textContent,"
         " shown: getComputedStyle(document.getElementById('conn')).display !== 'none', overlay: v}; })()")


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


def rect(page, sel):
    return page.evaluate(f"(() => {{ const e = document.querySelector({sel!r}); if (!e) return null;"
                         f" const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }})()")


def px(page, sel, prop):
    return page.evaluate(f"parseFloat(getComputedStyle(document.querySelector({sel!r})).{prop})")


def safe_patch(insets):
    """Route handler: env(safe-area-inset-*) -> fixed values, as a real iPhone
    reports them (emulated WebKit reports 0 for all four)."""
    def patch(route):
        r = route.fetch()
        body = r.text()
        for k, v in insets.items():
            body = body.replace(f"env(safe-area-inset-{k})", v)
        route.fulfill(response=r, body=body)
    return patch


# Both boxes must have a size: a hidden bar gives two empty rects, which would
# otherwise "contain" each other.
IN_TABS = ("(() => { const s = document.getElementById('tabs').getBoundingClientRect(),"
           " t = document.querySelector('#tabs .tab.on').getBoundingClientRect();"
           " return s.width > 0 && t.width > 0 && t.left >= s.left - 0.5 && t.right <= s.right + 0.5; })()")
STRIP = ("(() => { const s = document.getElementById('tabs'), r = s.getBoundingClientRect(),"
         " t = s.querySelector('.tab.on').getBoundingClientRect();"
         " return {scrollLeft: s.scrollLeft, strip: [r.left, r.right], tab: [t.left, t.right]}; })()")
# A visualViewport the test drives, so the page's fit() runs as on an iPhone:
# __set(h) is the soft keyboard taking the bottom (innerHeight - h) pixels.
FAKE_VV = """(() => { if (window.top !== window) return;
  const t = new EventTarget(); let h = null;
  Object.defineProperty(t, 'height', { get: () => h === null ? innerHeight : h });
  Object.defineProperty(t, 'width', { get: () => innerWidth });
  t.offsetTop = 0; t.offsetLeft = 0; t.scale = 1;
  t.__set = v => { h = v; t.dispatchEvent(new Event('resize')); };
  Object.defineProperty(window, 'visualViewport', { value: t, configurable: true }); })()"""
# One finger dragged down the terminal (dy px per move, 12 moves): older lines.
SWIPE = """(dy) => { const f = document.getElementById('frame'), w = f.contentWindow, d = f.contentDocument;
  const el = d.querySelector('.xterm-screen'), r = el.getBoundingClientRect();
  const x = r.left + r.width / 2; let y = r.top + 100;
  const mk = (type, yy) => { const t = new w.Touch({identifier: 1, target: el, clientX: x, clientY: yy});
    const on = type === 'touchend' ? [] : [t];
    return new w.TouchEvent(type, {touches: on, targetTouches: on, changedTouches: [t],
                                   bubbles: true, cancelable: true}); };
  el.dispatchEvent(mk('touchstart', y));
  for (let i = 0; i < 12; i++) { y += dy; el.dispatchEvent(mk('touchmove', y)); }
  el.dispatchEvent(mk('touchend', y)); }"""
# An iPad's Safari as it may look with a trackpad attached: it calls itself a
# Mac, has touch points, and (here, desktop WebKit) a fine pointer that hovers.
AS_IPAD = """Object.defineProperty(Navigator.prototype, 'platform', { get: () => 'MacIntel' });
Object.defineProperty(Navigator.prototype, 'maxTouchPoints', { get: () => %d });"""


def clients(name):
    return len([c for c in tmux("list-clients", "-t", f"={name}").stdout.splitlines() if c.strip()])


def winsize(name):
    return tmux("display", "-p", "-t", f"={name}:", "#{window_width}x#{window_height}").stdout.strip()


def live(page):
    page.frame_locator("#frame").locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000)


def pop_from(page, name):
    """Open from the landing page in `page` (a desktop: a pop-out); returns it, connected."""
    page.goto(f"{BASE}/")
    with page.expect_popup() as pi:
        page.click(f"a.open[data-name='{name}']")
    w = pi.value
    w.wait_for_selector("#tabs .tab.on", state="attached")
    live(w)
    wait_for(lambda: clients(name) >= 1, 10)
    time.sleep(1.2)
    return w


def note_says(page, text):
    return page.locator("#note").is_visible() and text in page.locator("#note").inner_text()


HIT = ("(sel) => { const r = document.querySelector(sel).getBoundingClientRect();"
       " const e = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);"
       " return !!e && !!e.closest(sel); }")
# What is on top at the centre of the terminal's top-right cell (xterm's geometry).
CORNER = ("(() => { const f = document.getElementById('frame'), r = f.getBoundingClientRect(),"
          " s = f.contentDocument.querySelector('.xterm-screen').getBoundingClientRect(),"
          " t = f.contentWindow.term, cw = s.width / t.cols, ch = s.height / t.rows;"
          " const e = document.elementFromPoint(r.left + s.left + s.width - cw / 2, r.top + s.top + ch / 2);"
          " return e && (e.id || e.tagName); })()")


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


def error_page_round(page, label, target):
    """serverjack down while a tab is tapped: the frame gets the browser's own
    error page (another origin's document), which no check could read, so
    the frame used to stay on it for good."""
    n = rs_restart("web", 3)
    page.click(f"#tabs .tab[data-name='{target}']")
    said = wait_for(lambda: page.evaluate(RETRY)["retry"], 6, 0.1)
    up = rs_up(n)
    t0 = time.time()
    back = wait_for(lambda: page.evaluate(ARG_OR_NULL) == target and page.evaluate(OVERLAY) == ""
                    and page.evaluate(FOCUSED), 25, 0.2)
    marker = f"EP{TAG}{label}"
    if back:
        type_line(page, "echo " + marker)
    ok(f"{label}: a tab tapped while serverjack is down comes back to that session by itself",
       up and back and wait_for(lambda: ran(target, marker), 5),
       f"up={up} back={back} arg={page.evaluate(ARG_OR_NULL)!r} after {time.time() - t0:.1f}s")
    ok("...saying it is reconnecting in the meantime", said)
    ok("...and not once it is back", not page.evaluate(RETRY)["retry"], page.evaluate(RETRY))


def term_live(page):
    """A terminal the page offers for typing: no ttyd overlay, the keyboard in
    it, and no 'connecting' or 'reconnecting' over it."""
    return (page.evaluate(OVERLAY) == "" and page.evaluate(FOCUSED)
            and not page.evaluate("['conn', 'retry'].some(c => document.body.classList.contains(c))"))


# ttyd's page with its WebSocket slow to open: the 'open' event and every
# message reach ttyd SLOW_MS late, in order (a phone on a slow network, a
# loaded box). ttyd builds the terminal, textarea and all, before the socket
# is open and listens for keys only once it is, so anything typed into it
# before then is dropped. Only in a frame, only while the page above has
# __sjSlowOn set. __sjSlow marks such a document, __sjOpened is set once
# ttyd has had its 'open'.
SLOW_MS = 3000
SLOW_JS = """(() => {
  if (window.top === window || location.pathname !== '/term/' || window.__sjSlow ||
      !window.top.__sjSlowOn) return;
  const W = window.WebSocket, D = %d;
  window.__sjSlow = 1;
  window.WebSocket = function (u, p) {
    const s = new W(u, p), at = Date.now() + D, q = [], add = s.addEventListener.bind(s);
    let t = null;
    const run = () => { t = null; while (q.length) { const [f, e] = q.shift(); f(e); } };
    s.addEventListener = (k, f, o) => add(k, k !== 'open' && k !== 'message' ? f : e => {
      if (k === 'open') q.push([() => { window.__sjOpened = 1; }, e]);
      if (!q.length && Date.now() >= at) return f(e);
      q.push([f, e]);
      if (!t) t = setTimeout(run, Math.max(0, at - Date.now()));
    }, o);
    return s;
  };
  window.WebSocket.prototype = W.prototype;
  Object.assign(window.WebSocket, {CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3});
})()""" % SLOW_MS
# One snapshot (a single evaluate, so nothing happens in between): is the
# frame such a document, has ttyd had its 'open', and what the page shows.
SLOW_STATE = ("(() => { let w = null; try { w = document.getElementById('frame').contentWindow; void w.document; }"
              " catch (e) { return null; } const c = document.body.classList, focused = " + FOCUSED + ";"
              " return {fresh: !!w.__sjSlow && !w.__sjOld, opened: !!w.__sjOpened, retry: c.contains('retry'),"
              " focused: focused, live: focused && " + OVERLAY + " === '' && !c.contains('conn') && !c.contains('retry')}; })()")


def is_term_page(url):
    return urlparse(url).path == "/term/"


def slow_ttyd(route):
    r = route.fetch()
    h = {k: v for k, v in r.headers.items() if k.lower() not in ("content-encoding", "content-length")}
    route.fulfill(status=r.status, headers=h,
                  body=r.text().replace("<head>", "<head><script>" + SLOW_JS + "</script>", 1))


def slow_round(page, sess, label, restart=True):
    """The frame reloads (the page's own reconnect after a restart of both,
    or a tab switch) into a ttyd page whose WebSocket takes SLOW_MS to open.
    Until it is open the page must not offer the terminal: it used to focus it
    (and drop 'reconnecting') as soon as the textarea was there, and the
    first thing typed was lost -- a CI runner hit this on its own."""
    # Into ttyd's page through a route; Chromium refuses a WebSocket to
    # 127.0.0.1 from a document a route made up (Local Network Access), so
    # there it is an init script. Firefox doesn't run init scripts in every
    # frame it loads.
    by_route = page.context.browser.browser_type.name != "chromium"
    if by_route:
        page.route(is_term_page, slow_ttyd)
    else:
        page.add_init_script(SLOW_JS)
    page.evaluate("window.__sjSlowOn = 1")
    try:
        page.evaluate("document.getElementById('frame').contentWindow.__sjOld = 1")
        if restart:
            n = rs_restart("both", 0.3)
        else:
            page.click(f"#tabs .tab[data-name='{sess}']")
        fresh = wait_for(lambda: (page.evaluate(SLOW_STATE) or {}).get("fresh"), 30, 0.02)
        opening, typed, marker = [], False, f"SL{TAG}{label}{int(restart)}"
        while fresh:
            st = page.evaluate(SLOW_STATE)
            if not st or st["opened"]:
                break
            opening.append((st["focused"], st["retry"]))
            if st["live"]:                          # looks ready, its socket still not open: type now
                type_line(page, "echo " + marker)
                typed = True
                break
            time.sleep(0.05)
        up = rs_up(n) if restart else True
        what = "after a restart" if restart else "at a tab switch"
        ok(f"{label}: ttyd's socket slow to open {what}: no keyboard in the terminal until it is",
           up and fresh and len(opening) > 5 and not any(f for f, _ in opening),
           f"up={up} fresh={fresh} samples={len(opening)} focused={sum(f for f, _ in opening)}")
        if restart:
            ok("...and 'reconnecting' over it all along", opening and all(r for _, r in opening),
               f"{sum(r for _, r in opening)}/{len(opening)}")
        live = typed or wait_for(lambda: term_live(page), 15, 0.02)
        if live and not typed:
            type_line(page, "echo " + marker)       # at once, the moment it looks ready
        ok("...and typing the moment it looks ready reaches tmux", live and wait_for(lambda: ran(sess, marker), 5),
           f"live={live} typed while opening={typed} overlay={page.evaluate(OVERLAY)!r}")
    finally:
        page.evaluate("window.__sjSlowOn = 0")
        if by_route:
            page.unroute(is_term_page, slow_ttyd)


def reconnect_rounds(page, sess, label, rounds):
    for i, (what, secs) in enumerate(rounds):
        n = rs_restart(what, secs)
        up = rs_up(n)
        t0 = time.time()
        # No user action at all until the frame is a live terminal again.
        live = wait_for(lambda: term_live(page), 15, 0.2)
        marker = f"RS{TAG}{label}{i}"
        if live:
            type_line(page, "echo " + marker)
        got = wait_for(lambda: ran(sess, marker), 5)
        ok(f"{label}: restart {what} ({secs}s down) -> reconnects by itself and typing reaches tmux",
           up and live and got, f"up={up} live={live} overlay={page.evaluate(OVERLAY)!r} "
                                f"after {time.time() - t0:.1f}s")


MADE = [f"pwc-a{TAG}", f"pwc-b{TAG}", f"pwc-c{TAG}", f"pwc-rs{TAG}",
        f"pwc-a-really-long-session-name-for-the-strip-{TAG}", f"pwc-p{TAG}", f"pwc-q{TAG}", f"pwc-zzpop{TAG}"]
FILLERS = [f"pwc-f{i:02d}-{TAG}" for i in range(18)]
A, B, C, RS, LONG, P, Q, LATE = MADE
new_session(A)
new_session(B, windows=3)
new_session(C)
new_session(RS)
new_session(LONG)
new_session(P)
new_session(Q)
new_session(LATE)

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
            slow_round(page, RS, "chromium")

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
            # ---- ttyd down mid-session (F09): the page says it is reconnecting
            # by itself, and ttyd's "Press ⏎ to Reconnect" (a key a phone's key
            # row doesn't have) is not shown
            n = rs_restart("ttyd", 8)
            said = wait_for(lambda: page.evaluate(RETRY)["retry"] and page.evaluate(RETRY)["overlay"] == "hidden", 6)
            st = page.evaluate(RETRY)
            ok("ttyd down mid-session: 'reconnecting' over the terminal, not ttyd's 'Press ⏎ to Reconnect'",
               said and st["shown"] and st["cap"].startswith("reconnecting"), str(st))
            rs_up(n)
            ok("...gone again once it is back",
               wait_for(lambda: page.evaluate(OVERLAY) == "" and not page.evaluate(RETRY)["retry"], 15),
               str(page.evaluate(RETRY)))
            error_page_round(page, "chromium", C)
            ok("no page errors", not errs, errs)
            b.close()

            print("reconnect after a restart (webkit iphone, firefox):")
            b = p.webkit.launch()
            page = b.new_context(**phone(p)).new_page()
            open_term(page, RS_BASE, RS)
            reconnect_rounds(page, RS, "webkit", [("both", 0.3), ("ttyd", 0)])
            slow_round(page, RS, "webkit")
            b.close()
            b = p.firefox.launch()
            page = b.new_context(viewport={"width": 1280, "height": 800}).new_page()
            open_term(page, RS_BASE, RS)
            reconnect_rounds(page, RS, "firefox", [("both", 0.3)])
            slow_round(page, RS, "firefox")
            slow_round(page, C, "firefox", restart=False)
            error_page_round(page, "firefox", A)
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
        # tmux has the session a moment before the page has the answer, and
        # the button says Starting… until then
        ok("the button says Start",
           wait_for(lambda: page.locator("#pop .btn[type=submit]").inner_text().strip() == "Start", 5),
           page.locator("#pop .btn[type=submit]").inner_text())

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
        # ttyd's own reconnect (a dropped socket, a phone waking) asks for the
        # name the frame was loaded with, so the frame follows too: it used
        # to show "No tmux session called <old name>" for 20 s after a drop.
        ok("...and so does the terminal, so a reconnect finds it under its new name",
           wait_for(lambda: page.evaluate(ARG_OR_NULL) == renamed and page.evaluate(FOCUSED), 10),
           page.evaluate(ARG_OR_NULL))
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

        # ---- a tab for a session that ended since the strip was drawn (it
        # can be 15 s old): the page stays where it was and says so -- it used
        # to leave for the list (a pop-out closed) over a session never opened
        stale = f"pwc-stale{TAG}"
        new_session(stale)
        MADE.append(stale)
        open_term(page, BASE, A)
        wait_for(lambda: page.locator(f"#tabs .tab[data-name='{stale}']").count() == 1, 5)
        tmux("kill-session", "-t", f"={stale}")
        page.click(f"#tabs .tab[data-name='{stale}']")
        time.sleep(1.5)
        ok("a tab whose session ended meanwhile: the page stays on its session, and says so",
           page.evaluate("location.pathname") == f"/s/{A}" and note_says(page, f"“{stale}” has ended")
           and wait_for(lambda: page.evaluate(ARG_OR_NULL) == A and page.evaluate(FOCUSED), 10),
           f"{page.url} arg={page.evaluate(ARG_OR_NULL)!r}")
        ok("...and the tab is gone", page.locator(f"#tabs .tab[data-name='{stale}']").count() == 0)
        type_line(page, f"echo STALE{TAG}")
        ok("...and typing still reaches it", wait_for(lambda: ran(A, f"STALE{TAG}"), 5))

        # ---- a list asked for before a switch, answered after it: it can't
        # have the new session in it, and must not send the page to the list
        fresh = f"pwc-fresh{TAG}"
        MADE.append(fresh)
        page.evaluate("""() => { const f = window.fetch; window.fetch = function (u) {
            const r = f.apply(this, arguments);
            return window.__slow && String(u).indexOf('/api/sessions') >= 0
              ? r.then(x => new Promise(ok => setTimeout(() => ok(x), 1500))) : r; }; }""")
        page.evaluate("window.__slow = 1; window.dispatchEvent(new Event('online')); window.__slow = 0")
        page.click("#add")
        page.fill("#pop_name", fresh)
        page.click("#pop button[type=submit]")
        time.sleep(3)
        ok("a late answer from before a switch doesn't send the page away from the new session",
           page.evaluate("location.pathname") == f"/s/{fresh}" and fresh in sessions(), page.url)
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

        # ---- ...but one whose STRIP had a session that ended stays open
        stale2 = f"pwc-stale2{TAG}"
        new_session(stale2)
        MADE.append(stale2)
        w = pop_from(pop, A)
        w.click("#handle")
        wait_for(lambda: w.locator(f"#tabs .tab[data-name='{stale2}']").count() == 1, 5)
        tmux("kill-session", "-t", f"={stale2}")
        w.click(f"#tabs .tab[data-name='{stale2}']")
        time.sleep(1.5)
        ok("a pop-out: a tab whose session ended meanwhile leaves the window open, on its session",
           not w.is_closed() and w.evaluate("location.pathname") == f"/s/{A}", "closed" if w.is_closed() else w.url)
        if not w.is_closed():
            w.close()
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

        # ======== the pop-out window: handle, bar, focus, size (G13 G15 G16 G18)
        # ...and its name (G14) and re-opening it (G17). FILLERS still exist,
        # so at 640px the strip overflows.
        for engine in ("chromium", "firefox", "webkit"):
            print(f"{engine} pop-out window:")
            b = getattr(p, engine).launch()
            ctx = b.new_context(viewport={"width": 1000, "height": 650})
            page = ctx.new_page()
            w = pop_from(page, P)
            errs = errors_of(w)
            hb, fr = rect(w, "#handle"), rect(w, "#frame")
            ok("the handle has a band of its own above the terminal", hb[3] <= fr[1] + 0.5, (hb, fr))
            ok("...so the terminal's top-right cell is the terminal's, not the handle's",
               w.evaluate(CORNER) == "frame", w.evaluate(CORNER))
            size = winsize(P)
            w.click("#handle")
            ok("the handle shows the bar, and is labelled for what it does now",
               w.locator("#bar").is_visible() and w.get_attribute("#handle", "aria-expanded") == "true"
               and w.get_attribute("#handle", "aria-label") == "Hide bar")
            ok("x is visible and hit-tests to itself (the handle no longer covers it)",
               w.locator("#close").is_visible() and w.evaluate(HIT, "#close"), rect(w, "#close"))
            time.sleep(0.8)
            ok("showing the bar does not resize the session", winsize(P) == size, f"{size} -> {winsize(P)}")
            ok("showing the bar leaves the keyboard in the terminal", wait_for(lambda: w.evaluate(FOCUSED), 3))
            type_line(w, f"echo SHOWN{TAG}{engine}")
            ok("...typing with the bar shown reaches tmux, whole",
               wait_for(lambda: ran(P, f"SHOWN{TAG}{engine}"), 5) and w.locator("#bar").is_visible())
            ok("...still the same size with the bar up", winsize(P) == size, f"{size} -> {winsize(P)}")
            w.keyboard.type("cat -v")
            w.keyboard.press("Enter")
            time.sleep(0.4)
            esc0 = pane(P).count("^[")
            w.keyboard.press("Escape")
            ok("Escape in the terminal puts the bar away",
               wait_for(lambda: not w.locator("#bar").is_visible(), 3)
               and w.get_attribute("#handle", "aria-label") == "Show bar")
            time.sleep(0.5)
            # The bar is an overlay: the Escape that dismisses it is not also
            # sent on (it interrupted an agent's turn, and made bash read the
            # next key as a Meta chord). The next one goes to the program.
            ok("...and only that: the program doesn't get that Escape", pane(P).count("^[") == esc0,
               pane(P)[-200:])
            w.keyboard.press("Escape")
            ok("...the next Escape reaches the program", wait_for(lambda: pane(P).count("^[") > esc0, 3),
               pane(P)[-200:])
            w.keyboard.press("Control+c")
            w.click("#handle")
            box = w.locator("#frame").bounding_box()
            w.mouse.click(box["x"] + 300, box["y"] + 300)
            ok("a click in the terminal puts the bar away", wait_for(lambda: not w.locator("#bar").is_visible(), 3))
            w.click("#handle")
            w.click("#handle")
            ok("the handle hides it again, keyboard back in the terminal",
               not w.locator("#bar").is_visible() and wait_for(lambda: w.evaluate(FOCUSED), 3))
            type_line(w, f"echo HIDDEN{TAG}{engine}")
            ok("...and typing reaches tmux", wait_for(lambda: ran(P, f"HIDDEN{TAG}{engine}"), 5))
            ok("...and the session was never resized", winsize(P) == size, f"{size} -> {winsize(P)}")

            # ---- G14: a tab picked inside the pop-out renames the window
            w.click("#handle")
            w.click(f"#tabs .tab[data-name='{Q}']")
            wait_for(lambda: w.evaluate(ARG) == Q, 5)
            ok("a tab picked in the pop-out: the window is named after it",
               w.evaluate("window.name") == f"serverjack-{Q}" and w.url.endswith(f"/s/{Q}?popout=1"),
               f"{w.evaluate('window.name')} {w.url}")
            ok("...and the bar went away with the pick", not w.locator("#bar").is_visible())
            wait_for(lambda: clients(Q) == 1, 8)

            # ---- G17: Open on the session a pop-out shows focuses it, no reload
            w.evaluate("window.__sj = 1")
            n, born = len(ctx.pages), w.evaluate("performance.timeOrigin")
            page.click(f"a.open[data-name='{Q}']")
            time.sleep(1.5)
            ok("Open on the session a pop-out shows: no new window, no reload, no second client",
               len(ctx.pages) == n and w.evaluate("window.__sj === 1")
               and w.evaluate("performance.timeOrigin") == born and clients(Q) == 1,
               f"pages {len(ctx.pages)}/{n} clients {clients(Q)}")
            with page.expect_popup() as pi:
                page.click(f"a.open[data-name='{P}']")
            w2 = pi.value
            w2.wait_for_url(f"**/s/{P}?popout=1")
            ok("Open on the session it showed before gets its own window, leaving this one alone",
               w.evaluate(ARG) == Q and w.evaluate("window.__sj === 1"), w.evaluate(ARG))
            w2.close()

            # ---- G16: revealing the bar shows the current tab. As met for
            # real: the FIRST reveal of a fresh pop-out whose session sorts
            # past the end of the strip (it has never been laid out).
            w3 = pop_from(page, LATE)
            w3.click("#handle")
            g = w3.evaluate(STRIP)
            ok("(its tab lies past the strip's first screenful)",
               g["tab"][1] - g["strip"][0] + g["scrollLeft"] > g["strip"][1] - g["strip"][0], g)
            ok("revealing the bar the first time brings the current tab into view",
               w3.locator("#bar").is_visible() and w3.evaluate(IN_TABS), g)
            w3.close()
            # ...and every reveal after that: strip scrolled to the start while
            # shown, hidden, shown again.
            w.set_viewport_size({"width": 640, "height": 400})
            w.click("#handle")
            w.click(f"#tabs .tab[data-name='{LATE}']")
            wait_for(lambda: w.evaluate(ARG) == LATE, 5)
            w.click("#handle")
            w.evaluate("document.getElementById('tabs').scrollLeft = 0")
            ok("(scrolled to the start, the current tab is out of view)", not w.evaluate(IN_TABS),
               w.evaluate(STRIP))
            w.click("#handle")
            w.click("#handle")
            ok("revealing it again brings the current tab back into view",
               w.locator("#bar").is_visible() and w.evaluate(IN_TABS), w.evaluate(STRIP))

            # ---- G13: x itself closes the pop-out
            try:
                w.click("#close")
            except PlaywrightError:
                pass                              # it closed during the click: the success case
            try:
                w.wait_for_event("close", timeout=3000)
            except PlaywrightError:
                pass
            ok("x in the pop-out closes it", w.is_closed())
            ok("no page errors", not errs, errs)
            b.close()

        # ================= G12: a popped-out session is not attached here again
        for engine in ("chromium", "firefox"):
            print(f"{engine}: a popped-out session is not attached a second time:")
            b = getattr(p, engine).launch()
            ctx = b.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            errs = errors_of(page)
            page.goto(f"{BASE}/")
            open_term(page, BASE, P)
            with page.expect_popup() as pi:
                page.click("#popout")
            w = pi.value
            w.wait_for_url(f"**/s/{P}?popout=1")
            live(w)
            page.wait_for_url(f"{BASE}/")
            wait_for(lambda: clients(P) == 1, 10)
            page.go_back()
            time.sleep(2)
            ok("Back after Pop out does not attach the tab again",
               "/s/" not in page.url and clients(P) == 1, f"{page.url} clients={clients(P)}")
            open_term(page, BASE, Q)
            born, n = w.evaluate("performance.timeOrigin"), len(ctx.pages)
            page.click(f"#tabs .tab[data-name='{P}']")
            time.sleep(1.5)
            ok("its tab in this tab's strip does not attach it here either",
               page.evaluate(ARG) == Q and clients(P) == 1 and len(ctx.pages) == n,
               f"arg={page.evaluate(ARG)} clients={clients(P)} pages={len(ctx.pages)}")
            ok("...says where it is", note_says(page, P), page.locator("#note").inner_text())
            ok("...and leaves the pop-out alone (no reload)", w.evaluate("performance.timeOrigin") == born)
            other = ctx.new_page()
            open_term(other, BASE, Q)
            n = len(ctx.pages)
            other.click(f"#tabs .tab[data-name='{P}']")
            time.sleep(1.5)
            ok("from a tab that did not open it: says so, and opens no window",
               other.evaluate(ARG) == Q and note_says(other, P) and len(ctx.pages) == n and clients(P) == 1,
               f"pages={len(ctx.pages)}/{n} clients={clients(P)}")
            other.click("#note button")
            ok("...and its 'Open here' attaches it here after all",
               wait_for(lambda: other.evaluate(ARG) == P, 5) and wait_for(lambda: clients(P) == 2, 8),
               f"clients={clients(P)}")
            other.close()
            page.click(f"#tabs .tab[data-name='{P}']")
            ok("(picked again while it is still popped out: the note again)",
               wait_for(lambda: note_says(page, P), 2) and page.evaluate(ARG) == Q)
            w.close()
            time.sleep(0.8)
            page.click(f"#tabs .tab[data-name='{P}']")
            ok("with the pop-out closed, its tab switches as usual", wait_for(lambda: page.evaluate(ARG) == P, 5))
            ok("...and the note saying it is in a pop-out is gone", not page.locator("#note").is_visible(),
               page.locator("#note").inner_text())
            ok("no page errors", not errs, errs)
            b.close()

        # ======================================== G19: pop-ups blocked
        print("chromium, pop-ups blocked:")
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script("window.open = () => null")
        page = ctx.new_page()
        errs = errors_of(page)
        page.goto(f"{BASE}/")
        page.click(f".sess:has(a.open[data-name='{P}']) details summary")
        page.click(f".sess:has(a.open[data-name='{P}']) a[data-open=popout]")
        page.wait_for_selector("#tabs .tab.on")
        ok("menu Pop out, blocked: an ordinary tab on the session, with its bar",
           page.url.endswith(f"/s/{P}") and page.locator("#bar").is_visible()
           and not page.evaluate("document.body.classList.contains('popout')"), page.url)
        ok("...which says why", wait_for(lambda: note_says(page, "opened here"), 2))
        page.click("#popout")
        ok("the terminal's Pop out, blocked: says so and stays",
           wait_for(lambda: note_says(page, "Allow pop-ups"), 2) and page.url.endswith(f"/s/{P}")
           and len(ctx.pages) == 1, page.url)
        ok("no page errors", not errs, errs)
        b.close()

        # ======================= G10: a touchscreen laptop keeps the desktop UI
        print("chromium, touchscreen laptop (touch events, mouse pointer):")
        b = p.chromium.launch(args=["--touch-events=enabled"])
        page = b.new_context(viewport={"width": 1280, "height": 800}).new_page()
        page.goto(f"{BASE}/")
        ok("(the browser does expose touch events here)", page.evaluate("'ontouchstart' in window"))
        page.click(f".sess:has(a.open[data-name='{P}']) details summary")
        ok("landing: no touch layout, and the menu offers Pop out",
           not page.evaluate("document.body.classList.contains('touch')")
           and page.locator(f".sess:has(a.open[data-name='{P}']) a[data-open=popout]").is_visible())
        page.goto(f"{BASE}/")
        with page.expect_popup() as pi:
            page.click(f"a.open[data-name='{P}']")
        try:
            pi.value.wait_for_url(f"**/s/{P}?popout=1")
        except PlaywrightError:
            pass
        ok("...and Open pops out", "popout=1" in pi.value.url, pi.value.url)
        pi.value.close()
        open_term(page, BASE, Q)
        ok("terminal: no touch layout, Pop out shown, the key row off by default",
           not page.evaluate("document.body.classList.contains('touch')")
           and page.locator("#popout").is_visible() and not page.locator("#keys").is_visible())
        ok("...and no touch textarea stretched over the terminal",
           page.frame_locator("#frame").locator("#sj-touch").count() == 0)
        # The layout is the desktop's, but a finger is still a finger.
        tmux("send-keys", "-t", f"={Q}:", "seq 1 400", "Enter")
        time.sleep(0.6)
        page.evaluate(SWIPE, 20)
        ok("...and a finger swipe on the terminal still scrolls tmux's history",
           wait_for(lambda: tmux("display", "-p", "-t", f"={Q}:", "#{pane_in_mode}").stdout.strip() == "1", 3))
        tmux("send-keys", "-t", f"={Q}:", "-X", "cancel")
        b.close()

        # ===== G10's limit: an iPad stays a tablet, even with a trackpad attached
        print("webkit, an iPad with a trackpad (Safari says Mac, fine pointer, touch points):")
        b = p.webkit.launch()
        for mtp, want, what in ((5, True, "an iPad"), (0, False, "a Mac")):
            ctx = b.new_context(viewport={"width": 1180, "height": 820})
            ctx.add_init_script(AS_IPAD % mtp)
            page = ctx.new_page()
            page.goto(f"{BASE}/")
            land = page.evaluate("document.body.classList.contains('touch')")
            open_term(page, BASE, Q)
            term = page.evaluate("document.body.classList.contains('touch')")
            ok(f"{what}: {'the touch' if want else 'the desktop'} layout on both pages",
               land == want and term == want and page.locator("#popout").is_visible() != want,
               f"landing={land} terminal={term}")
            ctx.close()
        b.close()

        # =================== F37 F81 F82: a notched iPhone's safe areas (WebKit)
        print("webkit iphone 14 landscape, notch at the sides:")
        b = p.webkit.launch()
        ctx = b.new_context(**phone(p, "iPhone 14 landscape"))
        ctx.add_init_script("try { localStorage.setItem('sj-keys', '1') } catch (e) {}")
        page = ctx.new_page()
        page.route("**/s/**", safe_patch({"top": "0px", "bottom": "21px", "left": "47px", "right": "47px"}))
        open_term(page, BASE, P)
        W = page.evaluate("innerWidth")
        logo, kbtn, fr, k0, kn = (rect(page, s) for s in ("#bar a.ib", "#keysbtn", "#frame", "#keys .k", "#copy"))
        ok("the bar's controls are inside the safe area", logo[0] >= 47 and kbtn[2] <= W - 47, (logo, kbtn, W))
        ok("so is the terminal (no columns under the notch)", fr[0] >= 47 and fr[2] <= W - 47, fr)
        ok("the key row starts and ends inside it", k0[0] >= 47 and kn[2] <= W - 47, (k0, kn))
        page.evaluate("document.getElementById('add').click()")
        time.sleep(0.4)
        inp = rect(page, "#pop input[name=name]")
        ok("the + sheet's fields are inside it", inp[0] >= 47 and inp[2] <= W - 47, inp)
        page.evaluate("document.getElementById('pop-cancel').click()")
        ok("the Copy view's text is inside it",
           px(page, "#screen-text", "paddingLeft") >= 47 + 12 and px(page, "#screen-text", "paddingRight") >= 47 + 12)
        page.set_viewport_size({"width": 390, "height": 664})          # turned back upright
        # (headless WebKit can take seconds to deliver the orientation change)
        ok("turned upright: the current tab is still in view (the strip got narrower)",
           wait_for(lambda: page.evaluate(IN_TABS), 6))
        b.close()

        print("webkit iphone 14 portrait, home indicator and soft keyboard:")
        b = p.webkit.launch()
        for keys in ("1", "0"):
            ctx = b.new_context(**phone(p))
            ctx.add_init_script(f"try {{ localStorage.setItem('sj-keys', '{keys}') }} catch (e) {{}}")
            ctx.add_init_script(FAKE_VV)
            page = ctx.new_page()
            errs = errors_of(page)
            page.route("**/s/**", safe_patch({"top": "47px", "bottom": "34px", "left": "0px", "right": "0px"}))
            open_term(page, BASE, P)
            H = page.evaluate("innerHeight")
            if keys == "1":
                ok("key row on: it pays the home indicator's inset",
                   px(page, "#keys", "paddingBottom") == 4 + 34, px(page, "#keys", "paddingBottom"))
                page.evaluate("visualViewport.__set(innerHeight - 300)")
                time.sleep(0.2)
                ok("keyboard up: the key row sits flush on it (no dead band)",
                   page.evaluate("document.body.classList.contains('kb')")
                   and px(page, "#keys", "paddingBottom") == 4
                   and abs(rect(page, "#keys")[3] - (H - 300)) < 1, rect(page, "#keys"))
                page.evaluate("visualViewport.__set(innerHeight)")
                time.sleep(0.2)
                ok("keyboard down again: the inset is back",
                   not page.evaluate("document.body.classList.contains('kb')")
                   and px(page, "#keys", "paddingBottom") == 4 + 34)
            else:
                ok("key row off: the terminal stops above the home indicator",
                   rect(page, "#frame")[3] <= H - 34 + 0.5, (rect(page, "#frame"), H))
                page.evaluate("visualViewport.__set(innerHeight - 300)")
                time.sleep(0.2)
                ok("...and reaches down to the keyboard when that is up",
                   abs(rect(page, "#frame")[3] - (H - 300)) < 1, rect(page, "#frame"))
            ok("no page errors", not errs, errs)
            ctx.close()
        b.close()
finally:
    for s in MADE + FILLERS:
        tmux("kill-session", "-t", f"={s}")

print("  " + ("all chrome checks passed" if not fails else f"{fails} chrome check(s) FAILED"))
if fails:
    raise SystemExit(1)
