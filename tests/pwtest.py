import os, sys, time, subprocess
from playwright.sync_api import sync_playwright

BASE = os.environ.get("SERVERJACK_TEST_BASE", "http://127.0.0.1:7690")
SESS = "pwtest"
fails = 0
def pane():
    return subprocess.run(["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default"), "capture-pane", "-p", "-t", SESS], capture_output=True, text=True).stdout
def cmd():
    return subprocess.run(["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default"), "display", "-p", "-t", SESS, "#{pane_current_command}"], capture_output=True, text=True).stdout.strip()
def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + extra) if extra and not cond else ""))
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
