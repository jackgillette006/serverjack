# Changelog

All notable changes to serverjack are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## Unreleased

## 1.6.0-rc.2 - 2026-10-04

rc.2 replaces rc.1, which was built but never published. It adds three
fixes found while verifying rc.1 on GitHub's runners and a real server: the
terminal takes the keyboard only once its connection is open, it never
changes width under a line being typed, and a page closed just as its
terminal starts leaves no tmux client behind.

This release is a full review of the UI on phones and desktops, from the
landing page through the terminal page to what tmux and ttyd are handed.
About 127 glitches and usability problems were found, confirmed and fixed,
most of them with a browser test that drives the real thing. The installer
and the update path are unchanged.

**Upgrading from 1.5.0.** What behaves differently on purpose:

- The landing page leads with **Sessions** whenever anything is running;
  Start a session comes first only when nothing is, or when the page comes
  back with an error to fix in one of its forms.
- In a directory picker a typed folder *name* is a search: Enter (Go) fills
  in the highlighted folder, a second Enter starts. A new folder comes only
  from the **+ New folder** row or a typed path.
- The terminal page asks before a close made with Ctrl held (the browser's
  own Ctrl+W, which bash uses to delete a word); no other way out asks.
- While a page has a session open, tmux's status line is off and a smaller
  window is padded with blanks; both go back to what they were when the last
  page leaves. A session 1.5.0 opened keeps its `status off` (it can't be
  told from one you set): `tmux set-option -u -t <name> status` clears it.
- Agent servers are found by serverjack's marks, not by name. Servers 1.5.0
  started are still recognised; a hand-made look-alike
  (`tmux new -s opencode-serve`) is not.
- 24-bit colour needs tmux 3.2 and the blank padding 3.3; an older tmux keeps
  the old behaviour. ttyd's new options apply once `serverjack-ttyd`
  restarts, which `install.sh`, `serverjack-ctl update` and the Update
  shortcut all do.
- **Reload pages left open from 1.5.0.** Only a 1.6 page reconnects by
  itself: once the update has restarted serverjack, a 1.5.0 terminal page
  shows "Press ⏎ to Reconnect" and keeps running 1.5.0's script until it is
  reloaded. Reload open tabs and pop-outs, and close and reopen the
  home-screen app (until then, tap the terminal and press return to
  reconnect; anything typed before that return is lost).

### Agent servers

#### Changed

- **Servers are found by what they are, not their name** (tmux session
  options set when serverjack starts one). Two project directories with the
  same name get a server each (`claude-remote-3d-lab-2`), a renamed server
  stays on its card, and an interactive session with a server-like name
  (`claude-remote-tools`) is no longer listed as an exited server whose
  Remove would kill it. Server sessions carry a **server** tag in the list.
- **The directory picker is in the row that uses it**, labelled
  **Directory**, and Enter in it can only press that row's button. Every
  ready card used to open with an unlabelled picker, and Enter ran the
  card's first button (on Codex, "Pair with phone").
- **"Start at boot" entries are visible**: a ticked directory with nothing
  running has its own row ("Starts at boot; not running now") to untick or
  Start, and one whose directory is gone says so and is simply forgotten
  when unticked. Before, the box came back unticked with no trace of the
  entry.
- Collapsed rows stay one line on a phone: one pill per server with counts
  ("Remote Control server: 2 running · 1 exited").

#### Fixed

- **Servers started from the page read "exited", and Start killed them.**
  Since 1.5.0 a Remote Control or OpenCode server showed "exited" with no
  Stop, and a second Start, a double tap or a restart with "start at boot"
  ticked replaced the live server, dropping the phone app's sessions. A
  running server now reads running, a second Start says "already running",
  and a second window in its session no longer makes it read "exited".
- The card is right as soon as a login or install finishes, and a slow or
  hung login check no longer holds up the page (the last answer shows, the
  check runs in the background and gives up after 5 s). serverjack starts
  the checks as it comes up, pages loaded together share one check, and
  `/api/status` (answered without an identity) runs none.
- Clearer copy: Stop and Remove name the directory; with no agent installed
  the Start card says so and links to Agent servers; action sessions are
  lower case (`pair-with-phone`). A trailing `;`, as in a pasted
  `find . -exec rm {} \;`, no longer confuses tmux. A NUL byte in a link or
  form field is refused instead of dropping the connection.

### Starting sessions and the directory picker

#### Changed

- **A typed folder name picks a folder; it never makes one.** `game` + Enter
  used to start in a new, empty `~/game` instead of the suggested
  `~/projects/game`. The folder with exactly that name (or else the top
  match) is highlighted as you type and is what Enter, Go and Start take; if
  nothing matches, the only row is **+ New folder `~/name`**. A typed path
  (a `/`, a leading `~`, or `.`) is used as typed.
- **A folder is created only when a session starts in it.** A refused Start
  leaves nothing behind, and Add a shortcut, the default directory and
  "start at boot" refuse a missing folder instead of creating it.
- **Save as a shortcut: naming it is enough** — a name ticks *Keep this
  command in Shortcuts*, and the box decides. No command is refused instead
  of silently starting a shell.
- Shortcut runs are named after the shortcut (`disk-usage`); shortcut rows
  show their directory first and wrap a long command between words, never
  after a hyphen (`ls -` / `la`).
- **Update serverjack asks before it runs** and shows its whole command; one
  stray tap used to restart every open terminal.
- A taken name gets an **Open** button for that session; the Start card's
  hint says why `sudo` prompts work.

#### Added

- **Edit a shortcut**: a pencil on each saved shortcut; *Save changes*
  replaces it in place and *Cancel* leaves the editor.
- A **›** on each folder suggestion shows its subfolders (Tab, for touch).

#### Fixed

- **The suggestion list no longer covers what is below it**: it sits under
  the field and pushes the rest down, everywhere a picker appears. Tapping
  Start or Save used to pick a folder instead; an agent card's buttons no
  longer move while it is open; a slow click still lands. The + sheet's
  list no longer hangs off a phone's screen.
- A swipe scrolls the list instead of picking; Tab out of an untouched field
  just moves on; a late lookup no longer reopens the list; long parent paths
  keep the folder name visible; hover and right-click behave; the fields
  have names a screen reader announces.
- **A refused Start keeps everything you typed**, directory and *Keep* tick
  included (the retry used to start in `~`); so do Add a shortcut, the agent
  cards and the + panel.
- **One tap is one submit**: Start reads *Starting…*, and a second tap on a
  slow link no longer runs the command twice. Back and reload never re-run a
  form, and Back after starting an agent shows a clean card.
- Multi-line commands run line by line (each line used to end in a stray
  carriage return). Changing the default directory keeps a half-filled
  Start card.
- Session names: a leading `$` is refused, renaming to `-x` works, and an
  unnamed session is named after the real command past `sudo -u nobody`.

### Landing page and sessions list

#### Changed

- **Running sessions come first** (see above): no session row used to be on
  the first screen of any phone or laptop.
- **Session rows lead with the short facts** (**attached** in words, the
  window count, the age), then the command and path, which are what a narrow
  row cuts. The age reads `up 6m`, not "6m ago", which read as activity.
- "Open in SSH app" is **SSH app (login only)**: an `ssh://` link can't
  attach a session; *Copy SSH command* does.
- The footer names the way back (the logo in a session's bar), not a back
  button; × is "Back to sessions"; neither leaves the session in the
  history.

#### Fixed

- **Kill, Rename, shortcuts, start at boot, the default directory and the
  Codex daemon land where you were**, with one line saying what happened,
  instead of reloading at the top with every card closed. **Kill and Rename
  happen in place**: a killed row leaves a line in its place for a few
  seconds (the list stays one card, and keyboard focus moves to the next
  row); Rename opens focused and shows a refusal under the field.
- **The session list keeps itself current** (every 15 s while visible, and
  when the page comes back), so a desktop list tab or a resumed home-screen
  app no longer goes stale; so do the agent cards and the load/memory line
  (at most once a minute). Rows that come and go no longer move the Start
  card you are typing in (Safari let it jump a row's height). Open on a session
  that has ended says so in its row's place, `/s/<name>` for a gone session
  goes back to the list with a note, and the session you just left no
  longer reads attached.
- **⋯ menus**: one at a time; Escape or a press outside closes them; they
  open upward near the bottom and fit a 320px phone; Rename no longer zooms
  iOS, and neither Rename nor a refused name flips the menu, blinks it or
  pushes it off the top of the page.
- Long names end in `…`; each row's buttons have their own accessible names
  ("Open main"); "Copy SSH command" no longer sticks; Ctrl/Cmd/Shift-click
  on Open gets the browser's own new tab.
- Dark scrollbars and checkboxes (`color-scheme: dark`); nothing scrolls
  under the iPhone status bar; no more "serverjack serverjack" header.
- 44px touch targets; the selected Start choice and the status dots survive
  Windows Contrast themes (and, like the phone ⋯ menu, iOS before 15.4 and
  Firefox before 121); the placeholder fits small phones; and the landing
  page follows iOS Larger Text.
- The 403 page says no Tailscale identity arrived (`127.0.0.1`, an SSH
  port-forward) instead of "another tailnet user … signed in as nobody".
- With CRT effects on, a slow next page no longer leaves a black screen.
  `/favicon.ico` answers; a client hanging up no longer logs a traceback.

### Terminal page (tabs, + panel, pop-out, reconnect)

#### Changed

- Phones and tablets have no × in the bar (it did what the logo does and
  read like "kill"); the logo plays the CRT power-off.
- Phone or desktop follows the main pointer: a touchscreen laptop keeps the
  desktop layout, a finger swipe still scrolls, and an iPad stays a tablet.
- The pop-out's ⋯ pill is a slim strip across the top, and the bar it shows
  lies over the terminal instead of resizing it; the Escape that puts it
  away goes no further (the next one reaches the program). Short landscape
  windows get a denser bar and key row.

#### Fixed

- **The terminal reconnects by itself** after serverjack or ttyd restarts
  (the Update shortcut included), a phone wakes before its network, or a tab
  is tapped while serverjack is unreachable — no more "Press ⏎ to
  Reconnect" with no Enter key; it says *reconnecting…* meanwhile. The
  "terminal isn't answering" page recovers on its own and has a Retry
  button.
- The terminal gets the keyboard, and *connecting* or *reconnecting…* go
  away, only once its connection is open: the first keys typed after a
  reconnect, a tab switch or on a slow network could go nowhere.
- The terminal takes its final width before it takes the keyboard, and
  never changes width while you are typing: on a phone, a command typed
  right after opening a session could have its output drawn over (the line
  re-wrapped under the shell a few seconds after the load).
- **A session that ends no longer drops you into another one**: a tab goes
  to the list ("… has ended"), a pop-out closes. A tab for a session that
  ended since the strip was read keeps you where you were, and so does a
  late answer from before a switch. A rename made elsewhere is followed by
  the tab, URL, title and the terminal itself, so a later reconnect finds
  it. Back after switching tabs leaves the page instead of moving only the
  terminal.
- **+ panel**: Cancel, Escape, + and a tap in the terminal close it with the
  keyboard back in the terminal; the name is optional for every type; a
  double tap starts one session; the phone sheet is opaque, and the CRT
  toggle has left it for the landing page's footer.
- **Tab strip**: edge fades, wheel scrolling, ellipsised names, the active
  tab kept in view, no snapping back on a poll. The window badge shows the
  count (`· 3 ▾`) and the list is fresh when opened.
- The terminal fills its frame from the start (19 columns were missing at
  1280px), with no light scrollbar on Windows, nor in the + panel's folder
  list and the Copy view.
- **Pop-out windows**: × is reachable and nothing covers the terminal's top
  right; showing the bar no longer eats typing or resizes the session; Open
  brings an open pop-out forward without reloading it; picking its tab
  elsewhere doesn't attach it twice; blocked pop-ups say so.
- iPhone: nothing under the notch in landscape, the prompt above the home
  indicator, the key row flush on the keyboard (checked in emulation only).
  The tabs, frame, window list and + errors are labelled for screen readers.

### Terminal input (soft keys, clipboard, scrolling, keyboard)

#### Changed

- **The phone key row puts the important keys on screen**: Esc through Copy
  fit from 320px, then the arrows and PgUp/PgDn, which repeat while held.
- **Ctrl+W asks before closing the page** (see above).

#### Added

- A screens count in the bar while a session is open on more than one
  screen (tap it to fit the session here); the landing row says "attached on
  2 screens", and `/api/sessions` carries `clients` and tmux's `id`.

#### Fixed

- **Typing after scrolling back ran the wrong command** (`echo hello world`
  ran `world`). Whatever you type, paste or tap now leaves serverjack's copy
  mode first, on any screen: with another screen on the session, a page
  looks at the pane again before the first key after a pause. Esc only leaves the scrollback, so it can't
  interrupt an agent; PgUp/PgDn page through it; your own copy mode is left
  alone.
- Soft keys fire on a tap, never on a swipe across the row (which sent ^C or
  Esc); Paste and Copy work where a touch brings no click; Ctrl then
  punctuation sends `Ctrl+\`, `Ctrl+_` and `Ctrl+]`, and Ctrl then Return,
  Backspace or an arrow from the keyboard takes Ctrl too (it stayed armed
  for the next letter); dictated text after a soft key arrives; an armed
  Ctrl doesn't survive a session switch.
- The Copy view takes focus (Esc closes it instead of reaching the program),
  copies exactly what is shown, and says when the session ended; on a phone
  its × no longer goes on to the keys button under it (hiding the key row
  and raising the keyboard).
- Firefox types again after a click on the bar; toggles no longer pop the
  phone keyboard; the paste hint no longer widens the Paste key.
- Ctrl+wheel zooms instead of typing arrows; the wheel follows a `mouse on`
  change; finger travel matches the lines scrolled.
- Ctrl+C drops the selection it copied, so the next one interrupts;
  Ctrl+Shift+C copies instead of opening the developer tools; a scroll drops
  the selection; copies lose tmux's padding; Firefox's Paste key works.
- With a session on a phone and a desktop, the screen you use takes the size
  back when you click or tap in it, without sending a key (and without
  flashing ttyd's size pill on a phone that has just opened it).

### Terminal and tmux

#### Changed

- **The tmux status line comes back** for SSH: it is off only while a page
  has the session open, and the last page to leave puts back what was there,
  your own `status` included.
- The desktop shows a phone-sized window with blank space around it, not a
  screen of `·` dots. ttyd's `COLSxROWS` pill no longer flashes on every
  resize (`-t disableResizeOverlay=false` brings it back).

#### Fixed

- **Readable colours**: grey hint text is 4.56:1 (was 2.29:1), and ttyd
  holds text at 4.5:1 against its cell (`minimumContrastRatio`, default
  theme only), so `ls -l`'s setuid and sticky entries are legible.
- **24-bit colour**: the browser attaches as an RGB client and sessions get
  `COLORTERM=truecolor`; tmux used to round nvim, bat and agent CLI colours
  to 256.
- Android no longer draws the terminal in a serif typewriter face (ttyd's
  `Courier`, dropped from the font list; not yet seen on a real phone).
- A started command waits (at most 5 s) for the page, so on a phone its
  `$ <command>` line stays in view above a `sudo` prompt.
- A session whose name ends in `;` attaches (tmux read the `;` as a command
  separator: no such session, or another one called `semi` for `semi;`).
- A page closed or switched away just as its terminal was starting no
  longer leaves an unseen tmux client attached to the session for good (it
  counted as another screen).
- Your global `after-new-window` hooks keep firing in a session a page has
  opened; the page used to leave an empty hook list on the session that hid
  them for good.
- Pages and scripts are gzipped for browsers that take it (the list page
  about 30 KB instead of 120), and the terminal page's script is cached
  under its hash instead of fetched on every open.

#### Hardening

- The terminal behind `/term/` now sends the same framing policy as
  serverjack's own pages (`X-Frame-Options: SAMEORIGIN` and
  `Content-Security-Policy: frame-ancestors 'self'`). The terminal page
  frames it from the same origin, so nothing visible changes.

### Docs and tests

- The README, ARCHITECTURE, DESIGN and MANUAL-TESTS describe this UI. The
  README gains the session bar, scrolling, copy and paste, selecting text
  with `mouse on`, the keys the browser keeps and Mac keyboards; Known
  limitations gain emoji widths and tmux's window sizing; and its second
  "Updating and rolling back" is now "Updating a git checkout". New
  screenshots and demo GIF.
- MANUAL-TESTS adds what emulation can't settle: iPhone landscape and
  Larger Text, two screens, an iPad, Windows classic scrollbars.
- New browser suites `pwagents`, `pwdirpick`, `pwflows`, `pwlayout`,
  `pwchrome`, `pwinput` and `pwtmux`, a host-side `tests/attach_restore.py`,
  and 256 unit tests (from 111). `tests/run.sh` starts a fourth instance
  (`tests/restartable.sh`) and still needs only docker and the host's tmux.

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
