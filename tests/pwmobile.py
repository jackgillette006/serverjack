"""Paste / Copy / soft-key checks: Chromium desktop, then WebKit iPhone."""
import os, sys, time, subprocess
from playwright.sync_api import sync_playwright
BASE = os.environ.get("SERVERJACK_TEST_BASE", "http://127.0.0.1:7690"); SESS = "pwtest"
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]
fails = 0
def pane(): return subprocess.run(T + ["capture-pane", "-p", "-t", SESS], capture_output=True, text=True).stdout
def clear(): subprocess.run(T + ["send-keys", "-t", SESS, "C-c", ""]); time.sleep(0.2); subprocess.run(T + ["send-keys", "-t", SESS, "clear", "Enter"]); time.sleep(0.4)
def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + extra) if extra and not cond else ""))

def suite(page, tag, can_read_clipboard):
    page.goto(f"{BASE}/s/{SESS}"); page.wait_for_selector("#tabs .tab.on")
    page.frame_locator("#frame").locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000); time.sleep(1.5)
    if not page.locator("#keys").is_visible():
        page.click("#keysbtn"); time.sleep(0.3)
    ok("key row visible", page.locator("#keys").is_visible())
    # type straight into the terminal (frame textarea has focus)
    page.keyboard.type(f"echo TYPED_{tag}"); page.keyboard.press("Enter"); time.sleep(1.0)
    out = pane()
    ok("typed command ran", out.count(f"TYPED_{tag}") >= 2, out[-200:])
    # Paste button
    if can_read_clipboard:
        page.evaluate(f"navigator.clipboard.writeText('echo PASTEBTN_{tag}')")
        page.click("#paste"); time.sleep(0.6)
        page.keyboard.press("Enter"); time.sleep(0.8)
        out = pane(); ok("Paste button pastes clipboard", f"PASTEBTN_{tag}" in out, out[-200:])
    # Copy view
    page.click("#copy"); time.sleep(0.8)
    ok("screen view opens with pane text", page.locator("#screen").is_visible() and f"TYPED_{tag}" in page.locator("#screen-text").inner_text())
    ok("screen text is natively selectable", page.evaluate("(s=>s.userSelect||s.webkitUserSelect)(getComputedStyle(document.getElementById('screen-text')))") in ("text", "auto"))
    page.click("#screen-close"); time.sleep(0.2)
    ok("screen view closes", not page.locator("#screen").is_visible())

with sync_playwright() as p:
    print("chromium desktop:")
    clear()
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1000, "height": 700}, permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page(); page.on("pageerror", lambda e: print("   [pageerror]", e))
    suite(page, "desk", True)
    page.screenshot(path="shots/desktop-paste.png")
    b.close()

    print("webkit iphone:")
    clear()
    b = p.webkit.launch()
    page = b.new_context(**p.devices["iPhone 14"]).new_page(); page.on("pageerror", lambda e: print("   [pageerror]", e))
    suite(page, "ios", False)
    # touch overlay: xterm's textarea should now cover the terminal
    fb = page.locator("#frame").bounding_box()
    tb = page.frame_locator("#frame").locator(".xterm-helper-textarea").bounding_box()
    ok("textarea stretched over terminal (native long-press paste target)", tb and tb["width"] > fb["width"] * 0.9 and tb["height"] > fb["height"] * 0.8, str(tb))
    page.screenshot(path="shots/iphone-paste.png")
    b.close()

if fails:
    raise SystemExit(1)
