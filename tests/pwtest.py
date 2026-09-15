import io, os, re, time, subprocess
from playwright.sync_api import sync_playwright
from PIL import Image

BASE = os.environ.get("SERVERJACK_TEST_BASE", "http://127.0.0.1:7690")
SESS = "pwtest"
fails = 0

# Read bin/serverjack's TOKENS text directly (no import -- that would run the
# whole module) so expected colors below come from the token, not a
# hand-typed duplicate of it. This script runs inside tests/run.sh's browser
# container, which only bind-mounts tests/ itself plus, read-only, the repo's
# bin/ (as /repo-bin) for exactly this -- fall back to the relative path for
# a run straight on the host against an already-running instance.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in ("/repo-bin/serverjack", os.path.join(_HERE, "..", "bin", "serverjack")):
    if os.path.exists(_candidate):
        with open(_candidate) as _f:
            _SERVERJACK_SRC = _f.read()
        break
else:
    raise FileNotFoundError("bin/serverjack not found (checked /repo-bin and ../bin)")


def token_hex(name):
    m = re.search(r"--" + re.escape(name) + r":\s*#([0-9a-fA-F]{6})", _SERVERJACK_SRC)
    assert m, f"token --{name} not found in bin/serverjack's TOKENS"
    return m.group(1)


def token_rgb_css(name):
    h = token_hex(name)
    return "rgb({}, {}, {})".format(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def png_color_count(png_bytes):
    """Number of distinct RGB colors in a screenshot clip -- used to prove a
    character is visible against its cell (more than one color) rather than
    painted in the exact same color as its background (exactly one)."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    return len(img.getcolors(maxcolors=img.width * img.height))


def pane():
    return subprocess.run(["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default"), "capture-pane", "-p", "-t", SESS], capture_output=True, text=True).stdout
def cmd():
    return subprocess.run(["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default"), "display", "-p", "-t", SESS, "#{pane_current_command}"], capture_output=True, text=True).stdout.strip()
def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    # str(extra): a non-string extra (a dict off page.evaluate(), say) must
    # not crash the whole suite on a FAIL -- that's strictly worse than the
    # failure it was reporting. Caught for real: this used to be a bare
    # `extra`, and a dict there turned one theme-check FAIL into a
    # TypeError that aborted pwtest.py before any later suite in the same
    # run.sh invocation got a chance to run.
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + str(extra)) if extra and not cond else ""))
    return cond

with sync_playwright() as p:
    # ---------- desktop Chromium (Linux platform => Ctrl shortcuts path)
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1100, "height": 700}, permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page()
    page.on("console", lambda m: print("   [console]", m.type, m.text) if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: print("   [pageerror]", e))
    page.goto(f"{BASE}/s/{SESS}")
    page.wait_for_selector("#tabs .tab.on")
    fr = page.frame_locator("#frame")
    fr.locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000)
    time.sleep(1.5)
    page.screenshot(path="shots/desktop.png")
    print("desktop:")
    ok("bar shows current tab", page.locator("#tabs .tab.on").inner_text() == SESS)
    ok("terminal textarea focused", page.evaluate("document.getElementById('frame').contentDocument.activeElement.className.includes('xterm-helper-textarea')"))

    # bin/serverjack's generated theme (a real ttyd -t theme=... server
    # option now, via `serverjack --print-theme` -- SERVERJACK_TERM_THEME
    # unset and no theme in TTYD_EXTRA_ARGS in tests/run.sh's common env, so
    # this instance gets it) should paint the terminal in the app's own
    # --bg-primary, not xterm.js's stock look. .xterm-screen and .xterm are
    # transparent in this ttyd/xterm.js build (checked directly:
    # getComputedStyle on both reports rgba(0,0,0,0) even with a theme
    # applied) -- .xterm-viewport is the element that actually carries the
    # painted background color.
    expected_bg = token_rgb_css("bg-primary")
    bg = fr.locator(".xterm-viewport").evaluate("el => getComputedStyle(el).backgroundColor")
    ok("terminal background matches the app's --bg-primary token", bg == expected_bg, f"{bg} != {expected_bg}")

    # The theme actually applied inside the iframe (window.term is ttyd's
    # client exposing its xterm.js Terminal instance globally) must be the
    # one bin/serverjack generated, not ttyd's stock theme, and cursorAccent
    # must differ from cursor: they were once the same value, which drew the
    # character under a non-blinking block cursor in the same color as its
    # own cursor cell -- invisible. The pixel check right after this proves
    # it visually; this is the same fact at the value level.
    applied_theme = page.evaluate(
        "document.getElementById('frame').contentDocument.defaultView.term.options.theme")
    ok("applied theme's cursorAccent differs from cursor",
       applied_theme.get("cursorAccent") != applied_theme.get("cursor"), applied_theme)
    ok("applied theme's cursorAccent matches --bg-primary (the fix)",
       applied_theme.get("cursorAccent") == "#" + token_hex("bg-primary"), applied_theme)

    # Visual proof the fix actually makes the glyph legible: clear the
    # screen, print one character, move the cursor back onto it (ArrowLeft),
    # then screenshot just that cursor cell (geometry from window.term's own
    # cursorX/Y and the text canvas's rect, in real page coordinates) and
    # count distinct colors in it. A single uniform color means the
    # character and its cursor cell were painted the same color -- invisible
    # -- which is exactly the bug this theme fixes.
    page.keyboard.type("clear"); page.keyboard.press("Enter"); time.sleep(0.4)
    page.keyboard.type("X"); time.sleep(0.2)
    page.keyboard.press("ArrowLeft"); time.sleep(0.4)
    cell = page.evaluate("""() => {
        const frameEl = document.getElementById('frame');
        const frameRect = frameEl.getBoundingClientRect();
        const fd = frameEl.contentDocument;
        const term = fd.defaultView.term;
        const canvases = fd.querySelectorAll('.xterm-screen canvas');
        const canvas = canvases[canvases.length - 1];
        const canvasRect = canvas.getBoundingClientRect();
        const cellW = canvasRect.width / term.cols, cellH = canvasRect.height / term.rows;
        const cx = term.buffer.active.cursorX, cy = term.buffer.active.cursorY;
        return {
            x: frameRect.left + canvasRect.left + cx * cellW,
            y: frameRect.top + canvasRect.top + cy * cellH,
            width: cellW, height: cellH,
        };
    }""")
    cell_png = page.screenshot(clip=cell)
    n_colors = png_color_count(cell_png)
    ok("cursor cell renders more than one color (glyph visible on its cursor)",
       n_colors > 1, f"{n_colors} distinct color(s)")

    # typing reaches the shell
    page.keyboard.type("echo TYPED_OK"); page.keyboard.press("Enter"); time.sleep(0.8)
    ok("typing reaches tmux", "TYPED_OK" in pane(), pane()[-200:])

    # Ctrl+C with no selection => SIGINT
    page.keyboard.type("sleep 100"); page.keyboard.press("Enter"); time.sleep(0.8)
    ok("sleep started", cmd() == "sleep", cmd())
    page.keyboard.press("Control+c"); time.sleep(0.8)
    ok("Ctrl+C (no selection) interrupts", cmd() != "sleep", cmd())

    # Ctrl+V pastes
    page.evaluate("navigator.clipboard.writeText('echo PASTED_OK')")
    page.keyboard.press("Control+v"); time.sleep(0.5); page.keyboard.press("Enter"); time.sleep(0.8)
    ok("Ctrl+V pastes", "PASTED_OK" in pane(), pane()[-200:])

    # Ctrl+C with a selection => copy, no SIGINT
    page.keyboard.type("echo COPYME_12345"); page.keyboard.press("Enter"); time.sleep(0.5)
    page.keyboard.type("sleep 100"); page.keyboard.press("Enter"); time.sleep(0.8)
    page.evaluate("navigator.clipboard.writeText('')")
    box = page.locator("#frame").bounding_box()
    # select the whole line containing COPYME by dragging across a row: find the row from tmux
    rows = pane().split("\n")
    ri = max(i for i, r in enumerate(rows) if "COPYME_12345" in r and not r.strip().startswith("echo"))  # the output line
    cell_h = page.evaluate("(()=>{const d=document.getElementById('frame').contentDocument;const r=d.querySelector('.xterm-rows')||d.querySelector('.xterm-screen');return r.getBoundingClientRect().height})()") / len(rows)
    y = box["y"] + cell_h * ri + cell_h / 2
    page.mouse.move(box["x"] + 2, y); page.mouse.down(); page.mouse.move(box["x"] + 300, y, steps=8); page.mouse.up()
    time.sleep(0.3)
    page.keyboard.press("Control+c"); time.sleep(0.6)
    clip = page.evaluate("navigator.clipboard.readText()")
    ok("Ctrl+C with selection copies", "COPYME_12345" in clip, repr(clip))
    ok("...and does not interrupt", cmd() == "sleep", cmd())
    page.keyboard.press("Control+c"); time.sleep(0.5)   # now really interrupt (selection cleared? if not, second press)
    if cmd() == "sleep":
        page.mouse.click(box["x"] + 50, box["y"] + 50); page.keyboard.press("Control+c"); time.sleep(0.5)
    ok("sleep interrupted afterwards", cmd() != "sleep", cmd())

    # soft keys: force the row on, run cat -v, press keys
    page.click("#keysbtn"); time.sleep(0.3)
    ok("key row visible", page.locator("#keys").is_visible())
    page.keyboard.type("cat -v"); page.keyboard.press("Enter"); time.sleep(0.6)
    for sel in ["[data-k=Escape]", "[data-k=Tab]:not([data-shift])", "[data-k=Tab][data-shift]", "[data-k=ArrowUp]"]:
        page.locator("#keys " + sel).dispatch_event("pointerdown"); time.sleep(0.2)
    page.locator("#ctrl").dispatch_event("pointerdown"); time.sleep(0.2)
    page.keyboard.type("l"); time.sleep(0.4)
    page.keyboard.press("Enter"); time.sleep(0.6)
    out = pane()
    ok("soft Esc/Tab/ShiftTab/Up/Ctrl+l received", all(x in out for x in ["^[", "^[[Z", "^[[A", "^L"]), out[-300:])
    page.locator("#keys [data-k=c][data-ctrl]").dispatch_event("pointerdown"); time.sleep(0.6)
    ok("soft ^C ends cat", cmd() != "cat", cmd())
    page.screenshot(path="shots/desktop-keys.png")

    # switching tabs swaps the frame
    other = page.locator("#tabs .tab:not(.on)").first
    oname = other.inner_text(); other.click(); time.sleep(0.5)
    ok("tab switch changes frame src", oname in page.get_attribute("#frame", "src"), page.get_attribute("#frame", "src"))
    ok("url updated", page.url.endswith("/s/" + oname), page.url)
    page.click(f"#tabs .tab:text-is('{SESS}')"); time.sleep(0.5)

    # + popover validation error
    page.click("#add"); page.fill("#pop [name=name]", SESS); page.click("#pop .btn"); time.sleep(0.5)
    ok("duplicate name error shown inline", page.locator("#err").is_visible() and "already exists" in page.locator("#err").inner_text())
    page.keyboard.press("Escape")

    # popout page variant
    page.goto(f"{BASE}/s/{SESS}?popout=1"); time.sleep(1.5)
    ok("popout hides bar", not page.locator("#bar").is_visible())
    page.click("#handle"); time.sleep(0.2)
    ok("handle shows bar", page.locator("#bar").is_visible())
    page.screenshot(path="shots/popout.png")
    b.close()

    # ---------- custom TTYD_EXTRA_ARGS theme wins over the generated one
    # run.sh's third instance starts with TTYD_EXTRA_ARGS='-t
    # theme={\"background\":\"#123456\"}'. bin/serverjack-ttyd's own
    # --print-theme call must detect that (_ttyd_extra_args_has_theme(),
    # reading the same TTYD_EXTRA_ARGS this process sees) and print nothing,
    # so it never adds a second, conflicting -t theme=... of its own --
    # ttyd keeps the *last* -t theme=... it sees, so an extra one after the
    # user's would otherwise silently override it.
    THEME_BASE = os.environ.get("SERVERJACK_TEST_THEME_BASE", "")
    if THEME_BASE:
        b = p.chromium.launch()
        tctx = b.new_context(viewport={"width": 1100, "height": 700})
        tpage = tctx.new_page()
        tpage.goto(f"{THEME_BASE}/s/{SESS}")
        tpage.wait_for_selector("#tabs .tab.on")
        tfr = tpage.frame_locator("#frame")
        tfr.locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000)
        time.sleep(1.5)
        bg = tfr.locator(".xterm-viewport").evaluate("el => getComputedStyle(el).backgroundColor")
        ok("custom TTYD_EXTRA_ARGS theme: it, not the generated one, is what rendered",
           bg == "rgb(18, 52, 86)", bg)   # #123456
        b.close()
    else:
        print("  (skipped: custom TTYD_EXTRA_ARGS theme -- SERVERJACK_TEST_THEME_BASE not set)")

    # ---------- iPhone-ish (WebKit engine, touch, 390x844)
    b = p.webkit.launch()
    ctx = b.new_context(**p.devices["iPhone 14"])
    page = ctx.new_page()
    page.on("pageerror", lambda e: print("   [webkit pageerror]", e))
    page.goto(f"{BASE}/"); time.sleep(1)
    page.screenshot(path="shots/iphone-landing.png", full_page=True)
    page.goto(f"{BASE}/s/{SESS}")
    page.wait_for_selector("#tabs .tab.on"); time.sleep(2)
    print("iphone (webkit):")
    ok("key row auto-shown on touch device", page.locator("#keys").is_visible())
    fh = page.evaluate("document.getElementById('frame').getBoundingClientRect().height")
    ih = page.evaluate("innerHeight")
    ok("frame fills between bars", 0.7 * ih < fh < ih, f"frame {fh} inner {ih}")
    page.screenshot(path="shots/iphone-term.png")
    page.tap("#keys [data-k=Escape]"); time.sleep(0.3)
    b.close()

if fails:
    raise SystemExit(1)
