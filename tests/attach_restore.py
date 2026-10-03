"""bin/tmux-attach.sh's session cosmetics, host-side: no browser, no ttyd.

While a page has a session open, tmux-attach.sh turns the status line off
and makes the fill-character a blank; when the last page leaves it puts
back exactly what was there before. Each "page" here is the script itself
on a pty, run the way ttyd runs it (own session and process group, hung up
as a group when the page goes), against a private tmux server. Checked:

- a value you set on the session or on a window yourself survives a page
  visit (it used to come back as tmux's default);
- a change you make while the page is open is kept;
- two pages: the first one leaving changes nothing, the second restores;
- a page that opens just as another closes keeps the status line off and
  the blank fill (the closing page's restore used to undo them);
- a page killed outright doesn't stop a later page from restoring;
- SERVERJACK_TMUX_STATUS=on leaves the status line alone, but the blank
  fill still comes and goes;
- a plain `tmux attach` (an ssh client) is not taken for a page;
- a page hung up while it is still setting up is not attached at all (it
  used to attach anyway, a client nobody saw that stayed for good);
- your global after-new-window hooks keep firing in a session while a page
  has it open and after it has gone (an empty session-level array used to
  be left behind, hiding them for good), and a session's own hooks stay;
- a session whose name ends in ';' is the one attached (tmux read the ';'
  as a command separator: no such session, or another one called "semi").

The environment has no UTF-8 locale on purpose: ttyd's need not have one,
and tmux then prints tabs and non-ASCII as '_' unless asked not to.
"""
import fcntl
import os
import pty
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "bin", "tmux-attach.sh")
ROOT = tempfile.mkdtemp(prefix="sj-attach-")
os.chmod(ROOT, 0o700)
RT = os.path.join(ROOT, "rt")
TMP = os.path.join(ROOT, "tmux")
for d in (RT, os.path.join(RT, "serverjack"), TMP):
    os.mkdir(d, 0o700)
# A private tmux server: the script's plain `tmux` finds it through
# TMUX_TMPDIR, and so does every check here.
ENV = {"HOME": ROOT, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TERM": "xterm-256color",
       "XDG_RUNTIME_DIR": RT, "TMUX_TMPDIR": TMP}
T = ["tmux", "-u"]
fails = 0
PAGES = {}


def tm(*args):
    return subprocess.run(T + list(args), capture_output=True, text=True, env=ENV).stdout


def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + str(extra)) if extra and not cond else ""))


def wait_for(fn, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.02)
    return bool(fn())


def status(s):
    """The session's own status value ('' = none set: tmux's default)."""
    return tm("show-options", "-qv", "-t", f"={s}:", "status").strip()


def fills(s):
    """Each window's own fill-character ('' = none set)."""
    return [tm("show-options", "-wqv", "-t", w, "fill-character").rstrip("\n")
            for w in tm("list-windows", "-t", f"={s}", "-F", "#{window_id}").split()]


def marks(s):
    """Anything of serverjack's still on the session, its windows or hooks."""
    left = [line for line in tm("show-options", "-t", f"={s}:").splitlines() if "serverjack" in line]
    for w in tm("list-windows", "-t", f"={s}", "-F", "#{window_id}").split():
        left += [w + " " + line for line in tm("show-options", "-w", "-t", w).splitlines() if "serverjack" in line]
    left += [line for line in tm("show-hooks", "-t", f"={s}:").splitlines()
             if "[73]" in line or line.strip() == "after-new-window"]      # [73], or an empty array
    return left


def attached(s):
    return int(tm("display", "-p", "-t", f"={s}:", "#{session_attached}").strip() or 0)


def page(s, extra_env=None):
    """tmux-attach.sh on a pty, as ttyd starts it. Returns its pid (also its
    process group: pty.fork() makes it a session leader)."""
    env = dict(ENV)
    env.update(extra_env or {})
    pid, fd = pty.fork()
    if pid == 0:
        os.execve("/bin/bash", ["bash", SCRIPT, s], env)
    os.set_blocking(fd, False)
    PAGES[pid] = fd
    return pid


def drain():
    for fd in PAGES.values():
        try:
            while os.read(fd, 65536):
                pass
        except OSError:
            pass


def leave(pid, sig=signal.SIGHUP):
    """The page goes: hang up its process group, as ttyd does, and wait for
    the script (and so its restore) to finish."""
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass
    deadline = time.time() + 10
    while time.time() < deadline:
        drain()
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done:
            break
        time.sleep(0.02)
    else:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        ok(f"page {pid} exited after the hangup", False)
    os.close(PAGES.pop(pid))


def opened(s, n):
    """Wait for the session's n-th client. A page does all of its setup
    before it attaches, so once it is attached that is done."""
    if not wait_for(lambda: attached(s) >= n):
        ok(f"{s}: {n} client(s) attached", False)
    drain()


def session(s, windows=1):
    tm("new-session", "-d", "-s", s, "-x", "80", "-y", "24", "sleep 3600")
    for _ in range(windows - 1):
        tm("new-window", "-d", "-t", f"={s}:", "sleep 3600")


def main():
    tm("start-server", ";", "set-option", "-g", "exit-empty", "off")
    # fill-character is tmux >= 3.3; on an older one only the status checks run.
    new_fill = subprocess.run(T + ["show-options", "-gw", "fill-character"],
                              capture_output=True, env=ENV).returncode == 0

    print("your own values survive a page visit")
    session("own", 3)
    tm("set-option", "-t", "=own:", "status", "2")
    if new_fill:
        tm("set-option", "-w", "-t", "=own:0", "fill-character", "x")
        tm("set-option", "-w", "-t", "=own:1", "fill-character", "·")
        tm("set-option", "-w", "-t", "=own:2", "fill-character", "\\;")    # a literal ';'
    before = fills("own")
    if new_fill:
        ok("(your own fill-characters are set)", before == ["x", "·", ";"], before)
    a = page("own")
    opened("own", 1)
    ok("page open: status off", status("own") == "off", status("own"))
    if new_fill:
        ok("page open: every window's fill is a blank", fills("own") == [" "] * 3, fills("own"))
        tm("new-window", "-d", "-t", "=own:", "sleep 3600")
        ok("...a window made while the page is open too", fills("own")[-1] == " ", fills("own"))
    leave(a)
    ok("page gone: the session's own status 2 is back", status("own") == "2", status("own"))
    if new_fill:
        ok("page gone: each window's own fill-character is back, the rest unset",
           fills("own") == before + [""], fills("own"))
    ok("page gone: nothing of serverjack's is left", not marks("own"), marks("own"))
    tm("set-option", "-t", "=own:", "status", "off")
    a = page("own")
    opened("own", 1)
    leave(a)
    ok("a session you set to status off yourself stays off", status("own") == "off", status("own"))

    print("a change made while the page is open is kept")
    session("chg")
    a = page("chg")
    opened("chg", 1)
    tm("set-option", "-t", "=chg:", "status", "on")
    if new_fill:
        tm("set-option", "-w", "-t", "=chg:0", "fill-character", "+")
    leave(a)
    ok("status set to on while open stays on", status("chg") == "on", status("chg"))
    if new_fill:
        ok("fill-character set while open stays", fills("chg") == ["+"], fills("chg"))
    ok("...and nothing of serverjack's is left", not marks("chg"), marks("chg"))

    print("two pages, an ssh client, a page killed outright")
    session("two", 2)
    a = page("two")
    opened("two", 1)
    b = page("two")
    opened("two", 2)
    ssh_pid, ssh_fd = pty.fork()
    if ssh_pid == 0:
        os.execvpe("tmux", ["tmux", "attach-session", "-t", "=two"], ENV)
    wait_for(lambda: attached("two") == 3)
    leave(a)
    ok("first page gone: status still off for the other", status("two") == "off", status("two"))
    if new_fill:
        ok("...and the fill still blank", fills("two") == [" "] * 2, fills("two"))
    leave(b)
    ok("last page gone, ssh client still attached: status back to tmux's default",
       status("two") == "" and attached("two") == 1, (status("two"), attached("two")))
    if new_fill:
        ok("...fill too", fills("two") == ["", ""], fills("two"))
    os.kill(ssh_pid, signal.SIGHUP)
    os.waitpid(ssh_pid, 0)
    os.close(ssh_fd)
    k = page("two")
    opened("two", 1)
    leave(k, signal.SIGKILL)      # no restore: its pid stays on the list
    ok("(a page killed outright leaves the status off)", status("two") == "off", status("two"))
    c = page("two")
    opened("two", 1)
    leave(c)
    ok("the next page to leave still restores", status("two") == "" and not marks("two"),
       (status("two"), marks("two")))

    print("a page opening just as another closes")
    session("race", 2)
    a = page("race")
    opened("race", 1)
    lost = []
    for lead in (0.0, 0.005, 0.01, 0.02, 0.03, 0.05) * 3:
        b = page("race")
        time.sleep(lead)
        leave(a)
        wait_for(lambda: attached("race") == 1)
        time.sleep(0.05)
        st, fl = status("race"), fills("race")
        if st != "off" or (new_fill and fl != [" ", " "]):
            lost.append((lead, st, fl))
        a = b
    ok("the newer page keeps status off and the blank fill, every time", not lost, lost)
    leave(a)
    ok("...and the last one out restores everything", status("race") == "" and not marks("race")
       and (not new_fill or fills("race") == ["", ""]), (status("race"), fills("race"), marks("race")))

    print("a page that goes while it is still setting up")
    if shutil.which("flock"):
        session("early")
        # Hold the bookkeeping lock, so the page is sure to be mid-setup when
        # it is hung up; ttyd keeps its terminal open until it exits.
        with open(os.path.join(RT, "serverjack", "attach.lock"), "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            e = page("early")
            time.sleep(0.4)
            os.killpg(e, signal.SIGHUP)
            time.sleep(0.1)
            fcntl.flock(held, fcntl.LOCK_UN)
        gone = wait_for(lambda: os.waitpid(e, os.WNOHANG)[0] == e, 5)
        drain()
        ok("it exits instead of attaching", gone and attached("early") == 0, attached("early"))
        if not gone:
            os.killpg(e, signal.SIGKILL)
            os.waitpid(e, 0)
        os.close(PAGES.pop(e))
        ok("...and leaves nothing of serverjack's behind", status("early") == "" and not marks("early"),
           (status("early"), marks("early")))
    else:
        print("  (skipped: no flock)")

    if new_fill:
        print("hooks: yours keep firing")
        tm("set-hook", "-g", "after-new-window", "set-option -w @sjtest_global ran")

        def fires(s):
            w = tm("new-window", "-d", "-P", "-F", "#{window_id}", "-t", f"={s}:", "sleep 3600").strip()
            time.sleep(0.1)
            return tm("show-options", "-wqv", "-t", w, "@sjtest_global").strip() == "ran"
        session("hk")
        ok("(a global after-new-window hook fires in a plain session)", fires("hk"))
        a = page("hk")
        opened("hk", 1)
        ok("page open: your global hook still fires on a new window", fires("hk"))
        ok("...which gets the blank fill too", fills("hk")[-1] == " ", fills("hk"))
        leave(a)
        ok("page gone: no hook array of serverjack's left on the session (it hid the global ones)",
           not tm("show-hooks", "-t", "=hk:").strip() and not marks("hk"),
           (tm("show-hooks", "-t", "=hk:"), marks("hk")))
        ok("...so your global hook fires there again", fires("hk"))
        session("hkown")
        tm("set-hook", "-t", "=hkown:", "after-new-window[1]", "set-option -w @sjtest_own yes")
        a = page("hkown")
        opened("hkown", 1)
        leave(a)
        own = tm("show-hooks", "-t", "=hkown:").splitlines()
        ok("a session's own hook array keeps its entries, and only those",
           own == ["after-new-window[1] set-option -w @sjtest_own yes"] and not marks("hkown"), own)
        tm("set-hook", "-gu", "after-new-window")

    print("a session called 'semi;'")
    tm("new-session", "-d", "-s", "semi", "-x", "80", "-y", "24", "sleep 3600")
    tm("new-session", "-d", "-s", "semi\\;", "-x", "80", "-y", "24", "sleep 3600")
    ok("(both exist)", tm("has-session", "-t", "=semi;:") == "" and
       "semi;" in tm("list-sessions", "-F", "#S").split(), tm("list-sessions", "-F", "#S"))
    a = page("semi;")
    wait_for(lambda: attached("semi;") >= 1)
    drain()
    ok("a page for 'semi;' attaches to 'semi;', not to 'semi'",
       attached("semi;") == 1 and attached("semi") == 0, (attached("semi;"), attached("semi")))
    leave(a)

    print("SERVERJACK_TMUX_STATUS=on")
    session("on")
    a = page("on", {"SERVERJACK_TMUX_STATUS": "on"})
    opened("on", 1)
    ok("status left alone", status("on") == "", status("on"))
    if new_fill:
        ok("the blank fill still applies", fills("on") == [" "], fills("on"))
    leave(a)
    ok("...and goes again", not marks("on") and (not new_fill or fills("on") == [""]),
       (fills("on"), marks("on")))


try:
    main()
finally:
    for pid in list(PAGES):
        try:
            os.killpg(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass
    subprocess.run(T + ["kill-server"], capture_output=True, env=ENV)
    shutil.rmtree(ROOT, ignore_errors=True)

sys.exit(1 if fails else 0)
