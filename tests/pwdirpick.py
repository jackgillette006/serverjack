"""The directory picker (.dirpick, DIRPICK_JS/DIRPICK_CSS in bin/serverjack):
what a typed folder name submits (an exact name over a partial one, a name
the list never showed, a name the page put in the box), the "+ New folder"
row, touch scrolling and drill-down, keyboard and mouse behaviour, late
lookups, layout (the list is in flow, so nothing under it is covered -- real
clicks, slow ones too -- and the folder name always shows), and the server
never creating a folder before a session really starts in it.

Self-contained: it builds its own fixture tree under the server's HOME with
`tmux run-shell` -- so the folders belong to the account serverjack runs as,
not to this container's root -- and removes it at the end. It works against
run.sh's harness and against any other throwaway instance (SERVERJACK_TEST_BASE
+ TMUX_SOCK). The default directory is set to ~ for the run and put back.
Each block runs on its own, so one that breaks early still lets the rest run.

Chromium/Firefox/WebKit desktop, WebKit iPhone 14 and SE, and Chromium Pixel
7 for the one thing only Chromium can drive: a real touch swipe (CDP).
Emulated WebKit is not iOS Safari -- docs/MANUAL-TESTS.md lists the picker
checks only a real iPhone can settle.
"""
import os
import re
import subprocess
import time
from urllib.parse import quote

from playwright.sync_api import sync_playwright

BASE = os.environ.get("SERVERJACK_TEST_BASE", "http://127.0.0.1:7690")
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]
TAG = str(int(time.time()))[-6:]
SAME = {"Sec-Fetch-Site": "same-origin"}
LONGP = "a-really-long-parent-directory-name-for-the-overflow-check"
LEAF = "with-a-nested-leaf-folder"
NEW = f"pwdp-new-{TAG}"
EX = f"pwex{TAG}"           # a folder name that is also part of a shallower one
DOT = f"v1.{TAG}"           # a dotted folder name, for "." meaning the default dir
MADE = []
fails = 0

# Delays /api/dirs by window.__dirDelay ms, for the late-answer checks.
SLOW_FETCH = """(() => {
  const f = window.fetch;
  window.__dirDelay = 0;
  window.fetch = function (u, o) {
    if (String(u).indexOf('/api/dirs') < 0 || !window.__dirDelay) return f.apply(this, arguments);
    return new Promise(r => setTimeout(r, window.__dirDelay)).then(() => f(u, o));
  };
})();"""

# The list has caught up with a typed "3d" (not still showing an earlier answer).
HAS_3D = "n >= 2 && l.querySelector('li').dataset.show.indexOf('3d') >= 0"


def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + extra) if extra and not cond else ""))
    return bool(cond)


def block(title, fn, *args):
    """One self-contained group of checks; a crash fails it and moves on."""
    global fails
    print(title + ":")
    try:
        fn(*args)
    except Exception as e:      # noqa: BLE001 -- report and carry on with the next block
        fails += 1
        print(f"  FAIL {title} stopped early -- {str(e).splitlines()[0]}")


def tmux(*args):
    return subprocess.run(T + list(args), capture_output=True, text=True).stdout.strip()


def cwd_of(name):
    return tmux("display", "-p", "-t", f"={name}:", "#{pane_current_path}")


def sess_from_url(page):
    m = re.search(r"/s/([^/?#]+)", page.url)
    return m.group(1) if m else ""


def dev(p, name):
    d = dict(p.devices[name])
    d.pop("default_browser_type", None)
    return d


def new_page(b, **ctxargs):
    ctx = b.new_context(**ctxargs)
    page = ctx.new_page()
    page.set_default_timeout(10000)
    page.on("pageerror", lambda e: print("   [pageerror]", e))
    return ctx, page


def started(page):
    """Wait for a Start to land on the terminal page; the session it made."""
    page.wait_for_selector("#tabs .tab.on", timeout=15000)
    s = sess_from_url(page)
    if s:
        MADE.append(s)
    return s


def list_open(page, sel):
    return page.evaluate(f"!document.querySelector('{sel} .dirlist').hidden")


def wait_rows(page, sel, test="n > 0", timeout=8000):
    page.wait_for_function(
        f"(() => {{ const l = document.querySelector('{sel} .dirlist');"
        f" const n = l && !l.hidden ? l.querySelectorAll('li').length : 0; return {test}; }})()",
        timeout=timeout)


def leaf_fits(page, sel):
    """Is the bold folder name of the first row whole and inside its row?"""
    page.wait_for_function(f"(() => {{ const b = document.querySelector('{sel} .dirlist li b');"
                           f" return b && b.textContent === '{LEAF}'; }})()")
    return page.evaluate(f"""(() => {{ const li = document.querySelector('{sel} .dirlist li'),
        b = li.querySelector('b'), r = b.getBoundingClientRect(), lr = li.getBoundingClientRect(),
        rest = li.querySelector('.rest');
        return {{inside: r.left >= lr.left && r.right <= lr.right, whole: b.scrollWidth <= b.clientWidth + 1,
                 cut: !!rest && rest.scrollWidth > rest.clientWidth}}; }})()""")


def wait_index(q, want, timeout=30):
    """Wait for the name-search index (cached ~20 s) to hold every path
    ending in one of want for the query q."""
    end, shows = time.time() + timeout, []
    while time.time() < end:
        shows = [d["show"] for d in api.get("/api/dirs?q=" + quote(q)).json().get("dirs", [])]
        if all(any(s.endswith(w) for s in shows) for w in want):
            break
        time.sleep(1)
    return shows


def hit_ok(page, sel):
    """Is the element itself what a click at its centre would land on?"""
    return page.evaluate("""(s) => { const e = document.querySelector(s);
        e.scrollIntoView({block: 'center'});
        const r = e.getBoundingClientRect();
        const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return h === e || e.contains(h) ? 'ok' : (h && (h.closest('li') ? 'LI' : h.tagName)); }""", sel)


def flash(page):
    return page.locator(".flash").inner_text() if page.locator(".flash").count() else ""


# ------------------------------------------------------------------ blocks --
def server_checks():
    r = api.post("/start", form={"what": "shell", "dir": f"{ROOT_SHOW}/fail-start", "name": TAKEN},
                 max_redirects=0)
    ok("a Start refused for its name is a 400", r.status == 400, str(r.status))
    ok("...and leaves no folder behind", not os.path.isdir(f"{ROOT}/fail-start"))
    r = api.post("/api/new", form={"kind": "shell", "dir": f"{ROOT_SHOW}/fail-new", "name": TAKEN})
    ok("the terminal panel's refused start leaves no folder either",
       "error" in r.json() and not os.path.isdir(f"{ROOT}/fail-new"), r.text())
    r = api.post("/shortcuts/add", form={"label": f"pwdp-{TAG}", "cmd": "true",
                                         "dir": f"{ROOT_SHOW}/gmae"}, max_redirects=0)
    ok("saving a shortcut for a folder that doesn't exist is refused, in ~ form",
       r.status == 400 and f"Not a directory: {ROOT_SHOW}/gmae" in r.text(), f"{r.status}")
    ok("...creates nothing", not os.path.isdir(f"{ROOT}/gmae"))
    ok("...and stores nothing", f"pwdp-{TAG}" not in api.get("/").text())
    r = api.post("/start", form={"what": "shell", "dir": f"{ROOT_SHOW}/kids/x\x00y"},
                 max_redirects=0)
    ok("a directory with a NUL byte is a clean 400, not a crash", r.status == 400, str(r.status))
    js = api.get("/api/dirs?q=" + quote(NEW)).json()
    ok("/api/dirs offers the folder a name would create, in ~ form",
       (js.get("create") or {}).get("show") == f"~/{NEW}", str(js.get("create")))
    js = api.get("/api/dirs?q=" + quote(f"{ROOT_SHOW}/kids")).json()
    ok("...and nothing for a folder that already exists", "create" not in js, str(js.get("create")))


def desktop(p, eng):
    b = getattr(p, eng).launch()
    try:
        _ctx, page = new_page(b, viewport={"width": 1280, "height": 800})
        page.goto(f"{BASE}/")
        dirbox = page.locator("#dir")

        # Tab / Shift+Tab out of an untouched field: focus moves, nothing filled.
        page.focus("#dir")
        wait_rows(page, "#startform")
        page.keyboard.press("Tab")
        ok("Tab out of an untouched field moves on and leaves it empty",
           page.evaluate("document.activeElement.id") == "name" and dirbox.input_value() == "",
           f"{page.evaluate('document.activeElement.id')!r} {dirbox.input_value()!r}")
        page.keyboard.press("Shift+Tab")
        wait_rows(page, "#startform")
        page.keyboard.press("Shift+Tab")
        ok("Shift+Tab out of it goes back, never completes",
           page.evaluate("document.activeElement.name") == "what" and dirbox.input_value() == "",
           f"{page.evaluate('document.activeElement.name')!r} {dirbox.input_value()!r}")
        dirbox.fill("3d")
        wait_rows(page, "#startform")
        page.keyboard.press("Shift+Tab")
        ok("Shift+Tab after typing doesn't drill down either",
           dirbox.input_value() == "3d" and page.evaluate("document.activeElement.id") != "dir",
           dirbox.input_value())

        # The mouse: hover highlights, right-click and padding keep everything.
        page.goto(f"{BASE}/")
        dirbox.click()
        dirbox.fill(f"{ROOT_SHOW}/")
        wait_rows(page, "#startform", "n >= 14")
        rows = page.locator("#startform .dirlist li")
        ok("a typed path highlights nothing by default (Enter keeps it as typed)",
           page.locator('#startform .dirlist li[aria-selected="true"]').count() == 0)
        rows.nth(2).hover()
        ok("hovering a row highlights it", rows.nth(2).get_attribute("aria-selected") == "true")
        page.mouse.move(5, 5)
        ok("...and leaving the list puts the highlight back",
           page.locator('#startform .dirlist li[aria-selected="true"]').count() == 0)
        rows.nth(3).click(button="right")
        page.wait_for_timeout(300)
        ok("right-click on a row picks nothing and keeps the list",
           dirbox.input_value() == f"{ROOT_SHOW}/" and list_open(page, "#startform")
           and page.evaluate("document.activeElement.id") == "dir", dirbox.input_value())
        box = page.locator("#startform .dirlist").bounding_box()
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + 2)   # top padding, clear of the rounded corners
        page.wait_for_timeout(400)
        ok("a click on the list's padding keeps focus and the list",
           page.evaluate("document.activeElement.id") == "dir" and list_open(page, "#startform"))
        target = rows.nth(1).get_attribute("data-show")
        rows.nth(1).click()
        ok("a click picks the row and keeps focus in the field",
           dirbox.input_value() == target and page.evaluate("document.activeElement.id") == "dir",
           f"{dirbox.input_value()!r} vs {target!r}")
    finally:
        b.close()


def desktop_layout(p):
    b = p.chromium.launch()
    try:
        _ctx, page = new_page(b, viewport={"width": 1280, "height": 800})
        # The aria wiring.
        page.goto(f"{BASE}/")
        a11y = page.evaluate("""(() => { const i = document.querySelector('#dir'),
            l = document.getElementById(i.getAttribute('aria-controls') || '-');
            return {list: !!l && l.getAttribute('role') === 'listbox' && !!l.getAttribute('aria-label'),
                    dir: i.getAttribute('aria-label'),
                    name: document.querySelector('#name').getAttribute('aria-label'),
                    cmd: document.querySelector('#cmd').getAttribute('aria-label')}; })()""")
        ok("the combobox controls a named listbox and every Start field has a name",
           a11y["list"] and a11y["dir"] and a11y["name"] and a11y["cmd"], str(a11y))

        # The default-dir form: the list sits in flow, Save stays clickable.
        page.click("details.ddchange summary")
        page.locator("#dd_dir").fill(ROOT_SHOW)
        wait_rows(page, "details.ddchange")
        save = page.locator('form[action="/prefs"] button[type=submit]')
        sb = save.bounding_box()
        hit = page.evaluate(f"document.elementFromPoint({sb['x'] + sb['width'] / 2}, {sb['y'] + sb['height'] / 2}).tagName")
        ok("the default-dir form's Save isn't under the list", hit == "BUTTON", hit)
        # /prefs answers /?done=dir, which the page script then strips from
        # the address: catch the navigation itself, not the address after it.
        with page.expect_navigation(url="**done=dir**"):
            save.click()
        ok("...and one click saves what was typed", f"Default directory: {ROOT_SHOW}" in flash(page), flash(page))
        api.post("/prefs", form={"dir": "~"})

        # The Start card with a mouse: the list is in flow there too, so the
        # fields and the button under it are where they look.
        page.goto(f"{BASE}/")
        page.click("#dir")
        page.locator("#dir").fill(f"{ROOT_SHOW}/")          # 16 rows: the list at its full height
        wait_rows(page, "#startform", "n >= 14")
        pos = page.evaluate("getComputedStyle(document.querySelector('#startform .dirlist')).position")
        name_hit, start_hit = hit_ok(page, "#name"), hit_ok(page, 'form[action="/start"] button[type=submit]')
        ok("on a desktop the open list covers neither Name nor Start",
           pos == "static" and name_hit == "ok" and start_hit == "ok", f"{pos} {name_hit} {start_hit}")
        # A slow click (button held 400 ms) on Start with the list open: the
        # field's blur must not close the list mid-press and move Start up.
        page.locator("#dir").fill(f"{ROOT_SHOW}/kids")
        wait_rows(page, "#startform")
        sb = page.locator('form[action="/start"] button[type=submit]').bounding_box()
        page.mouse.move(sb["x"] + sb["width"] / 2, sb["y"] + sb["height"] / 2)
        page.mouse.down()
        page.wait_for_timeout(400)
        page.mouse.up()
        s = started(page)
        ok("...and a slow click on Start still starts it", cwd_of(s).endswith(f"/pwdp-{TAG}/kids"), cwd_of(s))

        # A tool card. The picker sits in the row that uses it (run.sh's
        # "here" action; a card with nothing that reads a directory has no
        # picker at all), and that row's button sits beside the field. The
        # list opens in flow under the field: a button level with the list's
        # bottom moved every time the list opened or changed length, and a
        # dropdown over the card covered the row below (Log in).
        page.goto(f"{BASE}/")
        page.click("#tool-fake summary")
        run = '#tool-fake button[name=do][form="d-fake"]'
        login = '#tool-fake button[value="/tools/login"]'
        tbox = page.locator("#tool-fake .dirpick input")

        def doc_y(sel):
            return page.evaluate("""(s) => Math.round(
                document.querySelector(s).getBoundingClientRect().top + scrollY)""", sel)
        ys = [doc_y(run)]
        tbox.fill(f"{ROOT_SHOW}/")                  # 16 rows: the list at its full height
        wait_rows(page, "#tool-fake", "n >= 14")
        ys.append(doc_y(run))
        tbox.fill("3d")
        wait_rows(page, "#tool-fake", HAS_3D)
        ys.append(doc_y(run))
        ok("a tool card's button stays where it was while its list opens and changes length",
           len(set(ys)) == 1, f"y closed/full/3d: {ys}")
        login_hit, run_hit = hit_ok(page, login), hit_ok(page, run)
        page.click(run)
        ok("...the open list covers neither it nor the row below, and one real click runs it",
           login_hit == "ok" and run_hit == "ok" and bool(started(page)), f"{login_hit} {run_hit}")

        # The terminal's new-session panel.
        page.goto(f"{BASE}/s/{TAKEN}")
        page.click("#add")
        page.click("label[for=pop_name]")
        ok("the panel's Name label focuses its field", page.evaluate("document.activeElement.id") == "pop_name")
        page.click("label[for=pop_dir]")
        ok("...and Directory focuses the picker", page.evaluate("document.activeElement.id") == "pop_dir")
        wait_rows(page, "#pop")
        btn = page.locator("#pop button[type=submit]").bounding_box()
        hit = page.evaluate(f"(() => {{ const e = document.elementFromPoint({btn['x'] + btn['width'] / 2},"
                            f" {btn['y'] + btn['height'] / 2}); return e && (e.closest('button') || e).textContent; }})()")
        ok("the open list doesn't cover the panel's Start & open", "Start" in (hit or ""), repr(hit))
        page.fill("#pop_dir", f"{ROOT_SHOW}/{LONGP}/")
        fit = leaf_fits(page, "#pop")
        ok("in the 360px panel the folder name shows whole, the parent is what's cut",
           fit["inside"] and fit["whole"] and fit["cut"], str(fit))
    finally:
        b.close()


def submit_checks(p):
    b = p.chromium.launch()
    try:
        ctx, page = new_page(b, viewport={"width": 1280, "height": 800})
        page.close()
        ctx.add_init_script(SLOW_FETCH)
        page = ctx.new_page()
        page.set_default_timeout(10000)
        dirbox = page.locator("#dir")

        page.goto(f"{BASE}/")
        dirbox.fill("3d")
        wait_rows(page, "#startform", HAS_3D)
        top = page.locator("#startform .dirlist li").first
        want, want_show = top.get_attribute("data-path"), top.get_attribute("data-show")
        ok("a typed name highlights its top match", top.get_attribute("aria-selected") == "true")
        ok("...and offers a new folder only as an explicit last row",
           page.locator("#startform .dirlist li").last.get_attribute("data-create") == "1")
        page.click('form[action="/start"] button[type=submit]')     # a real click, list still up
        s = started(page)
        ok("Start with a typed name starts in the folder it matched",
           os.path.realpath(cwd_of(s)) == os.path.realpath(want), f"{cwd_of(s)!r} vs {want!r}")
        ok("...and no new folder by that name appears", not os.path.isdir(f"{HOME}/3d"))

        # With the list dismissed, a partial name is never swapped unseen:
        # Start shows the list again, and the next Start takes its highlight.
        page.goto(f"{BASE}/")
        dirbox.fill("3d")
        wait_rows(page, "#startform", HAS_3D)
        dirbox.press("Escape")
        page.click('form[action="/start"] button[type=submit]')
        wait_rows(page, "#startform", HAS_3D)
        sel = page.locator('#startform .dirlist li[aria-selected="true"]')
        ok("Start with a partial name and the list dismissed shows the list again instead",
           page.url.rstrip("/") == BASE and sel.count() == 1 and sel.get_attribute("data-show") == want_show
           and page.evaluate("document.activeElement.id") == "dir", page.url)
        page.click('form[action="/start"] button[type=submit]')
        s = started(page)
        ok("...and Start again starts in the highlighted match",
           os.path.realpath(cwd_of(s)) == os.path.realpath(want), f"{cwd_of(s)!r} vs {want!r}")

        # An exact folder name beats a shallower partial match: pwexN is
        # ~/pwdp-N/d00/pwexN, though ~/pwdp-N/x-pwexN ranks above it.
        shows = wait_index(EX, [f"/x-{EX}", f"/d00/{EX}"])
        page.goto(f"{BASE}/")
        dirbox.fill(EX)
        wait_rows(page, "#startform", "n >= 2")
        sel = page.locator('#startform .dirlist li[aria-selected="true"]')
        ok("a typed name highlights the folder of exactly that name, not the top row",
           page.locator("#startform .dirlist li").first.get_attribute("data-show").endswith(f"/x-{EX}")
           and sel.get_attribute("data-show") == f"{ROOT_SHOW}/d00/{EX}", str(shows))
        dirbox.press("Escape")
        page.click('form[action="/start"] button[type=submit]')
        s = started(page)
        ok("...and with the list dismissed Start goes straight there (one folder of that name)",
           cwd_of(s).endswith(f"/d00/{EX}"), cwd_of(s))

        # A name the page put in the box (a restored draft) was never looked
        # up: Start looks it up first rather than sending it as a new folder.
        page.goto(f"{BASE}/")
        page.evaluate(f"document.querySelector('#dir').value = '{EX}'")
        page.click('form[action="/start"] button[type=submit]')
        s = started(page)
        ok("a name put in the box by the page starts in its folder, not a new one",
           cwd_of(s).endswith(f"/d00/{EX}") and not os.path.isdir(f"{HOME}/{EX}"), cwd_of(s))
        page.goto(f"{BASE}/")
        page.evaluate("window.__dirDelay = 300; document.querySelector('#dir').value = '3d'")
        page.click('form[action="/start"] button[type=submit]')
        wait_rows(page, "#startform", HAS_3D)
        ok("...and a partial one shows the list rather than starting anywhere",
           page.url.rstrip("/") == BASE and not os.path.isdir(f"{HOME}/3d"), page.url)
        page.evaluate("window.__dirDelay = 0")

        # "." is the default directory (~ for this run), not a search for dots.
        wait_index(".", [f"/{DOT}"])
        page.goto(f"{BASE}/")
        dirbox.fill(".")
        page.wait_for_timeout(400)
        page.click('form[action="/start"] button[type=submit]')
        s = started(page)
        ok('"." starts in the default directory, not a dotted folder',
           os.path.realpath(cwd_of(s)) == os.path.realpath(HOME), cwd_of(s))

        # What a script without a submit (a tool card's "start at boot") gets.
        page.goto(f"{BASE}/")
        page.click("#tool-fake summary")
        tbox = page.locator("#tool-fake .dirpick input")
        tbox.fill("3d")
        wait_rows(page, "#tool-fake", HAS_3D)
        tbox.press("Escape")
        got = page.evaluate("document.querySelector('#tool-fake .dirpick input').dirValue()")
        page.wait_for_timeout(200)
        ok("dirValue(): a partial name with the list dismissed is null, and the list shows again",
           got is None and list_open(page, "#tool-fake"), repr(got))
        tbox.fill(EX)
        wait_rows(page, "#tool-fake", f"n >= 2 && l.querySelector('li').dataset.show.endsWith('/x-{EX}')")
        tbox.press("Escape")
        got = page.evaluate("document.querySelector('#tool-fake .dirpick input').dirValue()")
        ok("...and an exact one is that folder", got == f"{ROOT_SHOW}/d00/{EX}", repr(got))

        page.goto(f"{BASE}/")
        dirbox.fill(NEW)
        wait_rows(page, "#startform", "n === 1")
        row = page.locator("#startform .dirlist li").first
        ok("a name that matches nothing shows just the + New folder row",
           row.get_attribute("data-create") == "1" and "New folder" in row.inner_text(), row.inner_text())
        row.click()
        ok("...which fills in the path it will create", dirbox.input_value() == f"~/{NEW}", dirbox.input_value())
        ok("...without creating anything yet", not os.path.isdir(f"{HOME}/{NEW}"))
        page.click('form[action="/start"] button[type=submit]')
        s = started(page)
        ok("starting there creates it and starts in it",
           os.path.isdir(f"{HOME}/{NEW}") and cwd_of(s).endswith(f"/{NEW}"), cwd_of(s))

        page.goto(f"{BASE}/")
        dirbox.fill(f"{ROOT_SHOW}/brand/new")
        page.wait_for_timeout(500)
        dirbox.press("Enter")
        s = started(page)
        ok("a typed path that doesn't exist is still created on Enter",
           cwd_of(s).endswith("/brand/new") and os.path.isdir(f"{ROOT}/brand/new"), cwd_of(s))

        # Go/Enter right after typing, before the answer: still the top match.
        page.goto(f"{BASE}/")
        page.evaluate("window.__dirDelay = 400")
        dirbox.fill("3d")
        dirbox.press("Enter")
        page.wait_for_function("document.querySelector('#dir').value.startsWith('~') || location.pathname !== '/'")
        ok("Enter before the list catches up waits for it and takes the top match",
           "/s/" not in page.url and dirbox.input_value() == want_show,
           page.url if "/s/" in page.url else dirbox.input_value())
        ok("...creating nothing", not os.path.isdir(f"{HOME}/3d"))

        # Late answers (a slow network) never reopen a closed list.
        page.goto(f"{BASE}/")
        page.evaluate("window.__dirDelay = 700")
        dirbox.fill("pro")
        page.wait_for_timeout(200)          # the lookup is in flight now
        dirbox.press("Escape")
        page.wait_for_timeout(1500)
        ok("Escape before the answer arrives: the list stays closed", not list_open(page, "#startform"))
        page.focus("#dir")
        page.wait_for_timeout(120)
        page.focus("#name")
        page.wait_for_timeout(1500)
        ok("leaving the field before the answer: no list over the next field",
           not list_open(page, "#startform"))
        page.focus("#dir")
        dirbox.fill("proj")
        wait_rows(page, "#startform")
        page.keyboard.type("e")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        picked = dirbox.input_value()
        page.wait_for_timeout(1500)
        ok("a pick while an answer is on its way: it stays picked and closed",
           picked.startswith("~") and dirbox.input_value() == picked and not list_open(page, "#startform"),
           f"{picked!r} -> {dirbox.input_value()!r}")
        page.evaluate("window.__dirDelay = 0")
        page.focus("#name")
        page.focus("#dir")
        wait_rows(page, "#startform")
        page.focus("#name")
        page.wait_for_timeout(40)
        page.focus("#dir")
        page.wait_for_timeout(400)
        ok("blur and straight back: the list stays open", list_open(page, "#startform"))
        dirbox.fill("")
        page.keyboard.type("proj", delay=30)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        ok("Escape right after typing (no network delay): stays closed", not list_open(page, "#startform"))
    finally:
        b.close()


def phone(p, name):
    b = p.webkit.launch()
    try:
        _ctx, page = new_page(b, **dev(p, name))
        page.goto(f"{BASE}/")
        dirbox = page.locator("#dir")
        dirbox.tap()
        wait_rows(page, "#startform")
        cover = page.evaluate("""(() => { const c = s => { const e = document.querySelector(s),
            r = e.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
            if (y > innerHeight) return 'offscreen';
            const h = document.elementFromPoint(x, y); return h === e || e.contains(h) ? 'ok' : (h && h.tagName); };
            return {name: c('#name'), pos: getComputedStyle(document.querySelector('#startform .dirlist')).position}; })()""")
        ok("the open list pushes Name down instead of covering it",
           cover["name"] in ("ok", "offscreen") and cover["pos"] == "static", str(cover))

        if name == "iPhone 14":
            # Go (Enter) on a typed name takes the top match, a second Go starts there.
            dirbox.fill("3d")
            wait_rows(page, "#startform", HAS_3D)
            first = page.locator("#startform .dirlist li").first
            want_show, want = first.get_attribute("data-show"), first.get_attribute("data-path")
            dirbox.press("Enter")
            page.wait_for_timeout(300)
            ok("Go on a typed name fills its top match and doesn't submit yet",
               "/s/" not in page.url and dirbox.input_value() == want_show,
               page.url if "/s/" in page.url else dirbox.input_value())
            dirbox.press("Enter")
            s = started(page)
            ok("...and Go again starts there", os.path.realpath(cwd_of(s)) == os.path.realpath(want), cwd_of(s))
            ok("...with no new folder by the typed name", not os.path.isdir(f"{HOME}/3d"))

            # The › on a row drills in, the way Tab does from a keyboard.
            page.goto(f"{BASE}/")
            dirbox.tap()
            dirbox.fill(f"{ROOT_SHOW}/")
            wait_rows(page, "#startform", "n >= 14")
            page.locator('#startform .dirlist li[data-show$="/kids"] .into').tap()
            page.wait_for_function("document.querySelector('#dir').value.endsWith('/kids/')")
            wait_rows(page, "#startform",
                      "n === 1 && l.querySelector('li').dataset.show.endsWith('/kids/inner')")
            ok("tapping › shows that folder's subfolders and keeps the keyboard's field",
               dirbox.input_value() == f"{ROOT_SHOW}/kids/" and page.evaluate("document.activeElement.id") == "dir",
               dirbox.input_value())
            page.locator("#startform .dirlist li").first.tap()
            ok("...and tapping a row picks it", dirbox.input_value() == f"{ROOT_SHOW}/kids/inner",
               dirbox.input_value())

            # A name the page put in the box, then a tap on Start: looked up
            # first, then sent as its folder.
            wait_index(EX, [f"/d00/{EX}"])
            page.goto(f"{BASE}/")
            page.evaluate(f"document.querySelector('#dir').value = '{EX}'")
            page.tap('form[action="/start"] button[type=submit]')
            s = started(page)
            ok("a name the page put in the box, then Start: its folder", cwd_of(s).endswith(f"/d00/{EX}"), cwd_of(s))

        # The folder name stays visible under a long parent.
        page.goto(f"{BASE}/")
        dirbox.tap()
        dirbox.fill(f"{ROOT_SHOW}/{LONGP}/")
        fit = leaf_fits(page, "#startform")
        ok("a long parent path is cut, the folder name shows whole",
           fit["inside"] and fit["whole"] and fit["cut"], str(fit))

        # The terminal's new-session sheet: the list fits, Start & open stays reachable.
        page.goto(f"{BASE}/s/{TAKEN}")
        page.wait_for_selector("#tabs .tab.on")
        page.tap("#add")
        page.locator("#pop input[name=dir]").tap()
        page.locator("#pop input[name=dir]").fill(f"{ROOT_SHOW}/")
        wait_rows(page, "#pop", "n >= 14")
        geo = page.evaluate("""(() => { const pop = document.querySelector('#pop'),
            l = pop.querySelector('.dirlist'), bar = document.querySelector('#bar');
            return {lb: l.getBoundingClientRect().bottom, vh: innerHeight, pt: pop.getBoundingClientRect().top,
                    bb: bar.getBoundingClientRect().bottom}; })()""")
        ok("in the sheet the whole list is on screen, below the bar",
           geo["lb"] <= geo["vh"] and geo["pt"] >= geo["bb"] - 1, str(geo))
        hit = page.evaluate("""(() => { const pop = document.querySelector('#pop'); pop.scrollTop = pop.scrollHeight;
            const b = pop.querySelector('button[type=submit]'), r = b.getBoundingClientRect();
            const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
            return h === b || b.contains(h); })()""")
        ok("...and Start & open is never under the list", hit)
        kb = page.evaluate("""(() => { document.body.style.height = '300px';   // what fit() does with the keyboard up
            const pop = document.querySelector('#pop'); pop.scrollTop = 0;
            const r = pop.getBoundingClientRect(), n = pop.querySelector('input[name=name]').getBoundingClientRect();
            return {top: r.top, bottom: r.bottom, scrolls: pop.scrollHeight > pop.clientHeight, name: n.top >= r.top}; })()""")
        ok("with the keyboard up the sheet stays on screen and scrolls instead",
           kb["top"] >= 0 and kb["bottom"] <= 301 and kb["scrolls"] and kb["name"], str(kb))
    finally:
        b.close()


def pixel(p):
    b = p.chromium.launch()
    try:
        ctx, page = new_page(b, **dev(p, "Pixel 7"))
        page.goto(f"{BASE}/")
        dirbox = page.locator("#dir")
        dirbox.tap()
        dirbox.fill(f"{ROOT_SHOW}/")
        wait_rows(page, "#startform", "n >= 14")
        r2 = page.locator("#startform .dirlist li").nth(1).bounding_box()
        x, y = r2["x"] + 40, r2["y"] + r2["height"] / 2
        cdp = ctx.new_cdp_session(page)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        for i in range(1, 13):
            cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y - 10 * i}]})
            time.sleep(0.016)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        st, prev = -1, -2
        for _ in range(20):                 # let any fling settle before aiming the tap
            page.wait_for_timeout(150)
            prev, st = st, page.evaluate("document.querySelector('#startform .dirlist').scrollTop")
            if st == prev:
                break
        ok("a swipe on the list scrolls it and picks nothing",
           dirbox.input_value() == f"{ROOT_SHOW}/" and list_open(page, "#startform") and st > 0,
           f"value={dirbox.input_value()!r} scrollTop={st}")
        # Aim at the middle of a row that is wholly in view now (the middle
        # of the list can sit on a boundary between two rows).
        aim = page.evaluate("""(() => { const l = document.querySelector('#startform .dirlist'),
            lr = l.getBoundingClientRect(), mid = lr.top + lr.height / 2;
            const rows = [...l.querySelectorAll('li')].map(li => [li, li.getBoundingClientRect()])
              .filter(([, r]) => r.top >= lr.top && r.bottom <= lr.bottom)
              .sort((a, b) => Math.abs(a[1].top + a[1].height / 2 - mid) - Math.abs(b[1].top + b[1].height / 2 - mid));
            const [li, r] = rows[0];
            return {show: li.dataset.show, x: r.left + 60, y: r.top + r.height / 2}; })()""")
        page.touchscreen.tap(aim["x"], aim["y"])
        page.wait_for_timeout(300)
        ok("...then a tap on a row scrolled into view picks it",
           dirbox.input_value() == aim["show"], f"{dirbox.input_value()!r} vs {aim['show']!r}")

        page.goto(f"{BASE}/")
        page.tap("details.ddchange summary")
        page.locator("#dd_dir").tap()
        page.locator("#dd_dir").fill(ROOT_SHOW)
        wait_rows(page, "details.ddchange")
        with page.expect_navigation(url="**done=dir**"):
            page.tap('form[action="/prefs"] button[type=submit]')
        ok("one tap on the default-dir form's Save saves what was typed",
           f"Default directory: {ROOT_SHOW}" in flash(page), flash(page))
        api.post("/prefs", form={"dir": "~"})
    finally:
        b.close()


with sync_playwright() as p:
    api = p.request.new_context(base_url=BASE, extra_http_headers=SAME)
    kids = api.get("/api/dirs?q=" + quote("~/")).json()["dirs"]
    d0 = kids[0]
    HOME = d0["path"][: len(d0["path"]) - len(d0["show"]) + 1]       # the server's own HOME
    assert HOME + d0["show"][1:] == d0["path"], (HOME, d0)
    m = re.search(r'id="dir"[^>]*placeholder="([^"]*?) · ', api.get("/").text())
    OLD_DEFAULT = m.group(1) if m else "~"
    api.post("/prefs", form={"dir": "~"})
    ROOT_SHOW, ROOT = f"~/pwdp-{TAG}", f"{HOME}/pwdp-{TAG}"
    tmux("run-shell", f"mkdir -p {ROOT}/kids/inner {ROOT}/{LONGP}/{LEAF} {ROOT}/x-{EX} {ROOT}/d00/{EX} "
         + f"{ROOT}/{DOT} " + " ".join(f"{ROOT}/d{i:02d}" for i in range(12)))
    TAKEN = api.get("/api/sessions").json()[0]["name"]
    try:
        block("server (no folder before a session starts)", server_checks)
        for eng in ("chromium", "firefox", "webkit"):
            block(f"{eng} desktop", desktop, p, eng)
        block("chromium desktop (layout, panel, labels)", desktop_layout, p)
        block("chromium desktop (what a typed name submits, late answers)", submit_checks, p)
        for name in ("iPhone 14", "iPhone SE"):
            block(f"webkit {name}", phone, p, name)
        block("chromium Pixel 7 (touch swipe)", pixel, p)
    finally:
        for s in MADE:
            tmux("kill-session", "-t", f"={s}")
        tmux("run-shell", f"rm -rf {ROOT} {HOME}/{NEW}")
        api.post("/prefs", form={"dir": OLD_DEFAULT})
        api.dispose()

if fails:
    raise SystemExit(1)
