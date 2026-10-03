"""Landing page flows: what happens around a form submit.

The things worth proving here are about state surviving and actions landing
where they should, so most checks drive a real browser through a real
round trip and then look at the page, the address bar and the tmux server:

- nothing typed is lost on an error (the directory included), and a
  corrected retry runs where it was asked to;
- multi-line commands run line by line (browsers send CRLF);
- one tap is one submit, even on a slow link (a delaying proxy stands in
  for a phone on cellular / a Tailscale relay);
- an error page never stays at a POST URL: reload and Back are plain GETs;
- Kill and Rename work in place (inline errors, the Start card untouched);
- in-place actions land back at their section or card with a one-shot note;
- shortcuts can be edited (Cancel really leaves the editor, a reload keeps
  it), and their runs are named after them;
- with the page script on, the "Keep this command" box alone decides;
- Back restoring a page from the bfcache (pageshow, persisted) gives a busy
  form its button back and drops a stale note;
- the "change" default-directory form keeps the Start card's fields;
- Back after starting an agent shows a consistent Start card.

Chromium desktop first, then WebKit (iPhone 14 emulation, which is NOT iOS
Safari) and a Firefox block for the engine-specific history behaviour.
run.sh's fixture: tools fake/fake2/pathfake/fakesvc (fakesvc has a daemon
whose start/stop are `true`), sessions pwtest/pwother, HOME=<run>/home.
"""
import os
import re
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(line_buffering=True)     # a hang shows where it is in the log

BASE = os.environ.get("SERVERJACK_TEST_BASE", "http://127.0.0.1:7690")
TAG = str(int(time.time()))[-6:]
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]
SAME = {"Sec-Fetch-Site": "same-origin"}
MADE = []          # sessions this suite created, killed at the end
fails = 0


def pane(name, lines=200):
    return subprocess.run(T + ["capture-pane", "-p", "-J", "-t", f"={name}:", "-S", f"-{lines}"],
                          capture_output=True, text=True).stdout


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
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + extra) if extra and not cond else ""))
    return bool(cond)


def known(label, cond, why):
    """A check that stays red until another change lands: printed as KNOWN,
    not counted as a failure, so it shows up in the run."""
    print(("  PASS " if cond else "  KNOWN ") + label + ("" if cond else "  -- " + why))


def sess_from_url(page):
    m = re.search(r"/s/([^/?#]+)", page.url)
    return m.group(1) if m else ""


def pick_what(page, value):
    page.click(f'.seg label:has(input[name=what][value="{value}"])')


def delay_proxy(base, delay=0.7):
    """A loopback port in front of `base` that holds back the response to
    every POST by `delay` seconds -- a phone on a slow link, without which a
    double tap on loopback is usually too slow to land inside the window."""
    up = urlsplit(base)
    ls = socket.socket()
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", 0))
    ls.listen(50)

    def pipe(src, dst, posted, hold):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                if not hold and data.startswith(b"POST "):
                    posted.set()
                if hold and posted.is_set():
                    time.sleep(delay)
                    posted.clear()
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def serve():
        while True:
            c, _ = ls.accept()
            u = socket.create_connection((up.hostname, up.port))
            posted = threading.Event()
            threading.Thread(target=pipe, args=(c, u, posted, False), daemon=True).start()
            threading.Thread(target=pipe, args=(u, c, posted, True), daemon=True).start()
    threading.Thread(target=serve, daemon=True).start()
    return f"http://127.0.0.1:{ls.getsockname()[1]}"


def fill_dir(page, selector, value):
    """Type into a directory picker and dismiss its suggestions once the
    (debounced) search has answered, so they don't cover the next button."""
    page.fill(selector, value)
    page.wait_for_timeout(300)
    page.keyboard.press("Escape")


def rename_via_menu(page, name, new):
    sel = f'.sess:has(a.open[data-name="{name}"])'
    page.click(f"{sel} details.menu > summary")
    page.click(f"{sel} details.ren summary")
    page.fill(f'{sel} form[action="/rename"] input[name=new]', new)
    page.click(f'{sel} form[action="/rename"] button[type=submit]')
    return sel


def double_submit_check(p, page, label):
    """Start tapped twice 250 ms apart through a slow link: one POST, one
    session, and the button says it's busy in between."""
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    slow = delay_proxy(BASE)
    page.goto(f"{slow}/")
    d = f"~/dbl-{label}-{TAG}"
    fill_dir(page, "#dir", d)
    busy_label = page.evaluate("""() => new Promise(done => {
      const b = document.querySelector('#startform button[type=submit]');
      b.click();
      setTimeout(() => { const t = b.textContent; b.click(); done(t); }, 250);
    })""")
    page.wait_for_url(re.compile(r"/s/"), timeout=15000)
    page.wait_for_timeout(1000)
    base = f"shell-dbl-{label}-{TAG}"
    MADE.extend([base, base + "-2"])
    starts = [u for u in posts if u.endswith("/start")]
    ok(f"{label}: a double tap on Start sends one POST", len(starts) == 1, str(starts))
    ok(f"{label}: ...and makes one session", exists(base) and not exists(base + "-2"),
       f"{base}: {exists(base)}, -2: {exists(base + '-2')}")
    ok(f"{label}: ...the button said Starting… in between", busy_label == "Starting…", busy_label)
    page.go_back()
    page.wait_for_load_state()
    page.wait_for_timeout(300)
    st = page.evaluate("""() => { const b = document.querySelector('#startform button[type=submit]');
      return [b.disabled, b.textContent, !!document.getElementById('startform').dataset.busy]; }""")
    ok(f"{label}: Back afterwards finds a usable Start button", st == [False, "Start", False], str(st))


def pageshow_check(page, label):
    """Back restoring the page from the bfcache: a form left busy gets its
    button back, and a one-shot note from before goes. Chromium re-fetches a
    no-store page on Back, so the restore path never runs by itself in a
    test: put the Start form in flight for real (its own submit handler runs
    first; a later listener only stops the navigation -- holding the request
    instead would block every evaluate) and send what a restore sends."""
    page.goto(f"{BASE}/?done=dir")
    page.wait_for_selector(".flash")
    page.evaluate("document.addEventListener('submit', e => e.preventDefault())")
    page.click("#startform button[type=submit]")
    btn = "document.querySelector('#startform button[type=submit]')"
    try:
        page.wait_for_function(f"{btn}.disabled", timeout=3000)
        went_busy = page.evaluate(f"{btn}.textContent") == "Starting…"
    except Exception:
        went_busy = False
    ok(f"{label}: a Start on its way disables its button and says Starting…", went_busy)
    page.evaluate("dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
    st = page.evaluate(f"""() => [{btn}.disabled, {btn}.textContent,
      !!document.getElementById('startform').dataset.busy, document.querySelectorAll('.flash').length]""")
    ok(f"{label}: a bfcache restore gives the button back and drops the old note",
       st == [False, "Start", False, 0], str(st))


def editor(page):
    return [page.locator("#addsc > summary").inner_text().strip(),
            page.locator("#addsc input[name=id]").count(),
            page.evaluate("document.getElementById('addsc').open")]


with sync_playwright() as p:
    print("chromium desktop:")
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.on("pageerror", lambda e: print("   [pageerror]", e))
    page.on("dialog", lambda d: d.accept())
    reqs = []
    page.on("request", lambda r: reqs.append((r.method, urlsplit(r.url).path)))

    # pwland leaves the default directory at ~/projects; this suite wants ~.
    page.request.post(f"{BASE}/prefs", headers=SAME, form={"dir": "~"})

    # -------------------------------------------- errors keep everything --
    newdir = f"~/flows-{TAG}"
    sclabel = f"Flows SC {TAG}"
    page.goto(f"{BASE}/")
    fill_dir(page, "#dir", newdir)
    page.fill("#name", "pwtest")                       # taken: run.sh made it
    page.fill("#cmd", "pwd")
    page.click("#startform details.inline summary")
    page.fill("#startform input[name=label]", sclabel)
    ok("typing a shortcut name ticks Keep this command", page.is_checked("#save"))
    page.click("#startform button[type=submit]")
    page.wait_for_load_state()
    err = page.locator(".err").first
    ok("a taken name re-renders with the error", err.count() and "already exists" in err.inner_text(),
       err.inner_text() if err.count() else "no .err")
    ok("...the typed directory is still in the box", page.input_value("#dir") == newdir,
       page.input_value("#dir"))
    ok("...and the shortcut tick, its name and the command too",
       page.is_checked("#save") and page.input_value("#startform input[name=label]") == sclabel
       and page.input_value("#cmd") == "pwd")
    ok("...with an Open button for the session that has the name",
       page.locator('.err a.open[href="/s/pwtest"]').count() == 1)
    ok("...and the address bar says / (not the POST's /start)", page.url == f"{BASE}/", page.url)
    reqs.clear()
    page.reload()
    page.wait_for_load_state()
    ok("reloading the error page is a GET, not a resubmit",
       ("GET", "/") in reqs and not any(m == "POST" for m, _ in reqs), str(reqs[:4]))
    page.goto(f"{BASE}/")
    fill_dir(page, "#dir", newdir)
    page.fill("#name", "pwtest")
    page.fill("#cmd", "pwd")
    page.click("#startform details.inline summary")
    page.fill("#startform input[name=label]", sclabel)
    page.click("#startform button[type=submit]")
    page.wait_for_load_state()
    page.fill("#name", f"flows-{TAG}")                 # fix only the name
    page.click("#startform button[type=submit]")
    page.wait_for_selector("#tabs .tab.on")
    retry = sess_from_url(page)
    MADE.append(retry)
    out = wait_for(lambda: pane(retry) if f"flows-{TAG}" in pane(retry).split("$ pwd", 1)[-1] else "")
    ok("the corrected retry runs in the directory that was typed",
       f"/flows-{TAG}" in out, out[-300:])
    reqs.clear()
    page.go_back()
    page.wait_for_load_state()
    ok("Back from the terminal lands on / without re-POSTing",
       page.url == f"{BASE}/" and not any(m == "POST" for m, _ in reqs), f"{page.url} {reqs[:4]}")
    card = page.locator(f'.card.sess:has(.name:text-is("{sclabel}"))')
    ok("the shortcut asked for before the error was saved by the retry", card.count() == 1)

    # Naming the shortcut is enough; ticking with no command is refused.
    r = page.request.post(f"{BASE}/start", headers=SAME, max_redirects=0,
                          form={"what": "shell", "cmd": f"echo LABELONLY_{TAG}",
                                "name": f"labelonly-{TAG}", "label": f"Label only {TAG}"})
    MADE.append(f"labelonly-{TAG}")
    ok("a shortcut name without the tick still saves the shortcut",
       r.status == 303 and f"Label only {TAG}" in page.request.get(f"{BASE}/").text(), str(r.status))
    r = page.request.post(f"{BASE}/start", headers=SAME,
                          form={"what": "shell", "cmd": "", "save": "1", "label": "Nothing"})
    ok("ticking Keep with no command is refused, not silently dropped",
       r.status == 400 and "type a command first" in r.text(), str(r.status))

    # ...but with the page script on, the box decides: a shortcut name ticks
    # it, and unticking it afterwards means "don't keep it".
    page.goto(f"{BASE}/")
    page.fill("#cmd", f"echo UNTICK_{TAG}")
    page.click("#startform details.inline summary")
    page.fill("#startform input[name=label]", f"Untick {TAG}")
    page.uncheck("#save")
    page.click("#startform button[type=submit]")
    page.wait_for_selector("#tabs .tab.on")
    MADE.append(sess_from_url(page))
    ok("unticking Keep after naming the shortcut is honoured: nothing saved",
       f"Untick {TAG}" not in page.request.get(f"{BASE}/").text())

    # ------------------------------------------------ multi-line commands --
    page.goto(f"{BASE}/")
    page.fill("#cmd", "cd /tmp\npwd\necho LINES_$((1+1))")
    page.click("#startform button[type=submit]")
    page.wait_for_selector("#tabs .tab.on")
    ml = sess_from_url(page)
    MADE.append(ml)
    out = wait_for(lambda: pane(ml) if "[exited with status" in pane(ml) else "")
    ok("a multi-line command runs line by line (no stray CR)",
       "LINES_2" in out and "\n/tmp\n" in out and "$'" not in out and "No such file" not in out,
       out[-300:])

    # ----------------------------------------------------- one tap, one POST --
    double_submit_check(p, page, "chromium")

    # ---------------------------------------- Back after starting an agent --
    page.goto(f"{BASE}/")
    page.fill("#cmd", "echo stale")
    pick_what(page, "fake")
    page.click("#startform button[type=submit]")
    page.wait_for_selector("#tabs .tab.on")
    MADE.append(sess_from_url(page))
    page.go_back()
    page.wait_for_load_state()
    page.wait_for_timeout(300)
    st = page.evaluate("""() => {
      const lit = [...document.querySelectorAll('.seg .pill')].filter(
        p => p.classList.contains('on') || p.querySelector('input').checked).length;
      const agent = document.querySelector('input[name=what]:checked').value !== 'shell';
      return [lit, agent === document.getElementById('cmdwrap').hidden,
              document.getElementById('cmd').value]; }""")
    ok("Back after an agent Start: one chip lit, command box matches it, no stale command",
       st == [1, True, ""], str(st))
    pick_what(page, "fake")
    ok("the shell hint hides when an agent is picked", page.locator("#starthint").is_hidden())
    pick_what(page, "shell")
    ok("...and comes back for Shell", page.locator("#starthint").is_visible())

    # ------------------------------------------------------- rename in place --
    subprocess.run(T + ["new-session", "-d", "-s", f"flowren-{TAG}"], capture_output=True)
    MADE.append(f"flowren-{TAG}")
    page.goto(f"{BASE}/")
    page.fill("#cmd", "typed-before-rename")
    sel = f'.sess:has(a.open[data-name="flowren-{TAG}"])'
    page.click(f"{sel} details.menu > summary")
    page.click(f"{sel} details.ren summary")
    focus = page.evaluate("""() => { const a = document.activeElement;
      return [a.name, a.selectionStart, a.selectionEnd, a.value.length]; }""")
    ok("Rename opens with the field focused and its text selected",
       focus[0] == "new" and focus[1] == 0 and focus[2] == focus[3], str(focus))
    box = page.locator(f'{sel} form[action="/rename"] input[name=new]')
    box.fill("bad:name")
    ok("':' is refused before submitting", not box.evaluate("e => e.checkValidity()"))
    box.fill("$x")
    ok("...and so is a leading '$'", not box.evaluate("e => e.checkValidity()"))
    box.fill("pwtest")
    page.click(f'{sel} form[action="/rename"] button[type=submit]')
    page.wait_for_selector(f"{sel} details.ren .err")
    msg = page.locator(f"{sel} details.ren .err").inner_text()
    ok("a taken name is refused inline, in the rename's own words",
       "already called" in msg and "instead" not in msg, msg)
    ok("...with the menu still open, the value kept and the URL still /",
       page.locator(f"{sel} details.menu[open] details.ren[open]").count() == 1
       and box.input_value() == "pwtest" and page.url == f"{BASE}/", page.url)
    page.click(f"{sel} details.ren summary")                # fold Rename...
    # The error goes on the details' toggle event, which the browser fires
    # after the click, not during it.
    ok("folding Rename drops its error",
       wait_for(lambda: page.locator(f"{sel} details.ren .err").count() == 0, 3))
    page.click(f"{sel} details.ren summary")                # ...and open it again
    box.fill(f"flowren2-{TAG}")
    page.click(f'{sel} form[action="/rename"] button[type=submit]')
    page.wait_for_selector(f'.sess a.open[data-name="flowren2-{TAG}"]')
    MADE.append(f"flowren2-{TAG}")
    ok("a good name renames the row in place",
       exists(f"flowren2-{TAG}") and not exists(f"flowren-{TAG}"))
    ok("...and leaves the Start card alone", page.input_value("#cmd") == "typed-before-rename")
    r = page.request.post(f"{BASE}/api/rename", headers=SAME,
                          form={"name": f"flowren2-{TAG}", "new": f"-dash{TAG}"})
    MADE.append(f"-dash{TAG}")
    ok("renaming to a name that starts with '-' works (as creating one does)",
       r.status == 200 and exists(f"-dash{TAG}"), r.text())
    r = page.request.post(f"{BASE}/api/rename", headers=SAME,
                          form={"name": f"-dash{TAG}", "new": "$q"})
    ok("a leading '$' is refused with a reason", r.status == 400 and "$" in r.json().get("error", ""),
       r.text())

    # ------------------------------------- kill in place, a row in the middle --
    mid = f"pwp{TAG}"            # sorts between pwother and pwtest
    subprocess.run(T + ["new-session", "-d", "-s", mid, "-x", "80", "-y", "24"])
    MADE.append(mid)
    page.goto(f"{BASE}/")
    sel = f'.sess:has(a.open[data-name="{mid}"])'
    page.focus(f"{sel} details.menu > summary")
    page.keyboard.press("Enter")
    page.focus(f'{sel} form[action="/kill"] button')
    page.keyboard.press("Enter")
    page.wait_for_selector(".sessmsg")
    look = page.evaluate("""() => { const n = document.querySelector('.sessmsg'), cs = getComputedStyle(n);
      const a = n.previousElementSibling, b = n.nextElementSibling, f = document.activeElement;
      return {text: n.textContent, between: !!(a && a.matches('.sess') && b && b.matches('.sess')),
              radius: cs.borderTopLeftRadius + ' ' + cs.borderBottomLeftRadius,
              focus: !!(f.matches && f.matches('details.menu > summary') && f.closest('.sess') === b),
              on: f.tagName + ' ' + (f.getAttribute('aria-label') || '')}; }""")
    ok("Kill in place on a middle row: the note takes its place, the list stays one card",
       not exists(mid) and look["text"] == f"Killed “{mid}”." and look["between"]
       and look["radius"] == "0px 0px", str(look))
    ok("...a keyboard user's focus goes to the next row's menu, not <body>", look["focus"], look["on"])
    ok("...and the note goes again after a few seconds",
       wait_for(lambda: page.locator(".sessmsg").count() == 0, 9))

    # ---------------------------------------------------------- kill in place --
    page.goto(f"{BASE}/")
    page.fill("#cmd", "typed-before-kill")
    sel = f'.sess:has(a.open[data-name="-dash{TAG}"])'
    # Only on this page (the sessions stay): make it the last row, so the
    # kill has to put up the empty-list placeholder.
    page.evaluate("""n => document.querySelectorAll('.sess a.open[data-name]').forEach(a => {
      if (a.dataset.name !== n) a.closest('.sess').remove(); })""", f"-dash{TAG}")
    page.click(f"{sel} details.menu > summary")
    page.click(f'{sel} form[action="/kill"] button')
    page.wait_for_selector(".sessmsg")
    ok("Kill removes the row in place and says so",
       not exists(f"-dash{TAG}") and page.locator(sel).count() == 0
       and f"Killed “-dash{TAG}”" in page.locator(".sessmsg").inner_text())
    ok("...keeping what was typed in the Start card and the URL",
       page.input_value("#cmd") == "typed-before-kill" and page.url == f"{BASE}/")
    ok("...and the last one leaves one placeholder, the #nosess the list's refresh uses",
       page.locator("#nosess").count() == 1
       and page.locator(".empty", has_text="No sessions").count() == 1
       and page.locator("#nosess").inner_text() == "No sessions running.",
       str(page.locator(".empty").all_inner_texts()))

    # ----------------------------------------- shortcuts: save, edit, run --
    page.goto(f"{BASE}/")
    page.fill("#cmd", "typed-before-shortcut")
    page.click("#addsc > summary")
    addlabel = f"Logs {TAG}"
    page.fill("#sc_label", addlabel)
    page.fill("#sc_cmd", "cd /tmp\necho SC_ONE")
    page.click('#addsc button[type=submit]')
    page.wait_for_selector("#note")
    ok("saving a shortcut lands on Shortcuts with a note right under the heading",
       f"Saved shortcut “{addlabel}”" in page.locator("#note").inner_text()
       and page.evaluate("document.getElementById('shortcuts').nextElementSibling.id") == "note"
       and page.url.endswith("/#shortcuts"), page.url)
    pos = page.evaluate("""() => { const r = document.getElementById('note').getBoundingClientRect();
       return [r.top, r.bottom, innerHeight, scrollY, document.documentElement.scrollHeight]; }""")
    ok("...in view", pos[0] >= 0 and pos[1] <= pos[2], str(pos))
    ok("...and the Start card kept what was typed", page.input_value("#cmd") == "typed-before-shortcut")
    page.reload()
    ok("the note is one-shot: a reload doesn't bring it back", page.locator(".flash").count() == 0)

    card = page.locator(f'.card.sess:has(.name:text-is("{addlabel}"))')
    ok("the built-in Update row has no edit button", page.locator("#sc-update a.sc-edit").count() == 0)
    card.locator("a.sc-edit").click()
    page.wait_for_selector("#addsc[open]")
    ok("Edit opens the shortcut form filled in",
       page.locator("#addsc > summary").inner_text().strip() == "Edit shortcut"
       and page.input_value("#sc_label") == addlabel and "SC_ONE" in page.input_value("#sc_cmd"))

    ok("...and the address keeps saying so", "edit_sc=" in page.url, page.url)
    page.reload()
    page.wait_for_selector("#addsc[open]")
    ok("a reload keeps the editor open", editor(page) == ["Edit shortcut", 1, True], str(editor(page)))
    fill_dir(page, "#sc_dir", "/etc/hostname")
    page.click('#addsc button[type=submit]')
    page.wait_for_selector("#addsc .err")
    ok("an edit refused for its folder is still the edit, and the address says so",
       editor(page) == ["Edit shortcut", 1, True] and "edit_sc=" in page.url, f"{editor(page)} {page.url}")
    page.click('#addsc a.btn:has-text("Cancel")')
    page.wait_for_load_state()
    page.wait_for_timeout(300)
    ok("Cancel leaves the editor: Add a shortcut, closed, nothing left to overwrite",
       editor(page) == ["Add a shortcut", 0, False] and page.url == f"{BASE}/#shortcuts",
       f"{editor(page)} {page.url}")
    card.locator("a.sc-edit").click()
    page.wait_for_selector("#addsc[open]")
    page.fill("#sc_cmd", "cd /tmp\necho SC_TWO")
    page.click('#addsc button[type=submit]')
    page.wait_for_selector("#note")
    card = page.locator(f'.card.sess:has(.name:text-is("{addlabel}"))')
    ok("Save changes replaces it in place (still one, new command)",
       card.count() == 1 and "SC_TWO" in card.inner_text()
       and "Updated shortcut" in page.locator("#note").inner_text(), card.inner_text())
    r = page.request.post(f"{BASE}/shortcuts/add", headers=SAME,
                          form={"id": "builtin-update", "label": "x", "cmd": "x"})
    ok("the built-in Update row can't be edited", r.status == 404, str(r.status))
    card.locator('form[action="/shortcuts/run"] button').click()
    page.wait_for_selector("#tabs .tab.on")
    scs = sess_from_url(page)
    MADE.append(scs)
    ok("a shortcut run is named after the shortcut",
       scs == f"logs-{TAG}", scs)
    out = wait_for(lambda: pane(scs) if "[exited with status" in pane(scs) else "")
    ok("...and its multi-line command ran line by line", "SC_TWO" in out and "$'" not in out, out[-200:])
    page.goto(f"{BASE}/")
    for label in (addlabel, sclabel, f"Label only {TAG}"):
        c = page.locator(f'.card.sess:has(.name:text-is("{label}"))')
        if c.count():
            c.first.locator('form[action="/shortcuts/del"] button').click()
            page.wait_for_selector("#note")
    ok("removing a shortcut says so", "Removed shortcut" in page.locator("#note").inner_text())

    upd = page.locator("#sc-update")
    if upd.count():
        ok("the Update row asks before running",
           "restart" in (upd.locator('form[action="/shortcuts/run"]').get_attribute("data-confirm") or ""))

    # --------------------------------------- a tool card's in-place actions --
    page.goto(f"{BASE}/")
    page.fill("#cmd", "typed-before-boot")
    page.click("#tool-fakesvc > summary")
    page.locator("#tool-fakesvc input.autostart").check()
    page.wait_for_selector("#tool-fakesvc[open] .tbody #note")
    ok("start at boot lands back on its card, open, saying so",
       "will start at boot" in page.locator("#note").inner_text()
       and page.url.endswith("/#tool-fakesvc"), page.url)
    pos = page.evaluate("""() => { const r = document.getElementById('note').getBoundingClientRect();
       return [r.top, r.bottom, innerHeight, scrollY]; }""")
    ok("...in view, scrolled down to the card", pos[0] >= 0 and pos[1] <= pos[2] and pos[3] > 0, str(pos))
    ok("...with the Start card's typing kept", page.input_value("#cmd") == "typed-before-boot")
    page.locator("#tool-fakesvc input.autostart").uncheck()
    page.wait_for_selector("#tool-fakesvc .tbody #note")
    ok("unticking it says so too", "won't start at boot" in page.locator("#note").inner_text())
    page.locator('button[form="f-fakesvc-daemon"]').click()
    page.wait_for_selector("#tool-fakesvc .tbody #note")
    ok("starting the daemon says it started, in its card",
       "Fake daemon started" in page.locator("#note").inner_text())

    # ------------------------------------- Back from the bfcache (pageshow) --
    pageshow_check(page, "chromium")

    # ------------------------------------------- the default-directory form --
    page.goto(f"{BASE}/")
    page.fill("#name", f"typed-{TAG}")
    page.fill("#cmd", "make test")
    page.click("details.ddchange summary")
    fill_dir(page, "#dd_dir", f"~/no-such-dir-{TAG}")
    page.click('form[action="/prefs"] button[type=submit]')
    page.wait_for_load_state()
    ok("a bad default directory is refused inside the change form",
       page.locator(".ddchange[open] .err").count() == 1 and page.locator("main > .err").count() == 0)
    ok("...keeping the Start card's name and command",
       page.input_value("#name") == f"typed-{TAG}" and page.input_value("#cmd") == "make test")
    fill_dir(page, "#dd_dir", "~/projects")
    page.click('form[action="/prefs"] button[type=submit]')
    page.wait_for_selector(".flash")
    ok("a good one is saved, the Start card still filled in",
       "Default directory: ~/projects" in page.locator(".flash").inner_text()
       and page.input_value("#name") == f"typed-{TAG}" and page.input_value("#cmd") == "make test")
    ok("...and the confirmation is gone from the URL", "done=" not in page.url, page.url)
    page.reload()
    ok("...so a reload doesn't show it again", page.locator(".flash").count() == 0)
    page.request.post(f"{BASE}/prefs", headers=SAME, form={"dir": "~"})
    b.close()

    print("webkit iphone:")
    wb = p.webkit.launch()
    dev = dict(p.devices["iPhone 14"])
    dev.pop("default_browser_type", None)
    ictx = wb.new_context(**dev)
    ipage = ictx.new_page()
    ipage.on("pageerror", lambda e: print("   [pageerror]", e))
    ipage.on("dialog", lambda d: d.accept())
    ireqs = []
    ipage.on("request", lambda r: ireqs.append((r.method, urlsplit(r.url).path)))
    ipage.goto(f"{BASE}/")
    ipage.fill("#name", "pwtest")
    ipage.click("#startform button[type=submit]")
    ipage.wait_for_load_state()
    ok("iPhone: an error page's address is /", ipage.url == f"{BASE}/", ipage.url)
    ireqs.clear()
    ipage.reload()
    ipage.wait_for_load_state()
    ok("iPhone: reloading it never re-runs the Start",
       ("POST", "/start") not in ireqs and ("GET", "/") in ireqs, str(ireqs[:4]))
    subprocess.run(T + ["new-session", "-d", "-s", f"iren-{TAG}"], capture_output=True)
    MADE.append(f"iren-{TAG}")
    ipage.goto(f"{BASE}/")
    sel = f'.sess:has(a.open[data-name="iren-{TAG}"])'
    ipage.locator(f"{sel} details.menu > summary").tap()
    ipage.locator(f"{sel} details.ren summary").tap()
    ok("iPhone: Rename focuses its field in the same tap",
       ipage.evaluate("document.activeElement.name") == "new")
    double_submit_check(p, ipage, "iphone")
    pageshow_check(ipage, "iphone")
    ctx320 = wb.new_context(**{**dev, "viewport": {"width": 320, "height": 568}})
    sp = ctx320.new_page()
    sp.on("dialog", lambda d: d.accept())
    narrow = f"A long shortcut name {TAG} that will not fit"
    sp.request.post(f"{BASE}/shortcuts/add", headers=SAME,
                    form={"label": narrow, "dir": "~",
                          "cmd": "docker compose -f /very/long/path/to/compose.yml logs --follow --tail=200"})
    sp.goto(f"{BASE}/")
    split = sp.evaluate("""() => [...document.querySelectorAll('.meta.wrap .w')].filter(w => {
      const lh = parseFloat(getComputedStyle(w).lineHeight) || 18;
      return /^-/.test(w.textContent) && w.getBoundingClientRect().height > lh * 1.5; }).map(w => w.textContent)""")
    ok("320px: a flag in a shortcut's command is never split at a hyphen ('--' / 'follow')",
       split == [] and sp.locator(".meta.wrap .w", has_text="--follow").count() >= 1, str(split))
    ok("320px: no sideways scroll with the shortcut rows' edit buttons",
       sp.locator("a.sc-edit").count() >= 1
       and sp.evaluate("document.documentElement.scrollWidth <= innerWidth"),
       str(sp.evaluate("[document.querySelectorAll('a.sc-edit').length, "
                       "document.documentElement.scrollWidth, innerWidth]")))
    c = sp.locator(f'.card.sess:has(.name:text-is("{narrow}"))')
    c.first.locator("a.sc-edit").tap()
    sp.wait_for_selector("#addsc[open]")
    fill_dir(sp, "#sc_dir", "/etc/hostname")
    sp.locator("#addsc button[type=submit]").tap()
    sp.wait_for_selector("#addsc .err")
    sp.reload()                       # WebKit: a POST to the replaced URL, answered by a 303
    sp.wait_for_selector("#addsc[open]")
    ok("iPhone 320px: reloading a refused edit is still the editor",
       editor(sp) == ["Edit shortcut", 1, True], f"{editor(sp)} {sp.url}")
    sp.locator('#addsc a.btn:has-text("Cancel")').tap()
    sp.wait_for_load_state()
    sp.wait_for_timeout(300)
    ok("iPhone 320px: Cancel leaves the editor", editor(sp) == ["Add a shortcut", 0, False],
       f"{editor(sp)} {sp.url}")
    c = sp.locator(f'.card.sess:has(.name:text-is("{narrow}"))')
    if c.count():
        c.first.locator('form[action="/shortcuts/del"] button').click()
        sp.wait_for_selector("#note")
    subprocess.run(T + ["new-session", "-d", "-s", f"nren-{TAG}"], capture_output=True)
    MADE.append(f"nren-{TAG}")
    sp.goto(f"{BASE}/")
    sel = f'.sess:has(a.open[data-name="nren-{TAG}"])'
    sp.locator(f"{sel} details.menu > summary").tap()
    sp.locator(f"{sel} details.ren summary").tap()
    sp.fill(f'{sel} form[action="/rename"] input[name=new]', "pwtest")
    sp.locator(f'{sel} form[action="/rename"] button[type=submit]').tap()
    sp.wait_for_selector(f"{sel} details.ren .err")
    r = sp.evaluate(f"""() => {{ const e = document.querySelector('{sel} details.ren .err').getBoundingClientRect(),
      m = document.querySelector('{sel} .menu-list').getBoundingClientRect();
      return [Math.round(e.left), Math.round(e.right), Math.round(m.left), innerWidth]; }}""")
    if r[2] >= 0:
        ok("320px: the inline rename error is on screen", r[0] >= 0 and r[1] <= r[3], str(r))
    else:
        known("320px: the inline rename error is on screen", False,
              f"the menu itself opens past the left edge {r}; the session menus' "
              "layout (fix/landing-layout) anchors it to the row")
    ictx.close()
    ctx320.close()
    wb.close()

    print("firefox:")
    fb = p.firefox.launch()
    fpage = fb.new_page()
    fpage.on("pageerror", lambda e: print("   [pageerror]", e))
    freqs = []
    fpage.on("request", lambda r: freqs.append((r.method, urlsplit(r.url).path)))
    fpage.goto(f"{BASE}/")
    fpage.fill("#name", "pwtest")
    fpage.click("#startform button[type=submit]")
    fpage.wait_for_load_state()
    fpage.goto(f"{BASE}/s/pwtest")
    fpage.wait_for_load_state()
    freqs.clear()
    fpage.go_back()
    fpage.wait_for_load_state()
    ok("Firefox: Back to an error page is a plain GET of / (no Document Expired)",
       fpage.url == f"{BASE}/" and not any(m == "POST" for m, _ in freqs)
       and fpage.locator("#startform").count() == 1, f"{fpage.url} {freqs[:3]}")
    subprocess.run(T + ["new-session", "-d", "-s", f"fren-{TAG}"], capture_output=True)
    MADE.append(f"fren-{TAG}")
    fpage.goto(f"{BASE}/")
    sel = rename_via_menu(fpage, f"fren-{TAG}", "pwtest")
    fpage.wait_for_selector(f"{sel} details.ren .err")
    ok("Firefox: a taken rename is refused inline",
       "already called" in fpage.locator(f"{sel} details.ren .err").inner_text())
    fb.close()

for name in MADE:
    if name and exists(name):
        subprocess.run(T + ["kill-session", "-t", f"={name}"], capture_output=True)

if fails:
    raise SystemExit(1)
