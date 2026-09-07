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
AUTH = "http://127.0.0.1:7698"          # the SERVERJACK_ALLOW instance
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
    sysline = page.locator(".sysline").inner_text() if page.locator(".sysline").count() else ""
    ok("a system line renders under the tagline",
       "load" in sysline and "up " in sysline, repr(sysline))
    ok("...with memory and free disk too",
       "mem " in sysline and "free" in sysline, repr(sysline))
    # The one built-in shortcut. run.sh runs bin/serverjack out of the checkout,
    # so REPO/.git is there; never actually clicked (it would restart the unit).
    upd = page.locator("#sc-update")
    ok("built-in Update serverjack row is offered", upd.count() == 1)
    if upd.count():
        ok("...marked built-in, with no delete button",
           "built-in" in upd.inner_text().lower() and upd.locator('form[action="/shortcuts/del"]').count() == 0,
           upd.inner_text())
        ok("...showing the command and what it does",
           "git pull --ff-only" in upd.inner_text() and "reconnects" in upd.inner_text(),
           upd.inner_text())
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

    # ------------------------------------------------------------ rename ----
    newname = f"landren-{TAG}"
    page.goto(f"{BASE}/")
    sel = f'.sess:has(a.open[data-name="{run_sess}"])'
    page.click(f"{sel} details.menu summary")
    page.click(f"{sel} details.ren summary")
    page.fill(f'{sel} form[action="/rename"] input[name=new]', newname)
    page.click(f'{sel} form[action="/rename"] button[type=submit]')
    page.wait_for_load_state()
    ok("Rename in the menu renames the tmux session",
       exists(newname) and not exists(run_sess), f"{run_sess} -> {newname}")
    ok("...and the list shows the new name",
       page.locator(f'.sess:has(a.open[data-name="{newname}"])').count() == 1)
    # a duplicate is refused, and nothing is renamed
    sel = f'.sess:has(a.open[data-name="{newname}"])'
    page.click(f"{sel} details.menu summary")
    page.click(f"{sel} details.ren summary")
    page.fill(f'{sel} form[action="/rename"] input[name=new]', "pwtest")
    page.click(f'{sel} form[action="/rename"] button[type=submit]')
    page.wait_for_load_state()
    errtext = page.locator(".err").first.inner_text() if page.locator(".err").count() else ""
    ok("renaming onto an existing name is refused",
       "already exists" in errtext and exists(newname), errtext or "no error shown")
    # and a name tmux can't have
    r = page.request.post(f"{BASE}/api/rename", form={"name": newname, "new": "bad.name"})
    ok("/api/rename refuses a name with a dot",
       r.status == 400 and "contain" in r.json().get("error", ""), r.text())
    # put it back, so the cleanup at the end finds it
    page.goto(f"{BASE}/")
    sel = f'.sess:has(a.open[data-name="{newname}"])'
    page.click(f"{sel} details.menu summary")
    page.click(f"{sel} details.ren summary")
    page.fill(f'{sel} form[action="/rename"] input[name=new]', run_sess)
    page.click(f'{sel} form[action="/rename"] button[type=submit]')
    page.wait_for_load_state()
    ok("renaming back restores the old name", exists(run_sess) and not exists(newname))

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

    # ------------------------------------------------------ /api/status ----
    r = page.request.get(f"{BASE}/api/status")
    js = r.json()
    ok("/api/status answers", r.status == 200, str(r.status))
    ok("...with session counts",
       isinstance(js.get("sessions"), int) and isinstance(js.get("attached"), int),
       json.dumps(js)[:300])
    ok("...machine stats (load, mem, disk, uptime)",
       all(k in js for k in ("load", "mem_used_pct", "disk_free_gb", "uptime_s")),
       str(sorted(js)))
    ok("...a version", bool(js.get("version")), str(js.get("version")))
    ok("...and one entry per agent with its state",
       isinstance(js.get("agents"), list) and js["agents"]
       and all(set(("id", "label", "installed", "daemon_running", "servers")) <= set(a)
               for a in js["agents"]),
       json.dumps(js.get("agents"))[:300])
    # No session name may appear as a value anywhere in the payload. Compared
    # against the parsed values, not the raw text: agent ids are in there on
    # purpose ("fake" is both a tool and a session here), and a substring match
    # would trip over ordinary words like "servers" too.
    def strings(v):
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            for x in v.values():
                yield from strings(x)
        elif isinstance(v, list):
            for x in v:
                yield from strings(x)
    values = set(strings(js))
    agentwords = {w for a in js.get("agents", []) for w in (a["id"], a["label"])}
    live = [n for n in subprocess.run(T + ["list-sessions", "-F", "#{session_name}"],
                                      capture_output=True, text=True).stdout.split()
            if n not in agentwords]
    ok("/api/status names no sessions",
       bool(live) and not (values & set(live)), f"{sorted(values & set(live))} of {live}")
    # It is exempt from SERVERJACK_ALLOW on purpose: a dashboard tile carries
    # no tailnet identity, and the page itself stays 403.
    sr = page.request.get(f"{AUTH}/api/status")
    pr = page.request.get(f"{AUTH}/")
    ok("/api/status is reachable on the ALLOW instance with no identity header",
       sr.status == 200, str(sr.status))
    ok("...while the page itself is still 403", pr.status == 403, str(pr.status))

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
