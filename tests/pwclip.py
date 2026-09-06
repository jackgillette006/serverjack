import os, sys, time, subprocess
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:7699"; SESS = "pwtest"
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]
def pane(): return subprocess.run(T + ["capture-pane", "-p", "-t", SESS], capture_output=True, text=True).stdout
def cmd(): return subprocess.run(T + ["display", "-p", "-t", SESS, "#{pane_current_command}"], capture_output=True, text=True).stdout.strip()
def clear(): subprocess.run(T + ["send-keys", "-t", SESS, "C-c", ""]); time.sleep(0.2); subprocess.run(T + ["send-keys", "-t", SESS, "clear", "Enter"]); time.sleep(0.4)
def ok(label, cond, extra=""):
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + extra) if extra and not cond else ""))

with sync_playwright() as p:
    for bt in ("chromium", "firefox", "webkit"):
        print(bt + ":")
        clear()
        b = getattr(p, bt).launch()
        page = b.new_context(viewport={"width": 1000, "height": 600}).new_page()
        page.on("pageerror", lambda e: print("   [pageerror]", e))
        page.goto(f"{BASE}/s/{SESS}"); page.wait_for_selector("#tabs .tab.on")
        page.frame_locator("#frame").locator(".xterm-helper-textarea").wait_for(state="attached", timeout=15000); time.sleep(1.5)
        page.keyboard.type("echo COPYME_" + bt); page.keyboard.press("Enter"); time.sleep(0.5)
        page.keyboard.type("sleep 100"); page.keyboard.press("Enter"); time.sleep(0.8)
        ok("sleep started", cmd() == "sleep", cmd())
        box = page.locator("#frame").bounding_box()
        rows = pane().split("\n")
        ri = max(i for i, r in enumerate(rows) if ("COPYME_" + bt) in r and not r.strip().startswith("echo"))
        rh = page.evaluate("(()=>{const d=document.getElementById('frame').contentDocument;return d.querySelector('.xterm-screen').getBoundingClientRect().height})()") / len(rows)
        y = box["y"] + rh * ri + rh / 2
        page.mouse.move(box["x"] + 2, y); page.mouse.down(); page.mouse.move(box["x"] + 250, y, steps=8); page.mouse.up(); time.sleep(0.3)
        page.keyboard.press("Control+c"); time.sleep(0.6)
        ok("Ctrl+C with selection does not interrupt", cmd() == "sleep", cmd())
        page.mouse.click(box["x"] + 400, box["y"] + 300); time.sleep(0.2)     # clear selection
        page.keyboard.press("Control+c"); time.sleep(0.6)
        ok("Ctrl+C without selection interrupts", cmd() != "sleep", cmd())
        page.keyboard.type("echo PASTE:"); page.keyboard.press("Control+v"); time.sleep(0.5); page.keyboard.press("Enter"); time.sleep(0.8)
        out = pane()
        ok("Ctrl+V pastes what Ctrl+C copied", ("PASTE:COPYME_" + bt) in out, out[-160:])
        b.close()
