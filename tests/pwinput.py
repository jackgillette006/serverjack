"""Terminal input: the soft-key row, its Ctrl latch, Paste/Copy and focus.

Every check reads what the terminal really received off the tmux pane. The
suite makes its own scratch sessions (pwinput, pwinput2, pwinput-gone) and
kills them at the end, so it does not disturb run.sh's "pwtest". A "raw
logger" is `cat -v` with the tty's line editing, signals and echo off, so
each byte the page sends shows up as one visible token (ESC as ^[, 0x1c as
^\\, DEL as ^?).

Engines: Chromium desktop (mouse and keyboard), Chromium Pixel 7 (real touch
gestures through CDP: swipes and holds, which Playwright's WebKit cannot
do), WebKit iPhone 14 / iPhone SE (layout, page.tap()), and a focus check in
all three desktop engines. Emulated WebKit is Linux WebKit, not iOS Safari:
in particular it sends no click after a tap whose pointerdown was
preventDefault'ed (iOS does), which is exactly why the Paste and Copy keys
must not depend on that click.
"""
import os
import subprocess
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("SERVERJACK_TEST_BASE") or os.environ.get("BASE", "http://127.0.0.1:7690")
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]
S, S2, GONE = "pwinput", "pwinput2", "pwinput-gone"
SHELL = "env PS1='$ ' HISTFILE=/dev/null bash --noprofile --norc -i"
fails = 0


def tmux(*args):
    return subprocess.run(T + list(args), capture_output=True, text=True)


def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + str(extra)) if extra and not cond else ""))
    return bool(cond)


def wait_for(fn, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.15)
    return fn()


def mk(name):
    tmux("kill-session", "-t", f"={name}")
    tmux("new-session", "-d", "-s", name, "-x", "120", "-y", "30", "-c", "/tmp", SHELL)


def pane(name=S):
    return tmux("capture-pane", "-p", "-J", "-t", f"={name}:").stdout


def cmd(name=S):
    return tmux("display", "-p", "-t", f"={name}:", "#{pane_current_command}").stdout.strip()


def fresh(name=S):
    """A clean interactive bash in the pane (whatever ran there is killed)."""
    tmux("respawn-pane", "-k", "-t", f"={name}:", SHELL)
    tmux("clear-history", "-t", f"={name}:")
    wait_for(lambda: cmd(name) == "bash")
    time.sleep(0.3)


def shell(line, name=S):
    tmux("send-keys", "-t", f"={name}:", "-l", line)
    tmux("send-keys", "-t", f"={name}:", "Enter")


def rawlog(name=S):
    """cat -v with no line editing, no signals, no echo: the pane shows every
    byte the terminal sends, and nothing else."""
    fresh(name)
    shell("stty -icanon -isig -iexten -echo -ixon -icrnl; clear; cat -v", name)
    wait_for(lambda: cmd(name) == "cat")
    time.sleep(0.4)


def logged(name=S):
    return pane(name).strip()


def cooked_cat(name=S):
    """plain `cat -v` under bash: ^C (SIGINT) ends it, Esc shows as ^[."""
    fresh(name)
    shell("clear; cat -v", name)
    wait_for(lambda: cmd(name) == "cat")
    time.sleep(0.3)


def open_term(page, name=S, keys=True):
    page.goto(f"{BASE}/s/{name}")
    page.wait_for_selector("#tabs .tab.on")
    page.frame_locator("#frame").locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000)
    time.sleep(1.2)
    if keys and not page.locator("#keys").is_visible():
        page.click("#keysbtn")
        time.sleep(0.2)


TA_FOCUSED = """(() => { const f = document.getElementById('frame'), d = f.contentDocument,
  a = d && d.activeElement; return document.activeElement === f && !!a && a.classList.contains('xterm-helper-textarea'); })()"""
FOCUS_TERM = """(() => { const f = document.getElementById('frame'); f.contentWindow.focus();
  f.contentDocument.querySelector('.xterm-helper-textarea').focus(); })()"""
BLUR_TERM = "document.getElementById('frame').contentDocument.querySelector('.xterm-helper-textarea').blur()"
NO_CLIPBOARD = "Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })"


def inside(page, sel):
    """the element's box lies wholly inside the viewport, without scrolling anything"""
    return page.evaluate("""s => { const r = document.querySelector(s).getBoundingClientRect();
      return r.width > 0 && r.left >= 0 && r.right <= innerWidth + 0.5; }""", sel)


def dispatch_tap(page, sel, **up):
    """A synthetic pointer press: pointerdown, then pointerup (optionally moved)."""
    loc = page.locator(sel)
    loc.dispatch_event("pointerdown", {"pointerId": 7, "clientX": 100, "clientY": 100, "isPrimary": True})
    loc.dispatch_event("pointerup", {"pointerId": 7, "clientX": 100 + up.get("dx", 0), "clientY": 100, "isPrimary": True})


mk(S)
mk(S2)
mk(GONE)
try:
    with sync_playwright() as p:
        # ------------------------------------------------ Chromium desktop
        print("chromium desktop:")
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 800},
                            permissions=["clipboard-read", "clipboard-write"])
        page = ctx.new_page()
        page.on("pageerror", lambda e: print("   [pageerror]", e))
        open_term(page)
        ok("desktop: the whole key row fits, nothing faded",
           all(inside(page, f"#keys .k:nth-child({i})") for i in range(1, 14))
           and page.get_attribute("#keys", "class") in ("", None), page.get_attribute("#keys", "class"))

        # Keyboard Enter/Space, element.click() and a real mouse click each send exactly one key.
        rawlog()
        page.focus("#keys [data-k=ArrowUp]")
        page.keyboard.press("Enter"); time.sleep(0.3)
        page.keyboard.press("Space"); time.sleep(0.3)
        page.eval_on_selector("#keys [data-k=ArrowDown]", "b => b.click()"); time.sleep(0.3)
        page.click("#keys [data-k=ArrowLeft]"); time.sleep(0.4)
        out = logged()
        ok("Enter and Space on a focused soft key each send it", out.count("^[[A") == 2, repr(out))
        ok("element.click() (assistive tech) sends the key once", out.count("^[[B") == 1, repr(out))
        ok("a real mouse click sends the key exactly once", out.count("^[[D") == 1, repr(out))
        page.focus("#ctrl"); page.keyboard.press("Space"); time.sleep(0.2)
        ok("Ctrl arms from the keyboard too (aria-pressed)",
           "armed" in page.get_attribute("#ctrl", "class") and page.get_attribute("#ctrl", "aria-pressed") == "true")
        page.keyboard.press("Space"); time.sleep(0.2)
        ok("...and disarms", "armed" not in page.get_attribute("#ctrl", "class")
           and page.get_attribute("#ctrl", "aria-pressed") == "false")

        # The soft Ctrl latch with punctuation and digits sends the control byte.
        rawlog()
        seq = [("\\", "^\\"), ("[", "^["), ("]", "^]"), ("_", "^_"), ("^", "^^"), ("?", "^?"),
               ("@", "^@"), ("/", "^_"), ("-", "^_"), ("2", "^@"), ("6", "^^"), ("l", "^L"), (".", ".")]
        for ch, _ in seq:
            page.click("#ctrl"); page.evaluate(FOCUS_TERM)
            page.keyboard.type(ch); time.sleep(0.15)
        time.sleep(0.4)
        want = "".join(w for _, w in seq)
        out = logged()
        ok("Ctrl latch + \\ [ ] _ ^ ? @ / - 2 6 l send their control bytes; '.' goes through as typed",
           out == want, f"{out!r} != {want!r}")
        ok("...and the latch is released", "armed" not in page.get_attribute("#ctrl", "class"))

        # Copy view: Copy all keeps the newlines; a tapped line keeps its indentation.
        fresh()
        shell("clear; printf 'top line\\n    indented line\\n\\nlast line\\n'")
        time.sleep(0.6)
        page.click("#copy")
        page.wait_for_function("document.querySelectorAll('#screen-text .ln').length > 3")
        page.evaluate("navigator.clipboard.writeText('')")
        page.click("#screen-copy"); time.sleep(0.4)
        clip = page.evaluate("navigator.clipboard.readText()")
        ok("Copy all keeps the line breaks and the blank line",
           "top line\n    indented line\n\nlast line\n" in clip, repr(clip))
        page.locator("#screen-text .ln", has_text="indented line").click(); time.sleep(0.4)
        clip = page.evaluate("navigator.clipboard.readText()")
        ok("tapping an indented line copies its indentation", clip == "    indented line", repr(clip))
        page.click("#screen-close"); time.sleep(0.3)

        # Copy view takes focus: Esc closes it and never reaches the program underneath.
        cooked_cat()
        page.evaluate(FOCUS_TERM)
        page.click("#copy"); time.sleep(0.5)
        ok("opening the Copy view moves focus into it",
           page.evaluate("document.activeElement.id") == "screen-text" and not page.evaluate(TA_FOCUSED))
        page.keyboard.type("q"); page.keyboard.press("Escape"); time.sleep(0.4)
        ok("Esc closes the Copy view", not page.locator("#screen").is_visible())
        ok("...and puts focus back in the terminal", page.evaluate(TA_FOCUSED))
        page.keyboard.type("zq"); page.keyboard.press("Enter"); time.sleep(0.5)
        out = pane()
        ok("neither the Esc nor the keys typed in the view reached the terminal; typing after it does",
           "^[" not in out and "zq" in out and "qzq" not in out, repr(out))

        # Copy view errors: say so, and never let Copy all copy a status line.
        page.route("**/api/screen*", lambda r: r.abort())
        page.click("#copy"); time.sleep(0.6)
        ok("server unreachable: the view says so",
           "Can’t reach serverjack" in page.inner_text("#screen-text"), page.inner_text("#screen-text"))
        page.click("#screen-copy"); time.sleep(0.2)
        ok("...and Copy all has nothing to copy", page.inner_text("#screen-copy") == "nothing to copy")
        page.unroute("**/api/screen*")
        page.click("#screen-refresh"); time.sleep(0.6)
        ok("Refresh recovers", page.locator("#screen-text .ln").count() > 0
           and "reach" not in page.inner_text("#screen-text"))
        page.keyboard.press("Escape"); time.sleep(0.3)

        # Paste without clipboard access: a hint above the row; the key keeps its label and width.
        page.reload(); open_term(page)
        page.evaluate(NO_CLIPBOARD)
        w0 = page.locator("#paste").bounding_box()["width"]
        page.click("#paste"); time.sleep(0.15)
        w1 = page.locator("#paste").bounding_box()["width"]
        page.click("#paste"); time.sleep(0.2)
        ok("no clipboard: a hint says how to paste instead", "on" in (page.get_attribute("#hint", "class") or "")
           and "Ctrl+V" in page.inner_text("#hint"), page.inner_text("#hint"))
        ok("...and the Paste key does not change width", abs(w1 - w0) < 0.5, f"{w0} -> {w1}")
        time.sleep(1.6)
        ok("...or keep a stale label after two quick presses", page.inner_text("#paste") == "Paste",
           page.inner_text("#paste"))
        b.close()

        # --------------------------------- focus after bar/overlay clicks, all engines
        for bt in ("chromium", "firefox", "webkit"):
            print(bt + " desktop focus:")
            b = getattr(p, bt).launch()
            page = b.new_context(viewport={"width": 1280, "height": 800}).new_page()
            page.on("pageerror", lambda e: print("   [pageerror]", e))
            open_term(page, keys=False)
            fresh(); time.sleep(0.3)
            steps = [("the keys toggle", lambda: page.click("#keysbtn")),          # shows the row
                     ("a soft key", lambda: page.click("#keys [data-k=ArrowDown]")),
                     ("Close on the Copy view", lambda: (page.click("#copy"), time.sleep(0.4), page.click("#screen-close"))),
                     ("the active tab", lambda: page.click("#tabs .tab.on")),
                     ("the keys toggle again", lambda: page.click("#keysbtn"))]    # hides it
            for i, (what, act) in enumerate(steps):
                act(); time.sleep(0.4)
                tok = f"F44{i}{bt[:2]}"
                page.keyboard.type(f"echo {tok}"); page.keyboard.press("Enter"); time.sleep(0.5)
                ok(f"after clicking {what}, typing reaches the terminal", pane().count(tok) >= 2, pane()[-160:])
            b.close()

        # -------------------------------- Chromium Pixel 7: real touch gestures
        print("chromium pixel 7 (touch):")
        b = p.chromium.launch()
        dev = dict(p.devices["Pixel 7"]); dev.pop("default_browser_type", None)
        ctx = b.new_context(**dev, permissions=["clipboard-read", "clipboard-write"])
        page = ctx.new_page()
        page.on("pageerror", lambda e: print("   [pageerror]", e))
        cdp = ctx.new_cdp_session(page)

        def centre(sel):
            bb = page.locator(sel).bounding_box()
            return bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2

        def touch(kind, x=None, y=None):
            pts = [] if x is None else [{"x": x, "y": y}]
            cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": pts})

        def swipe(sel, dx, dy=0, steps=10):
            x, y = centre(sel)
            touch("touchStart", x, y)
            for i in range(1, steps + 1):
                time.sleep(0.016)
                touch("touchMove", x + dx * i / steps, y + dy * i / steps)
            touch("touchEnd")

        open_term(page)
        ok("touch: keys are 44px tall", page.locator("#keys .k").first.bounding_box()["height"] >= 44)
        cooked_cat()
        swipe("#keys [data-k=c][data-ctrl]", -200); time.sleep(0.8)
        sl = page.evaluate("document.getElementById('keys').scrollLeft")
        ok("a swipe starting on ^C scrolls the row", sl > 20, sl)
        ok("...and does not send ^C (cat still running)", cmd() == "cat", cmd())
        page.evaluate("document.getElementById('keys').scrollLeft = 0"); time.sleep(0.3)
        swipe("#keys [data-k=Escape]", -150); time.sleep(0.6)
        swipe("#keys [data-k=Tab]:not([data-shift])", 0, -60); time.sleep(0.6)   # slide off upwards
        ok("a swipe or slide-off starting on Esc / Tab sends nothing", pane().strip() == "", repr(pane().strip()))
        swipe("#ctrl", -150); time.sleep(0.5)
        ok("a swipe starting on Ctrl does not arm it", "armed" not in page.get_attribute("#ctrl", "class"))
        page.evaluate("document.getElementById('keys').scrollLeft = 0"); time.sleep(0.3)
        page.tap("#keys [data-k=c][data-ctrl]"); time.sleep(0.6)
        ok("a tap on ^C still interrupts", cmd() != "cat", cmd())

        rawlog()
        x, y = centre("#keys [data-k=ArrowLeft]")
        touch("touchStart", x, y); time.sleep(1.2); touch("touchEnd"); time.sleep(0.4)
        held = logged().count("^[[D")
        ok("holding ← repeats it", held >= 5, held)
        page.tap("#keys [data-k=ArrowLeft]"); time.sleep(0.4)
        ok("...a tap sends it once", logged().count("^[[D") == held + 1, logged().count("^[[D"))

        # Text that arrives without a key press (dictation, predictions, emoji) after soft keys.
        rawlog()
        page.tap("#keys [data-k=Escape]"); time.sleep(0.3)
        page.keyboard.insert_text("zz"); time.sleep(0.4)
        ok("dictated text right after a soft key arrives", logged() == "^[zz", repr(logged()))
        page.tap("#ctrl"); time.sleep(0.2)
        page.keyboard.type("c"); time.sleep(0.2)
        page.keyboard.type("x"); time.sleep(0.2)
        page.keyboard.insert_text("hello"); time.sleep(0.4)
        ok("...and after a Ctrl-latched key typed on the keyboard", logged() == "^[zz^Cxhello", repr(logged()))
        page.tap("#ctrl"); time.sleep(0.2)
        page.keyboard.insert_text("d"); time.sleep(0.2)
        page.keyboard.insert_text("ok"); time.sleep(0.4)
        ok("...and after a Ctrl-latched key arriving as text", logged() == "^[zz^Cxhello^Dok", repr(logged()))

        rawlog()
        page.evaluate("navigator.clipboard.writeText('PASTEONCE')")
        page.tap("#paste"); time.sleep(1.0)
        ok("one tap on Paste pastes exactly once", logged() == "PASTEONCE", repr(logged()))

        # Synthetic presses: a press that moved, or was cancelled, does nothing.
        dispatch_tap(page, "#keys [data-k=c][data-ctrl]", dx=60); time.sleep(0.3)
        page.locator("#ctrl").dispatch_event("pointerdown", {"pointerId": 9})
        page.locator("#ctrl").dispatch_event("pointercancel", {"pointerId": 9}); time.sleep(0.2)
        ok("a moved or cancelled press sends nothing", logged() == "PASTEONCE" and
           "armed" not in page.get_attribute("#ctrl", "class"), repr(logged()))

        if "armed" in page.get_attribute("#ctrl", "class"):
            page.tap("#ctrl"); time.sleep(0.2)
        page.tap("#ctrl"); time.sleep(0.2)
        ok("a tap arms Ctrl", "armed" in page.get_attribute("#ctrl", "class"))
        page.tap(f"#tabs .tab[data-name='{S2}']")
        page.wait_for_function(f"location.pathname.endsWith('/{S2}')"); time.sleep(0.4)
        ok("switching sessions disarms Ctrl", "armed" not in page.get_attribute("#ctrl", "class"))

        # The Copy view's x sits right over the keys toggle: the click the
        # browser sends after the tap used to land on the toggle once the view
        # had gone, hiding the key row and focusing the terminal (on a phone,
        # raising the keyboard nobody asked for). Twice: it flipped each time.
        TERMFOCUS = ("(() => { const f = document.getElementById('frame'), d = f.contentDocument;"
                     " return document.activeElement === f && !!d && !!d.activeElement &&"
                     " d.activeElement.className.includes('xterm-helper-textarea'); })()")
        KEYSTATE = "[document.body.classList.contains('keys'), localStorage.getItem('sj-keys')]"
        flips = []
        for _ in range(2):
            page.evaluate("document.getElementById('frame').contentDocument.activeElement.blur(); document.activeElement.blur()")
            before = page.evaluate(KEYSTATE)
            page.tap("#copy"); time.sleep(0.5)
            page.tap("#screen-close"); time.sleep(0.6)
            after = page.evaluate(KEYSTATE)
            if after != before or page.evaluate(TERMFOCUS) or page.locator("#screen").is_visible():
                flips.append((before, after, page.evaluate(TERMFOCUS)))
        ok("touch: Close in the Copy view leaves the key row and the keyboard as they were", not flips, flips)
        b.close()

        # -------------------------------- WebKit iPhone 14 / SE
        print("webkit iphone:")
        b = p.webkit.launch()
        dev = dict(p.devices["iPhone 14"]); dev.pop("default_browser_type", None)
        ctx = b.new_context(**dev)
        page = ctx.new_page()
        page.on("pageerror", lambda e: print("   [pageerror]", e))
        open_term(page)
        for sel, what in [("[data-k=Escape]", "Esc"), ("[data-k=Tab]:not([data-shift])", "Tab"),
                          ("[data-k=Tab][data-shift]", "⇧Tab"), ("#ctrl", "Ctrl"),
                          ("[data-k=c][data-ctrl]", "^C"), ("#paste", "Paste"), ("#copy", "Copy")]:
            ok(f"390px: {what} is on screen without scrolling the row", inside(page, "#keys " + sel))
        ok("390px: the row is marked as having more keys (fade on the right)",
           "more" in (page.get_attribute("#keys", "class") or ""))

        rawlog()
        page.tap("#copy"); time.sleep(0.6)
        ok("tap on Copy opens the screen-text view", page.locator("#screen").is_visible())
        page.keyboard.type("q"); time.sleep(0.3)
        ok("...typing while it is open reaches nothing", logged() == "", repr(logged()))
        page.tap("#screen-close"); time.sleep(0.4)
        ok("tap on Close closes it", not page.locator("#screen").is_visible())
        ok("...without forcing focus (and the phone keyboard) into the terminal", not page.evaluate(TA_FOCUSED))

        page.evaluate(BLUR_TERM)
        page.tap("#keysbtn"); time.sleep(0.3)
        ok("keyboard down: the keys toggle hides the row and leaves the keyboard down",
           not page.locator("#keys").is_visible() and not page.evaluate(TA_FOCUSED))
        page.tap("#keysbtn"); time.sleep(0.3)
        page.evaluate(FOCUS_TERM)
        page.tap("#keysbtn"); time.sleep(0.3)
        ok("keyboard up: the keys toggle leaves it up", page.evaluate(TA_FOCUSED))
        page.tap("#keysbtn"); time.sleep(0.3)
        # The current tab of a one-window session: nothing to pick, so a tap
        # leaves the keyboard as it was, too.
        one = tmux("display", "-p", "-t", f"={S}:", "#{session_windows}").stdout.strip() == "1"
        page.evaluate(BLUR_TERM)
        page.tap(f"#tabs .tab[data-name='{S}']"); time.sleep(0.8)
        ok("keyboard down: a tap on the current tab of a one-window session leaves it down",
           one and not page.evaluate(TA_FOCUSED), one)
        page.evaluate(FOCUS_TERM)
        page.tap(f"#tabs .tab[data-name='{S}']"); time.sleep(0.8)
        ok("keyboard up: ...and up", page.evaluate(TA_FOCUSED))

        page.evaluate(NO_CLIPBOARD)
        page.tap("#paste"); time.sleep(0.8)
        ok("tap on Paste with no clipboard access shows the long-press hint",
           "on" in (page.get_attribute("#hint", "class") or "") and "Long-press" in page.inner_text("#hint"),
           page.inner_text("#hint"))
        b.close()

        b = p.webkit.launch()
        dev = dict(p.devices["iPhone SE"]); dev.pop("default_browser_type", None)
        page = b.new_context(**dev).new_page()
        page.on("pageerror", lambda e: print("   [pageerror]", e))
        open_term(page)
        ok("320px: ^C, Paste and Copy are on screen",
           all(inside(page, "#keys " + s) for s in ("[data-k=c][data-ctrl]", "#paste", "#copy")))
        page.evaluate("(k => k.scrollLeft = k.scrollWidth)(document.getElementById('keys'))"); time.sleep(0.3)
        cls = page.get_attribute("#keys", "class") or ""
        ok("320px, scrolled to the end: the fade moves to the left edge", "less" in cls and "more" not in cls, cls)
        b.close()

        # -------------------------------- the session goes away under an open Copy view
        print("chromium, session gone:")
        b = p.chromium.launch()
        page = b.new_context(viewport={"width": 1000, "height": 700}).new_page()
        page.on("pageerror", lambda e: print("   [pageerror]", e))
        open_term(page, GONE)
        page.click("#copy"); time.sleep(0.5)
        # The page itself notices an ended session at once and leaves for the
        # session list. Hold that back with a session list that still has it,
        # so what the Copy view says on its own can be read first.
        stale = page.evaluate("fetch('/api/sessions').then(r => r.text())")
        page.route("**/api/sessions", lambda route: route.fulfill(
            status=200, content_type="application/json", body=stale))
        tmux("kill-session", "-t", f"={GONE}")
        page.click("#screen-refresh"); time.sleep(0.5)
        ok("the Copy view says the session has ended", page.inner_text("#screen-text") == "This session has ended.",
           page.inner_text("#screen-text"))
        page.unroute("**/api/sessions")
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        # location, not page.url: Playwright does not always see a history.replaceState

        def where():
            try:
                return page.evaluate("location.pathname")
            except Exception:                      # mid-navigation: ask again
                return "/s/" + GONE
        moved = wait_for(lambda: not where().endswith("/" + GONE), 10)
        ok("leaving for the session list closes the view", moved and not page.locator("#screen").is_visible(),
           where())
        b.close()
finally:
    for n in (S, S2, GONE):
        tmux("kill-session", "-t", f"={n}")

if fails:
    raise SystemExit(1)
