"""Landing page: Run a command, shortcuts, and the agent cards.

Chromium desktop only -- the landing page has no engine-specific code, and the
things worth proving here are server-side (a command really ran in a real tmux
session, a shortcut was stored and removed, an agent card's buttons hit the
right route). run.sh points the app at shots/cfg with a single fake tool
(bin=true, login_check=true, run=bash, one action `hello`) and a second one
with nothing but a run command, so nothing here touches a real coding CLI.
"""
import json
import os
import re
import subprocess
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:7699"
TAG = str(int(time.time()))[-6:]
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]
MADE = []          # sessions this suite created, killed at the end


def pane(name, lines=200):
    return subprocess.run(T + ["capture-pane", "-p", "-J", "-t", f"={name}:", "-S", f"-{lines}"],
                          capture_output=True, text=True).stdout


def pcmd(name):
    return subprocess.run(T + ["display", "-p", "-t", f"={name}:", "#{pane_current_command}"],
                          capture_output=True, text=True).stdout.strip()


def exists(name):
    return subprocess.run(T + ["has-session", "-t", f"={name}"],
                          capture_output=True).returncode == 0


def wait_for(fn, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.25)
    return fn()


def ok(label, cond, extra=""):
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + extra) if extra and not cond else ""))
    return bool(cond)


def sess_from_url(page):
    """The session name a redirect to /s/<name> landed on."""
    m = re.search(r"/s/([^/?#]+)", page.url)
    return m.group(1) if m else ""


with sync_playwright() as p:
    print("chromium desktop:")
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1100, "height": 900},
                        permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page()
    page.on("pageerror", lambda e: print("   [pageerror]", e))
    page.on("dialog", lambda d: d.accept())          # confirm() on delete/kill
    page.goto(f"{BASE}/")

    # ---------------------------------------------------------- layout ----
    heads = page.eval_on_selector_all("main h2", "els => els.map(e => e.textContent.trim())")
    def at(t):
        return heads.index(t) if t in heads else -1
    ok("sections in order: Run a command < Sessions < Agents",
       -1 < at("Run a command") < at("Sessions") < at("Agents"), str(heads))
    ok("Run card has the paste box, dir picker and Run button",
       page.locator("#cmd").count() == 1 and page.locator("#dir").count() == 1
       and page.locator('form[action="/run"] button[type=submit]').count() == 1)
    page.screenshot(path="shots/landing.png", full_page=True)

    # ------------------------------------------- run + save a shortcut ----
    scname = f"landsc-{TAG}"
    page.fill("#cmd", f"echo LAND_{TAG}")
    page.click('form[action="/run"] details.inline summary')
    page.check("#save")
    page.fill('form[action="/run"] input[name=label]', scname)
    page.click('form[action="/run"] button[type=submit]')
    page.wait_for_selector("#tabs .tab.on")
    run_sess = sess_from_url(page)
    MADE.append(run_sess)
    ok("Run lands on the terminal page for a new session",
       bool(run_sess) and exists(run_sess), f"url={page.url}")
    out = wait_for(lambda: pane(run_sess) if "[exited with status" in pane(run_sess) else "")
    ok("the pasted command ran in that session", f"LAND_{TAG}" in out, out[-300:])
    ok("...and the login shell reports its exit status",
       "[exited with status 0]" in out, out[-300:])

    # ----------------------------------------------- shortcut lifecycle ----
    page.goto(f"{BASE}/")
    card = page.locator(f'.card.sess:has(.name:text-is("{scname}"))')
    ok("Save as a shortcut stored it", card.count() == 1)
    ok("shortcut card shows the command",
       f"LAND_{TAG}" in card.first.inner_text(), card.first.inner_text() if card.count() else "")
    card.first.locator('form[action="/shortcuts/del"] button').click()
    page.wait_for_load_state()
    ok("delete removes the shortcut",
       page.locator(f'.card.sess:has(.name:text-is("{scname}"))').count() == 0)

    # -------------------------------------------------- agent accordion ----
    tool = page.locator("#tool-fake")
    ok("fake agent row renders", tool.count() == 1)
    ok("every agent row is collapsed on load",
       page.locator("details.tool[open]").count() == 0,
       str(page.eval_on_selector_all("details.tool[open]", "e => e.map(x => x.id)")))
    ok("the summary reports the tool ready", "Ready" in tool.locator("summary .state").inner_text(),
       tool.locator("summary .state").inner_text() if tool.count() else "")
    # native exclusive accordion: <details name="agent">
    page.click("#tool-fake2 > summary")
    ok("opening a row opens it", page.locator("#tool-fake2[open]").count() == 1)
    page.click("#tool-fake > summary")
    ok("...and opening another closes the first",
       page.locator("#tool-fake[open]").count() == 1
       and page.locator("#tool-fake2[open]").count() == 0,
       str(page.eval_on_selector_all("details.tool[open]", "e => e.map(x => x.id)")))
    page.screenshot(path="shots/landing-agent.png", full_page=True)
    open_btn = tool.locator('button[value="/tools/open"]')
    ok("open row offers Open", open_btn.count() == 1)
    ok("the open row lists Open, the action and Log in / switch account",
       [x.strip() for x in page.eval_on_selector_all(
           "#tool-fake .orow", "e => e.map(x => x.innerText.split('\\n')[0])")]
       == ["Open", "hello", "Log in / switch account"],
       str(page.eval_on_selector_all("#tool-fake .orow", "e => e.map(x => x.innerText)")))

    # phone width: an open row must not push the page sideways
    nctx = b.new_context(viewport={"width": 375, "height": 780}, is_mobile=True,
                         has_touch=True, device_scale_factor=2)
    np = nctx.new_page()
    np.goto(f"{BASE}/")
    np.click("#tool-fake > summary")
    np.screenshot(path="shots/landing-agent-375.png", full_page=True)
    ok("no horizontal overflow at 375px with a row open",
       np.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
       str(np.evaluate("[document.documentElement.scrollWidth, innerWidth]")))
    nctx.close()

    open_btn.first.click()
    page.wait_for_selector("#tabs .tab.on")
    fake_sess = sess_from_url(page)
    MADE.append(fake_sess)
    ok("Open starts a session for the tool",
       re.fullmatch(r"fake(-\d+)?", fake_sess or "") and exists(fake_sess), f"url={page.url}")
    ok("...running the tool's command", wait_for(lambda: pcmd(fake_sess) == "bash"), pcmd(fake_sess))
    out = wait_for(lambda: pane(fake_sess) if re.search(r"[$#]\s*$", pane(fake_sess).rstrip("\n")) else "")
    ok("...and the pane sits at a shell prompt",
       bool(re.search(r"[$#]\s*$", out.rstrip("\n"))), repr(out[-120:]))

    # the row's extra action button is a second submit on the same form
    page.goto(f"{BASE}/")
    page.click("#tool-fake > summary")
    act = page.locator('#tool-fake .orow:has(.olabel:text-is("hello")) '
                       'button[value="/tools/action:0"]')
    ok("action option row present", act.count() == 1,
       page.locator("#tool-fake .opts").inner_text())
    act.first.click()
    page.wait_for_selector("#tabs .tab.on")
    act_sess = sess_from_url(page)
    MADE.append(act_sess)
    out = wait_for(lambda: pane(act_sess) if "ACTION_RAN" in pane(act_sess) else "")
    ok("action runs its command in a session", "ACTION_RAN" in out, out[-300:])

    # ------------------------------------------------------ /api/tools ----
    r = page.request.get(f"{BASE}/api/tools")
    js = r.json()
    st = next((x for x in js if x["id"] == "fake"), None)
    ok("/api/tools reports the fake tool", st is not None, json.dumps(js))
    if st:
        ok("...installed", st["installed"] is True, json.dumps(st))
        ok("...logged in", st["logged_in"] is True, json.dumps(st))

    # ------------------------------------------------------- clean up ----
    page.goto(f"{BASE}/")
    for name in [n for n in MADE if n and exists(n)]:
        sel = f'.sess:has(a.open[data-name="{name}"])'
        page.click(f"{sel} details.menu summary")
        page.click(f'{sel} form[action="/kill"] button')
        page.wait_for_load_state()
    ok("kill menu removes the sessions it made",
       not any(exists(n) for n in MADE if n), str([n for n in MADE if n and exists(n)]))

    # --------------------------------------------------- cross-site POST --
    r = page.request.post(f"{BASE}/run", headers={"Sec-Fetch-Site": "cross-site"},
                          form={"cmd": f"echo XSITE_{TAG}"})
    ok("cross-site POST /run is refused", r.status == 403, str(r.status))
    ok("...and nothing was started", not exists("echo"), "session 'echo' exists")
    b.close()

# belt and braces: run.sh's cleanup also sweeps these names
for name in MADE:
    if name and exists(name):
        subprocess.run(T + ["kill-session", "-t", f"={name}"], capture_output=True)
