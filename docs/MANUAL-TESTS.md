# serverjack — manual test prompts for other machines

URL: https://<your-host>/  (device must be on the tailnet)

Paste the block for the device into Claude (Claude Code with the Chrome
extension on a desktop, or just follow it by hand on a phone) and send the
results back to the serverjack session. Report each line as PASS / FAIL with a
one-line note; screenshots of anything odd help.

## Desktop (Windows / Linux, Chrome or Firefox)

You are testing a browser-based tmux terminal at https://<your-host>/ .
Open it in Chrome (with the Claude in Chrome extension) or do the steps by hand.
1. Landing page, top to bottom: a "Run a command" box, Shortcuts, Sessions (listed with Open buttons plus a "New shell" form with a Name box and a Directory dropdown), Agents (one collapsed row per coding tool).
2. Create a Shell session named "t-desktop" in ~/workspace. You should land in a terminal with a tab bar on top and "t-desktop" highlighted.
3. Type `echo hello` Enter. Output appears.
4. Type `sleep 30` Enter, then press Ctrl+C with NOTHING selected. The sleep is interrupted (prompt comes back).
5. Type `echo COPYTEST` Enter. Drag-select the word COPYTEST in the output with the mouse. Press Ctrl+C. Then click in the terminal, type `echo ` and press Ctrl+V, then Enter. Expect "COPYTEST" echoed back. (Copy with a selection must NOT interrupt anything.)
6. Copy some text from another app, click the terminal, press Ctrl+V. It pastes. Ctrl+Shift+V also pastes.
7. Click another tab in the bar. The terminal switches; the URL changes to /s/<name>. Click back.
8. Press + in the bar, try to create a session with the same name "t-desktop". An inline error appears. Escape closes the panel.
9. On the home page, Open pops the session out into a separate small window with only the terminal (a ⋯ button in its top-right corner shows/hides the bar) and the home page stays. Clicking Open again for the same session refocuses that window instead of opening another. ☰ inside the pop-out closes it.
9b. In the ⋯ menu of a session: "Open here" opens it in this tab; "Copy SSH command" copies an `ssh -t ... tmux attach` line that works in a terminal; "Open in SSH app" launches your SSH client if one is installed.
9c. From an in-tab session, ↗ pops it out and this tab goes back to the list (you are not attached twice).
10. Press ✕ in the bar, confirm. You are moved to another session (or the list if none).
11. Resize the browser window. The terminal reflows (tmux status bar stays at the bottom).
12. Reload the page while in a session. You reconnect into the same session with its history intact.
Report PASS/FAIL per step plus browser name and OS.

## Mac (Safari and Chrome)

Same steps as Desktop, but copy/paste uses Cmd+C / Cmd+V (native). Ctrl+C is always interrupt on Mac.
Also check: 13. In Safari, ↗ pop-out gives a window without the address bar.

## iPhone (Safari)

You are testing a browser-based tmux terminal at https://<your-host>/ on iPhone Safari. Do each step and report PASS/FAIL with a note.
1. Landing page is readable, buttons are tappable, the Directory dropdown is dark (not a white box). The Run box, Shortcuts, Sessions and Agents sections are all reachable by scrolling.
2. Create a Shell session "t-phone". The terminal opens with a tab bar at the top and a row of keys (Esc, Tab, ⇧Tab, Ctrl, arrows, ^C, PgUp, PgDn) at the bottom.
3. Tap the terminal. The keyboard opens. Is the key row still visible above the keyboard, and is the terminal not hidden under the keyboard? (This is the most likely failure — describe exactly what you see.)
4. Type `echo hi` and Return. Output appears.
5. Type `sleep 30` Return, tap ^C in the key row. The sleep stops.
6. Tap Esc, ↑, ↓, Tab: no crash; ↑ recalls the previous command in bash.
7. Tap Ctrl, then type `c` on the keyboard: acts like Ctrl+C (interrupts a `sleep 30`). Tap Ctrl then `l`: screen clears.
8. Lock the phone for a minute, unlock, return to Safari. The terminal reconnects to the same session on its own (a brief "reconnecting" is fine).
9. Switch to another app and back. Same as 8.
10. Rotate to landscape and back. Terminal reflows.
11. Double-tap and pinch on the terminal: does it zoom the page? (Report; not necessarily a fail.)
12. Long-press in the terminal: can you select and copy text? Long-press then Paste: does it paste?
13. Tap ↗ pop-out: expected to just open a new tab (phones don't do popups). Not a fail.
14. Share → Add to Home Screen. Open it from the home screen. It should open full screen with no Safari bars, and opening a session should stay inside it.
15. ☰ goes back to the list; ✕ kills the current session after a confirm.
Report PASS/FAIL per step and the iOS version.

## Run a command (any device; step 4 needs a real iPhone)

1. Paste `echo RUNBOX; pwd` into the Run box and tap Run. A new tmux session opens in the terminal, the output appears, and you are left at a **shell prompt** in that session (it does not disappear).
2. Go back to the list. The session created in step 1 is in the Sessions list. Kill it.
3. Run `ls /nonexistent-path`. You see the error and still land at a prompt.
4. **iPhone**: run `sudo -k true`. The `[sudo] password for <user>:` prompt appears in the terminal, tapping the terminal opens the keyboard, and typing the password (characters not echoed) then Return succeeds. Then run `sudo -k apt-get -s install cowsay` and confirm the password prompt behaves the same for a longer-running command. This is the main use case — describe exactly what happens if anything is awkward.
5. Run something long (`sleep 60`), lock the phone, unlock: you are still attached and the command is still running.

## Save as a shortcut

1. In the Run box, enter `df -h /` , tick "save as a shortcut", give it a name, Run.
2. Go back to the list: the shortcut appears in the Shortcuts section. Tap it: it runs in a new session and leaves you at a prompt.
3. `cat ~/.config/serverjack/shortcuts.json` in a terminal shows it.
4. Delete the shortcut from the page. It disappears from the list and from the JSON file.

## Agents accordion (any device)

0. **The accordion itself**: every tool is one collapsed row, and the whole Agents section is about as tall as one card. Each row reads without opening it: tool name, state ("Not installed" / "Installed · not logged in" / "Ready" with a green dot), and a pill for any server or daemon ("running" / "exited" / "stopped"). Tap anywhere on a row — the whole row is the target, comfortably tappable on a phone — and it opens while the previously open row closes. The chevron on the right flips. On a phone nothing overflows sideways at any point.

Then test each of the three states. The easiest way to see all three is on a machine where at least one tool is missing and one is installed.

1. **Not installed**: a tool with no binary on the box shows an Install button and the exact install command as text. Tap Install: the command shown is the command that runs, it runs in a visible terminal, and when it finishes you are at a prompt. Reload the landing page: the row has moved on to the next state.
2. **Installed, not logged in**: the row shows a Log in button, and "Open anyway" underneath it. Tap Log in: the login flow runs in the terminal and prints a URL or device code that is readable and tappable/selectable on the phone. Complete it, reload: the row is now Ready.
3. **Ready**: the body is the directory picker, then one option row per way of starting the tool. Each option row has its label, a one-line note saying how it differs from the others, and its button(s) on the right (underneath, on a phone). Check the order: Open, then any extra actions, then the server, then the daemon, then a quiet "Log in / switch account". Pick a directory and tap the Open row's button: the tool starts in that directory.
4. Every option that needs a directory (Open, an action marked `dir`, starting a server) uses the one picker at the top — change it and check the next thing you start lands in the new directory.
5. If Node.js is not installed, the Gemini CLI row says so instead of offering an Install button that would fail.
6. `SERVERJACK_TOOLS=claude,codex` in the env file (restart the units) shows only those two rows, in that order. Unset it again afterwards.
7. `~/.config/serverjack/tools.json` containing `[{"id":"gemini","hidden":true}]` hides the Gemini row and leaves the others alone.
8. A tool installed into a private bin dir that only `.bashrc` adds to `PATH` (e.g. OpenCode in `~/.opencode/bin`) still reads as installed — that is the `paths` field doing its job.
9. If an action fails (e.g. start a server in a directory that doesn't exist), the page comes back with the error at the top **and that tool's row open**, not collapsed.

## Remote control (needs the tools installed and logged in)

1. **Claude Code**: open the Claude Code row and tap Start on the "Remote Control server" option row. A tmux session named `claude-remote` opens and `claude remote-control` prints a **QR code** in the terminal. On a desktop the QR is scannable from the screen with the Claude app; on a phone check that it renders as a QR and not as broken block characters. Go back to the list: `claude-remote` is in the Sessions list, the Claude Code row's summary shows the server pill as "running", and its option row now offers Stop and Open.
2. **Codex daemon**: on the Codex row, tap Start on the daemon option row. Reload the landing page: the summary pill shows the daemon as running, and `~/.codex/app-server-daemon/app-server.pid` exists with a live pid. Tap Stop, reload: it shows stopped and the pidfile is gone or stale. Start it again and tap "Pair with phone": `codex remote-control pair` runs in a terminal and prints pairing output; pair the ChatGPT app and open a session in a directory from the app.
3. **OpenCode**: tap Start on its server option row. Session `opencode-serve` appears and `opencode serve` stays up; the OpenCode mobile app can reach it over the tailnet.
4. **Copilot CLI**: the "Open with remote control" option row runs `copilot --remote` in a session; the plain Open row above it runs `copilot` without it. Claude Code has the same pair.
5. Kill any test sessions with ✕ when done.

## Coding-tool sessions (any device)

1. From the Claude Code row, pick a directory and tap Open. Claude Code starts inside the session in that directory.
2. Same for Codex. If Codex isn't installed you should see "codex: command not found" followed by a shell prompt in the chosen directory — not a blank or vanished session.
3. Kill both test sessions with ✕ when done.

## Second account on the same machine

Needs a second Linux login on the box. Run as that account, with the first
account's serverjack up and published on 443.

1. `bash install.sh` with no flags: it refuses before starting anything, names
   the port that is taken, and prints a paste-ready command with free ports,
   a free HTTPS port and a `--title` suggestion. Check with `systemctl --user
   status serverjack` that nothing of this account's was started.
2. Re-run with the printed flags. `~/.config/serverjack/env` now has
   `SERVERJACK_PORT`, `TTYD_PORT`, `SERVERJACK_HTTPS_PORT` and
   `SERVERJACK_TITLE` set to those values; both units are active.
3. The "Open:" line ends in `:8443` (or whichever HTTPS port). Open it on a
   phone: the page loads, the tab title is this account's `--title`, and the
   Sessions list shows **only this account's** tmux sessions (`tmux ls` in the
   terminal agrees; the other account's sessions are not listed anywhere).
4. Reload the first account's URL (no port). It still works and still shows the
   first account's sessions — the second install did not steal `/` on 443.
   `tailscale serve status` lists both blocks.
5. Re-run `bash install.sh` in the second account with no flags: same ports
   read back from the env file, no duplicate lines in the env file, no change
   to the 443 mounts.
6. If the second account is not the `tailscale set --operator` user, serve is
   denied: the installer prints the one-time root step and the note that the
   operator grant is a single username per machine, and the local units are
   still running (reachable at `http://127.0.0.1:<port>/`).
7. `bash uninstall.sh` in the second account: it says it is turning off
   `https=<its own port>` only, and `tailscale serve status` still shows the
   first account's 443 block intact and working in a browser.
8. Re-install the second account and check `loginctl show-user <user> -p Linger`
   — linger is per user, so this account needs its own
   `sudo loginctl enable-linger` before its units survive a logout/reboot.
