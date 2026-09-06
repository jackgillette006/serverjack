# Browser terminal — manual test prompts for other machines

URL: https://<your-host>/  (device must be on the tailnet)

Paste the block for the device into Claude (Claude Code with the Chrome
extension on a desktop, or just follow it by hand on a phone) and send the
results back to the serverjack session. Report each line as PASS / FAIL with a
one-line note; screenshots of anything odd help.

## Desktop (Windows / Linux, Chrome or Firefox)

You are testing a browser-based tmux terminal at https://<your-host>/ .
Open it in Chrome (with the Claude in Chrome extension) or do the steps by hand.
1. Landing page: sessions listed with Open buttons; the "New session" form has Shell / Claude Code / Codex, a Name box and a Directory dropdown.
2. Create a Shell session named "t-desktop" in ~/workspace. You should land in a terminal with a tab bar on top and "t-desktop" highlighted.
3. Type `echo hello` Enter. Output appears.
4. Type `sleep 30` Enter, then press Ctrl+C with NOTHING selected. The sleep is interrupted (prompt comes back).
5. Type `echo COPYTEST` Enter. Drag-select the word COPYTEST in the output with the mouse. Press Ctrl+C. Then click in the terminal, type `echo ` and press Ctrl+V, then Enter. Expect "COPYTEST" echoed back. (Copy with a selection must NOT interrupt anything.)
6. Copy some text from another app, click the terminal, press Ctrl+V. It pastes. Ctrl+Shift+V also pastes.
7. Click another tab in the bar. The terminal switches; the URL changes to /s/<name>. Click back.
8. Press + in the bar, try to create a session with the same name "t-desktop". An inline error appears. Escape closes the panel.
9. Press ↗ (pop out). A small separate window opens with only the terminal; a ⋯ button in its top-right corner shows/hides the bar. Close it.
10. Press ✕ in the bar, confirm. You are moved to another session (or the list if none).
11. Resize the browser window. The terminal reflows (tmux status bar stays at the bottom).
12. Reload the page while in a session. You reconnect into the same session with its history intact.
Report PASS/FAIL per step plus browser name and OS.

## Mac (Safari and Chrome)

Same steps as Desktop, but copy/paste uses Cmd+C / Cmd+V (native). Ctrl+C is always interrupt on Mac.
Also check: 13. In Safari, ↗ pop-out gives a window without the address bar.

## iPhone (Safari)

You are testing a browser-based tmux terminal at https://<your-host>/ on iPhone Safari. Do each step and report PASS/FAIL with a note.
1. Landing page is readable, buttons are tappable, the Directory dropdown is dark (not a white box).
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

## Codex / Claude Code sessions (any device)

1. New session → Claude Code, name "t-claude", directory ~/workspace/projects/fit-app. Claude Code starts inside the session in that directory.
2. New session → Codex, name "t-codex". If Codex isn't installed you should see "codex: command not found" followed by a shell prompt in the chosen directory — not a blank or vanished session.
3. Kill both test sessions with ✕ when done.
