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
    hold.close()

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
