#!/usr/bin/env python3
"""PTY-driven dialogue runner for one guided-install scenario.

See tests/guided-install.sh, which builds the argv (a `docker exec ... script
-qfc '...' /dev/null` command -- `script` is what allocates the REAL pty the
child sees as /dev/tty; this driver just feeds stdin/reads stdout over the
plain pipes docker exec -i gives it) and the exchange list for each scenario.

Usage:
  guided-install-driver.py <timeout-seconds> <exchanges.json> -- <argv...>

exchanges.json is a JSON list of [expect_substring, send_or_null] pairs,
matched IN ORDER against the growing combined stdout+stderr stream:
  - waits (up to <timeout-seconds>, reset for EACH exchange -- an earlier
    slow step such as `apt-get install` must not eat into a later prompt's
    own budget; found by this exact thing happening with a single
    cumulative deadline) for expect_substring to appear
  - if send_or_null is a string, writes it + "\n" to the child's stdin
  - if send_or_null is null, sends nothing (used for a final "this text
    must appear before exit" check)

Prints the full transcript to stderr (always, pass or fail -- this is the
"real terminal I/O" evidence, not an assumption) followed by "EXIT <code>"
naming the child's actual exit status. Exits 0 if every exchange matched
within its own <timeout-seconds> window, 1 otherwise (a timeout, or the
child dying before a later expect was reached).
"""
import json
import os
import select
import subprocess
import sys
import time


def main():
    timeout = float(sys.argv[1])
    exchanges_path = sys.argv[2]
    if sys.argv[3] != "--":
        sys.exit("usage: guided-install-driver.py <timeout> <exchanges.json> -- <argv...>")
    argv = sys.argv[4:]
    with open(exchanges_path, encoding="utf-8") as fh:
        exchanges = json.load(fh)

    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, bufsize=0)
    buf = b""
    transcript = []

    def pump(poll_timeout):
        nonlocal buf
        assert proc.stdout is not None
        r, _, _ = select.select([proc.stdout], [], [], poll_timeout)
        if proc.stdout in r:
            chunk = os.read(proc.stdout.fileno(), 65536)
            if chunk:
                buf += chunk
                transcript.append(chunk.decode(errors="replace"))
                return True
        return False

    ok = True
    for expect, send in exchanges:
        expect_b = expect.encode()
        found = False
        deadline = time.time() + timeout  # fresh budget for THIS exchange
        match_at = -1
        while time.time() < deadline:
            match_at = buf.find(expect_b)
            if match_at != -1:
                found = True
                break
            if not pump(0.2) and proc.poll() is not None:
                pump(0.2)  # one last drain after the child exits
                match_at = buf.find(expect_b)  # the drain above may have just delivered it
                if match_at != -1:
                    found = True
                break
        if not found:
            ok = False
            sys.stderr.write(f"\n*** TIMEOUT waiting for: {expect!r}\n")
            break
        # Keep whatever arrived AFTER the match, not just what's left after a
        # blind `buf = b""` -- two consecutive say() lines can land in the
        # SAME pty read (one os.read() call), so the next exchange's own
        # text can already be sitting in buf right now. Discarding all of
        # buf here throws that away and the next expect then waits forever
        # for a line the child already printed and will never print again --
        # found by exactly that happening (two adjacent prompts, one read).
        buf = buf[match_at + len(expect_b):]
        if send is not None:
            try:
                assert proc.stdin is not None
                proc.stdin.write((send + "\n").encode())
                proc.stdin.flush()
            except BrokenPipeError:
                pass

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        ok = False
        sys.stderr.write("\n*** TIMEOUT waiting for the child to exit\n")
        proc.kill()
        proc.wait()
    while pump(0.1):
        pass

    sys.stderr.write("".join(transcript))
    sys.stderr.write(f"\nEXIT {proc.returncode}\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
