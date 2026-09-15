"""Driver for docs/shots/make.sh, run inside the Playwright container.

Takes the README screenshots and logo closeups against an isolated, neutral serverjack
instance (see make.sh for how it's set up): the landing page on a desktop
viewport, the landing page on an emulated iPhone, and one open terminal
session on an emulated iPhone. Nothing here asserts anything -- make.sh
already knows the instance came up (it polls /healthz) -- this file only
frames and captures.
"""
import os

from playwright.sync_api import sync_playwright

BASE = os.environ["SHOTS_BASE"]
OUT = os.environ["SHOTS_OUT"]

with sync_playwright() as p:
    # ---------------------------------------------------------- desktop ----
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1100, "height": 900})
    page = ctx.new_page()
    page.goto(f"{BASE}/", wait_until="networkidle")
    page.wait_for_selector("h2:text('Sessions')")
    # Pick the OpenCode pill so the Start card's hint reads "Runs opencode"
    # here too, same as the demo GIF (see gif_record.py) -- the README still
    # and the GIF should show the exact same Start card, not the bare
    # Shell-selected default.
    page.click('.seg label:has(input[name=what][value="opencode"])')
    page.wait_for_selector("#toolhint:has-text('Runs')")
    page.wait_for_timeout(400)          # let layout settle before capture
    page.screenshot(path=os.path.join(OUT, "desktop.png"), full_page=True)

    # A close view of the real header and served app icon for the branding PR.
    # The URL comes off the page itself -- ICON_REV is a content hash now, not
    # a literal "?v=prompt-jack" -- so this never drifts from what's served.
    page.locator("h1").screenshot(path=os.path.join(OUT, "prompt-jack-header.png"))
    icon_href = page.locator('link[rel=icon]').get_attribute("href")
    page.goto(f"{BASE}{icon_href}", wait_until="networkidle")
    page.set_viewport_size({"width": 256, "height": 256})
    page.screenshot(path=os.path.join(OUT, "prompt-jack-icon.png"))
    b.close()
    print("captured desktop.png")

    # ------------------------------------------------------ iphone landing --
    b = p.webkit.launch()
    ctx = b.new_context(**p.devices["iPhone 14"])
    page = ctx.new_page()
    page.goto(f"{BASE}/", wait_until="networkidle")
    page.wait_for_selector("h2:text('Sessions')")
    page.wait_for_timeout(400)
    page.screenshot(path=os.path.join(OUT, "iphone-landing.png"), full_page=True)
    ctx.close()
    b.close()
    print("captured iphone-landing.png")

    # -------------------------------------------------------- iphone term --
    b = p.webkit.launch()
    ctx = b.new_context(**p.devices["iPhone 14"])
    page = ctx.new_page()
    # make.sh already fed the "game" session its ls / git log transcript
    # directly over tmux (send-keys), so the pane has fixed, settled content
    # before we ever connect -- no live typing here, and so nothing to race
    # against ttyd's WebSocket (that used to occasionally desync the on-
    # screen xterm from the real pane under load, e.g. a concurrent
    # tests/run.sh).
    page.goto(f"{BASE}/s/game", wait_until="networkidle")
    page.wait_for_selector("#tabs .tab.on")
    term = page.frame_locator("#frame").locator(".xterm-helper-textarea")
    term.wait_for(state="attached", timeout=15000)

    # Confirm the terminal actually painted the transcript (not just that the
    # frame attached) before trusting a screenshot of it: read the rendered
    # rows back through the DOM screen-view (#copy), which is real xterm
    # content, not the server-side pane.
    for attempt in range(6):
        page.wait_for_timeout(500)
        page.click("#copy")
        page.wait_for_selector("#screen", state="visible", timeout=5000)
        rendered = page.locator("#screen-text").inner_text()
        page.click("#screen-close")
        page.wait_for_selector("#screen", state="hidden", timeout=5000)
        if "git log" in rendered and "Initial commit" in rendered:
            break
    else:
        raise RuntimeError(f"terminal never rendered the transcript: {rendered!r}")

    # Undo the verification's own side effects before the shot: opening the
    # screen-view scrolled the soft-key row to the Copy button (and left it
    # holding focus's outline), not the Esc/Tab/Ctrl start it should show.
    page.evaluate("document.getElementById('keys').scrollLeft = 0")
    term.click()

    if not page.locator("#keys").is_visible():
        page.click("#keysbtn")
        page.wait_for_timeout(200)

    page.wait_for_timeout(300)
    page.screenshot(path=os.path.join(OUT, "iphone-term.png"), full_page=True)
    ctx.close()
    b.close()
    print("captured iphone-term.png")
