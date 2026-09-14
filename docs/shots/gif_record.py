"""Driver for docs/shots/make-gif.sh, run inside the Playwright container.

Records a video of the demo flow against the same isolated, neutral
serverjack instance make.sh uses for the three static screenshots (see
make-gif.sh, which sets it up identically): land on the phone-emulated
landing page, pick the "Claude Code" pill, type the ~/projects/3d-lab path
into the "...or type a path" input (the <select> picker doesn't render as a
native popup under emulation, so typing is the only part of the directory
picker that's actually visible on screen), tap Start, sit on the live
terminal for a few seconds, tap back to the session list.

The fake "Claude Code" tool in the scratch cfg still just execs a plain bash
shell under the hood (see make-gif.sh's tools.json and its fixture `claude`
wrapper on PATH) -- nothing real starts, and the terminal never fakes a
product UI. To put something visible on screen without racing ttyd's
WebSocket with live keystrokes (see shots.py's docstring -- typing through
the browser under load once left a capture showing a blank pane), this
script hands the new session's name to make-gif.sh over
SHOTS_OUT/session_name.txt the moment Start lands it on the terminal page,
and waits for SHOTS_OUT/typed_done: the host feeds that session a short,
honest, neutral transcript (`ls --color=always`, `git status`, then a live
`ls`) directly over tmux (guaranteed to be the same tmux binary/version as
the server, unlike one apt-installed inside this container) while the video
is rolling.

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
import time

from playwright.sync_api import sync_playwright

BASE = os.environ["SHOTS_BASE"]
OUT = os.environ["SHOTS_OUT"]
NAME_FILE = os.path.join(OUT, "session_name.txt")
DONE_FILE = os.path.join(OUT, "typed_done")

# The app's --accent token (bin/serverjack's TOKENS block) -- kept in sync by
# hand, not imported, since this runs in a container with no access to the
# repo beyond this one file.
ACCENT = "#39ff88"

TAP_RING_SCRIPT = """
(() => {
  const ACCENT = "__ACCENT__";
  const install = () => {
    if (document.getElementById('sj-tap-style')) return;
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
""".replace("__ACCENT__", ACCENT)


def wait_for_file(path, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(path):
            return True
        time.sleep(0.1)
    return False


with sync_playwright() as p:
    b = p.webkit.launch()
    device = dict(p.devices["iPhone 14"])
    device["device_scale_factor"] = 2   # 390x844 CSS -> 780x1688 video
    ctx = b.new_context(**device, record_video_dir=OUT,
                        record_video_size={"width": 780, "height": 1688})
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

    # ---------------------------------------------- pick Claude Code, 3d-lab
    tap(page.locator('.seg label:has(input[name=what][value="claude"])'))
    page.wait_for_timeout(800)

    # The <select> directory picker never renders as a native popup under
    # emulation, so it's invisible in a recording -- type the path into the
    # "...or type a path" input instead, character by character, so a viewer
    # can actually see the directory being chosen.
    path_input = page.locator('#startform input[name="dir_custom"]')
    tap(path_input)
    path_input.press_sequentially("~/projects/3d-lab", delay=83)   # ~1.5s total
    page.wait_for_timeout(200)

    # --------------------------------------------------------------- start --
    tap(page.locator('form[action="/start"] button[type=submit]'), pre_delay=200)
    page.wait_for_selector("#tabs .tab.on")
    m = re.search(r"/s/([^/?#]+)", page.url)
    name = m.group(1) if m else ""
    with open(NAME_FILE, "w") as f:
        f.write(name)
    print(f"started session {name!r}, waiting for make-gif.sh to feed it")

    term = page.frame_locator("#frame").locator(".xterm-helper-textarea")
    term.wait_for(state="attached", timeout=15000)
    page.wait_for_timeout(500)

    if not wait_for_file(DONE_FILE, timeout=4.0):
        print("warning: never saw typed_done -- recording may lack the fed transcript")
    page.wait_for_timeout(3500)   # hold on the terminal, content visible

    # ---------------------------------------------------------- back out --
    tap(page.locator('a.ib[title="All sessions"]'), pre_delay=250)
    sessions_h2 = page.locator("h2:text-is('Sessions')")
    sessions_h2.wait_for(state="visible")
    # The Sessions list sits below the Start-a-session and Shortcuts cards,
    # off the bottom of a phone viewport -- scroll it into view so the
    # recording actually shows the new claude-3d-lab session card, not just
    # the top of the page again.
    sessions_h2.scroll_into_view_if_needed()
    page.wait_for_timeout(1500)   # hold on the list, showing claude-3d-lab

    ctx.close()   # finalizes the .webm -- ends the recording right here
    b.close()

print("recorded demo video")
