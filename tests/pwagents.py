"""Agent servers: starting, finding, stopping and auto-starting them from the
agent cards, plus the cards' own layout.

Unlike the other suites this one starts its own serverjack instances (no
ttyd: nothing here needs a terminal to draw), inside the browser container,
each with its own HOME, config dir and runtime dir, all on one private tmux
server. The fixture tools are fakes whose "servers" are `sleep 3600`:

  srv   a per-directory server (Claude's model) plus an action without a
        directory, so the card has both a picker and an unrelated button
  solo  a single server (OpenCode's model)
  pair  a daemon and a "Pair with phone" action -- nothing reads a directory
  slow  not logged in; its login takes 3 s and its login_check is a file test

and two more instances: one for autostart against an already running
server, one with no installed agent at all.

Every check here goes through the page's own forms where a user would, and
reads the truth back from tmux, not from the page.
"""
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
SJ_BIN = os.environ.get("SERVERJACK_BIN") or next(
    p for p in ("/repo-bin/serverjack", os.path.join(HERE, "..", "bin", "serverjack"))
    if os.path.exists(p))
ROOT = tempfile.mkdtemp(prefix="sj-pwagents-")
TMUX_DIR = os.path.join(ROOT, "tmux")
os.makedirs(TMUX_DIR, mode=0o700)
T = ["tmux", "-S", os.path.join(TMUX_DIR, f"tmux-{os.getuid()}", "default")]
PROCS = []
fails = 0


def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + str(extra)) if extra and not cond else ""))
    return bool(cond)


def wait_for(fn, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    return fn()


def tm(*args):
    return subprocess.run(T + list(args), capture_output=True, text=True).stdout.strip()


def exists(name):
    return subprocess.run(T + ["has-session", "-t", f"={name}"], capture_output=True).returncode == 0


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_instance(tag, tools, ids, autostart=None, delay="3600"):
    """One serverjack, its own HOME/config/runtime dir, the shared tmux."""
    home = os.path.join(ROOT, tag, "home")
    cfg = os.path.join(ROOT, tag, "cfg")
    rt = os.path.join(ROOT, tag, "rt")
    for d in ("projects/web-app", "projects/3d-lab", "projects/ai/3d-lab", "projects/remote-tools",
              "projects/synth-ios", "projects/enter-chromium", "projects/enter-firefox",
              "projects/enter-webkit",
              "projects/a-really-long-project-directory-name/with-a-nested-child-folder"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    os.makedirs(cfg, mode=0o700)
    os.makedirs(rt, mode=0o700)
    with open(os.path.join(cfg, "tools.json"), "w") as f:
        json.dump(tools(home), f)
    if autostart:
        with open(os.path.join(cfg, "autostart.json"), "w") as f:
            json.dump(autostart(home), f)
        os.chmod(os.path.join(cfg, "autostart.json"), 0o600)
    port = free_port()
    env = {k: v for k, v in os.environ.items() if k != "TMUX" and not k.startswith("SERVERJACK_")}
    env.update(HOME=home, SERVERJACK_LISTEN="tcp", SERVERJACK_PORT=str(port),
               SERVERJACK_CONFIG=cfg, XDG_RUNTIME_DIR=rt, TMUX_TMPDIR=TMUX_DIR,
               SERVERJACK_TOOLS=ids, SERVERJACK_TITLE="agents", SERVERJACK_TERM_THEME="",
               TTYD_EXTRA_ARGS="", SERVERJACK_AUTOSTART_DELAY=delay)
    log = open(os.path.join(ROOT, tag, "web.log"), "w")
    PROCS.append(subprocess.Popen([sys.executable, SJ_BIN], env=env, stdout=log,
                                  stderr=subprocess.STDOUT))
    base = f"http://127.0.0.1:{port}"
    up = wait_for(lambda: _healthy(base), 15)
    if not up:
        print(open(os.path.join(ROOT, tag, "web.log")).read()[-2000:])
        raise SystemExit(f"serverjack instance {tag} did not come up")
    return base, home, cfg, os.path.join(ROOT, tag, "web.log")


def _healthy(base):
    try:
        with urllib.request.urlopen(base + "/healthz", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def main_tools(home):
    return [
        {"id": "srv", "label": "Srv agent", "bin": "true", "login": "echo LOGIN",
         "login_check": "true", "run": "bash",
         "actions": [{"label": "hello", "cmd": "echo ACTION_RAN", "note": "Says hello."}],
         "server": {"label": "Remote Control server", "cmd": "sleep 3600", "session": "srv-remote",
                    "per_dir": True, "note": "A fake per-directory server."}},
        {"id": "solo", "label": "Solo agent", "bin": "true", "login_check": "true", "run": "bash",
         "server": {"label": "Solo server", "cmd": "sleep 3600", "session": "solo-serve",
                    "note": "A fake single server."}},
        {"id": "pair", "label": "Pair agent", "bin": "true", "login_check": "true", "run": "bash",
         "daemon": {"label": "Fake daemon", "start": "true", "stop": "true",
                    "pidfile": os.path.join(home, "nope.pid"), "note": "Pair once with the code above."},
         "actions": [{"label": "Pair with phone", "cmd": "echo PAIR_RAN"}]},
        {"id": "slow", "label": "Slow login", "bin": "true", "run": "bash",
         "actions": [{"label": "noop", "cmd": "true"}],      # keeps its card once ready
         "login": "sleep 3; touch " + os.path.join(home, "slow-flag"),
         "login_check": "test -f " + os.path.join(home, "slow-flag")},
    ]


def card(page, tid):
    page.goto(BASE + "/")
    if page.locator(f"#tool-{tid}[open]").count() == 0:
        page.click(f"#tool-{tid} > summary")
    return page.locator(f"#tool-{tid}")


def start_from_card(page, tid, d):
    card(page, tid)
    page.fill(f"#dp-{tid}", d)
    with page.expect_navigation():
        page.click(f'#tool-{tid} button[form="d-{tid}"][value="/tools/server"]')


def summary_text(page, tid):
    page.goto(BASE + "/")
    return page.locator(f"#tool-{tid} summary .state").inner_text()


def autostart_entries(cfg):
    try:
        with open(os.path.join(cfg, "autostart.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


GONE_PARENT = "/proc/sj-pwagents-gone/proj"      # a directory that cannot be created
BASE, HOME, CFG, LOG = start_instance(
    "main", main_tools, "srv,solo,pair,slow",
    autostart=lambda home: [{"tool": "srv", "kind": "server",
                             "dir": os.path.join(home, "projects/synth-ios")},
                            {"tool": "srv", "kind": "server",
                             "dir": os.path.join(home, "projects/deleted-proj")},
                            {"tool": "srv", "kind": "server", "dir": GONE_PARENT}])
SAME = {"Sec-Fetch-Site": "same-origin"}

try:
    with sync_playwright() as p:
        print("chromium desktop:")
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("pageerror", lambda e: print("   [pageerror]", e))
        dialogs = []

        def on_dialog(d):
            dialogs.append(d.message)
            d.accept()
        page.on("dialog", on_dialog)

        # ------------------------------------------ F01: start from the card
        start_from_card(page, "srv", "~/projects/web-app")
        ok("Start on the card lands on the new server's session",
           page.url.endswith("/s/srv-remote-web-app"), page.url)
        ok("...and the pane reports the server's own command, not the bash wrapper",
           wait_for(lambda: tm("display", "-p", "-t", "=srv-remote-web-app:",
                               "#{pane_current_command}") == "sleep"),
           tm("display", "-p", "-t", "=srv-remote-web-app:", "#{pane_current_command}"))
        st = summary_text(page, "srv")
        ok("back on the list, the summary reads running", "1 running" in st and "exited" not in st, st)
        card(page, "srv")
        row = page.locator('#tool-srv .orow:has(code:text-is("~/projects/web-app"))')
        ok("...the instance row offers Stop and says it is running",
           row.locator('button:text-is("Stop")').count() == 1
           and "Running for this directory." in row.inner_text(), row.inner_text())
        before = tm("display", "-p", "-t", "=srv-remote-web-app:", "#{session_created} #{pane_pid}")
        start_from_card(page, "srv", "~/projects/web-app")
        err = page.locator(".err").inner_text() if page.locator(".err").count() else ""
        ok("a second Start for the same directory says it is already running",
           "already running" in err and "/s/" not in page.url, f"{page.url} {err!r}")
        ok("...and the server was not replaced (same created time and pid)",
           tm("display", "-p", "-t", "=srv-remote-web-app:", "#{session_created} #{pane_pid}") == before,
           before)
        js = page.request.get(BASE + "/api/status").json()
        srv = next(a for a in js["agents"] if a["id"] == "srv")
        ok("/api/status counts it as running", srv["servers_running"] == 1, json.dumps(srv))

        # A window opened beside the server (prefix+c, the window tabs) is a
        # plain shell, and it becomes the session's active pane.
        wid = tm("new-window", "-P", "-F", "#{window_id}", "-t", "=srv-remote-web-app:", "exec bash")
        wait_for(lambda: tm("display", "-p", "-t", "=srv-remote-web-app:",
                            "#{pane_current_command}") == "bash")
        page.wait_for_timeout(300)
        st = summary_text(page, "srv")
        ok("a second window in the server's session leaves it reading running",
           "1 running" in st and "exited" not in st, st)
        before = tm("display", "-p", "-t", "=srv-remote-web-app:", "#{session_created} #{session_windows}")
        start_from_card(page, "srv", "~/projects/web-app")
        err = page.locator(".err").inner_text() if page.locator(".err").count() else ""
        ok("...and Start still says already running, leaving both windows",
           "already running" in err
           and tm("display", "-p", "-t", "=srv-remote-web-app:",
                  "#{session_created} #{session_windows}") == before, f"{before} {err!r}")
        tm("kill-window", "-t", wid)

        # --------------------------- F17: identity by mark, not by name ----
        start_from_card(page, "srv", "~/projects/3d-lab")
        start_from_card(page, "srv", "~/projects/ai/3d-lab")
        ok("two directories with the same basename get a server each",
           exists("srv-remote-3d-lab") and exists("srv-remote-3d-lab-2")
           and page.url.endswith("/s/srv-remote-3d-lab-2"), page.url)
        card(page, "srv")
        codes = page.eval_on_selector_all("#tool-srv .orow code", "e => e.map(x => x.textContent)")
        ok("...and the card lists both directories",
           "~/projects/3d-lab" in codes and "~/projects/ai/3d-lab" in codes, codes)

        r = page.request.post(BASE + "/start", headers=SAME,
                              form={"what": "srv", "dir": "~/projects/remote-tools"})
        ok("an interactive session gets a name inside the server's prefix",
           exists("srv-remote-tools"), r.url)
        card(page, "srv")
        ok("...but the card does not take it for a server",
           page.locator('#tool-srv code:text-is("~/projects/remote-tools")').count() == 0,
           page.locator("#tool-srv .opts").inner_text())
        page.request.post(BASE + "/tools/server", headers=SAME,
                          form={"id": "srv", "action": "stop", "session": "srv-remote-tools"})
        ok("...and a Stop aimed at it does not kill it", exists("srv-remote-tools"))
        names = page.eval_on_selector_all(".card.sess:has(.name .pill:text-is('server')) .name",
                                          "e => e.map(x => x.textContent)")
        ok("the Sessions list tags the servers, and only them",
           any("srv-remote-web-app" in n for n in names)
           and not any("srv-remote-tools" in n for n in names), names)

        start_from_card(page, "solo", "~/projects/web-app")
        ok("the single server starts", exists("solo-serve"), page.url)
        r = page.request.post(BASE + "/api/rename", headers=SAME,
                              form={"name": "solo-serve", "new": "renamed-solo"})
        st = summary_text(page, "solo")
        ok("after a rename the card still finds it running", "running" in st, st)
        card(page, "solo")
        ok("...with Stop and Open, and no Start to press twice",
           page.locator('#tool-solo button:text-is("Stop")').count() == 1
           and page.locator("#dp-solo").count() == 0)
        r = page.request.post(BASE + "/tools", headers=SAME,
                              form={"id": "solo", "do": "/tools/server", "dir": "~/projects/3d-lab"})
        ok("...a Start from a stale page says it is already running, and starts nothing",
           r.status == 400 and "already running" in r.text() and not exists("solo-serve"),
           f"{r.status} {exists('solo-serve')}")
        card(page, "solo")
        with page.expect_navigation():
            page.click('#tool-solo button:text-is("Stop")')
        ok("...and Stop stops the renamed session", wait_for(lambda: not exists("renamed-solo"), 5))

        # The same, in place: the list's Rename and Kill don't reload the
        # page, so the agent card that names the server's session is redrawn
        # with it. Its Stop used to post the old name: it killed nothing,
        # dropped the boot entry anyway and said "stopped".
        start_from_card(page, "solo", "~/projects/web-app")
        card(page, "solo")
        with page.expect_navigation():
            page.locator("#tool-solo input.autostart").click()
        page.goto(BASE + "/")
        page.click("#tool-solo > summary")
        sel = '.sess:has(a.open[data-name="solo-serve"])'
        page.click(f"{sel} details.menu > summary")
        page.click(f"{sel} details.ren summary")
        page.fill(f'{sel} form[action="/rename"] input[name=new]', "solo-inplace")
        page.click(f'{sel} form[action="/rename"] button[type=submit]')
        stop_name = '#tool-solo form[action="/tools/server"] input[name=session]'
        ok("a Rename in place redraws the server's card, still open, with the new name",
           wait_for(lambda: page.locator(stop_name).count() == 1
                    and page.locator(stop_name).get_attribute("value") == "solo-inplace", 5)
           and page.locator("#tool-solo[open]").count() == 1,
           page.eval_on_selector_all(stop_name, "e => e.map(x => x.value)"))
        with page.expect_navigation():
            page.click('#tool-solo button:text-is("Stop")')
        note = page.locator("#note").inner_text() if page.locator("#note").count() else ""
        ok("...so its Stop, with no reload, stops that session, drops its boot entry and says so",
           wait_for(lambda: not exists("solo-inplace"), 5)
           and not [e for e in autostart_entries(CFG) if e["tool"] == "solo"]
           and "stopped “solo-inplace”" in note, f"{note!r} {autostart_entries(CFG)}")
        r = page.request.post(BASE + "/tools/server", headers=SAME,
                              form={"id": "solo", "action": "stop", "session": "solo-inplace"})
        ok("a Stop with nothing left to stop says so, and is no 'stopped' note",
           r.status == 400 and "isn’t running" in r.text() and "done=server-stop" not in r.url,
           f"{r.status} {r.url}")
        start_from_card(page, "solo", "~/projects/web-app")
        page.goto(BASE + "/")
        page.click("#tool-solo > summary")
        sel = '.sess:has(a.open[data-name="solo-serve"])'
        page.click(f"{sel} details.menu > summary")
        page.click(f'{sel} form[action="/kill"] button[type=submit]')
        ok("a Kill in place turns the open card back to Start",
           wait_for(lambda: page.locator("#tool-solo[open] #dp-solo").count() == 1, 5)
           and "stopped" in page.locator("#tool-solo summary .state").inner_text(),
           page.locator("#tool-solo").inner_text())
        page.fill("#dp-solo", "web-a")
        ok("...with a working directory picker",
           wait_for(lambda: page.locator("#tool-solo .dirlist li").count() > 0, 5),
           page.locator("#dp-solo").get_attribute("aria-controls"))
        page.locator("#dp-solo").press("Escape")

        # ---------------------------------------------- F19: start at boot
        card(page, "srv")
        prow = page.locator('#tool-srv .orow:has(code:text-is("~/projects/synth-ios"))')
        ok("a saved boot directory with nothing running gets its own row",
           prow.count() == 1 and "Starts at boot" in prow.inner_text(),
           page.locator("#tool-srv .opts").inner_text())
        ok("...with a ticked box and a Start button",
           prow.locator("input.autostart:checked").count() == 1
           and prow.locator('button:text-is("Start")').count() == 1)
        ok("the per-directory Start row has no box of its own (it could only ever show ~)",
           page.locator('#tool-srv .orow:has(.odir) input.autostart').count() == 0)
        # click(), not uncheck()/check(): the box submits its form on change,
        # and uncheck() then waits for the box on the old page to read
        # unticked -- a race with the navigation, lost now and then.
        with page.expect_navigation():
            prow.locator("input.autostart").click()
        ok("unticking it forgets the entry",
           not any("synth-ios" in (e.get("dir") or "") for e in autostart_entries(CFG)),
           autostart_entries(CFG))
        card(page, "srv")
        ok("...and the row is gone",
           page.locator('#tool-srv code:text-is("~/projects/synth-ios")').count() == 0)

        # A boot directory that has gone: deleted, or (the realistic one) on a
        # drive that is not mounted, where it cannot even be created.
        for gone, shown in ((os.path.join(HOME, "projects/deleted-proj"), "~/projects/deleted-proj"),
                            (GONE_PARENT, GONE_PARENT)):
            card(page, "srv")
            grow = page.locator(f'#tool-srv .orow:has(code:text-is("{shown}"))')
            ok(f"a boot directory that is gone gets a row saying so, with no Start ({shown})",
               grow.count() == 1 and "directory is gone" in grow.inner_text()
               and grow.locator('button:text-is("Start")').count() == 0,
               page.locator("#tool-srv .opts").inner_text())
            with page.expect_navigation():
                grow.locator("input.autostart").click()
            ok("...unticking it forgets the entry",
               not any(e.get("dir") == gone for e in autostart_entries(CFG)), autostart_entries(CFG))
            ok("...and does not re-create the directory", not os.path.exists(gone))

        card(page, "solo")
        page.fill("#dp-solo", "~/projects/web-app")
        with page.expect_navigation():
            page.locator("#tool-solo input.autostart").click()
        ents = [e for e in autostart_entries(CFG) if e["tool"] == "solo"]
        ok("ticking the single server's box saves the picked directory",
           len(ents) == 1 and ents[0]["dir"].endswith("/projects/web-app"), ents)
        card(page, "solo")
        ok("...and the card shows it ticked, naming the directory",
           page.locator("#tool-solo input.autostart:checked").count() == 1
           and "Starts at boot in ~/projects/web-app" in page.locator("#tool-solo .opts").inner_text(),
           page.locator("#tool-solo .opts").inner_text())
        with page.expect_navigation():
            page.locator("#tool-solo input.autostart").click()
        ok("...and unticking removes it",
           not [e for e in autostart_entries(CFG) if e["tool"] == "solo"], autostart_entries(CFG))

        # ---------------------------------------------- F16: the picker ----
        card(page, "pair")
        ok("a card where nothing reads a directory has no picker",
           page.locator("#tool-pair .dirpick").count() == 0)
        card(page, "srv")
        ok("the per-directory card has exactly one picker, in its Start row, labelled",
           page.locator("#tool-srv .dirpick").count() == 1
           and page.locator('#tool-srv .orow:has(button[value="/tools/server"]) .dirpick').count() == 1
           and page.locator('#tool-srv label[for="dp-srv"]').inner_text() == "Directory")
        # The "hello" action comes first in the card. Enter in the picker used
        # to press it (implicit submission takes a form's first button).
        for eng in ("chromium", "firefox", "webkit"):
            eb = getattr(p, eng).launch()
            ep = eb.new_page()
            ep.goto(BASE + "/")
            ep.click("#tool-srv > summary")
            ep.fill("#dp-srv", f"~/projects/enter-{eng}")
            ep.wait_for_timeout(400)              # let the suggestion list settle, then close it
            ep.locator("#dp-srv").press("Escape")
            ep.locator("#dp-srv").press("Enter")
            ep.wait_for_url(re.compile(r"/s/"), timeout=10000)
            ok(f"{eng}: Enter in the picker starts the server there, not the unrelated action",
               ep.url.endswith(f"/s/srv-remote-enter-{eng}") and not exists("hello"), ep.url)
            eb.close()

        # ----------------------------------------------------- F54: copy ----
        # Make one instance exit: kill whatever holds its terminal.
        pid = tm("display", "-p", "-t", "=srv-remote-3d-lab:", "#{pane_pid}")
        with open(f"/proc/{pid}/stat") as f:
            tpgid = int(f.read().rsplit(")", 1)[1].split()[5])
        os.killpg(tpgid, signal.SIGTERM)
        wait_for(lambda: tm("display", "-p", "-t", "=srv-remote-3d-lab:", "#{pane_current_command}") == "bash")
        card(page, "srv")
        confirms = page.eval_on_selector_all('#tool-srv form[action="/tools/server"][data-confirm]',
                                             "e => e.map(x => x.dataset.confirm)")
        ok("Stop's confirm names the directory",
           "Stop Remote Control server in “~/projects/web-app”?" in confirms, confirms)
        ok("Remove on an exited server asks to remove it, not to stop it",
           "Remove the exited Remote Control server in “~/projects/3d-lab”?" in confirms, confirms)
        st = page.locator("#tool-srv summary .state").inner_text()
        ok("the summary counts the exited one", "1 exited" in st, st)
        dialogs.clear()
        with page.expect_navigation():
            page.click('#tool-srv .orow:has(code:text-is("~/projects/3d-lab")) button:text-is("Remove")')
        ok("...Remove shows that confirm and removes the session",
           dialogs and dialogs[0].startswith("Remove the exited") and not exists("srv-remote-3d-lab"),
           dialogs)

        card(page, "pair")
        page.click('#tool-pair .orow:has(.olabel:text-is("Pair with phone")) button')
        page.wait_for_url(re.compile(r"/s/"))
        ok("an action's session is named in lower case", page.url.endswith("/s/pair-with-phone"),
           page.url)

        # ---------------------------------------- F18: login state is fresh
        card(page, "slow")
        ok("the slow tool starts out not logged in",
           "not logged in" in page.locator("#tool-slow summary").inner_text())
        page.click('#tool-slow button:text-is("Log in")')
        page.wait_for_url(re.compile(r"/s/login-slow"))
        st = summary_text(page, "slow")          # a render in the middle of the flow
        ok("...still not logged in while the login runs", "not logged in" in st, st)
        flag = os.path.join(HOME, "slow-flag")
        ok("...the login finishes", wait_for(lambda: os.path.exists(flag), 10))
        wait_for(lambda: tm("display", "-p", "-t", "=login-slow:", "#{pane_current_command}") == "bash", 5)
        st = summary_text(page, "slow")
        ok("the card says Ready as soon as it has, not a minute later", "Ready" in st, st)

        # -------------------------------- F59: the collapsed row stays short
        start_from_card(page, "srv", "~/projects/a-really-long-project-directory-name/"
                                     "with-a-nested-child-folder")
        for w in (320, 390):
            nctx = b.new_context(viewport={"width": w, "height": 800}, is_mobile=True,
                                 has_touch=True, device_scale_factor=2)
            np_ = nctx.new_page()
            np_.goto(BASE + "/")
            summ = np_.locator("#tool-srv > summary")
            pills = np_.locator("#tool-srv summary .pill")
            box = pills.first.bounding_box() if pills.count() else None
            ok(f"{w}px: one server pill for every instance, one line tall",
               pills.count() == 1 and box and box["height"] < 26
               and "running" in pills.first.inner_text(),
               f"{pills.count()} {box} {pills.first.inner_text() if pills.count() else ''}")
            ok(f"{w}px: the collapsed row is short", summ.bounding_box()["height"] < 110,
               summ.bounding_box())
            ok(f"{w}px: the status dots never shrink",
               np_.evaluate("getComputedStyle(document.querySelector('#tool-srv summary .pill'),"
                            "'::before').flexShrink") == "0")
            tags = np_.evaluate("""() => [...document.querySelectorAll('.card.sess .name .pill')]
              .filter(t => t.textContent.trim().toLowerCase() === 'server')
              .map(t => { const p = t.getBoundingClientRect(),
                                r = t.closest('.name').getBoundingClientRect();
                          return [t.closest('.name').textContent.trim(),
                                  p.width > 20 && p.right <= r.right + 0.5]; })""")
            ok(f"{w}px: every server tag in the Sessions list is whole, however long the name",
               len(tags) >= 3 and all(v for _n, v in tags), tags)
            np_.click("#tool-srv > summary")
            np_.screenshot(path=f"shots/agents-srv-{w}.png", full_page=True)
            ok(f"{w}px: no horizontal overflow with the card open",
               np_.evaluate("document.documentElement.scrollWidth <= innerWidth"),
               np_.evaluate("[document.documentElement.scrollWidth, innerWidth]"))
            nctx.close()

        # ------------------------------ F60: a slow page never stays black
        # Chromium only: emulated WebKit does not reliably tick the CSS
        # animation while a navigation is pending, so it proves nothing there.
        tctx = b.new_context(viewport={"width": 390, "height": 800}, is_mobile=True, has_touch=True)
        tp = tctx.new_page()
        tp.set_default_timeout(15000)
        tp.goto(BASE + "/")
        held = []
        # Hold the next page's response, like a slow server or a bad network.
        tp.route(re.compile(r".*/s/srv-remote-web-app$"), lambda route: held.append(route))
        # Playwright cannot evaluate in a page with a navigation pending, so the
        # page samples its own opacity into localStorage, read back afterwards.
        # Tapping Open (touch: same tab, through the CRT power-off) from the
        # page itself, so Playwright does not wait on the held navigation.
        tp.evaluate("""(sel) => { const t0 = performance.now(), out = [];
          const iv = setInterval(() => {
            out.push([Math.round(performance.now() - t0), +getComputedStyle(document.body).opacity]);
            localStorage.setItem('sj-test-opacity', JSON.stringify(out));
            if (out.length > 25) clearInterval(iv);
          }, 100);
          document.querySelector(sel).click(); }""",
                    '.card.sess a.open[data-name="srv-remote-web-app"]')
        tp.wait_for_timeout(2200)                 # pumps the route handler too
        for route in held:
            route.continue_()
        tp.wait_for_url(re.compile(r"/s/srv-remote-web-app"))
        samples = json.loads(tp.evaluate("localStorage.getItem('sj-test-opacity')") or "[]")
        ok("leaving collapses the page (CRT power-off)",
           any(o < 0.1 for t, o in samples if 150 <= t <= 800), samples)
        ok("...but if the next page is slow, the old one comes back instead of a blank screen",
           samples and all(o > 0.99 for t, o in samples if t >= 1300), samples)
        tctx.close()
        b.close()

        # --------------------- autostart against an already running server
        before = tm("display", "-p", "-t", "=srv-remote-web-app:", "#{pane_pid}")
        _b2, _h2, _c2, log2 = start_instance(
            "auto", main_tools, "srv",
            autostart=lambda home: [{"tool": "srv", "kind": "server",
                                     "dir": os.path.join(HOME, "projects/web-app")}], delay="1")
        line = wait_for(lambda: "already running" in open(log2).read() and open(log2).read(), 15)
        ok("autostart leaves a running server alone", bool(line), open(log2).read()[-500:])
        ok("...same pid", tm("display", "-p", "-t", "=srv-remote-web-app:", "#{pane_pid}") == before)

        # -------------------------------- F61: a fresh install, no agents
        base3, _h3, _c3, _l3 = start_instance(
            "none", lambda home: [{"id": "nope", "label": "Nope", "bin": "sj-pwagents-missing",
                                   "install": "echo INSTALL", "run": "nope"}], "nope")
        b = p.chromium.launch()
        page = b.new_page()
        page.goto(base3 + "/")
        hint = page.locator('#startform .hint:has(a[href="#agents"])')
        ok("with no agent installed, the Start card points at Agent servers",
           hint.count() == 1 and page.locator("h2#agents").count() == 1,
           page.locator("#startform").inner_text())
        page.goto(BASE + "/")
        ok("...and says nothing of the sort once one is",
           page.locator('#startform .hint:has(a[href="#agents"])').count() == 0)
        gap = page.evaluate("(() => { const h = document.querySelector('#agents + p.hint'),"
                            " n = h && h.nextElementSibling; if (!n) return null;"
                            " return n.getBoundingClientRect().top - h.getBoundingClientRect().bottom; })()")
        ok("the Agent servers lead-in keeps a heading's gap above its cards", gap is not None and gap >= 7, gap)
        b.close()
finally:
    for proc in PROCS:
        proc.terminate()
    for proc in PROCS:
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
    subprocess.run(T + ["kill-server"], capture_output=True)
    shutil.rmtree(ROOT, ignore_errors=True)

if fails:
    raise SystemExit(1)
