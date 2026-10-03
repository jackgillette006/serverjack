"""The terminal itself: what bin/serverjack-ttyd, bin/tmux-attach.sh and the
session-creation path hand to ttyd and tmux, checked in a real browser.

- the generated theme is legible: SGR 90 grey and the `ls` white-on-colour
  pairs reach 4.5:1 in rendered pixels (minimumContrastRatio rides with the
  theme), and ttyd's font list has no Courier;
- a resize no longer flashes ttyd's "COLSxROWS" pill over the terminal, nor
  does a phone opening a session of another size (the page's size nudge
  used to land before ttyd had its settings);
- tmux passes 24-bit colour through to the browser (-T RGB), and sessions
  started from the page get COLORTERM=truecolor;
- a command started from a phone prints its "$ <cmd>" line at the phone's
  width, so none of it is pushed into history above a sudo prompt;
- the page's tmux cosmetics (status off, blank fill-character) are put back
  when the last page leaves, even with an ssh-style client still attached,
  and a smaller second client leaves blank space, not '·' dots.

Runs inside tests/run.sh's browser container like the other pw*.py suites:
SERVERJACK_TEST_BASE is the ordinary instance, TMUX_SOCK its tmux server.
The "ssh client" is a real tmux client on a pty, started from this
container. Every session here is created by this suite and killed at the
end; pwtest/pwother are left alone.
"""
import io
import os
import pty
import re
import signal
import struct
import subprocess
import time
import fcntl
import termios

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = os.environ.get("SERVERJACK_TEST_BASE", "http://127.0.0.1:7690")
T = ["tmux", "-S", os.environ.get("TMUX_SOCK", "/tmp/tmux-1000/default")]
TAG = str(int(time.time()))[-5:]
MADE = []
PTYS = []
fails = 0


def tm(*args):
    return subprocess.run(T + list(args), capture_output=True, text=True).stdout


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
        time.sleep(0.25)
    return fn()


def lum(rgb):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def new_shell(name):
    """A plain bash session on the harness's tmux server, 80x24 like tmux's
    own default for a detached session."""
    tm("new-session", "-d", "-s", name, "-x", "80", "-y", "24", "bash --noprofile --norc -i")
    MADE.append(name)
    time.sleep(0.3)


def open_term(page, name):
    page.goto(f"{BASE}/s/{name}")
    page.wait_for_selector("#tabs .tab.on")
    page.frame_locator("#frame").locator(".xterm-helper-textarea").wait_for(state="attached", timeout=20000)
    time.sleep(1.5)


def attach_pty(name, cols, rows):
    """A plain `tmux attach` on a real pty -- what the landing page's "Copy
    SSH command" ends in, from the tmux server's point of view."""
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        os.execvp(T[0], T + ["attach-session", "-t", f"={name}"])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    PTYS.append((pid, fd))
    return pid


def drop_pty(pid):
    for i, (p, fd) in enumerate(PTYS):
        if p == pid:
            try:
                os.kill(pid, signal.SIGHUP)
                os.waitpid(pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
            os.close(fd)
            PTYS.pop(i)
            return


# Geometry of the terminal's text canvas in page coordinates, plus a few
# live options -- window.term is ttyd's xterm.js Terminal.
GEOM = """() => { const f = document.getElementById('frame'), fr = f.getBoundingClientRect();
  const d = f.contentDocument, t = d.defaultView.term;
  const cs = d.querySelectorAll('.xterm-screen canvas'), r = cs[cs.length - 1].getBoundingClientRect();
  return {x: fr.left + r.left, y: fr.top + r.top, cw: r.width / t.cols, ch: r.height / t.rows,
          cols: t.cols, rows: t.rows, mcr: t.options.minimumContrastRatio,
          font: t.options.fontFamily, theme: t.options.theme}; }"""


def cell_contrast(page, row, col, n):
    """Strongest contrast between any pixel in cells [col, col+n) of a screen
    row and that box's dominant colour (its background): a glyph is only as
    readable as its most solid stroke."""
    g = page.evaluate(GEOM)
    im = Image.open(io.BytesIO(page.screenshot())).convert("RGB")
    dpr = im.width / page.viewport_size["width"]
    box = (int((g["x"] + col * g["cw"]) * dpr), int((g["y"] + row * g["ch"]) * dpr),
           int((g["x"] + (col + n) * g["cw"]) * dpr), int((g["y"] + (row + 1) * g["ch"]) * dpr))
    colors = im.crop(box).getcolors(maxcolors=1 << 20)    # [(count, rgb), ...]
    bg = max(colors)[1]
    return max(contrast(rgb, bg) for _n, rgb in colors)


def screen_row(name, prefix):
    for i, line in enumerate(tm("capture-pane", "-p", "-t", f"={name}:").splitlines()):
        if line.startswith(prefix):
            return i
    return None


def start_from_landing(page, cmd):
    """Type a command into the Start card and press Start, like a user."""
    page.goto(f"{BASE}/")
    page.fill("#cmd", cmd)
    page.click('form[action="/start"] button[type=submit]')
    page.wait_for_url(re.compile(r"/s/"))
    name = re.search(r"/s/([^/?#]+)", page.url).group(1)
    MADE.append(name)
    page.frame_locator("#frame").locator(".xterm-helper-textarea").wait_for(state="attached", timeout=20000)
    return name


def device(p, name):
    d = dict(p.devices[name])
    d.pop("default_browser_type", None)
    return d


with sync_playwright() as p:
    # ------------------------------------------------ theme + ttyd options
    print("chromium desktop: theme, font, resize overlay, truecolor")
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1100, "height": 700})
    page = ctx.new_page()
    page.on("pageerror", lambda e: print("   [pageerror]", e))
    s_theme = f"pwtmux-theme-{TAG}"
    new_shell(s_theme)
    open_term(page, s_theme)
    g = page.evaluate(GEOM)
    ok("minimumContrastRatio 4.5 rides along with the generated theme",
       g["mcr"] == 4.5, g["mcr"])
    ok("ttyd's font list has no Courier (Cutive Mono on Android)",
       "courier" not in (g["font"] or "").lower() and "monospace" in (g["font"] or ""), g["font"])
    bb = g["theme"].get("brightBlack", "")
    ok("theme's brightBlack (SGR 90 grey) is 4.5:1 against the background",
       bb and contrast(hex_rgb(bb), hex_rgb(g["theme"]["background"])) >= 4.5, bb)

    # Rendered pixels: the grey hint colour on the background, and the two
    # Debian LS_COLORS pairs the theme made unreadable (setuid 37;41 at
    # 1.35:1 and sticky 37;44 at 1.14:1 before).
    tm("send-keys", "-t", f"={s_theme}:",
       r"clear; printf 'C0 \e[90mGREYHINTGREYHINT\e[0m\nC1 \e[37;41mSETUIDFILE\e[0m\nC2 \e[37;44mSTICKYDIRS\e[0m\n'",
       "Enter")
    row = wait_for(lambda: screen_row(s_theme, "C0 "))
    time.sleep(0.6)
    if ok("contrast card printed", row is not None):
        for label, r, n in (("SGR 90 grey text", 0, 16), ("ls setuid (white on red)", 1, 10),
                            ("ls sticky dir (white on blue)", 2, 10)):
            c = cell_contrast(page, row + r, 3, n)
            # 4.4, not 4.5: antialiasing never quite reaches the nominal colour
            ok(f"{label} renders at about 4.5:1 or better", c >= 4.4, f"{c:.2f}:1")

    # ttyd's resize overlay: a "COLSxROWS" div appended to the terminal on
    # every resize. Watch for it while the viewport shrinks, which changes
    # cols and rows the same way a phone keyboard or a rotation does.
    page.evaluate("""() => { const d = document.getElementById('frame').contentDocument;
      window.__pill = [];
      new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {
        if (/^\\s*\\d+x\\d+\\s*$/.test(n.textContent || '')) window.__pill.push(n.textContent); })))
        .observe(d.body, {childList: true, subtree: true}); }""")
    before = page.evaluate("document.getElementById('frame').contentWindow.term.cols")
    page.set_viewport_size({"width": 800, "height": 480})
    time.sleep(1.0)
    after = page.evaluate("document.getElementById('frame').contentWindow.term.cols")
    pills = page.evaluate("window.__pill")
    ok("the terminal did resize (cols changed)", after != before, f"{before} -> {after}")
    ok("...without ttyd's COLSxROWS overlay pill", pills == [], pills)

    # Truecolor: the browser's tmux client advertises RGB, so a 24-bit
    # background reaches xterm.js as itself, not as the nearest of 256.
    feats = tm("list-clients", "-t", f"={s_theme}", "-F", "#{client_termfeatures}")
    ok("the page's tmux client has the RGB feature", "RGB" in feats, feats.strip())
    tm("send-keys", "-t", f"={s_theme}:", r"clear; printf '\e[48;2;1;2;3mT\e[0mRGBCELL\n'", "Enter")
    wait_for(lambda: screen_row(s_theme, "TRGBCELL"))
    time.sleep(0.5)
    cell = page.evaluate("""() => { const t = document.getElementById('frame').contentWindow.term, b = t.buffer.active;
      for (let y = 0; y < b.length; y++) { const l = b.getLine(y);
        if (l && l.translateToString(true).startsWith('TRGBCELL')) { const c = l.getCell(0);
          return {rgb: c.isBgRGB(), color: c.getBgColor()}; } } return null; }""")
    ok("a 24-bit background arrives in the browser as RGB, unchanged",
       bool(cell) and cell["rgb"] and cell["color"] == 0x010203, cell)

    # --------------------------------------------- page cosmetics + restore
    print("chromium desktop + an ssh-style client: status line, fill-character")
    s_two = f"pwtmux-two-{TAG}"
    new_shell(s_two)
    tm("new-window", "-d", "-t", f"={s_two}:", "bash --noprofile --norc -i")
    open_term(page, s_two)
    status = tm("show-options", "-qv", "-t", f"={s_two}:", "status").strip()
    ok("with the page open, the session's status line is off", status == "off", status)
    wins = tm("list-windows", "-t", f"={s_two}", "-F", "#{window_id}").split()
    fills = [tm("show-options", "-wv", "-t", w, "fill-character") for w in wins]
    ok("...and every window's fill-character is a blank", fills == [" \n"] * len(wins), fills)
    tm("new-window", "-d", "-t", f"={s_two}:", "bash --noprofile --norc -i")
    new_w = tm("list-windows", "-t", f"={s_two}", "-F", "#{window_id}").split()[-1]
    ok("...including a window made while the page is open",
       tm("show-options", "-wv", "-t", new_w, "fill-character") == " \n",
       tm("show-options", "-w", "-t", new_w))

    # A smaller second client takes the window (window-size latest); the
    # page, bigger, then shows it in its corner with the rest padded.
    ssh = attach_pty(s_two, 40, 12)
    wait_for(lambda: tm("display", "-p", "-t", f"={s_two}:", "#{window_width}").strip() == "40", 5)
    time.sleep(1.0)
    text = page.evaluate("""() => { const t = document.getElementById('frame').contentWindow.term, b = t.buffer.active;
      let s = ''; for (let y = b.viewportY; y < b.viewportY + t.rows; y++) {
        const l = b.getLine(y); if (l) s += l.translateToString() + '\\n'; } return s; }""")
    ok("the window shrank to the smaller client (precondition)",
       tm("display", "-p", "-t", f"={s_two}:", "#{window_width}").strip() == "40",
       tm("display", "-p", "-t", f"={s_two}:", "#{window_width}x#{window_height}"))
    ok("...and the page pads the rest with blanks, not tmux's '·' dots",
       "·" not in text, f"{text.count(chr(0xb7))} dots")

    page.close()        # the page leaves; the ssh-style client stays
    restored = wait_for(lambda: tm("show-options", "-qv", "-t", f"={s_two}:", "status").strip() == "", 5)
    ok("once the page leaves, the status line is the user's own again, ssh client still attached",
       restored and tm("display", "-p", "-t", f"={s_two}:", "#{session_attached}").strip() == "1",
       tm("show-options", "-t", f"={s_two}:", "status") + tm("list-clients", "-t", f"={s_two}"))
    ok("...and fill-character is back to tmux's default on every window",
       all(tm("show-options", "-wqv", "-t", w, "fill-character") == ""
           for w in tm("list-windows", "-t", f"={s_two}", "-F", "#{window_id}").split()))
    drop_pty(ssh)
    ctx.close()
    b.close()

    # ---------------------------------------------------- phone: F35
    # read -p stands in for sudo: it prints a password prompt and waits.
    long_cmd = "read -p '[sudo] password: ' pw  # sudo systemctl restart nginx"
    for eng, dev in (("webkit", "iPhone 14"), ("webkit", "iPhone SE")):
        print(f"{eng} {dev}: a command started from the phone")
        b = getattr(p, eng).launch()
        ctx = b.new_context(**device(p, dev))
        page = ctx.new_page()
        page.on("pageerror", lambda e: print("   [pageerror]", e))
        name = start_from_landing(page, long_cmd)
        wait_for(lambda: "password:" in tm("capture-pane", "-p", "-t", f"={name}:"), 10)
        time.sleep(0.5)
        visible = tm("capture-pane", "-p", "-t", f"={name}:")
        info = tm("display", "-p", "-t", f"={name}:", "#{window_width}x#{window_height} history=#{history_size}")
        ok("the session runs at the phone's width (narrower than 80)",
           int(info.split("x")[0]) < 80, info.strip())
        ok("the start of the \"$ <cmd>\" line is on screen above the password prompt",
           "$ read -p" in visible and "password:" in visible,
           [line for line in visible.splitlines() if line.strip()][:3])
        ok("...and nothing was pushed into history", info.strip().endswith("history=0"), info.strip())
        if dev == "iPhone 14":
            # COLORTERM, on the same kind of session (started from the page).
            name2 = start_from_landing(page, "echo CT=$COLORTERM.")
            out = wait_for(lambda: tm("capture-pane", "-p", "-t", f"={name2}:")
                           if "[exited with status" in tm("capture-pane", "-p", "-t", f"={name2}:") else "")
            ok("sessions started from the page have COLORTERM=truecolor",
               "CT=truecolor." in out, [line for line in out.splitlines() if "CT=" in line])
            # A phone opening a session of another size takes the size (a nudge
            # one row smaller and back): that used to land before ttyd had its
            # settings -- disableResizeOverlay among them -- so the COLSxROWS
            # pill flashed over the terminal all the same.
            pc = b.new_context(**device(p, dev))
            pc.add_init_script("""(() => { if (!location.pathname.startsWith('/term')) return;
              window.top.__pills = window.top.__pills || [];
              new MutationObserver(() => {
                for (const el of document.querySelectorAll('.xterm > div:not([class])')) {
                  const t = (el.textContent || '').trim();
                  if (/^\\d+x\\d+$/.test(t) && getComputedStyle(el).opacity !== '0') window.top.__pills.push(t);
                }
              }).observe(document, { subtree: true, childList: true, characterData: true }); })()""")
            pills = []
            for i in range(5):
                s_pill = f"pwtmux-pill{i}-{TAG}"
                tm("new-session", "-d", "-s", s_pill, "-x", "120", "-y", "30")
                MADE.append(s_pill)
                pp = pc.new_page()
                pp.goto(f"{BASE}/s/{s_pill}")
                pp.wait_for_timeout(2500)
                pills += pp.evaluate("window.__pills || []")
                pp.close()
            ok("a phone opening a session of another size shows no COLSxROWS pill", not pills, pills)
            pc.close()
        ctx.close()
        b.close()

for pid, _fd in list(PTYS):
    drop_pty(pid)
for name in MADE:
    tm("kill-session", "-t", f"={name}")

if fails:
    raise SystemExit(1)
