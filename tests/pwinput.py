"""Terminal input: the soft-key row, its Ctrl latch, Paste/Copy and focus.

Every check reads what the terminal really received off the tmux pane. The
suite makes its own scratch sessions (pwinput, pwinput2, pwinput-gone,
pwscroll) and kills them at the end, so it does not disturb run.sh's
"pwtest". A "raw
logger" is `cat -v` with the tty's line editing, signals and echo off, so
each byte the page sends shows up as one visible token (ESC as ^[, 0x1c as
^\\, DEL as ^?).

The second half is scrolling, the clipboard and two screens on one session:
typing after a wheel or a swipe (here or on the other device) runs as typed
instead of going to tmux's copy mode, while Esc (key row, keyboard, Ctrl+[,
vi mode-keys too) only leaves it and PgUp/PgDn page it; Ctrl+wheel never
reaches the program;
wheel travel per row; tmux mouse mode toggled under an open page; the
selection dropped by a scroll, copies without tmux's padding, Ctrl+C after a
copy, Ctrl+Shift+C; the Paste key's bracketed paste (Firefox included); the
leave prompt (only for a close made with Ctrl held, i.e. Ctrl+W); and which
screen gets the session's size.

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


def show_keys(page, want=True, tap=False):
    """the key row shown (or hidden), whatever it was; True when it was toggled"""
    if page.locator("#keys").is_visible() == want:
        return False
    (page.tap if tap else page.click)("#keysbtn")
    time.sleep(0.3)
    return True


def inside(page, sel):
    """the element's box lies wholly inside the viewport, without scrolling anything"""
    return page.evaluate("""s => { const r = document.querySelector(s).getBoundingClientRect();
      return r.width > 0 && r.left >= 0 && r.right <= innerWidth + 0.5; }""", sel)


SC = "pwscroll"            # scrolling, clipboard, two screens
HAS_SEL = "document.getElementById('frame').contentWindow.term.hasSelection()"
TERM_SIZE = "(t => [t.cols, t.rows])(document.getElementById('frame').contentWindow.term)"
# What happened to the next wheel / Ctrl+Shift+C keydown in the frame: a window
# capture listener sees the event first, and reads defaultPrevented once the
# page's own handlers are done with it.
WATCH = """kind => { const w = document.getElementById('frame').contentWindow; window.__seen = [];
  w.addEventListener(kind, e => { if (kind === 'keydown' && e.code !== 'KeyC') return;
    setTimeout(() => window.__seen.push(e.defaultPrevented), 0); }, true); }"""


# A wheel over the terminal, dispatched in the frame: the page's own scroll
# path (the one a swipe takes too), in an engine Playwright can't swipe in.
PHONE_WHEEL = """dy => { const f = document.getElementById('frame'), w = f.contentWindow;
  f.contentDocument.querySelector('.xterm-screen').dispatchEvent(
    new w.WheelEvent('wheel', { deltaY: dy, deltaMode: 0, bubbles: true, cancelable: true })); }"""


def mode(name=SC):
    """(pane_in_mode, scroll_position, serverjack's copy-mode mark)"""
    out = tmux("display", "-p", "-t", f"={name}:", "#{pane_in_mode}\t#{scroll_position}\t#{@serverjack_scrolled}")
    return tuple((out.stdout.rstrip("\n").split("\t") + ["", "", ""])[:3])


def window(name=SC):
    return tmux("display", "-p", "-t", f"={name}:", "#{window_width}x#{window_height}").stdout.strip()


def history(name=SC, n=300):
    fresh(name)
    shell(f"clear; seq 1 {n}", name)
    time.sleep(0.6)


def cell_h(page):
    return page.evaluate("""(() => { const f = document.getElementById('frame'), t = f.contentWindow.term;
      return f.contentDocument.querySelector('.xterm-screen').getBoundingClientRect().height / t.rows; })()""")


def over_term(page):
    box = page.locator("#frame").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    return box


def ran(token, name=SC):
    """`echo hello <token>` ran as typed: its output line is there, and no
    fragment of it ran as a command of its own"""
    out = pane(name)
    return any(line.strip() == "hello " + token for line in out.splitlines()) and "not found" not in out


def row_y(page, needle, name=SC):
    """page y of the (last) row of the pane that contains needle"""
    rows = pane(name).split("\n")
    i = max(n for n, r in enumerate(rows) if needle in r and not r.startswith("$"))
    box = page.locator("#frame").bounding_box()
    h = cell_h(page)
    return box["y"] + h * i + h / 2


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

        # The latch and a keyboard key that is no character: Ctrl goes with it
        # and lets go, as with the soft keys (it stayed armed, and the next
        # letter went as a control character: Return then x sent ^M^X).
        rawlog()
        for key in ("Enter", "Backspace", "ArrowUp"):
            page.tap("#ctrl"); time.sleep(0.2)
            page.keyboard.press(key); time.sleep(0.2)
            page.keyboard.type("x"); time.sleep(0.2)
        time.sleep(0.3)
        ok("Ctrl latch: Return, Backspace and an arrow from the keyboard take it, and it lets go",
           logged() == "^Mx^Hx^[[1;5Ax" and "armed" not in page.get_attribute("#ctrl", "class"), repr(logged()))

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
            if not page.locator("#copy").is_visible():
                flips.append("the key row went away")
                break
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

        # ================================================================
        # Scrolling, the clipboard and two screens on one session
        # ================================================================
        mk(SC)
        for bt in ("chromium", "firefox", "webkit"):
            print(bt + " desktop, scrolling and clipboard:")
            b = getattr(p, bt).launch()
            ctx = b.new_context(viewport={"width": 1280, "height": 800},
                                **({"permissions": ["clipboard-read", "clipboard-write"]} if bt == "chromium" else {}))
            page = ctx.new_page()
            page.on("pageerror", lambda e: print("   [pageerror]", e))
            # The page asks before it is left (below). Navigations made by the
            # test itself say yes; while the prompt is under test, it is
            # recorded and answered "stay".
            asked, guard = [], [False]

            def on_dialog(d):
                if not guard[0]:
                    return d.accept()
                asked.append(d.type)
                d.dismiss()
            page.on("dialog", on_dialog)
            open_term(page, SC, keys=False)

            # Typing while scrolled back goes to the program, not to tmux's
            # copy mode (which ate "echo " and ran "hello ...").
            history()
            over_term(page)
            page.mouse.wheel(0, -(cell_h(page) * 10 + 2)); time.sleep(0.7)
            ok("a wheel of 10 rows' travel scrolls tmux 10 lines", mode()[:2] == ("1", "10"), mode())
            tok = "WHEEL" + bt[:2].upper()
            page.keyboard.type(f"echo hello {tok}"); page.keyboard.press("Enter")
            ok("typing while scrolled back leaves copy mode and runs the line as typed",
               wait_for(lambda: ran(tok)) and mode()[0] == "0", pane(SC)[-240:])

            # Esc only leaves the scrollback; Ctrl+wheel (and a pinch) is the
            # browser's zoom and never reaches the program.
            fresh(SC)
            shell("seq 1 100; stty -icanon -isig -iexten -echo -ixon -icrnl; cat -v", SC)
            wait_for(lambda: cmd(SC) == "cat"); time.sleep(0.4)
            over_term(page)
            page.mouse.wheel(0, -(cell_h(page) * 3 + 2)); time.sleep(0.6)
            page.keyboard.press("Escape"); time.sleep(0.5)
            ok("Esc leaves the scrollback and sends nothing on", mode()[0] == "0" and logged(SC).endswith("100"),
               (mode(), logged(SC)[-40:]))
            # ...also under `mode-keys vi`, where copy mode's own Esc only
            # clears the selection; and Ctrl+[ is the same byte as Esc.
            tmux("set-option", "-w", "-t", f"={SC}:", "mode-keys", "vi")
            page.mouse.wheel(0, -(cell_h(page) * 3 + 2)); time.sleep(0.6)
            page.keyboard.press("Escape"); time.sleep(0.5)
            ok("...also under mode-keys vi", mode()[0] == "0" and logged(SC).endswith("100"), (mode(), logged(SC)[-40:]))
            tmux("set-option", "-wu", "-t", f"={SC}:", "mode-keys")
            page.mouse.wheel(0, -(cell_h(page) * 3 + 2)); time.sleep(0.6)
            page.keyboard.press("Control+BracketLeft"); time.sleep(0.5)
            ok("...and Ctrl+[ does the same", mode()[0] == "0" and logged(SC).endswith("100"), (mode(), logged(SC)[-40:]))
            # PgUp/PgDn, on the key row or the keyboard, page the scrollback
            # instead of leaving it; PgDn at the bottom leaves it, and
            # serverjack's mark goes with it.
            toggled = show_keys(page)
            over_term(page)
            page.mouse.wheel(0, -(cell_h(page) * 3 + 2)); time.sleep(0.6)
            page.click("#keys [data-k=PageUp]"); time.sleep(0.5)
            up1 = mode()
            page.keyboard.press("PageUp"); time.sleep(0.5)
            up2 = mode()
            ok("PgUp on the key row and the keyboard pages further back, sending nothing",
               up1[0] == up2[0] == "1" and 3 < int(up1[1] or 0) < int(up2[1] or 0) and logged(SC).endswith("100"),
               (up1, up2, logged(SC)[-40:]))
            for _ in range(6):
                if mode()[0] != "1":
                    break
                page.click("#keys [data-k=PageDown]"); time.sleep(0.4)
            ok("PgDn pages back down and leaves at the bottom, sending nothing",
               mode()[0] == "0" and logged(SC).endswith("100"), (mode(), logged(SC)[-40:]))
            ok("...and serverjack's mark goes with it", wait_for(lambda: mode()[2] == "", 2.5), mode())
            if toggled:
                show_keys(page, False)
            over_term(page)
            page.evaluate(WATCH, "wheel")
            page.keyboard.down("Control")
            page.mouse.wheel(0, -120); time.sleep(0.3); page.mouse.wheel(0, 120); time.sleep(0.3)
            page.keyboard.up("Control"); time.sleep(0.4)
            seen = page.evaluate("window.__seen")
            ok("Ctrl+wheel sends nothing to the program and isn't scrolled", logged(SC).endswith("100")
               and mode()[0] == "0", (mode(), logged(SC)[-40:]))
            ok("...and is left to the browser (not cancelled, so it zooms)", seen and not any(seen), seen)
            page.keyboard.type("k"); time.sleep(0.4)
            ok("...and typing still arrives", logged(SC).endswith("100\nk"), logged(SC)[-40:])

            # tmux mouse mode changed under the open page: the wheel follows it.
            history(n=100)
            tmux("set-option", "-t", f"={SC}:", "mouse", "on")
            page.reload(); open_term(page, SC, keys=False)
            tmux("set-option", "-t", f"={SC}:", "mouse", "off"); time.sleep(1.0)
            over_term(page)
            page.mouse.wheel(0, -(cell_h(page) * 4 + 2)); time.sleep(0.7)
            scrolled = mode()
            tmux("send-keys", "-t", f"={SC}:", "-X", "cancel"); time.sleep(0.3)
            ok("mouse turned off while open: the wheel scrolls (no arrow keys typed)",
               scrolled[0] == "1" and pane(SC).rstrip().endswith("$"), (scrolled, pane(SC)[-60:]))
            # The page drops its own scroll mark on its next state poll (every
            # 2 s). Start the mouse-on round once that has happened, rather than
            # hoping the poll lands inside the window below on a slow runner.
            wait_for(lambda: mode()[2] == "", 6)
            tmux("set-option", "-t", f"={SC}:", "mouse", "on"); time.sleep(1.0)
            page.mouse.wheel(0, -(cell_h(page) * 4 + 2)); time.sleep(0.7)
            ok("mouse turned on while open: tmux scrolls it itself (no serverjack mark)",
               mode()[0] == "1" and mode()[2] == "", mode())
            tmux("send-keys", "-t", f"={SC}:", "-X", "cancel")
            tmux("set-option", "-u", "-t", f"={SC}:", "mouse")

            # A scroll moves the text under xterm's selection (it stayed on the
            # same screen cells, over other lines): it is dropped.
            fresh(SC)
            shell("clear; for i in $(seq 1 300); do echo row-$i; done", SC); time.sleep(0.8)
            box = page.locator("#frame").bounding_box()
            page.mouse.click(box["x"] + 30, row_y(page, "row-280"), click_count=3, delay=60); time.sleep(0.3)
            had = page.evaluate(HAS_SEL)
            over_term(page); page.mouse.wheel(0, -200); time.sleep(0.8)
            left = page.evaluate(HAS_SEL) and page.evaluate("document.getElementById('frame').contentWindow.term.getSelection()")
            ok("a selection is dropped when the page scrolls tmux", had and not left, (had, left))
            tmux("send-keys", "-t", f"={SC}:", "-X", "cancel")

            # Ctrl+Shift+C copies, and is never the browser's (DevTools' picker).
            # Not in WebKit: its user agent says Mac, where Cmd copies.
            if bt != "webkit":
                rawlog(SC)
                page.evaluate(WATCH, "keydown")
                page.keyboard.press("Control+Shift+C"); time.sleep(0.4)
                ok("Ctrl+Shift+C with nothing selected: kept from the browser, nothing typed",
                   page.evaluate("window.__seen") == [True] and logged(SC) == "",
                   (page.evaluate("window.__seen"), logged(SC)))

            # The Paste key: one bracketed paste, also in Firefox (it used to be empty there).
            fresh(SC)
            shell("printf '\\e[?2004h'; stty -icanon -isig -iexten -echo -ixon -icrnl; clear; cat -v", SC)
            wait_for(lambda: cmd(SC) == "cat"); time.sleep(0.4)
            page.evaluate("Object.defineProperty(navigator, 'clipboard', { configurable: true, "
                          "value: { readText: () => Promise.resolve('echo L1\\necho L2') } })")
            page.click("#keysbtn"); time.sleep(0.2)
            page.click("#paste"); time.sleep(0.8)
            ok("the Paste key pastes once, bracketed, newlines as Enter",
               logged(SC) == "^[[200~echo L1^Mecho L2^[[201~", repr(logged(SC)))
            page.click("#keysbtn"); time.sleep(0.2)

            # A pop-out opened again from the list while it is open (and typed
            # in) is brought forward as it is -- not reloaded -- and nothing asks.
            land = ctx.new_page(); land.goto(f"{BASE}/")
            with land.expect_popup() as pi:
                land.click(f"a.open[data-name={SC}]")
            pop = pi.value
            pop.frame_locator("#frame").locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000)
            time.sleep(1.2)
            pop.frame_locator("#frame").locator(".xterm-helper-textarea").type("x"); time.sleep(0.2)
            pop_asked = []
            pop.on("dialog", lambda d: (pop_asked.append(d.type), d.dismiss()))
            pop.evaluate("window.__was = 1")
            land.bring_to_front(); land.click(f"a.open[data-name={SC}]")
            time.sleep(1.5)
            kept = pop.evaluate("window.__was === 1")
            ok("a pop-out opened again from the list is focused, not reloaded, and doesn't ask",
               kept and pop_asked == [], (kept, pop_asked))
            pop.close(); land.close()

            # Leaving: Ctrl+W (a close the page can't see) asks first; serverjack's own exits don't.
            open_term(page, SC, keys=False)
            page.keyboard.type("x"); time.sleep(0.2)
            guard[0] = True
            page.click(f"#tabs .tab[data-name='{S2}']"); page.wait_for_timeout(800)
            page.click(f"#tabs .tab[data-name='{SC}']"); page.wait_for_timeout(800)
            page.click("#bar a.ib"); page.wait_for_url(f"{BASE}/", timeout=5000)
            guard[0] = False
            open_term(page, SC, keys=False)
            page.keyboard.type("x"); time.sleep(0.2)
            guard[0] = True
            page.click("#close"); page.wait_for_url(f"{BASE}/", timeout=5000)
            ok("switching sessions, the logo and x leave without asking", asked == [], asked)
            guard[0] = False
            # Closing it with Ctrl up (the tab's x, the mouse) just closes.
            plain = ctx.new_page(); plain.on("dialog", on_dialog)
            open_term(plain, SC, keys=False)
            plain.keyboard.type("x"); time.sleep(0.2)
            guard[0] = True
            plain.close(run_before_unload=True); page.wait_for_timeout(1000)
            ok("closing the tab with Ctrl up (the mouse) doesn't ask", asked == [] and plain.is_closed(), asked)
            guard[0] = False
            open_term(page, SC, keys=False)
            page.keyboard.type("x"); time.sleep(0.2)
            guard[0] = True
            keeper = ctx.new_page()
            # Ctrl+W itself never reaches a page, but the Ctrl press does: a
            # close while Ctrl is held is what Ctrl+W looks like from here.
            page.keyboard.down("Control")
            page.close(run_before_unload=True); keeper.wait_for_timeout(1000)
            ok("closing the tab with Ctrl held (what Ctrl+W does) asks first",
               asked == ["beforeunload"] and not page.is_closed(), asked)
            page.keyboard.up("Control"); time.sleep(0.2)
            page.close(run_before_unload=True); keeper.wait_for_timeout(1000)
            ok("...and after staying, with Ctrl let go, it closes without asking again",
               asked == ["beforeunload"] and page.is_closed(), (asked, page.is_closed()))
            # A session ended with Ctrl+D: Ctrl is often still down when the
            # page leaves for the list ~150 ms later. That is serverjack's own
            # way out, not a close: no prompt, in a tab or a pop-out.
            asked.clear()
            ender = f"pwctrld-{bt[:2]}"
            mk(ender)
            page = ctx.new_page(); page.on("dialog", on_dialog)
            open_term(page, ender, keys=False)
            box = page.locator("#frame").bounding_box()
            page.mouse.click(box["x"] + 200, box["y"] + 200); time.sleep(0.3)
            page.keyboard.type("echo ready-$((6*7))"); page.keyboard.press("Enter")
            wait_for(lambda: "ready-42" in pane(ender))     # the shell has the keyboard
            guard[0] = True
            page.keyboard.down("Control"); page.keyboard.press("d")
            time.sleep(0.3)
            page.keyboard.up("Control")
            ended = wait_for(lambda: tmux("has-session", "-t", f"={ender}").returncode != 0, 5)
            # page.url only changes as Playwright handles the navigation event,
            # which a bare sleep never lets it do: wait in Playwright's own time.

            def off_terminal():
                try:
                    page.wait_for_timeout(50)
                except Exception:
                    pass
                return "/s/" not in page.url
            left = wait_for(off_terminal, 10)
            guard[0] = False
            ok("Ctrl+D held a moment ends the session and goes to the list without asking",
               asked == [] and ended and left, (asked, ended, page.url))
            mk(ender)
            land = ctx.new_page(); land.goto(f"{BASE}/")
            with land.expect_popup() as pi:
                land.click(f"a.open[data-name={ender}]")
            pop = pi.value
            pop.frame_locator("#frame").locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000)
            time.sleep(1.2)
            pop_asked = []
            pop.on("dialog", lambda d: (pop_asked.append(d.type), d.dismiss()))
            box = pop.locator("#frame").bounding_box()
            pop.mouse.click(box["x"] + 200, box["y"] + 200); time.sleep(0.3)
            pop.keyboard.type("echo ready-$((6*7))"); pop.keyboard.press("Enter")
            wait_for(lambda: "ready-42" in pane(ender))
            pop.keyboard.down("Control"); pop.keyboard.press("d")
            time.sleep(0.3)
            try:
                pop.keyboard.up("Control")
            except Exception:                     # the pop-out closed first: that's the point
                pass
            closed = wait_for(lambda: land.wait_for_timeout(50) or pop.is_closed(), 10)
            ok("...and a pop-out ended that way just closes", closed and pop_asked == [], (closed, pop_asked))
            land.close()
            b.close()

        # Clipboard detail where the clipboard can be read (Chromium).
        print("chromium desktop, copying:")
        b = p.chromium.launch()
        page = b.new_context(viewport={"width": 1280, "height": 800},
                             permissions=["clipboard-read", "clipboard-write"]).new_page()
        page.on("pageerror", lambda e: print("   [pageerror]", e))
        open_term(page, SC, keys=False)
        fresh(SC)
        shell("clear; printf 'PADDED_LINE      \\n'", SC); time.sleep(0.6)
        box = page.locator("#frame").bounding_box()
        page.mouse.click(box["x"] + 30, row_y(page, "PADDED_LINE"), click_count=3, delay=60); time.sleep(0.3)
        raw = page.evaluate("document.getElementById('frame').contentWindow.term.getSelection()")
        page.evaluate("navigator.clipboard.writeText('')")
        page.keyboard.press("Control+c"); time.sleep(0.5)
        clip = page.evaluate("navigator.clipboard.readText()")
        ok("copied lines lose the trailing spaces drawn on screen", raw.startswith("PADDED_LINE ")
           and clip == "PADDED_LINE", (raw, clip))
        shell("clear; echo SHIFTCOPY", SC); time.sleep(0.6)
        page.mouse.click(box["x"] + 30, row_y(page, "SHIFTCOPY"), click_count=3, delay=60); time.sleep(0.3)
        page.evaluate("navigator.clipboard.writeText('')")
        page.evaluate(WATCH, "keydown")
        page.keyboard.press("Control+Shift+C"); time.sleep(0.5)
        ok("Ctrl+Shift+C copies the selection, kept from the browser",
           page.evaluate("navigator.clipboard.readText()") == "SHIFTCOPY" and page.evaluate("window.__seen") == [True],
           (page.evaluate("navigator.clipboard.readText()"), page.evaluate("window.__seen")))
        ok("...and drops the selection, as Ctrl+C does", not page.evaluate(HAS_SEL))
        b.close()

        # ---------------------------------- two screens on one session
        print("two screens (chromium desktop + webkit iphone 14):")
        bd, bw = p.chromium.launch(), p.webkit.launch()
        desk = bd.new_context(viewport={"width": 1280, "height": 800}).new_page()
        desk.on("pageerror", lambda e: print("   [desk pageerror]", e))
        dev = dict(p.devices["iPhone 14"]); dev.pop("default_browser_type", None)
        phone = bw.new_context(**dev).new_page()
        phone.on("pageerror", lambda e: print("   [phone pageerror]", e))
        phone.on("dialog", lambda d: d.accept())          # its reload below, after typing
        history()
        open_term(desk, SC, keys=False)
        open_term(phone, SC, keys=False)
        dsize, psize = desk.evaluate(TERM_SIZE), phone.evaluate(TERM_SIZE)
        ok("the phone attaching takes the window (tmux: latest client)", window() == "%dx%d" % tuple(psize),
           (window(), psize))
        ok("both pages say the session is also open on another screen",
           wait_for(lambda: not desk.locator("#screens").is_hidden() and not phone.locator("#screens").is_hidden(), 8)
           and "another screen" in (desk.get_attribute("#screens", "aria-label") or ""))
        land = bd.new_page(); land.goto(f"{BASE}/")
        meta = land.locator(f".sess:has(a.open[data-name={SC}]) .meta").inner_text()
        ok("the landing row says how many screens", "attached on 2 screens" in meta, meta)
        land.close()

        # Copy mode entered from the phone is left before the desktop's typing.
        phone.evaluate(f"fetch('/api/scroll', {{ method: 'POST', body: new URLSearchParams({{ name: '{SC}', lines: 10 }}) }})")
        wait_for(lambda: mode()[0] == "1")
        ok("the phone's scroll puts the shared pane in copy mode", mode() == ("1", "10", "1"), mode())
        time.sleep(2.5)                                   # the desktop's poll while it has focus
        desk.keyboard.type("echo hello DESKTOP"); desk.keyboard.press("Enter")
        ok("...and the desktop's next line still runs as typed", wait_for(lambda: ran("DESKTOP")), pane(SC)[-240:])
        # ...and straight after it, before the desktop's next look at the pane
        # (every 2 s) could tell it (G11): with another screen on the
        # session, its first key after a while waits for one more look.
        for delay in (0.3, 1.0):
            time.sleep(1)                                 # a hand moving to the phone and back
            phone.evaluate(f"fetch('/api/scroll', {{ method: 'POST', body: new URLSearchParams({{ name: '{SC}', lines: 10 }}) }})")
            wait_for(lambda: mode()[0] == "1", 3)
            time.sleep(delay)
            tok = f"QUICK{int(delay * 10)}"
            desk.keyboard.type(f"echo hello {tok}"); desk.keyboard.press("Enter")
            ok(f"...even typed {delay}s after the phone's scroll", wait_for(lambda: ran(tok)) and mode()[0] == "0",
               pane(SC)[-240:])
        # The phone's own scroll, through the page (the same path as a swipe),
        # and typing straight after it: held until copy mode is left.
        phone.evaluate(PHONE_WHEEL, -(5 * cell_h(phone) + 2))
        wait_for(lambda: mode()[0] == "1", 3)
        scrolled = mode()
        phone.keyboard.type("echo hello PHONE"); phone.keyboard.press("Enter")
        ok("typing on the phone right after its own scroll runs as typed",
           scrolled[0] == "1" and wait_for(lambda: ran("PHONE")) and mode()[0] == "0", (scrolled, pane(SC)[-240:]))
        tmux("copy-mode", "-t", f"={SC}:"); time.sleep(2.5)      # prefix-[ in some client: the user's copy mode
        desk.keyboard.type("z"); time.sleep(0.6)
        ok("copy mode the user entered themselves is left alone", mode()[0] == "1" and mode()[2] == "", mode())
        tmux("send-keys", "-t", f"={SC}:", "-X", "cancel")

        # The key row's Esc after a scroll only leaves the scrollback: it is
        # how a phone gets back, and sent on it would interrupt an agent.
        fresh(SC)
        shell("seq 1 100; stty -icanon -isig -iexten -echo -ixon -icrnl; cat -v", SC)
        wait_for(lambda: cmd(SC) == "cat"); time.sleep(0.4)
        toggled = show_keys(phone, tap=True)
        phone.evaluate(PHONE_WHEEL, -(4 * cell_h(phone) + 2))
        wait_for(lambda: mode()[0] == "1", 3); time.sleep(0.4)
        scrolled = mode()
        phone.tap("#keys [data-k=Escape]"); time.sleep(0.8)
        ok("the phone's key-row Esc after a scroll leaves it and sends nothing on",
           scrolled[0] == "1" and mode()[0] == "0" and logged(SC).endswith("100"), (scrolled, mode(), logged(SC)[-40:]))
        if toggled:
            show_keys(phone, False, tap=True)

        # The screen you engage with takes the size back; no key is sent.
        rawlog(SC)
        phone.reload(); open_term(phone, SC, keys=False)          # phone attached last: it has the size
        wait_for(lambda: window() == "%dx%d" % tuple(phone.evaluate(TERM_SIZE)))
        box = desk.locator("#frame").bounding_box()
        desk.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        ok("clicking in the desktop's terminal gives it the size back",
           wait_for(lambda: window() == "%dx%d" % tuple(dsize)), (window(), dsize))
        phone.tap("#screens")
        ok("tapping the screens cue on the phone takes it for the phone",
           wait_for(lambda: window() == "%dx%d" % tuple(phone.evaluate(TERM_SIZE))), window())
        desk.wait_for_timeout(1100)
        desk.evaluate("window.dispatchEvent(new Event('focus'))")
        ok("the desktop window taking focus takes it back", wait_for(lambda: window() == "%dx%d" % tuple(dsize)), window())
        ok("...and none of that typed anything", logged(SC) == "", repr(logged(SC)))
        phone.context.close()
        ok("with the phone gone the cue goes too", wait_for(lambda: desk.locator("#screens").is_hidden(), 8))
        bd.close(); bw.close()

        # 320px: the cue appearing keeps the current tab in view.
        bs, bw = p.chromium.launch(), p.webkit.launch()
        other = bs.new_page(); open_term(other, SC, keys=False)
        dev = dict(p.devices["iPhone SE"]); dev.pop("default_browser_type", None)
        page = bw.new_context(**dev).new_page()
        open_term(page, SC)
        shown = wait_for(lambda: not page.locator("#screens").is_hidden(), 8)
        # how much of the current tab's width the strip shows
        inview = page.evaluate("""(() => { const t = document.querySelector('#tabs .tab.on').getBoundingClientRect(),
          s = document.getElementById('tabs').getBoundingClientRect();
          return (Math.min(t.right, s.right) - Math.max(t.left, s.left)) / t.width; })()""")
        ok("320px: the cue shows and the current tab stays in view", shown and inview > 0.95, (shown, inview))
        page.screenshot(path="shots/pwinput-320-screens.png")
        bs.close(); bw.close()

        # ------------------------- Pixel 7: a real swipe, then a predicted word
        print("chromium pixel 7, swipe then type:")
        b = p.chromium.launch()
        dev = dict(p.devices["Pixel 7"]); dev.pop("default_browser_type", None)
        ctx = b.new_context(**dev)
        page = ctx.new_page()
        page.on("pageerror", lambda e: print("   [pageerror]", e))
        cdp = ctx.new_cdp_session(page)
        open_term(page, SC)
        history()
        fb = page.locator("#frame").bounding_box()
        x, y0 = fb["x"] + fb["width"] / 2, fb["y"] + fb["height"] * 0.3
        h = cell_h(page)

        def swipe_down(rows):
            """a finger dragged down over the terminal: scrolls back <rows> lines"""
            cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y0}]})
            for i in range(1, 13):
                time.sleep(0.016)
                cdp.send("Input.dispatchTouchEvent", {"type": "touchMove",
                                                      "touchPoints": [{"x": x, "y": y0 + (h * rows + 4) * i / 12}]})
            cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            time.sleep(0.8)
        swipe_down(12)
        ok("a 12-row swipe scrolls 12 lines", mode()[:2] == ("1", "12"), mode())
        page.keyboard.insert_text("echo hello SWIPED"); time.sleep(0.1)
        page.keyboard.press("Enter")
        ok("a word arriving as text (prediction, dictation) right after runs as typed",
           wait_for(lambda: ran("SWIPED")) and mode()[0] == "0", pane(SC)[-240:])
        # Back from a swipe with the key row's Esc: nothing reaches the program.
        fresh(SC)
        shell("seq 1 100; stty -icanon -isig -iexten -echo -ixon -icrnl; cat -v", SC)
        wait_for(lambda: cmd(SC) == "cat"); time.sleep(0.4)
        swipe_down(5)
        scrolled = mode()
        page.tap("#keys [data-k=Escape]"); time.sleep(0.8)
        ok("the key row's Esc after a swipe leaves the scrollback and sends nothing on",
           scrolled[0] == "1" and mode()[0] == "0" and logged(SC).endswith("100"), (scrolled, mode(), logged(SC)[-40:]))
        b.close()
finally:
    for n in (S, S2, GONE, SC, "pwctrld-ch", "pwctrld-fi", "pwctrld-we"):
        tmux("kill-session", "-t", f"={n}")

if fails:
    raise SystemExit(1)
