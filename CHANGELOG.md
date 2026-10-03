# Changelog

All notable changes to serverjack are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## Unreleased

### Changed

- **Running sessions come first on the landing page.** With any sessions
  running, the page now reads Sessions, Start a session, Shortcuts, Agent
  servers. Before, the Start card and every shortcut sat above them, so no
  session row was on the first screen of any phone or laptop and reopening
  or killing one -- the everyday thing -- always meant a long scroll. With
  none running, Start a session still leads.

### Fixed

- **Agent servers started from the page read "exited", and Start killed
  them.** A Remote Control or OpenCode server started from its card (or by
  start at boot) showed "exited" with no Stop, because since 1.5.0 the
  command ran behind a `bash -lc` that tmux reported instead of the server.
  Pressing Start again, a double tap, or any serverjack restart with "start
  at boot" ticked then killed the live server and started a new one,
  silently dropping the phone app's sessions. The pane now reports the
  server itself, a running server reads running with Stop and Open, and a
  second Start says "already running" and leaves it alone. Servers started
  by 1.5.0 that are still up are recognised as running too. `/api/status`
  counts them again. A server is judged by its own pane, so opening a
  second window in its session (prefix+c, the window tabs) or splitting it
  no longer makes it read "exited" either.
- **Servers are found by what they are, not by their name.** serverjack
  marks the sessions it starts as servers (tmux session options) and finds
  them by that. Two project directories with the same name
  (`~/projects/3d-lab`, `~/projects/ai/3d-lab`) now get a server each
  (`claude-remote-3d-lab-2`) instead of refusing or replacing the other
  one; a renamed server is still on its card, and Start no longer starts a
  second one beside it; and an interactive session that merely has a
  server-like name (Claude in `~/projects/remote-tools` is
  `claude-remote-tools`) is no longer listed as an exited server whose
  Remove button would kill it. Server sessions carry a small **server** tag
  in the Sessions list. A session serverjack did not start is no longer
  taken for a server even when its name matches: a `tmux new -s
  opencode-serve` you made by hand is not on the card, and Start makes
  `opencode-serve-2` beside it. Only servers started by serverjack 1.5.0
  (same name and same command) are still adopted.
- **The agent card is right as soon as a login or install finishes.** A
  look at the list in the middle of a login (Back to finish OAuth in another
  app, another tab, a dashboard polling `/api/status`) kept the card on
  "not logged in" (or "Not installed") for up to a minute after it had
  worked. Installed is now checked on every load, and the login check runs
  fresh while a login or install session is still running.
- **A slow or hung login check no longer holds up the page.** The landing
  page, `/api/status` and `/api/tools` waited for every tool's login check
  once a minute (up to 15 s each if a CLI hung). The last answer is now
  shown at once and re-checked in the background, one check per tool at a
  time, and a check gives up after 5 s.
- **Leaving a page never leaves a black screen.** With the CRT effects on,
  the power-off collapsed the page and held it invisible until the next
  page arrived — on a slow network, or with serverjack down, a home-screen
  app sat on a black screen with no sign of life. If the next page has not
  arrived within a second, the old one comes back.
- **"Start at boot" entries you ticked are visible and can be unticked.**
  Ticking the box on a server's Start row saved an entry for the typed
  directory, but the box could only ever show the home directory's, so it
  came back unticked, nothing on the card mentioned it, and it could only be
  removed by starting that server and stopping it. A saved directory with
  nothing running now has a row of its own ("Starts at boot; not running
  now") with the box ticked and a Start button; the per-directory Start row
  no longer has a box (tick it on the server's own row); and a single
  server's box shows its one entry and says which directory it starts in,
  running or not. A directory that has since gone (deleted, a drive not
  mounted) gets a row saying so, and unticking it just forgets the entry: it
  neither re-creates the directory nor fails because it can't.
- **The directory picker on an agent card is where it is used.** Every
  ready card used to start with an unlabelled picker that most of its
  buttons ignored (Codex has nothing that reads a directory), far above the
  Start row it belonged to, and Enter in it ran the card's first button —
  on Codex, "Pair with phone". The picker now appears, labelled
  **Directory**, only in a row whose button uses it, and Enter in it can
  only press that button.
- **Collapsed agent rows stay short on a phone.** A per-directory server
  showed one wordy pill per instance in the collapsed row, each wrapping to
  several lines at phone width with its status dot squashed to a sliver, so
  Claude's row could be 200+ px tall. It is now one pill per server with the
  counts ("Remote Control server: 2 running · 1 exited", each directory in
  its tooltip and in the open card), every pill stays on one line (its label
  is what gets cut short), and dots keep their size.
- Agent card copy: Remove on an exited server asked "Stop Remote Control
  server?"; Stop and Remove now say what they do and name the directory
  ("Remove the exited Remote Control server in “~/projects/web-app”?").
  Codex's daemon note pointed to a pairing code "below" for a row that is
  above it. Running an action names its session in lower case
  (`pair-with-phone`, not `Pair-with-phone`, which sorted above every other
  session).
- A fresh install with no agent installed showed a lone "Shell" choice and
  nothing about where agents come from. The Start card now says "No coding
  agents installed yet" and links to Agent servers, whose hint now reads as
  a sentence and starts with installing.
- A command ending in `;` — the `\;` closing a pasted
  `find . -exec rm {} \;` — or a directory or session name ending in one
  failed oddly: tmux reads a trailing `;` in any argument as the end of its
  own command. serverjack now escapes it.
- **Directory picker: a typed folder name no longer creates a new, empty
  folder.** Typing part of a name (`game`, `3d`) and pressing Enter, Go on a
  phone, or tapping Start sent the text itself, so the session started in a
  brand-new empty `~/game` instead of the `~/projects/game` the list was
  suggesting -- and that stray folder then outranked the real one in later
  searches. Now the folder with exactly that name (or else the top match) is
  highlighted as you type, and Enter, Go and Start take the highlighted row
  (Enter pressed straight after typing waits for the list to catch up), so
  `lab` finds `~/projects/ai/lab` even when `~/projects/3d-lab` ranks above
  it. A new folder is something you can see: if nothing matches, the list's
  only row is **+ New folder `~/name`**, and that is what Start creates; a
  typed path (with a `/` or a leading `~`, or `.` for the default directory)
  is still used exactly as typed. With the list dismissed, Start uses a name
  only when exactly one folder has it, and otherwise shows the list again
  rather than guess. A name the page fills in itself is looked up before it
  is sent, and an agent card's "start at boot" box uses the same folder its
  Start would (it used to make `~/game` too).
- Directory picker: a folder is created only when a session actually starts
  in it. A Start refused for its name still left the new folder behind, and
  saving a shortcut with a mistyped directory silently created it. Now a
  refused start leaves the disk as it was, and Add a shortcut and "start at
  boot" refuse a folder that doesn't exist ("Not a directory:
  ~/projects/gmae") instead of inventing one. Errors name the path in its
  `~` form, the way the picker shows it, and a directory with a NUL byte in
  it is a clean error instead of a dropped connection.
- Directory picker on touch screens: swiping the suggestion list scrolls it.
  It used to pick whichever folder your finger first landed on, so only the
  rows visible without scrolling could ever be chosen.
- Directory picker: the suggestion list no longer covers what's below it.
  It sits in the page under the field and pushes the rest down (about five
  rows tall at most), on a phone and a desktop, in the Start card, the agent
  cards, Add a shortcut, the default-directory form and the terminal's +
  panel. Tapping or clicking Name, Save, Start or Start & open used to pick
  a folder instead. A slow click is fine too: the list waits for the button
  to come back up before it closes, so Start doesn't move out from under it.
- Terminal + panel on phones: the directory list hung off the bottom of the
  sheet (two rows visible) over Start & open, and with the keyboard up the
  top of the sheet went off-screen. The sheet now stops below the tab bar,
  so + still closes it, and scrolls inside when it's taller than the screen.
- Directory picker: Tab and Shift+Tab out of an untouched field just move
  on. Each press used to fill in a folder (`~/`, then `~/bin/`, ...) and the
  session started there; Shift+Tab drilled down too. Tab still completes and
  drills into a match once you've typed or arrowed to one.
- Directory picker: closing the list (a pick, Escape, or leaving the field)
  cancels a lookup still on its way, so a slow answer -- likely over
  Tailscale on a phone -- no longer reopens the list after a pick, or over
  the next field after you've moved on.
- Directory picker: a long parent path no longer hides the folder name. The
  parent is shortened from its left end and the folder name always shows,
  so rows under the same long parent can be told apart; hovering a row shows
  its full path.
- Directory picker with a mouse: rows highlight on hover (and Enter takes the
  hovered row), a right-click no longer picks a row, and a click on the
  list's padding no longer closes it and drops focus.
- Accessibility: the directory field points at a labelled suggestion list
  (`aria-controls`), the Start card's fields have names a screen reader can
  announce (Directory, Session name, Command, Shortcut name), and the
  terminal + panel's Name and Directory labels belong to their fields, so
  clicking a label focuses it and voice control can find them.
- **Start a session: an error no longer wipes the directory.** Any refusal
  (a taken name, a bad name, a folder that isn't one) came back with every
  field refilled except the directory box, so the corrected retry quietly
  started in `~` -- a pasted `./deploy.sh` ran in the wrong place. The
  directory now comes back too, and so does the *Keep this command in
  Shortcuts* tick (it used to come back unticked, so the retry didn't save
  the shortcut either). Same for Add a shortcut, a failing agent card and
  the terminal page's `/new`.
- **Multi-line commands run line by line.** Browsers send every newline in a
  text box as CR+LF, and each line but the last ran with a stray carriage
  return glued to its last word (`cd: $'projects\r': No such file or
  directory`). Fixed for the Start card, Add a shortcut and `/run`; shortcuts
  already saved that way are repaired when they're read.
- **One tap is one submit.** On a slow link a second tap on Start (or Run,
  Save, an agent button) sent the form again: the command ran twice, a saved
  shortcut appeared twice, or you landed on "already exists" for the session
  you had just made. A form now ignores further submits until the page
  changes; Start reads *Starting…* meanwhile, and Back gives you a usable form.
- **Back and reload never re-run a form.** An error page stayed at its POST
  address (`/start`, `/tools`, `/rename`, ...): Back to it showed Chrome's
  "Confirm Form Resubmission" or Firefox's "Document Expired", and WebKit
  silently sent the form again. The address bar now reads `/` with the form
  still filled in.
- **Kill, Rename, shortcuts, start at boot and the Codex daemon land where
  you were.** Each used to reload the page at the top with every card
  closed and no word about what happened; on a phone the result was one to
  two screens down. The page now comes back at that section or agent card,
  open, with one line saying what happened ("Killed “main”.", "Saved
  shortcut “Deploy”.", "Codex: Remote control daemon stopped."), and
  anything half-typed in the Start card is kept. The note shows once: a
  reload or Back doesn't bring it back (the old "Default directory: ..." note
  did, on every reload).
- **Kill and Rename happen in place.** No reload: the row goes away or shows
  its new name, and an agent card whose server it was is redrawn to match.
  Rename opens focused with the old name selected, refuses `:` and `.`
  before sending, and shows a refusal right under the field with the menu
  still open and your text kept.
- Changing the default directory ("Starts in ~ · change") no longer empties a
  half-filled Start card, and a folder it refuses is reported inside that
  form instead of at the top of the page, off-screen on a phone.
- Back after starting an agent left Chrome showing two chips lit, the command
  box up and the previous command ready to run again. The Start card now
  comes back clean and consistent.
- Renaming a session to a name starting with `-` failed with tmux's raw
  "unknown flag" error, although creating one worked.
- A session name starting with `$` was accepted, and the session then
  couldn't be opened, killed or renamed (tmux reads `$x` as a session id, and
  `$3` would have hit someone else's session). It's refused up front now.
- Unnamed sessions are named after the command that actually runs, past a
  wrapper's options: `sudo -u nobody true` is `true` (was `u`), `env FOO=1
  printenv` is `printenv` (was `foo-1`).
- Renaming onto a taken name said "Open it instead.", which was written for
  starting a session; a rename now says "Another session is already called
  “main”. Pick a different name."

- **Dark scrollbars and checkboxes.** The page never said it was dark-only, so
  Chrome, Edge and Firefox drew light-grey scrollbars (on the page, the folder
  suggestions and a long command box) and white unchecked checkboxes next to
  the dark UI. Every page now declares `color-scheme: dark`.
- **Home-screen app: nothing scrolls under the status bar any more.** The
  iPhone app draws under a transparent status bar, and once the list was
  scrolled, cards and the bright Start button passed right under the clock.
  A solid strip the height of the status bar now stays behind it (it is zero
  tall on desktop, Android and in landscape).
- **"serverjack serverjack" in the header.** The title next to the wordmark
  defaults to the hostname; when that is also "serverjack" it is now left out.
- **The 403 page no longer calls you "another tailnet user … signed in as
  nobody"** when no Tailscale identity reached serverjack at all (opening it
  on `127.0.0.1`, over an SSH port-forward, or through a proxy that isn't
  trusted for identity) -- usually the owner. It now says no identity
  arrived and points at the `tailscale serve` address; a real wrong login
  still gets the old wording, and the allowed logins are still never named.
- **Session rows on a phone show what matters.** The meta line was one
  ellipsised line in the order command · path · windows · age · attached, so
  on a phone the path ate the space and the window count, age and
  "attached" were cut off (leaving only the dot's colour). It now leads with
  the short facts -- **attached** in words, the window count when there is
  more than one, the age -- and the command and path take what is left.
  Shortcut rows lead with their directory, so two shortcuts that differ
  only in where they run can be told apart.
- **The age says what it measures.** "6m ago" was the session's creation time
  but read as last activity; it now reads `up 6m` (`up 3h`, `up 2d`), the
  same word the machine line above uses.
- **Long names end in "…"** instead of being cut mid-letter, the full name is
  a hover title on desktop, and the "built-in" pill on the Update row is no
  longer sliced on a 320px screen. The shortcut name fields now stop at the
  60 characters the server keeps, instead of silently cutting the rest.
- **The ⋯ menu fits on narrow phones.** On a 375px or smaller screen the menu
  (and more so with Rename unfolded) ran off the left edge, cutting "Open
  here" to "here" and hiding the start of the rename box. Below 480px it now
  drops in under the row at the row's width. The rename box is 16px, so iOS
  no longer zooms the page when you tap it.
- **Screen readers and Voice Control can tell rows apart.** Every row's ⋯,
  Open, Remove and Run used to have the same name ("More", "Open", …); they
  are now "More actions for main", "Open main", "Remove shortcut Logs",
  "Run Logs", and the status dot is announced as "attached"/"not attached".
- **"Open in SSH app" is now "SSH app (login only)".** It sat in each
  session's menu but opened the same bare `ssh://user@host` for all of them;
  an `ssh://` link cannot carry `tmux attach`, so the label now says what it
  does (Copy SSH command is the one that attaches).
- **One ⋯ menu at a time, and Escape closes it.** Opening a second row's menu
  left the first one open underneath (so the "Kill session" you saw could
  belong to a different row), Escape did nothing, tabbing out left the menu
  covering the next rows, and a half-typed rename was still there next time.
  Now opening one closes the others, Escape closes Rename and then the menu
  and puts focus back on its ⋯, focus or a press outside closes it, and a
  closed menu always reopens with Rename folded and the real name in it.
- **A menu near the bottom of the screen opens upward** (or scrolls itself
  into view when there is no room either way) instead of opening off-screen
  so the tap looked like it did nothing; an open menu's ⋯ now looks pressed.
- **"Copy SSH command" tapped twice no longer sticks on "Copied".**
- **Ctrl/Cmd/Shift-click on Open** gets the browser's own new tab or window
  on the normal session page, instead of our pop-up (or, on "Open here",
  instead of navigating the list away).
- **The session list keeps itself current.** It was a snapshot from page
  load: on a desktop, where the list tab stays open while sessions pop out,
  and in the home-screen app, which resumes without reloading, sessions
  killed or started elsewhere, attached dots and ages all went stale, and
  Open on a session that had ended loaded a full copy of the landing page
  with an error at `/s/<name>` (in a 1000x650 pop-up on desktop). The list
  now re-reads the sessions every 15 seconds while visible and whenever the
  page comes back, patching rows in place (never under an open menu), says
  so when serverjack can't be reached, and Open on a session it knows has
  ended shows a note instead. `/s/<name>` for a gone session redirects to the
  list with a one-line note, or in a pop-out shows a small "session ended"
  page with a Close button.
- **The session you just left no longer shows as "attached".** The list was
  rendered while the old page's terminal connection was still closing, so
  every round trip marked that session attached; a second look a second
  after load corrects it.
- **Bigger touch targets.** On touch screens the disclosures ("Save as a
  shortcut", "Starts in … · change", "Add a shortcut"), the Shell/agent
  chips, the save checkbox's label, Docs, the CRT toggle, the rename box and
  its Save, and the agent cards' small buttons are now at least 44px tall
  (some were 18-24px). "Start at boot" -- which acts the moment it is
  ticked -- gets a 44px label and is kept clear of the Stop/Start button
  next to it. "Starts in … · change" is the small muted footnote it was
  always meant to be (its style lost to a more specific rule), and the CRT
  toggle meets text contrast.
- **Windows Contrast themes** no longer hide which Start choice is selected
  or erase the status dots (both were drawn only with colours and
  backgrounds that a contrast theme replaces).
- The command box's example fits its two rows on 320-360px phones
  ("Optional command, e.g. sudo apt install ffmpeg"), and install commands in
  an agent card's notes wrap at spaces instead of mid-word
  (`curl -fsSL http` / `s://...`).
- `/favicon.ico` answers with the app icon instead of a 404 on every desktop
  visit, and a client that hangs up mid-response (a phone locking, a tab
  closing) no longer leaves a `BrokenPipeError` traceback in the journal.

### Changed

- **"Save as a shortcut": naming it is enough.** A name typed into the panel
  was thrown away unless the separate box was ticked too; now typing a name
  ticks the box, and the box decides: untick it again and nothing is kept.
  Saving with no command is refused instead of silently starting a plain
  shell.
- **Shortcut runs are named after the shortcut** ("Disk usage" runs as
  `disk-usage`, then `disk-usage-2`), not the command's first word -- two
  shortcuts that both start with `cd` used to share one name family.
- **Update serverjack asks before it runs** ("Update serverjack and restart
  it?"): one stray tap used to pull new code and restart every open
  terminal. The row shows its whole command (wrapped, home as `~`) and says
  what it does for this install.
- The duplicate-name error on the Start card now has an **Open** button for
  the session that has the name; its text no longer says "Open it instead."
- Start card copy: the hint says why `sudo` prompts work (a real terminal)
  and hides when an agent is picked; the shortcut-name box says it names the
  shortcut. The empty Shortcuts hint says "No saved shortcuts yet" (the
  built-in Update row is right above it) and is a line, not a second card.
- Shortcut rows wrap a long command instead of cutting it off.

### Added

- Directory picker: a **›** at the end of each suggestion shows that
  folder's subfolders -- the touch equivalent of Tab, and clickable with a
  mouse too -- while tapping or clicking the row itself still picks it.
  Tapping the field again after a pick brings the list back.

- **Edit a shortcut.** A pencil on each saved shortcut opens it in the
  shortcut form; *Save changes* replaces it in place, same position in the
  list, and *Cancel* puts the form back to Add a shortcut. A reload keeps
  the editor open; if the shortcut was removed meanwhile (another tab), what
  you typed comes back as a new shortcut to save. The built-in Update row
  has none.

## 1.5.0 - 2026-09-16

- Directory picker: picking or Tab-completing a suggestion now keeps the
  `~/...` form in the box instead of swapping in the expanded absolute home
  path (it looked jarring to watch `~/projects` turn into `/home/you/...`).
  Submits are unchanged -- the server expands `~` either way.

- **Reliability**: the systemd units set `OOMPolicy=continue`. Before, a
  kernel OOM kill of any process in a unit's cgroup -- including the tmux
  sessions and coding agents started through serverjack, which share it --
  stopped the whole unit under systemd's default `OOMPolicy=stop`, and
  because that stop is "clean" `Restart=on-failure` did not bring the page
  back. Now an OOM-killed child leaves the front door up; only an OOM kill
  of the unit's own main process counts as a failure (and still restarts).

- **WSL**: `bin/serverjack-setup` now detects WSL and, while the port is
  still the untouched default (7680), offers to install on `--port 7690`
  instead — Windows Delivery Optimization already listens on 7680 on the
  *Windows* side of a WSL2 machine, so a Windows browser could never reach
  serverjack there even though it comes up fine on `127.0.0.1:7680` inside
  the VM. `install.sh`'s own final summary prints the same warning and fix
  for anyone who lands on 7680 without going through the guided prompt. See
  the README's new [WSL](README.md#wsl) note.

### Added

- Every directory picker (Start a session, each tool card, Add a shortcut,
  the terminal's new-session panel) is now one combobox with search,
  autocomplete and Tab completion, replacing the old `<select>` + "…or type
  a path" input pair. Typing part of a folder's name finds it anywhere it's
  nested, not just at the top level ("3d-lab" finds
  `~/projects/ai/3d-lab`); arrow keys move the highlight, Enter picks it,
  and Tab fills the highlighted-or-first match with a trailing `/` and
  shows its children, so it drills down the way shell completion does.
  Backed by a new `GET /api/dirs?q=` (`dir_search()` in `bin/serverjack`),
  behind the same identity check as `/api/sessions`. A typed path that
  doesn't exist yet is still created when the session starts; a picked
  suggestion always exists already. New `SERVERJACK_DIR_DEPTH` (default 5)
  caps how deep the search index walks under each `SERVERJACK_DIRS` root.
  Results rank **least nested first**: a shallower match always beats a
  deeper one regardless of exact/prefix/substring, which only breaks ties
  at the same depth; a folder's children (matched only through its own
  name) always sort after every direct match, however shallow, so drilling
  in never buries a real match under its own contents. You can also set a
  **default directory** from the page itself — the muted "Starts in
  `~/projects` · change" line under the Start card's picker reveals an
  inline form, saved to `prefs.json` — which an empty picker, a relative
  typed path, and every other picker's placeholder on the page (Add a
  shortcut, every tool card, the terminal's new-session panel) all use
  instead of `~`. New `SERVERJACK_DEFAULT_DIR` env sets the fallback for
  before one is ever chosen.

## 1.4.0 - 2026-09-15

### Fixed (round 5 review: security blockers, 17 install-flow findings, 7 installer gaps)

- **Security.** The guided install (`bin/serverjack-setup`) used to run
  `install.sh` (starting the units and publishing the tailscale serve route)
  BEFORE writing `SERVERJACK_ALLOW`, leaving a fresh install briefly
  reachable with no per-login restriction. `install.sh` gains an `--allow`
  flag that persists it to the env file before anything starts; setup
  resolves the allow-list and passes it through instead of a post-hoc
  `env_setcfg` + restart.
- The rerun menu's "publish" option now actually turns publishing off (and
  changes the https port) instead of leaving the old tailscale serve
  mapping reachable regardless, and asks the allow-list question on the
  local-only -> published transition, which it used to skip.
- `serverjack-ctl update` now requires SHA256SUMS to independently confirm
  a release archive, not just note a disagreement with the bootstrap's own
  embedded sha256; `bin/serverjack-ctl`'s `activate_release()` is now the
  one place update/resume/rollback share backup, the interruption trap, the
  health wait and restore-on-failure (the resume path used to have none of
  that); `serverjack-ctl`/`serverjack-setup` back up and restore
  `~/.local/bin/ttyd` and `fzf` across a failed update, not just the units/
  env/binaries they already covered.
- `install.sh` now actually fails (exit 1) when the units or the local
  health check never come up, instead of always exiting 0; the managed-
  install finalizer only clears the resumable `"state": "installing"`
  marker once that health check has actually confirmed success.
- `bin/serverjack-setup` takes `~/.local/share/serverjack/.lock` narrowly
  around its own mutations (install.sh, install.json/env writes, serve
  changes), so a guided install/rerun can no longer interleave with a
  concurrent `serverjack-ctl update`/`rollback`.
- `--no-serve` now persists (`SERVERJACK_SERVE` in the env file) for a git-
  checkout install too, so `serverjack-ctl update`'s git-channel path (and
  the rerun menu, and the page's Update row) stop silently re-publishing on
  every later update.
- The bootstrap validates every flag it's about to forward to
  `serverjack-setup` (the set it actually accepts, plus install.sh's legacy
  `--ttyd-port`, accepted with a warning) BEFORE downloading or staging
  anything -- a typo used to only be discovered after a release was already
  staged and "current" already swapped to it.
- One `update_install_json()` read-modify-write helper (`bin/serverjack-lib.sh`)
  is now shared by the bootstrap, `serverjack-ctl` and `serverjack-setup`,
  so a caller that only means to change one field (`install_args`) can no
  longer silently drop another (most importantly an in-progress update's
  `"state": "activating"`).
- `bin/serverjack-ctl`'s `units_active()` used to be a single
  `systemctl is-active unit1 unit2` call -- that's a logical OR per
  `systemctl(1)`, not AND, so a health check could pass with one of the two
  units down. Every local health-check `curl` now also carries a
  per-request timeout, so a listener that accepts a connection and never
  responds can no longer hang a whole health-check loop.
- Fixed the systemd-escaped `ExecStart=` comparison (`bin/serverjack-ctl`'s
  `detect_channel()`, `bin/serverjack-setup`'s rerun detection) for a
  `$HOME` containing a literal `%`, `\` or `"`.
- `build-release.sh`'s archive mtime is now pinned to the release commit's
  own timestamp (`SOURCE_DATE_EPOCH`), not the real build-time clock, so two
  builds of the same tree are actually byte-identical (its `RELEASE` file's
  own build timestamp aside, which stays real on purpose).
- `bin/serverjack-ctl`'s and `bin/serverjack-setup`'s `--help` derive their
  printed range from the header comment's own end instead of a hardcoded
  line count that silently truncates as the header grows.
- Fixed a broken README anchor link (text and href naming two different,
  real sections) and added `scripts/check-readme-anchors.py` to catch it
  again.
- The page's "Update serverjack" row is now gated on
  `~/.local/bin/serverjack-ctl` actually existing, not just on this process
  physically living under `~/.local/share/serverjack/releases/` (a tarball
  extracted there by hand, never run through the bootstrap, used to show
  the row and then fail to launch it).
- `serverjack-setup`'s `read_tailscale_self()` used tab as its field
  separator with `IFS=$'\t' read` -- tab is one of bash's built-in "IFS
  whitespace" characters regardless of what else is in `$IFS`, so a tagged
  node with no user login (an empty field between two tabs) silently
  shifted every field after it. Switched to `|`, an ordinary delimiter.
- `serverjack-setup` now treats a missing `install-path` with no unit as
  "nothing installed here" (pointing at the one-liner) instead of
  "internal error" -- the ordinary state right after `uninstall.sh`, which
  deliberately removes that file.
- `bootstrap/launcher.sh` (the canonical source of the website's physical
  installer, `bootstrap/launcher.sh` here / `serverjack/install.sh` in the
  website repo, exported by `scripts/export-launcher.sh`) fixed a real bug
  where its own progress message printed to stdout got pasted into the
  downloaded bootstrap's path by the caller's own command substitution;
  refuses a truncated or HTML response before ever running it; and, along
  with the bootstrap itself, now checks the real prerequisite floor (bash,
  curl, python3, tar, sha256sum, a working `systemd --user`, flock, CA
  certificates) before downloading or staging anything, offering the exact
  distro install command with sudo (default no).
- The guided flow now completes a `--unix` install's "tailscale serve needs
  root to proxy to a Unix socket" step interactively too (same consent
  prompt as the other one-time root steps), instead of only ever printing
  it for the operator to paste by hand.
- `.github/workflows/release.yml` now refuses to draft a release unless the
  tagged commit already has passing "Browser and security tests", "Lint"
  and "Install suites (managed + guided)" check runs, and verifies the
  built archive's sha256 against both SHA256SUMS and the bootstrap's own
  embedded pin (plus the bootstrap's end-of-file marker) before drafting.
- README: qualified "No Node, no sudo, no root" and the unconditional
  Tailscale-reachability claim, corrected the VibeTunnel/node-pty
  comparison, bumped the stated Python floor to 3.10 (3.9 still works),
  added a "Tested on" platform list, documented the real one-command-
  install prerequisite floor and the git-checkout-to-managed migration
  path, and relabeled the guided setup's final tailnet check as confirming
  the app answers locally -- never as proof unauthorized users are denied.

### Added

- **One-command managed install.** `scripts/build-release.sh <version>`
  packages a release archive (`dist/serverjack-<version>.tar.gz`) and renders
  `dist/serverjack-bootstrap.sh` from `bootstrap/serverjack-bootstrap.sh.in`,
  with the archive's URL and sha256 embedded. The rendered bootstrap installs
  a specific released version with no git checkout: downloads and verifies
  the archive, extracts it to `~/.local/share/serverjack/releases/<version>/`,
  points `~/.local/share/serverjack/current` at it, writes `install.json`,
  then hands off to that release's own `bin/serverjack-setup`. Refuses to run
  as root or to silently take over an existing (git or managed) install.
- **`bin/serverjack-setup`: the guided part of the one-command install.**
  Runs before `install.sh` (the bootstrap execs it; it's also runnable by
  hand from a checkout, and aliased as `serverjack-ctl setup`), asking on
  `/dev/tty` whatever `install.sh` itself never does — each question backed
  by the same flag `install.sh` takes, so a fully-flagged run never touches a
  terminal at all: confirms a supported OS/architecture with a working
  `systemd --user`; finds actually-missing prerequisites (tmux, curl,
  python3, `ss`, tar, `sha256sum`, `flock`, ca-certificates — derived from
  what the scripts use, not the README's short list) and offers one
  `sudo apt-get update && apt-get install -y ...`; for a genuinely fresh
  install (not yet this account's own), refuses to silently take over an
  unrecognized existing install or another account's serverjack already on
  the target port; offers to install/sign in to Tailscale or skip `tailscale
  serve` entirely for a
  self-managed reverse proxy; if publishing, asks who may reach it
  (`SERVERJACK_ALLOW`) — a detected single tailnet login by default, a typed
  list, or an explicit "yes" before ever leaving it open to the whole
  tailnet; asks whether other Linux accounts share the machine (`--unix`);
  runs the one-time root steps (`loginctl enable-linger`,
  `tailscale set --operator`) inline instead of only printing them, showing
  the exact `sudo` command first and defaulting every such prompt to **no**
  (a bare Enter runs nothing), keeping another account's existing operator
  grant unless you explicitly say to replace it,
  and offering an alternate `--https-port` rather than overwriting an
  existing foreign `tailscale serve` mapping; then runs `install.sh` and
  verifies units, the loopback health check, and — when publishing — the
  tailnet URL itself before printing the private address. No controlling
  terminal for a still-unanswered question, or a refused/failed sudo step,
  stops cleanly with exactly what's left to do — never a silent fallback to
  a broad-access default. Re-running it on an already-installed account
  shows the current state and offers update / change-allow-list /
  change-publish-settings / leave-it-alone, rather than refusing outright.
  The resolved install flags are recorded in `install.json`'s
  `"install_args"` so a later `serverjack-ctl update` replays the same
  choices instead of reverting to `install.sh`'s own defaults.
- `tests/guided-install.sh`, a container test (the same privileged Debian 13
  systemd fixture as `tests/managed-install.sh`, a fake `tailscale` binary
  standing in for the real one) driving `serverjack-setup` through a REAL pty
  (`tests/guided-install-driver.py`, spawning `script -qfc '...' /dev/null`)
  for: missing prerequisites offered and refused, then offered and accepted
  with Tailscale entirely missing and serve skipped; no controlling terminal
  (clean stop, exit 2); root refused; an unsupported OS refused; Tailscale
  logged out then brought to Running by "up" with the login URL surfaced and
  polled, untagged with the allow-list defaulting to the detected login; a
  tagged node requiring an allow-list; an existing foreign `tailscale serve`
  mapping offered an alternate `--https-port`; "other accounts share this
  machine?" selecting `--unix`; and a rerun that changes nothing when told
  to. Optional, host-side, wired into `bash tests/run.sh`.
- `bin/serverjack-ctl`, a lifecycle helper installed to `~/.local/bin/` for
  every install: `status`, `versions`, `update [--version X]` (stages and
  health-checks a new release without touching the running one, auto-rolling
  back on failure), `rollback`, `uninstall [--yes]` (keeps
  `~/.config/serverjack` and tmux sessions), `prune [--yes]`. Works from the
  terminal even if the web UI is unhealthy.
- `install.sh` now bakes the stable `~/.local/share/serverjack/current/...`
  path into the systemd units when run from inside a managed release
  directory, so a later release only needs its `current` symlink swapped and
  the units restarted, never reinstalled. Git-checkout installs are
  unchanged.
- The "Update serverjack" shortcut and `update_available()` now cover managed
  installs too (running `serverjack-ctl update`), alongside the existing git
  `git pull` behavior; `/api/status` gains a `"channel"` field
  (`"release"`/`"git"`/`"unknown"`).
- `.github/workflows/release.yml`: pushing a `vX.Y.Z` tag builds and attaches
  the release archive, bootstrap and `SHA256SUMS` to a **draft** GitHub
  release (publishing stays a manual step — see CONTRIBUTING.md "Releasing").
- `tests/managed-install.sh`, a container test (privileged Debian 13 systemd,
  no git, no GitHub reachable for the release) proving the whole path: a
  piped install, a rerun preserving env/shortcuts, an update with a live tmux
  session surviving, a broken release being auto-rolled-back, a no-`--yes`
  update with no tty refusing cleanly, an explicit rollback, a truncated
  bootstrap and a corrupted archive both executing/installing nothing, an
  uninstall keeping config and tmux, and root being refused. Optional,
  host-side, wired into `bash tests/run.sh`.

### Changed

- Terminal uses the app's color theme by default (`SERVERJACK_TERM_THEME=off`
  to keep ttyd's default). The theme is generated once, in `bin/serverjack`,
  from the same `TOKENS` the rest of the app uses (`_term_theme()`), instead
  of being hand-typed into `bin/serverjack-ttyd`. `bin/serverjack-ttyd` asks
  for it as JSON (`serverjack --print-theme`, a new flag) and passes it to
  ttyd as a real `-t theme=...` server option. This was briefly a
  `?theme=...` URL query instead -- ttyd's client applies that last, so it
  seemed like the more robust mechanism, but only ttyd clients new enough to
  read a URL query at all actually do; older ttyd (still what some distros'
  package archives ship) silently ignores it and falls back to its stock
  look. A `-t theme=...` server option works on every ttyd version this
  project has ever supported. A `-t theme=...` (or
  `--client-option[=]theme=...`) of your own in `TTYD_EXTRA_ARGS` is
  detected automatically (`_ttyd_extra_args_has_theme()`) and
  `--print-theme` prints nothing in that case, so `bin/serverjack-ttyd`
  never prepends a second, conflicting `-t theme=...` ahead of yours.
- CI now installs the exact ttyd version and binary `install.sh` pins for
  real installs (`scripts/fetch-ttyd.sh`, called by both, fetch-and-verify
  factored out of `install.sh` into one shared place) instead of
  `apt-get install ttyd` -- ubuntu-24.04's archive carries 1.7.4, whose
  client is the older one described above; that mismatch is exactly what
  let the URL-query theme bug pass CI clean while working locally.
- Tests no longer inherit `SERVERJACK_TERM_THEME` or `TTYD_EXTRA_ARGS` from
  the maintainer's own shell (both have been found already set there):
  `tests/run.sh` and `tests/security-wrapper.sh` now pin both explicitly so
  an opted-out or customized ambient environment can't make the suite fail
  for a reason unrelated to the change under test.
- README "Why serverjack" opens with what serverjack does (start an agent in
  the right directory, paste the command it asked for, close finished tmux
  sessions) rather than with checking on a running agent, which is what the
  vendors' remote-control features are for.
- fzf 0.74.4 (was 0.74.3): pinned checksums bumped for the linux_amd64,
  linux_arm64 and linux_armv7 assets in `install.sh`.
- The deny page (wrong tailnet user) and the "terminal unavailable" page no
  longer link a manifest and icons a client in either state can't use — both
  are error interstitials, not something to "Add to Home Screen".
- `ICON_REV`, the icon/manifest cache-buster, is now a hash of the Prompt
  Jack artwork and `VERSION` instead of a hand-maintained string, so any
  future artwork change refreshes cached browsers on its own; icon and
  manifest responses also carry an `ETag`.
- `docs/shots/fixture.sh` factors out the isolated-instance setup previously
  duplicated between `docs/shots/make.sh` and `make-gif.sh`, so the README
  stills and the demo GIF are built from identical fixture data (down to the
  Start card's "Runs `claude`" hint, now shown in both).
- `docs/shots/make-social.sh` renders `social-preview.tmpl.html` using the
  real color tokens and Prompt Jack mark loaded from `bin/serverjack` itself,
  instead of a hand-copied stylesheet and SVG path data that could drift from
  what actually ships; `gif_record.py`'s tap-ring color now reads `--accent`
  off the live page instead of a hardcoded hex.
- README "Install" section leads with the managed one-command install
  (`curl -fsSL .../serverjack-bootstrap.sh | bash`); the git checkout is now
  documented as the development path. Works once a release with these assets
  exists (v1.4.0 will be the first).

### Fixed

- A coding CLI installed under a private PATH entry (nvm's versioned bin
  dir, a tool's own `"paths"` glob in `tools.json`) showed as installed and
  its Start card pill appeared, but starting it failed with "command not
  found": Debian's `/etc/profile` resets `PATH` inside the login shell that
  runs the command. `command_args()` now re-exports `TOOL_PATH` as the first
  thing that login shell does, after its own startup files (and their PATH
  reset) have already run — the configured command text itself is left
  exactly as configured, never rewritten to an absolute path, so the echoed
  `$ claude` line and the pane's reported process name still just name the
  tool instead of baking in TOOL_PATH's real location.
- The demo GIF had a flat grey letterbox band across the bottom fifth of
  every frame: the recorded video's pixel size didn't match the emulated
  iPhone's real viewport. `gif_record.py` now derives the recording size
  from the device's own viewport and scale factor instead of a stale
  hardcoded size, and `make-gif.sh` verifies the rendered video isn't
  letterboxed (with a detected-crop fallback) before converting it.
- `docs/shots/make-gif.sh`: a process-wide `export HOME` meant for tmux
  sessions was also stripping Docker's own config from every later `docker`
  call the script made; HOME is now scoped to the tmux session's environment
  instead. A missing session name from the recorder now fails the script
  instead of silently overwriting `demo.gif` with a blank capture.
- The terminal's default (non-blinking, block) cursor drew the character
  under it in the same color as its own cursor cell (`cursorAccent` equalled
  `cursor`), making the glyph invisible while the cursor sat on it and the
  terminal had focus. `cursorAccent` is now the page background token
  instead, matching how the cursor reads everywhere else it appears on top
  of app-colored surfaces.
- `docs/shots` fixture robustness: `make-gif.sh`'s `/tmp`-leak guard read a
  plain `capture-pane`, which (once OpenCode's TUI is up) sees only its
  current alternate screen, never the shell's own scrollback the leak check
  actually needs -- it now passes `-a` to read that instead. Recording and
  the host-side regression check both now wait for OpenCode's real "Ask
  anything" ready text (a generous timeout, `screenReaderMode=true` mirroring
  it into the DOM for `gif_record.py` to wait on; plain `capture-pane` --
  what's *currently* on screen -- for `make-gif.sh`'s own check) instead of a
  fixed 5-second sleep. The fixture's OpenCode is now found reliably even
  when the host also has one on `PATH` (`~/.opencode/bin` is prepended in
  `make.sh`/`make-gif.sh`, and preferred outright over `PATH` when resolving
  which binary to use), it's symlinked in rather than copied (no reason to
  duplicate a ~180 MB binary into a throwaway run), the version probe runs
  against the fixture's own `HOME` under a timeout and fails loudly instead
  of silently, and a missing OpenCode binary is now caught before the
  fixture creates its run directory instead of leaking it on exit.

### Changed (documentation, merged separately as PR #19)

- README proof bullets qualified for accuracy: "no root" now says serverjack
  runs as your own account with no root in daily use, and names the two
  one-time root commands `install.sh` prints when they're needed; "only
  reachable on your Tailscale network" now says reachable only over
  Tailscale by default, with `SERVERJACK_ALLOW` for a shared tailnet; the
  "one stdlib Python file" bullet now notes the installer also fetches a
  prebuilt ttyd binary and fzf.
- README quick start gets a short "Who can reach it" paragraph right after
  the install block, covering the single-user, shared-tailnet and
  shared-machine cases and linking to the security model.
- README "Why this and not X" no longer claims VibeTunnel, Agentboard and
  Codeman all require compiling `node-pty`: VibeTunnel ships prebuilt
  binaries and an npm package, and only Codeman's Linux installer documents
  installing Node.js and a build toolchain.
- FAQ "Why not Claude's own remote control, or Codex's?" no longer says
  remote control only drives an already-running session — Claude's server
  mode can start multiple new sessions in a chosen directory. Reframed
  around what the vendor features cover (starting and driving their own
  agent) versus what serverjack is for (a shell, the `sudo` prompt, existing
  tmux sessions, agents with no remote-control feature of their own, and the
  vendor tools' own install/login/server steps).
- README gets a new "Updating and rolling back" section (written for the
  git-checkout channel; the managed one-command install above supersedes
  it for new installs): `git pull --ff-only && bash install.sh` to update,
  config and tmux sessions surviving a restart, rolling back to a tagged
  version, and how to recover if the web UI is down after an update.
- README's Python requirement changed from "3.9+" to "3.10 or newer
  recommended (3.9 still works but is end-of-life upstream)"; the badge now
  reads 3.10+.
- CONTRIBUTING.md: "small, finished tool" reworded to "intentionally small",
  and a "Useful contributions" list added (mobile input, reconnection,
  installation on more distributions, coexistence with desktop tmux
  clients, following agent CLI command changes).
- README install section gets a "Tested on" list of the platforms actually
  exercised: the maintainer's Debian 13 server with iPhone Safari and a
  Windows browser, an independent user's server with a Mac browser and
  iPhone, a clean Debian 13 container install, and CI on Ubuntu 24.04 with
  Chromium, Firefox and WebKit emulation.

## 1.3.0 - 2026-09-14

### Changed

- Prompt Jack branding: the J-shaped plug and separate terminal chevron now
  appear in page headers, the terminal's All sessions link, and browser and
  home-screen icons. SVG and antialiased PNG icons share the same geometry;
  refreshed icon URLs replace the previously cached artwork.
- README repositioned around "Jack into your server": a demo GIF and a
  five-bullet proof list above the fold, "Why serverjack" reordered to lead
  with the reason the project exists, and a social preview image for link
  previews. No behavior change.
- Added `docs/FAQ.md`, answering the five questions this kind of project
  gets asked first: why not plain ttyd, why not the vendors' own remote
  control, why Tailscale and not a password, whether it phones home, and how
  to run it without Tailscale. Linked from the README's security section and
  its Contents list.

## 1.2.1 - 2026-09-14

### Fixed

- The first card under "Agent servers" had square top corners: the rounding
  rule keyed off the card following the heading directly, and an intro line
  now sits between them. The first card of a run is rounded regardless of
  what precedes it (same for the Sessions list).

## 1.2.0 - 2026-09-14

### Added

- Every way to start a session (the Start a session card, the terminal page's
  "+" popover, `/start`, `/new`/`/api/new`, `/tools/open`, and a run shortcut)
  now takes an optional name. Left blank, the session is named for its type
  and directory instead of a bare kind — a shell in `~/projects/3d-lab`
  becomes `shell-3d-lab`, `sudo apt install ffmpeg` becomes `apt` (or
  `apt-src` run from `~/src`).

### Changed

- Landing page: "Run a command" and "New shell" are replaced by one "Start a
  session" card at the top — Shell (the default) or any installed agent, a
  directory (defaults to `~`), and an optional command for Shell. Picking an
  agent just runs its plain command (`claude`, `codex`, ...) in the chosen
  directory; there's no remote-control/server-mode choice on this card any
  more. The bottom accordion is renamed "Agent servers" and now only lists a
  tool that needs installing, logging in, or has a server/daemon/extra action
  to offer — a tool that's ready with nothing else to configure (just Gemini
  CLI, by default) has no row there any more. Removed the "Open with remote
  control" action from Claude Code's and Copilot's cards (an interactive
  session now starts from the top instead; Claude's Remote Control server is
  unaffected).

## 1.1.0 - 2026-09-13

### Added

- `bin/serverjack --version` and `bin/serverjack --check` (alias `--doctor`), a
  read-only startup diagnosis: Python, tmux and ttyd versions, runtime and
  config directory modes, env-file permissions, Tailscale reachability and
  whether the listen target is free. `install.sh --version` reports the same
  number. The version shows in the page footer and in `/api/status`.
- `docs/ARCHITECTURE.md`: request flow, the security model as implemented, the
  WebSocket proxy, tmux integration, the agent registry and the test strategy.
- `tests/test_unit.py`: 27 unit tests over the pure functions (form limits,
  host validation, allow-list matching, tools.json merge, atomic config
  writes), run before the browser suites.
- A `lint` job in CI: shellcheck, pyflakes and a Python 3.9 compile check.
- `docs/shots/make.sh`: reproducible, neutral README screenshots.

### Changed

- Clone anywhere: the quick start no longer suggests a path, and
  `SERVERJACK_DIRS` defaults to `~/projects:~/src:~/code:~`.
- Fixed the four outstanding shellcheck warnings.

## 1.0.0 - 2026-09-13

First public release.

serverjack is a web front door to a home server, reached over Tailscale from
a phone or a laptop: a landing page that runs a pasted command in a new tmux
session, a session list with one-tap attach, a browser terminal (ttyd behind
serverjack's own proxy) with a phone soft-key row, and cards that launch and
log in to coding-agent CLIs. One Python file, no Node, no sudo.

### Added

- Landing page, session tabs, tmux window picker, phone soft keys, pop-out
  windows, PWA install on iOS, and a CRT effects toggle.
- Agent cards for Claude Code, Codex, OpenCode, GitHub Copilot CLI and Gemini
  CLI, with install and login flows and one-click actions; a JSON registry
  (`tools.json`) for adding or overriding tools.
- Identity from Tailscale headers (`SERVERJACK_ALLOW`), a peer-uid check for
  other local accounts, and a Unix-socket listen mode for shared machines.
- Idempotent `install.sh` and a conservative `uninstall.sh` that only removes
  `tailscale serve` mappings it owns.
- Real-browser test suite (Chromium, Firefox, WebKit with iPhone emulation)
  plus HTTP and wrapper security regressions, run in CI on every push and
  pull request.

### Security

- Request-parsing hardening (body limits, strict `Content-Length`, chunked
  transfer refused), owner-only config files, a restricted
  `TTYD_EXTRA_ARGS` allowlist, and symlink-safe socket handling.

Verified on a clean Debian 13 install. See the
[v1.0.0 release notes](https://github.com/jackgillette006/serverjack/releases/tag/v1.0.0).
