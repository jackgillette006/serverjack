"""Driver for docs/shots/make-gif.sh, run inside the Playwright container.

Records a video of the demo flow against the same isolated, neutral
serverjack instance make.sh uses for the README screenshots (see
make-gif.sh, which sets it up identically): land on the phone-emulated
landing page, pick the "OpenCode" pill, type the ~/projects/3d-lab path
into the directory combobox (character by character, so the live
suggestion list dropping in is visible too), tap Start, sit on the live
terminal while the real OpenCode TUI opens in that directory, tap back to
the session list.

OpenCode in the scratch cfg is the genuine binary (see fixture.sh -- it's
copied into the fake HOME, never a fake stand-in), so nothing needs typing
into the session after Start: the terminal just shows the real program
booting and rendering its own ready state on its own. That also sidesteps
what used to be the reason for feeding a scripted transcript over tmux here
(see shots.py's docstring -- typing through the browser under load once
raced ttyd's WebSocket and left a capture showing a blank pane): there's no
shell prompt in this pane to type a command at any more, real or fake, so
this script hands the new session's name to make-gif.sh over
SHOTS_OUT/session_name.txt (only so the host-side /tmp/ regression check
knows which tmux session to look at) and otherwise just waits.

A small tap-ring overlay is injected via add_init_script (persists across
the full-page navigations the Start form and the "All sessions" link both
do) so a viewer can follow every tap in the finished GIF -- it draws and
fades out a ring purely with CSS/JS, is never part of the app's own DOM, and
has no effect on serverjack itself.

Playwright writes the .webm to SHOTS_OUT when the context closes; make-gif.sh
converts it with ffmpeg.
"""
import os
import re

from playwright.sync_api import sync_playwright

BASE = os.environ["SHOTS_BASE"]
OUT = os.environ["SHOTS_OUT"]
NAME_FILE = os.path.join(OUT, "session_name.txt")

TAP_RING_SCRIPT = """
(() => {
  const install = () => {
    if (document.getElementById('sj-tap-style')) return;
    // The app's own --accent custom property (bin/serverjack's TOKENS
    // block), read live off the real page instead of a hex copied here by
    // hand. Read inside install(), which only runs after DOMContentLoaded
    // (or, on the rare page that's already past it, right away) -- by then
    // the app's own <style> block in <head> has been parsed and the
    // property is real; on the initial about:blank document there is no
    // such property and this falls back to the shipped color.
    const ACCENT = getComputedStyle(document.documentElement)
      .getPropertyValue('--accent').trim() || '#39ff88';
    const style = document.createElement('style');
    style.id = 'sj-tap-style';
    style.textContent = `
      .sj-tap-ring{position:fixed;left:0;top:0;width:44px;height:44px;
        margin:-22px 0 0 -22px;border-radius:50%;border:3px solid ${ACCENT};
        /* A dark edge on both sides of the green border, plus the green
           glow: without it, a tap on serverjack's own accent-green Start
           button (or any pill/control in its "on" state) draws a green
           ring on a same-green fill and it all but disappears. The dark
           edge keeps it visible there too, the glow keeps it visible on
           the app's normal near-black surfaces. */
        box-shadow:0 0 0 1.5px rgb(0 0 0 / .55),inset 0 0 0 1.5px rgb(0 0 0 / .55),
          0 0 14px 2px ${ACCENT};
        pointer-events:none;z-index:2147483647;
        opacity:.95;transform:scale(.35);
        transition:opacity 400ms ease-out,transform 400ms ease-out;}
      .sj-tap-ring.sj-fade{opacity:0;transform:scale(1.15)}
    `;
    document.documentElement.appendChild(style);
    const show = (x, y) => {
      if (typeof x !== 'number' || typeof y !== 'number') return;
      const ring = document.createElement('div');
      ring.className = 'sj-tap-ring';
      ring.style.left = x + 'px';
      ring.style.top = y + 'px';
      document.documentElement.appendChild(ring);
      requestAnimationFrame(() => requestAnimationFrame(() => ring.classList.add('sj-fade')));
      setTimeout(() => ring.remove(), 500);
    };
    document.addEventListener('pointerdown', (e) => show(e.clientX, e.clientY), true);
    document.addEventListener('click', (e) => show(e.clientX, e.clientY), true);
    window.__sjShowRing = show;
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
})();
"""


with sync_playwright() as p:
    b = p.webkit.launch()
    device = dict(p.devices["iPhone 14"])
    device["device_scale_factor"] = 2   # CSS px -> video px multiplier
    # record_video_size must be exactly the viewport in CSS px times the
    # scale factor above, or Playwright pads the recording out to it with a
    # flat grey band -- computed from the device dict itself (390x664 CSS at
    # the time of writing, not the 390x844 once hardcoded here, which is what
    # produced that band) so it can never drift out of sync with `device`
    # again. make-gif.sh re-checks this after conversion by sampling the
    # frame itself, in case a future Playwright device update changes the
    # viewport under us.
    vp = device["viewport"]
    video_size = {"width": vp["width"] * device["device_scale_factor"],
                  "height": vp["height"] * device["device_scale_factor"]}
    ctx = b.new_context(**device, record_video_dir=OUT, record_video_size=video_size)
    ctx.add_init_script(TAP_RING_SCRIPT)
    page = ctx.new_page()

    def tap(locator, hold_ms=180, pre_delay=0):
        """Click by hand (move, mouse down, hold, mouse up) instead of the
        atomic page.click(), and draw the tap ring with a direct call into
        the page instead of trusting the pointerdown listener to win the
        race. Both the Start form's submit and the "All sessions" link
        navigate the page the instant their click handler runs (FX is off,
        so serverjack's own powerOff() transition is skipped) -- a plain
        .click() (and, it turns out, even a synthetic pointerdown/mousedown
        from Playwright, still holding before mouse.up()) can have the DOM
        torn down by navigation before the video recorder ever flushes a
        frame with the ring on it: the ring's own lifetime isn't the
        problem, the abruptness of the page swap is. For those two taps,
        pre_delay holds on the *stable, pre-navigation* page after the ring
        is drawn but before any mouse event at all, so there's no question
        the recorder gets frames of it before the click that tears the page
        down even begins."""
        box = locator.bounding_box()
        if not box:
            locator.click()
            return
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.evaluate("([x, y]) => window.__sjShowRing && window.__sjShowRing(x, y)", [x, y])
        if pre_delay:
            page.wait_for_timeout(pre_delay)
        page.mouse.move(x, y)
        page.mouse.down()
        page.wait_for_timeout(hold_ms)
        page.mouse.up()

    # ------------------------------------------------------- landing page --
    page.goto(f"{BASE}/", wait_until="networkidle")
    page.wait_for_selector("h2:text-is('Sessions')")
    page.wait_for_timeout(1500)   # brief hold on the landing page

    # -------------------------------------------------- pick OpenCode, 3d-lab
    tap(page.locator('.seg label:has(input[name=what][value="opencode"])'))
    page.wait_for_timeout(800)

    # The directory field is the picker itself -- type the path in character
    # by character so a viewer can see it being chosen (the live suggestion
    # list drops in as they go), then close that list before moving on so
    # it isn't still open over the Start button in the next shot.
    path_input = page.locator('#startform input[name="dir"]')
    tap(path_input)
    path_input.press_sequentially("~/projects/3d-lab", delay=83)   # ~1.5s total
    page.wait_for_timeout(400)   # let the last debounced /api/dirs fetch land
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)

    # --------------------------------------------------------------- start --
    tap(page.locator('form[action="/start"] button[type=submit]'), pre_delay=200)
    page.wait_for_selector("#tabs .tab.on")
    m = re.search(r"/s/([^/?#]+)", page.url)
    name = m.group(1) if m else ""
    with open(NAME_FILE, "w") as f:
        f.write(name)
    print(f"started session {name!r}")

    term = page.frame_locator("#frame").locator(".xterm-helper-textarea")
    term.wait_for(state="attached", timeout=15000)
    # OpenCode is a real ~180 MB binary, not an instant fake shell -- wait for
    # its actual ready-state TUI text ("Ask anything...") instead of a fixed
    # sleep guessed from one cold-container timing. make-gif.sh starts this
    # fixture's ttyd with screenReaderMode=true (TTYD_EXTRA_ARGS), which
    # mirrors the terminal's text into a real DOM tree
    # (.xterm-accessibility-tree) purely for this wait -- xterm.js renders to
    # canvas by default and that text isn't otherwise in the DOM to wait on.
    # Generous timeout: a cold container with no page/fs cache warm has taken
    # ~4s after the textarea attached for the TUI to finish painting.
    page.frame_locator("#frame").locator(".xterm-accessibility-tree", has_text="Ask anything") \
        .wait_for(state="attached", timeout=30000)
    page.wait_for_timeout(3000)   # hold on the rendered terminal

    # ---------------------------------------------------------- back out --
    tap(page.locator('a.ib[title="All sessions"]'), pre_delay=250)
    sessions_h2 = page.locator("h2:text-is('Sessions')")
    sessions_h2.wait_for(state="visible")
    # The Sessions list sits below the Start-a-session and Shortcuts cards,
    # off the bottom of a phone viewport -- scroll it into view so the
    # recording actually shows the new opencode-3d-lab session card, not
    # just the top of the page again.
    sessions_h2.scroll_into_view_if_needed()
    page.wait_for_timeout(1500)   # hold on the list, showing opencode-3d-lab

    ctx.close()   # finalizes the .webm -- ends the recording right here
    b.close()

print("recorded demo video")
