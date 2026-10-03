"""Landing-page layout and live behaviour: what the list looks like on a phone
and a desktop, and that it keeps itself current.

Chromium desktop plus emulated WebKit iPhones (390 and 320 wide). Emulated
WebKit is not iOS Safari: these checks prove CSS geometry and page script,
not iOS-only behaviour (focus zoom, the standalone status bar, Dynamic Type),
which docs/MANUAL-TESTS.md covers on a real phone.

Uses run.sh's instance and tmux server. Sessions it needs (a long name, one
with a client attached) are made with tmux directly and killed at the end;
the two shortcuts it adds are removed again.
"""
import os
import re
import subprocess
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("SERVERJACK_TEST_BASE", "http://127.0.0.1:7690")
TAG = str(int(time.time()))[-6:]
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]
SAME = {"Sec-Fetch-Site": "same-origin"}
MADE = []
fails = 0


def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + extra) if extra and not cond else ""))
    return bool(cond)


def tmux(*args):
    return subprocess.run(T + list(args), capture_output=True, text=True)


def exists(name):
    return tmux("has-session", "-t", f"={name}").returncode == 0


def make(name):
    tmux("new-session", "-d", "-s", name, "-x", "100", "-y", "30", "sleep 900")
    MADE.append(name)
    return name


def wait_for(fn, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.25)
    return fn()


def phone(p, browser, width=None, height=None):
    d = dict(p.devices["iPhone 14"])
    d.pop("default_browser_type", None)
    if width:
        d["viewport"] = {"width": width, "height": height or 640}
    return browser.new_context(**d)


with sync_playwright() as p:
    # ------------------------------------------------------------ chrome --
    print("chromium desktop:")
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.on("pageerror", lambda e: print("   [pageerror]", e))
    page.goto(f"{BASE}/")
    ok("the page declares a dark color-scheme (dark scrollbars and checkboxes)",
       page.evaluate("getComputedStyle(document.documentElement).colorScheme") == "dark",
       page.evaluate("getComputedStyle(document.documentElement).colorScheme"))
    r = page.request.get(f"{BASE}/favicon.ico")
    ok("/favicon.ico answers with the PNG icon instead of a 404",
       r.status == 200 and r.headers.get("content-type") == "image/png"
       and r.body()[:8] == b"\x89PNG\r\n\x1a\n", f"{r.status} {r.headers.get('content-type')}")
    ctx.close()

    # ------------------------------------------- status-bar strip (iPhone) --
    print("webkit iphone 14:")
    wk = p.webkit.launch()
    ictx = phone(p, wk)
    ipage = ictx.new_page()
    ipage.on("pageerror", lambda e: print("   [pageerror]", e))
    ipage.goto(f"{BASE}/")
    # Emulated WebKit reports no safe-area inset, so stand in for the
    # home-screen app's 47px one, then scroll content under it.
    ipage.add_style_tag(content="#sbbg{height:47px!important}")
    ipage.evaluate("window.scrollTo(0, 300)")
    ipage.wait_for_timeout(300)
    strip = ipage.evaluate("""() => { const e = document.getElementById('sbbg');
      if (!e) return null; const s = getComputedStyle(e);
      return [s.position, s.backgroundColor, +s.zIndex]; }""")
    ok("a fixed, opaque strip sits behind the status bar above menus",
       bool(strip) and strip[0] == "fixed" and strip[1] == "rgb(8, 15, 14)" and strip[2] > 6, str(strip))
    ipage.screenshot(path="shots/layout-statusbar.png", clip={"x": 0, "y": 0, "width": 390, "height": 60})
    from PIL import Image
    img = Image.open("shots/layout-statusbar.png").convert("RGB")
    sx = img.width / 390.0
    band = {img.getpixel((int(x * sx), int(y * sx))) for x in range(0, 390, 13) for y in range(2, 45, 7)}
    ok("...and scrolled content no longer shows through under the clock",
       all(max(abs(c - e) for c, e in zip(px, (8, 15, 14))) <= 6 for px in band), str(sorted(band)[:6]))
    ictx.close()

    # ------------------------------------------------------- session rows --
    # A long name, and a session with a client attached (a desktop tab on it).
    dctx = b.new_context(viewport={"width": 1280, "height": 800})
    page = dctx.new_page()
    page.on("pageerror", lambda e: print("   [pageerror]", e))
    longname = make(f"pwlay-a-very-long-session-name-for-overflow-{TAG}")
    att = make(f"pwlay-att-{TAG}")
    # One shortcut in a deep directory: its row's "directory first, in full"
    # check has something to cut.
    SC_DIRS = {f"pwlay Tail the build log forever and ever {TAG}": "~",
               f"pwlay logs {TAG}": "~/projects/ai/3d-lab/scenes"}
    for label, cmd, cwd in ((f"pwlay Tail the build log forever and ever {TAG}", "tail -f /dev/null", "~"),
                            (f"pwlay logs {TAG}", "docker compose logs -f --tail=100 web",
                             "~/projects/ai/3d-lab/scenes")):
        page.request.post(f"{BASE}/shortcuts/add", headers=SAME,
                          form={"label": label, "cmd": cmd, "dir": cwd})
    hold = b.new_context(viewport={"width": 1000, "height": 600}).new_page()
    hold.goto(f"{BASE}/s/{att}")
    wait_for(lambda: tmux("display", "-p", "-t", f"={att}:", "#{session_attached}").stdout.strip() not in ("", "0"))
    # SF Mono / Consolas are ~0.6em wide; the container's fallback mono is
    # 0.5em and would under-report clipping, so measure with a 0.6em face.
    MONO = ":root{--font-mono:'Liberation Mono',monospace!important}"
    for w in (390, 320):
        c = phone(p, wk, w, 700)
        pg = c.new_page()
        pg.goto(f"{BASE}/")
        pg.add_style_tag(content=MONO)
        pg.wait_for_timeout(200)
        rows = pg.evaluate("""() => [...document.querySelectorAll('.sess[data-session]')].map(r => {
          const nm = r.querySelector('.name .nm'), name = r.querySelector('.name'),
                meta = r.querySelector('.meta'), f = r.querySelector('.facts'),
                a = r.querySelector('.att'), mr = meta.getBoundingClientRect();
          return {n: r.dataset.session, title: name.title, ell: getComputedStyle(nm).textOverflow,
                  clipped: nm.scrollWidth > nm.clientWidth + 1, nmText: nm.textContent,
                  facts: f.textContent, factsLeft: f.getBoundingClientRect().left - mr.left,
                  factsFit: f.scrollWidth <= f.clientWidth + 1,
                  attRight: a ? a.getBoundingClientRect().right - mr.right : null,
                  dot: r.querySelector('.dot').getAttribute('aria-label')}; })""")
        lr = next((r for r in rows if r["n"] == longname), None)
        ok(f"{w}px: a long session name ends in an ellipsis and keeps its full name as a title",
           bool(lr) and lr["clipped"] and lr["ell"] == "ellipsis" and lr["title"] == longname
           and lr["nmText"] == longname, str(lr))
        ok(f"{w}px: every row's meta starts with the short facts (attached, windows, age)",
           rows and all(r["factsLeft"] <= 1
                        and re.match(r"(attached · )?(\d+ windows · )?up (<1m|\d+[mhd])$", r["facts"])
                        for r in rows),
           str([(r["n"], r["facts"], r["factsLeft"]) for r in rows]))
        if w >= 390:
            ok(f"{w}px: ...shown in full, not cut by the path",
               all(r["factsFit"] for r in rows), str([(r["n"], r["facts"]) for r in rows if not r["factsFit"]]))
        ar = next((r for r in rows if r["n"] == att), None)
        ok(f"{w}px: an attached session says 'attached' in words, first, fully visible",
           bool(ar) and ar["facts"].startswith("attached") and ar["attRight"] is not None
           and ar["attRight"] <= 0.5 and ar["dot"] == "attached", str(ar))
        ok(f"{w}px: the status dot has a text alternative on every row",
           all(r["dot"] in ("attached", "not attached") for r in rows), str([r["dot"] for r in rows]))
        # The directory is an inline span in a wrapping meta line, so it has
        # no scroll box of its own to measure: "first" is its first line box
        # at the meta's left edge, "in full" every line box of it inside the
        # meta, which itself is not clipped.
        sc = pg.evaluate("""() => [...document.querySelectorAll('.sess:not([data-session]):not(#sc-update)')].map(r => {
          const nm = r.querySelector('.nm'), f = r.querySelector('.facts'), m = f && f.parentElement;
          const mr = m && m.getBoundingClientRect(), fr = f ? [...f.getClientRects()] : [];
          return {t: nm.textContent, title: r.querySelector('.name').title, ell: getComputedStyle(nm).textOverflow,
                  dir: f ? f.textContent : null,
                  first: !!f && m.firstElementChild === f && fr.length > 0 && Math.abs(fr[0].left - mr.left) <= 1,
                  dirFit: !!f && fr.length > 0 && fr.every(x => x.left >= mr.left - 1 && x.right <= mr.right + 1)
                          && (getComputedStyle(m).overflowX === 'visible' || m.scrollWidth <= m.clientWidth + 1)}; })""")
        mine = [x for x in sc if x["t"].startswith("pwlay ")]
        ok(f"{w}px: shortcut rows show their directory first, in full",
           len(mine) == 2 and all(x["dir"] == SC_DIRS.get(x["t"]) and x["first"] and x["dirFit"] for x in mine),
           str(mine))
        ok(f"{w}px: a long shortcut label ends in an ellipsis with the full label as a title",
           all(x["ell"] == "ellipsis" and x["title"] == x["t"] for x in mine), str(mine))
        pill = pg.evaluate("""() => { const u = document.querySelector('#sc-update .name');
          if (!u) return null; const p = u.querySelector('.pill').getBoundingClientRect(),
          n = u.getBoundingClientRect(); return [p.right - n.right, p.width]; }""")
        ok(f"{w}px: the built-in pill is never sliced",
           pill is None or (pill[0] <= 0.5 and pill[1] > 50), str(pill))
        pg.screenshot(path=f"shots/layout-rows-{w}.png", full_page=True)
        c.close()

    # ------------------------------------- sessions above the fold (F29) --
    # With sessions running they lead the page, so a row is on the first
    # screen of a phone and a laptop (this fixture has the built-in Update
    # row plus at least two shortcuts above them in the old order).
    for label, mk in (("iPhone 14 390x664", lambda: phone(p, wk, 390, 664)),
                      ("iPhone SE 320x568", lambda: phone(p, wk, 320, 568)),
                      ("desktop 1280x720", lambda: b.new_context(viewport={"width": 1280, "height": 720}))):
        c = mk()
        pg = c.new_page()
        pg.goto(f"{BASE}/")
        geo = pg.evaluate("""() => { const h = document.getElementById('sessions'),
          r = document.querySelector('.sess[data-session]');
          return [h.getBoundingClientRect().top, r.getBoundingClientRect().bottom, innerHeight,
                  document.querySelectorAll('.sess:not([data-session])').length]; }""")
        ok(f"{label}: the Sessions heading and its first row are on the first screen",
           geo[1] <= geo[2] and geo[3] >= 3, str(geo))
        c.close()

    # ------------------------------------- touch targets on a phone (F73) --
    c = phone(p, wk)
    pg = c.new_page()
    pg.goto(f"{BASE}/")
    pg.locator("#startform details.inline > summary").tap()
    for d in pg.query_selector_all("details.tool"):
        pg.evaluate("d => d.open = true", d)
    sizes = pg.evaluate("""() => {
      const h = sel => [...document.querySelectorAll(sel)].filter(e => e.offsetParent)
        .map(e => Math.round(e.getBoundingClientRect().height));
      return {summaries: h('details.card > summary, details.inline > summary'),
              pills: h('.seg .pill'), save: h('.save'), docs: h('.docs'), ab: h('.ab'),
              sm: h('.btn.sm'), fxt: h('.foot .fxt')}; }""")
    small = {k: v for k, v in sizes.items() if any(x < 44 for x in v)}
    ok("every tappable control on the landing page is at least 44px tall on touch",
       not small and sizes["summaries"] and sizes["pills"] and sizes["fxt"], str(small or sizes))
    c.close()

    # ---------------------------- forced colours: state survives (F56) --
    fctx = b.new_context(viewport={"width": 1280, "height": 800}, forced_colors="active")
    fp = fctx.new_page()
    fp.goto(f"{BASE}/")
    fc = fp.evaluate("""() => { const bg = e => getComputedStyle(e).backgroundColor;
      const on = document.querySelector('.seg .pill:has(input:checked)'),
            off = document.querySelector('.seg .pill:not(:has(input:checked))'),
            dot = document.querySelector('.sess .dot'), page = getComputedStyle(document.body).backgroundColor;
      return {on: bg(on), off: off ? bg(off) : null, dot: bg(dot), page: page}; }""")
    ok("Windows Contrast: the selected Start choice looks different from the others",
       fc["off"] is None or fc["on"] != fc["off"], str(fc))
    ok("Windows Contrast: status dots are still drawn", fc["dot"] not in (fc["page"], "rgba(0, 0, 0, 0)"), str(fc))
    fctx.close()

    # -------------------------- command box and install notes (F74) --
    c = b.new_context(viewport={"width": 320, "height": 700})
    pg = c.new_page()
    pg.goto(f"{BASE}/")
    pg.add_style_tag(content=MONO)
    fits = pg.evaluate("""() => { const t = document.getElementById('cmd'); t.value = t.placeholder;
      const r = t.scrollHeight <= t.clientHeight + 1; t.value = ''; return [r, t.placeholder]; }""")
    ok("320px: the command box's example fits its two rows (nothing cut in half)", fits[0], str(fits))
    wrap = pg.evaluate("""() => { const c = document.createElement('code'), n = document.createElement('p');
      n.className = 'note'; n.appendChild(c); document.body.appendChild(n); const s = getComputedStyle(c);
      const r = [s.wordBreak, s.overflowWrap]; n.remove(); return r; }""")
    ok("install commands in notes wrap at spaces, not mid-word", wrap == ["normal", "anywhere"], str(wrap))
    c.close()

    # ------------------------------------------ per-row accessible names --
    page.goto(f"{BASE}/")
    names = page.evaluate("""() => ({
      more: [...document.querySelectorAll('.sess[data-session] details.menu > summary')].map(e => e.getAttribute('aria-label')),
      open: [...document.querySelectorAll('.sess[data-session] a.open')].map(e => e.getAttribute('aria-label')),
      del: [...document.querySelectorAll('form[action="/shortcuts/del"] button')].map(e => e.getAttribute('aria-label')),
      run: [...document.querySelectorAll('.sess:not(#sc-update) form[action="/shortcuts/run"] button')].map(e => e.getAttribute('aria-label')),
      ssh: [...document.querySelectorAll('a[data-open=ssh]')].map(e => e.textContent.trim())})""")
    ok("each row's ⋯ is named for its session",
       f"More actions for {att}" in names["more"] and len(set(names["more"])) == len(names["more"]),
       str(names["more"]))
    ok("each Open link is named for its session, starting with the visible word",
       f"Open {att}" in names["open"] and len(set(names["open"])) == len(names["open"]), str(names["open"]))
    ok("shortcut Remove and Run buttons name their shortcut",
       f"Remove shortcut pwlay logs {TAG}" in names["del"] and f"Run pwlay logs {TAG}" in names["run"],
       str(names))
    ok("the ssh:// item says it only logs in, not that it opens this session",
       names["ssh"] and all(t == "SSH app (login only)" for t in names["ssh"]), str(names["ssh"][:2]))
    ok("shortcut name fields stop at the 60 characters the server keeps",
       page.get_attribute("#sc_label", "maxlength") == "60"
       and page.get_attribute('#startform input[name=label]', "maxlength") == "60")

    # --------------------------------- ⋯ menu fits on narrow phones (F25) --
    for w in (320, 360, 375, 390):
        c = phone(p, wk, w, 700)
        pg = c.new_page()
        pg.goto(f"{BASE}/")
        sel = f'.sess[data-session="{longname}"]'
        pg.locator(f"{sel} details.menu > summary").tap()
        pg.locator(f"{sel} details.ren > summary").tap()
        pg.wait_for_timeout(250)
        box = pg.evaluate(f"""() => {{ const r = document.querySelector('{sel}');
          const l = r.querySelector('.menu-list').getBoundingClientRect(),
                s = r.querySelector('form[action="/rename"] button').getBoundingClientRect(),
                i = r.querySelector('form[action="/rename"] input[name=new]');
          return [l.left, l.right, s.left, s.right, innerWidth, parseFloat(getComputedStyle(i).fontSize)]; }}""")
        ok(f"{w}px: the open menu with Rename unfolded stays on screen",
           box[0] >= 0 and box[1] <= box[4] and box[2] >= 0 and box[3] <= box[4], str(box))
        ok(f"{w}px: ...and the rename box is 16px, so iOS doesn't zoom on focus",
           box[5] >= 16, str(box[5]))
        c.close()

    # ------------------------------------------------- ⋯ menu behaviour --
    print("chromium desktop, menus:")
    mctx = b.new_context(viewport={"width": 1280, "height": 800},
                         permissions=["clipboard-read", "clipboard-write"])
    mp = mctx.new_page()
    mp.on("pageerror", lambda e: print("   [pageerror]", e))
    mp.goto(f"{BASE}/")
    rows_sel = ".sess[data-session]"
    first, second = mp.eval_on_selector_all(rows_sel, "els => els.slice(0, 2).map(e => e.dataset.session)")

    def row(n):
        return f'.sess[data-session="{n}"]'

    def open_menus():
        return mp.eval_on_selector_all("details.menu[open]", "els => els.map(e => e.closest('.sess').dataset.session)")
    mp.click(f"{row(second)} details.menu > summary")
    mp.click(f"{row(first)} details.menu > summary")
    mp.wait_for_timeout(150)
    ok("opening a second row's ⋯ closes the first (one menu at a time)",
       open_menus() == [first], str(open_menus()))
    mp.keyboard.press("Escape")
    mp.wait_for_timeout(100)
    ok("Escape closes the menu and puts focus back on its ⋯",
       open_menus() == [] and mp.evaluate(
           f"document.activeElement === document.querySelector('{row(first)} details.menu > summary')"),
       str(open_menus()))
    # Rename typed into, then abandoned: reopening shows it folded, original name
    mp.click(f"{row(first)} details.menu > summary")
    mp.click(f"{row(first)} details.ren > summary")
    mp.fill(f'{row(first)} form[action="/rename"] input[name=new]', "half-typed")
    mp.keyboard.press("Escape")
    mp.wait_for_timeout(100)
    ok("Escape inside Rename folds Rename first, leaving the menu open",
       open_menus() == [first] and mp.locator(f"{row(first)} details.ren[open]").count() == 0)
    mp.mouse.click(5, 5)
    mp.wait_for_timeout(100)
    mp.click(f"{row(first)} details.menu > summary")
    ren_state = mp.evaluate(f"""() => {{ const r = document.querySelector('{row(first)} details.ren');
      return [r.open, r.querySelector('input[name=new]').value]; }}""")
    ok("reopening the menu shows Rename folded with the original name",
       ren_state == [False, first], str(ren_state))
    # keyboard: tabbing out of the menu closes it
    mp.keyboard.press("Escape")
    mp.focus(f"{row(first)} details.menu > summary")
    mp.keyboard.press("Enter")
    for _ in range(12):
        mp.keyboard.press("Tab")
        if not mp.evaluate(f"document.querySelector('{row(first)} details.menu').contains(document.activeElement)"):
            break
    mp.wait_for_timeout(100)
    ok("tabbing out of an open menu closes it", open_menus() == [], str(open_menus()))
    # Copy SSH command tapped twice: the label must come back
    mp.click(f"{row(first)} details.menu > summary")
    cp = mp.locator(f"{row(first)} [data-copy]")
    if cp.count():
        cp.click()
        mp.wait_for_timeout(300)
        cp.click()
        mp.wait_for_timeout(1700)
        ok("Copy SSH command tapped twice goes back to its label, not 'Copied' for good",
           cp.inner_text().strip() == "Copy SSH command", cp.inner_text())
    mp.keyboard.press("Escape")
    # Ctrl+click Open: the browser's own new tab on /s/<name>, not our pop-up
    with mctx.expect_page() as newp:
        mp.click(f"{row(first)} a.open", modifiers=["Control"])
    np_ = newp.value
    try:
        np_.wait_for_url("**/s/**", timeout=5000)
    except Exception:
        pass
    ok("Ctrl+click on Open opens the plain session page in a new tab, not the pop-out",
       "/s/" in np_.url and "popout" not in np_.url and mp.url.rstrip("/") == BASE,
       f"new={np_.url!r} landing={mp.url!r}")
    np_.close()
    mctx.close()

    # ------------------------------------------- the list keeps current --
    print("chromium desktop, live list:")
    lctx = b.new_context(viewport={"width": 1280, "height": 800})
    lp = lctx.new_page()
    lp.on("pageerror", lambda e: print("   [pageerror]", e))
    doomed = make(f"pwlay-doomed-{TAG}")
    lp.goto(f"{BASE}/")
    lp.wait_for_timeout(2500)                        # the first poll has run, past the throttle
    tmux("kill-session", "-t", f"={doomed}")
    newcomer = make(f"pwlay-new-{TAG}")

    def poke():
        lp.evaluate("document.dispatchEvent(new Event('visibilitychange'))")

    def present(n):
        return lp.evaluate(f"[...document.querySelectorAll('.sess[data-session]')].some(r => r.dataset.session === {n!r})")
    poke()
    ok("a session killed elsewhere drops off the list without a reload",
       wait_for(lambda: not present(doomed), 6), doomed)
    ok("...and one started elsewhere appears, as a full row",
       wait_for(lambda: present(newcomer), 6)
       and lp.locator(f'.sess[data-session="{newcomer}"] a.open[data-name="{newcomer}"]').count() == 1
       and lp.locator(f'.sess[data-session="{newcomer}"] form[action="/kill"]').count() == 1, newcomer)
    # Open on a row the last poll already knew was gone: a note, no pop-up.
    # An open menu elsewhere holds the row in place (the poll never moves rows
    # under an open menu), which is exactly when a stale row can be tapped.
    victim = make(f"pwlay-victim-{TAG}")
    lp.wait_for_timeout(1100)
    poke()
    wait_for(lambda: present(victim), 6)
    other = lp.eval_on_selector_all(".sess[data-session]", "els => els[0].dataset.session")
    lp.click(f'.sess[data-session="{other}"] details.menu > summary')
    tmux("kill-session", "-t", f"={victim}")
    lp.wait_for_timeout(1100)
    poke()
    wait_for(lambda: lp.evaluate(f"(() => {{ const r = [...document.querySelectorAll('.sess[data-session]')]"
                                 f".find(r => r.dataset.session === {victim!r}); return !!r; }})()"), 2)
    lp.wait_for_timeout(800)
    ok("...but not while a menu is open (rows never move under an open menu)", present(victim))
    pages_before = len(lctx.pages)
    lp.click(f'.sess[data-session="{victim}"] a.open')
    lp.wait_for_timeout(500)
    ok("Open on a session that has ended says so instead of opening it",
       len(lctx.pages) == pages_before and not present(victim)
       and victim in (lp.locator("#sessnote").inner_text() if lp.locator("#sessnote").count() else ""),
       f"pages {pages_before}->{len(lctx.pages)}")
    # serverjack unreachable: say so (after two misses), and clear it after
    lp.route("**/api/sessions", lambda route: route.abort())
    for _ in range(2):
        lp.wait_for_timeout(1100)
        poke()
    down = wait_for(lambda: lp.locator("#sessnote.err").count() == 1, 4)
    lp.screenshot(path="shots/layout-unreachable.png")
    lp.unroute("**/api/sessions")
    lp.wait_for_timeout(1100)
    poke()
    ok("when serverjack can't be reached the list says it may be out of date, then recovers",
       down and wait_for(lambda: lp.locator("#sessnote.err").count() == 0, 4))
    # the server side of a stale Open
    r = lp.goto(f"{BASE}/s/{victim}")
    ok("/s/<gone> lands on the list with a one-line note, not an error copy at /s/",
       # r.url: the page script strips the one-shot note from the address bar
       r.url.startswith(f"{BASE}/?done=ended&") and lp.locator(".flash").count() == 1
       and victim in lp.locator(".flash").inner_text(), r.url)
    r = lp.goto(f"{BASE}/s/{victim}?popout=1")
    ok("/s/<gone>?popout=1 is a small 'session ended' page with a Close button",
       r.status == 404 and lp.locator("#close").count() == 1
       and lp.locator(".sess").count() == 0 and victim in lp.inner_text("body"), str(r.status))
    # The session you just left shows as attached at render time (its socket
    # is still closing); a second look a second later must correct it.
    lp.goto(f"{BASE}/s/{att}")
    lp.wait_for_selector("#tabs .tab.on")
    lp.wait_for_timeout(1500)
    hold.close()                                     # only this page is attached now
    lp.goto(f"{BASE}/")
    ok("the session just left does not stay 'attached' once its client is gone",
       wait_for(lambda: lp.evaluate(
           f"!document.querySelector('.sess[data-session=\"{att}\"] .dot.on')"), 4)
       and tmux("display", "-p", "-t", f"={att}:", "#{session_attached}").stdout.strip() in ("", "0"),
       tmux("display", "-p", "-t", f"={att}:", "#{session_attached}").stdout.strip())
    lctx.close()

    # ------------------------------------ leaving a session (F14) --
    print("chromium desktop, leaving a session:")
    xctx = b.new_context(viewport={"width": 1280, "height": 800})
    xp = xctx.new_page()
    xp.goto(f"{BASE}/")
    foot = xp.locator(".foot").inner_text()
    ok("the footer names the control that exists, not a back button",
       "back button" not in foot and "logo" in foot and "kill" in foot, foot)
    for ctl in ("#close", "#bar a.ib.home"):
        xp.goto(f"{BASE}/")
        xp.goto(f"{BASE}/s/{first}")
        xp.wait_for_selector("#tabs .tab.on")
        if ctl == "#close":
            ok("× is labelled for what it does", xp.get_attribute("#close", "aria-label") == "Back to sessions",
               xp.get_attribute("#close", "aria-label"))
        xp.click(ctl)
        xp.wait_for_url(f"{BASE}/")
        xp.go_back()
        xp.wait_for_load_state()
        ok(f"{ctl} back to the list replaces the terminal in history (Back doesn't re-open it)",
           "/s/" not in xp.url, xp.url)
    xctx.close()

    # -------------------------- a menu near the bottom of the screen (F65) --
    print("webkit iphone, menus near the bottom:")
    for w, h in ((390, 664), (844, 390)):
        c = phone(p, wk, w, h)
        pg = c.new_page()
        pg.goto(f"{BASE}/")
        last = pg.eval_on_selector_all(".sess[data-session]", "els => els[els.length - 1].dataset.session")
        # put the last row's bottom edge at the bottom of the screen
        pg.evaluate(f"""() => {{ const r = document.querySelector('.sess[data-session="{last}"]');
          window.scrollBy(0, r.getBoundingClientRect().bottom - innerHeight + 2); }}""")
        pg.wait_for_timeout(150)
        pg.locator(f'.sess[data-session="{last}"] details.menu > summary').tap()
        pg.wait_for_timeout(400)
        box = pg.evaluate(f"""() => {{ const l = document.querySelector('.sess[data-session="{last}"] .menu-list')
          .getBoundingClientRect(); return [l.top, l.bottom, innerHeight]; }}""")
        ok(f"{w}x{h}: the last row's menu opens fully on screen (flipped up or scrolled in)",
           box[0] >= 0 and box[1] <= box[2] + 0.5, str(box))
        if w == 390:
            pg.screenshot(path="shots/layout-menu-bottom.png")
        c.close()

    # ---- an open menu that changes size: Rename, then a refused name (F31) --
    # The row is put at a known height (main's top padding) so that its menu
    # fits below on its own but not with Rename open (A), or opens upward and
    # fits above with Rename open but not with the error too (B, at the top
    # of the page, where no scroll reaches what is above it).
    c = phone(p, wk, 390, 664)
    pg = c.new_page()
    pg.goto(f"{BASE}/")
    names = pg.eval_on_selector_all(".sess[data-session]", "els => els.map(e => e.dataset.session)")
    victim, taken = names[0], names[1]
    sel = f'.sess[data-session="{victim}"]'
    LIST = f"(() => {{ const l = document.querySelector('{sel} .menu-list'), r = l.getBoundingClientRect();" \
           " return {top: r.top, bottom: r.bottom, h: r.height, up: l.classList.contains('up')}; })()"

    def menu_steps(page):
        page.locator(f"{sel} details.menu > summary").tap()
        page.wait_for_timeout(250)
        a = page.evaluate(LIST)
        page.locator(f"{sel} details.ren summary").tap()
        page.wait_for_timeout(250)
        b_ = page.evaluate(LIST)
        page.fill(f"{sel} input[name=new]", taken)
        page.locator(f'{sel} form[action="/rename"] button').tap()
        page.wait_for_selector(f"{sel} .menu-list .err")
        page.wait_for_timeout(250)
        return a, b_, page.evaluate(LIST)

    def at(page, top, height):
        page.set_viewport_size({"width": 390, "height": height})
        page.evaluate(f"""() => {{ window.scrollTo(0, 0); const m = document.querySelector('main'),
          r = document.querySelector('{sel}').getBoundingClientRect();
          m.style.paddingTop = (parseFloat(getComputedStyle(m).paddingTop) + {top} - r.top) + 'px'; }}""")
        return page.evaluate(f"document.querySelector('{sel}').getBoundingClientRect().height")

    l1, l2, l3 = menu_steps(pg)                    # measured: fresh, with Rename, with the error
    for case in ("A", "B"):
        pg.goto(f"{BASE}/")
        if case == "A":
            top = l2["h"] + 60
            row_h = at(pg, top, 664)
            at(pg, top, int(top + row_h + 4 + l1["h"] + 20))
        else:
            top = int(l2["h"] + 12 + (l3["h"] - l2["h"]) / 2)
            row_h = at(pg, top, 664)
            at(pg, top, int(top + row_h + 40))
        pg.locator(f"{sel} details.menu > summary").tap()
        pg.wait_for_timeout(250)
        # its own entrance animation over first (a loaded machine runs it late)
        wait_for(lambda: pg.evaluate(f"""(() => {{ const l = document.querySelector('{sel} .menu-list');
          return getComputedStyle(l).opacity === '1' && !(l.getAnimations && l.getAnimations().length); }})()"""), 3)
        fresh = pg.evaluate(LIST)
        pg.evaluate("""() => { window.__op = []; const t0 = performance.now(), l = document.querySelector('%s .menu-list');
          (function f() { window.__op.push(parseFloat(getComputedStyle(l).opacity));
            if (performance.now() - t0 < 300) requestAnimationFrame(f); })(); }""" % sel)
        pg.locator(f"{sel} details.ren summary").tap()
        pg.wait_for_timeout(350)
        ren, ops = pg.evaluate(LIST), pg.evaluate("window.__op")
        if case == "A":
            ok("A menu that opened downward stays downward when Rename makes it taller (no jump)",
               not fresh["up"] and not ren["up"] and ren["bottom"] <= pg.evaluate("innerHeight") + 0.5,
               str([fresh, ren]))
        else:
            ok("An upward menu doesn't blink when Rename opens (no replayed animation)",
               fresh["up"] and ren["up"] and min(ops or [0]) > 0.9, str([fresh, ren, min(ops or [0])]))
            pg.fill(f"{sel} input[name=new]", taken)
            pg.locator(f'{sel} form[action="/rename"] button').tap()
            pg.wait_for_selector(f"{sel} .menu-list .err")
            pg.wait_for_timeout(350)
            err = pg.evaluate(LIST)
            first = pg.evaluate(f"document.querySelector('{sel} .menu-list a').getBoundingClientRect().top")
            ok("...and a refused name grows it without pushing Open here off the top of the page",
               err["top"] >= -0.5 and first >= -0.5 and err["bottom"] <= pg.evaluate("innerHeight") + 0.5,
               str([l1, l2, l3, fresh, ren, err, first]))
    c.close()

    wk.close()
    b.close()

for name in MADE:
    if exists(name):
        tmux("kill-session", "-t", f"={name}")
# the shortcuts this suite added (labels start "pwlay ")
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.goto(f"{BASE}/")
    for sid in pg.eval_on_selector_all(
            '.sess:has(.nm:text-matches("^pwlay ")) form[action="/shortcuts/del"] input[name=id]',
            "els => els.map(e => e.value)"):
        pg.request.post(f"{BASE}/shortcuts/del", headers=SAME, form={"id": sid})
    b.close()

if fails:
    raise SystemExit(1)
