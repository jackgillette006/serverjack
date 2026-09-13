"""Open/pop-out behaviour: desktop pops out and stays; phone navigates; in-session
pop-out returns the tab to the list; SSH copy item present."""
import os, time
from playwright.sync_api import sync_playwright
BASE = os.environ.get("SERVERJACK_TEST_BASE", "http://127.0.0.1:7690"); SESS = "pwtest"
fails = 0
def ok(label, cond, extra=""):
    global fails
    if not cond:
        fails += 1
    print(("  PASS " if cond else "  FAIL ") + label + (("  -- " + extra) if extra and not cond else ""))
with sync_playwright() as p:
    print("chromium desktop:")
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1100, "height": 700}, permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page(); page.on("pageerror", lambda e: print("   [pageerror]", e))
    page.goto(f"{BASE}/"); time.sleep(0.5)
    with page.expect_popup() as pi:
        page.click(f"a.open[data-name={SESS}]")
    pop = pi.value; time.sleep(1.5)
    ok("Open pops out a window", f"/s/{SESS}" in pop.url and "popout=1" in pop.url, pop.url)
    ok("home page stays", page.url.rstrip("/") == BASE, page.url)
    ok("popout has no bar", not pop.locator("#bar").is_visible())
    # same session again => refocus, not a second window
    n = len(ctx.pages); page.click(f"a.open[data-name={SESS}]"); time.sleep(0.8)
    ok("opening again reuses the window", len(ctx.pages) == n, str(len(ctx.pages)))
    # ☰ inside the popout closes it
    pop.click("#handle"); time.sleep(0.2); pop.click("#bar a.ib"); time.sleep(0.6)
    ok("☰ in popout closes the window", pop.is_closed())
    # menu: Open here navigates in-tab; SSH items exist
    page.click(f"a.open[data-name={SESS}] ~ details summary, .sess:has(a.open[data-name={SESS}]) details summary"); time.sleep(0.2)
    m = page.locator(f".sess:has(a.open[data-name={SESS}]) .menu-list")
    ok("menu shows SSH copy + app link", m.locator("[data-copy]").count() == 1 and m.locator("a[data-open=ssh]").count() == 1)
    cmd = m.locator("[data-copy]").get_attribute("data-copy")
    ok("ssh command attaches to the session", cmd.startswith("ssh -t ") and f"tmux attach -t {SESS}" in cmd, cmd)
    m.locator("[data-copy]").click(); time.sleep(0.4)
    ok("copy puts it on the clipboard", page.evaluate("navigator.clipboard.readText()") == cmd)
    if not m.is_visible(): page.click(f".sess:has(a.open[data-name={SESS}]) details summary"); time.sleep(0.2)
    m.locator("a[data-open=here]").click(); page.wait_for_selector("#tabs .tab.on"); time.sleep(1)
    ok("Open here navigates in this tab", page.url.endswith(f"/s/{SESS}"), page.url)
    # in-session ↗: pops out, this tab returns to the list
    with page.expect_popup() as pi:
        page.click("#popout")
    pop2 = pi.value; time.sleep(1.0)
    ok("↗ pops out", "popout=1" in pop2.url, pop2.url)
    ok("...and this tab goes back to the list", page.url.rstrip("/") == BASE, page.url)
    b.close()

    print("webkit iphone:")
    b = p.webkit.launch(); page = b.new_context(**p.devices["iPhone 14"]).new_page()
    page.on("pageerror", lambda e: print("   [pageerror]", e))
    page.goto(f"{BASE}/"); time.sleep(0.5)
    ok("Pop out hidden in menu on phone", not page.locator(".sess a[data-open=popout]").first.is_visible())
    page.click(f"a.open[data-name={SESS}]"); page.wait_for_selector("#tabs .tab.on"); time.sleep(1)
    ok("Open navigates in the same tab", page.url.endswith(f"/s/{SESS}"), page.url)
    ok("↗ hidden in the bar on phone", not page.locator("#popout").is_visible())
    b.close()

if fails:
    raise SystemExit(1)
