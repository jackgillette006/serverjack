"""Driver for docs/shots/make-gif.sh, run inside the Playwright container.

Records a video of the demo flow against the same isolated, neutral
serverjack instance make.sh uses for the three static screenshots (see
make-gif.sh, which sets it up identically): land on the phone-emulated
landing page, pick the "Claude Code" pill and the ~/projects/3d-lab
directory, tap Start, sit on the live terminal for a few seconds, tap back
to the session list.

The fake "Claude Code" tool in the scratch cfg just runs bash (same trick
make.sh and tests/run.sh use), so nothing real starts. To put something
visible on screen without racing ttyd's WebSocket with live keystrokes (see
shots.py's docstring -- typing through the browser under load once left a
capture showing a blank pane), this script hands the new session's name to
make-gif.sh over SHOTS_OUT/session_name.txt and waits for
SHOTS_OUT/typed_done: the host sends `ls` into that session directly over
tmux (guaranteed to be the same tmux binary/version as the server, unlike
one apt-installed inside this container) while the video is rolling.

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


def wait_for_file(path, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(path):
            return True
        time.sleep(0.1)
    return False


with sync_playwright() as p:
    b = p.webkit.launch()
    ctx = b.new_context(**p.devices["iPhone 14"], record_video_dir=OUT)
    page = ctx.new_page()

    # ------------------------------------------------------- landing page --
    page.goto(f"{BASE}/", wait_until="networkidle")
    page.wait_for_selector("h2:text-is('Sessions')")
    page.wait_for_timeout(4000)   # hold on the landing page a moment

    # ---------------------------------------------- pick Claude Code, 3d-lab
    page.click('.seg label:has(input[name=what][value="claude"])')
    page.wait_for_timeout(1000)
    page.select_option("#dir", label="~/projects/3d-lab")
    page.wait_for_timeout(1000)

    # --------------------------------------------------------------- start --
    page.click('form[action="/start"] button[type=submit]')
    page.wait_for_selector("#tabs .tab.on")
    m = re.search(r"/s/([^/?#]+)", page.url)
    name = m.group(1) if m else ""
    with open(NAME_FILE, "w") as f:
        f.write(name)
    print(f"started session {name!r}, waiting for make-gif.sh to type into it")

    term = page.frame_locator("#frame").locator(".xterm-helper-textarea")
    term.wait_for(state="attached", timeout=15000)
    page.wait_for_timeout(1500)

    if not wait_for_file(DONE_FILE, timeout=8.0):
        print("warning: never saw typed_done -- recording may lack the `ls` output")
    page.wait_for_timeout(4000)   # let `ls`'s output paint and hold on screen
    page.wait_for_timeout(3000)   # sit on the terminal a moment longer

    # ---------------------------------------------------------- back out --
    page.click('a.ib[title="All sessions"]')
    page.wait_for_selector("h2:text-is('Sessions')")
    page.wait_for_timeout(4000)   # hold on the list before the recording ends

    ctx.close()   # finalizes the .webm
    b.close()

print("recorded demo video")
