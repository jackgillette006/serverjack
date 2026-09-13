"""Unit tests for the pure(ish) helpers in bin/serverjack, run with plain
unittest (no pytest, no extra dependency) -- see tests/run.sh, which wires
this in as a host-side step alongside security_http.py.

bin/serverjack has no .py suffix and isn't meant to be imported by anything
else, so setUpModule() loads it with importlib.util instead of a normal
`import`. Loading it still runs every module-level statement (RUNTIME_DIR =
runtime_dir(), the tailscale probes, ...) -- that's unavoidable short of
restructuring the file, so this module points XDG_RUNTIME_DIR and
SERVERJACK_CONFIG at throwaway temp directories *before* the import, so a
test run never reads or writes the real ~/.config/serverjack or the real
runtime directory of a serverjack actually running on this machine.

Tests either call a plain module-level function directly, or -- for methods
on Handler that only touch a handful of attributes (form(), identity_ok())
-- call the unbound method with a small stand-in object instead of a real
HTTP connection.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import stat
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVERJACK_PATH = os.path.join(HERE, "..", "bin", "serverjack")

mod = None          # set by setUpModule
_tmpdirs = []        # cleaned up in tearDownModule


def setUpModule():
    global mod
    runtime = tempfile.mkdtemp(prefix="sj-unit-runtime-")
    config = tempfile.mkdtemp(prefix="sj-unit-config-")
    _tmpdirs.extend([runtime, config])
    os.chmod(runtime, 0o700)

    # A clean, deterministic environment: no leftover SERVERJACK_* from the
    # real shell, and the two paths above standing in for the real ones.
    for key in list(os.environ):
        if key.startswith("SERVERJACK_"):
            del os.environ[key]
    os.environ["XDG_RUNTIME_DIR"] = runtime
    os.environ["SERVERJACK_CONFIG"] = config

    # bin/serverjack has no .py suffix, so spec_from_file_location() can't
    # guess a loader for it -- name one explicitly (it's plain source).
    loader = importlib.machinery.SourceFileLoader("serverjack_under_test", SERVERJACK_PATH)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)


def tearDownModule():
    for d in _tmpdirs:
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------- helpers ---

class FakeHeaders:
    """Just enough of email.message.Message's interface for form()/
    identity_ok(): .get(name) and .get_all(name)."""

    def __init__(self, **kw):
        self._h = kw

    def get(self, name, default=None):
        v = self._h.get(name)
        if isinstance(v, list):
            return v[0] if v else default
        return v if v is not None else default

    def get_all(self, name):
        v = self._h.get(name)
        if v is None:
            return []
        return v if isinstance(v, list) else [v]


class FakeRfile:
    def __init__(self, data=b""):
        self.data = data

    def read(self, n):
        chunk, self.data = self.data[:n], self.data[n:]
        return chunk


class FormHandlerStub:
    """Stands in for a Handler instance across the one method under test
    (form()): the attributes it reads, plus a send_bytes() that records
    what would have gone to the client instead of writing to a socket."""

    def __init__(self, headers=None, body=b""):
        self.headers = FakeHeaders(**(headers or {}))
        self.rfile = FakeRfile(body)
        self.close_connection = False
        self.sent = None

    def send_bytes(self, data, ctype, status=200, cache=True):
        self.sent = (status, data)


class IdentityHandlerStub:
    OPEN_PATHS = ("/healthz", "/api/status")

    def __init__(self, peer, login=None, command="GET"):
        self.peer = peer
        self.headers = FakeHeaders(**({"Tailscale-User-Login": login} if login else {}))
        self.command = command


# ------------------------------------------------------------------ tests --

class ProcAddrTests(unittest.TestCase):
    """_proc_addr() decodes /proc/net/tcp's hex, little-endian fields."""

    def test_ipv4(self):
        # 127.0.0.1:7680 -- the hex address is little-endian per 4-byte word.
        self.assertEqual(mod._proc_addr("0100007F:1E00"), ("127.0.0.1", 7680))

    def test_hostname_of_strips_port_and_keeps_brackets(self):
        self.assertEqual(mod._hostname_of("example.com:8443"), "example.com")
        self.assertEqual(mod._hostname_of("[::1]:7680"), "[::1]")
        self.assertEqual(mod._hostname_of(""), "")


class HostAllowedTests(unittest.TestCase):
    def test_loopback_names_always_allowed(self):
        for h in ("127.0.0.1", "localhost", "[::1]", "localhost:9999"):
            self.assertTrue(mod.host_allowed(h), h)

    def test_unknown_name_rejected(self):
        self.assertFalse(mod.host_allowed("definitely-not-a-real-host.invalid"))
        self.assertFalse(mod.host_allowed(""))   # HTTP/1.1 requires a Host


class SafeDirTests(unittest.TestCase):
    def test_fixes_loose_mode(self):
        d = tempfile.mkdtemp()
        try:
            os.chmod(d, 0o755)
            self.assertEqual(mod.safe_dir(d, "test dir"), d)
            self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_rejects_symlink(self):
        d = tempfile.mkdtemp()
        link = d + "-link"
        try:
            os.symlink(d, link)
            with self.assertRaises(SystemExit):
                mod.safe_dir(link, "test dir")
        finally:
            os.unlink(link)
            shutil.rmtree(d, ignore_errors=True)

    def test_rejects_non_directory(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            with self.assertRaises(SystemExit):
                mod.safe_dir(path, "test dir")
        finally:
            os.unlink(path)


class FormParsingTests(unittest.TestCase):
    """Handler.form(), called unbound against a stand-in object -- see
    security_http.py for the same limits proven end-to-end over a real
    socket against a running instance."""

    def test_rejects_chunked_transfer_encoding(self):
        stub = FormHandlerStub(headers={"Transfer-Encoding": "chunked"})
        self.assertIsNone(mod.Handler.form(stub))
        self.assertTrue(stub.close_connection)
        self.assertEqual(stub.sent[0], 400)

    def test_content_length_limits(self):
        cases = [
            ("invalid", 400),   # not a decimal string
            ("-1", 400),        # not a decimal string (leading '-')
            ("65537", 413),     # a real number, but over the 64K cap
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                stub = FormHandlerStub(headers={"Content-Length": value})
                self.assertIsNone(mod.Handler.form(stub))
                self.assertTrue(stub.close_connection)
                self.assertEqual(stub.sent[0], expected)

    def test_duplicate_content_length_rejected(self):
        stub = FormHandlerStub(headers={"Content-Length": ["4", "4"]})
        self.assertIsNone(mod.Handler.form(stub))
        self.assertEqual(stub.sent[0], 400)

    def test_valid_body_is_parsed(self):
        body = b"cmd=echo+hi&dir=%2Ftmp"
        stub = FormHandlerStub(headers={"Content-Length": str(len(body))}, body=body)
        result = mod.Handler.form(stub)
        self.assertEqual(result, {"cmd": "echo hi", "dir": "/tmp"})
        self.assertFalse(stub.close_connection)


class IdentityAllowListTests(unittest.TestCase):
    """Handler.identity_ok() against the module-global ALLOW list --
    monkeypatched per test and restored afterward."""

    def setUp(self):
        self._orig_allow = mod.ALLOW

    def tearDown(self):
        mod.ALLOW = self._orig_allow

    def test_no_allow_list_means_everyone_in(self):
        mod.ALLOW = []
        ok, login = mod.Handler.identity_ok(IdentityHandlerStub(peer=0), "/")
        self.assertTrue(ok)

    def test_matching_login_admitted(self):
        mod.ALLOW = ["alice@example.com"]
        stub = IdentityHandlerStub(peer=0, login="alice@example.com")   # peer 0 = root, trusted
        ok, login = mod.Handler.identity_ok(stub, "/")
        self.assertTrue(ok)
        self.assertEqual(login, "alice@example.com")

    def test_wrong_login_refused(self):
        mod.ALLOW = ["alice@example.com"]
        stub = IdentityHandlerStub(peer=0, login="mallory@example.com")
        ok, _login = mod.Handler.identity_ok(stub, "/")
        self.assertFalse(ok)

    def test_untrusted_peer_header_ignored(self):
        # peer 12345 is not in TRUST_IDENTITY_UIDS, so even a matching
        # header must not be believed -- it could have set it itself.
        mod.ALLOW = ["alice@example.com"]
        stub = IdentityHandlerStub(peer=12345, login="alice@example.com")
        ok, login = mod.Handler.identity_ok(stub, "/")
        self.assertFalse(ok)
        self.assertEqual(login, "")

    def test_open_paths_exempt_on_get_only(self):
        mod.ALLOW = ["alice@example.com"]
        stub_get = IdentityHandlerStub(peer=0, login=None, command="GET")
        ok, _ = mod.Handler.identity_ok(stub_get, "/healthz")
        self.assertTrue(ok)
        stub_post = IdentityHandlerStub(peer=0, login=None, command="POST")
        ok, _ = mod.Handler.identity_ok(stub_post, "/healthz")
        self.assertFalse(ok)


class ToolsJsonMergeTests(unittest.TestCase):
    """load_tools(): tools.json entries merge field-by-field over a
    matching built-in id; unknown ids are appended; "hidden" filters."""

    def setUp(self):
        self._orig_tools_file = mod.TOOLS_FILE
        self._orig_tools_env = os.environ.pop("SERVERJACK_TOOLS", None)
        fd, self.tools_file = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        mod.TOOLS_FILE = self.tools_file

    def tearDown(self):
        mod.TOOLS_FILE = self._orig_tools_file
        if self._orig_tools_env is not None:
            os.environ["SERVERJACK_TOOLS"] = self._orig_tools_env
        os.unlink(self.tools_file)

    def _load(self, entries):
        with open(self.tools_file, "w") as f:
            json.dump(entries, f)
        return mod.load_tools()

    def test_merge_overrides_one_field_and_keeps_the_rest(self):
        tools, error = self._load([{"id": "claude", "label": "Claude (renamed)"}])
        self.assertIsNone(error)
        by_id = {t["id"]: t for t in tools}
        self.assertEqual(by_id["claude"]["label"], "Claude (renamed)")
        self.assertEqual(by_id["claude"]["bin"], "claude")   # untouched by the override

    def test_hidden_entry_is_filtered_out(self):
        tools, _ = self._load([{"id": "gemini", "hidden": True}])
        self.assertNotIn("gemini", {t["id"] for t in tools})

    def test_unknown_id_is_appended_with_defaults(self):
        tools, _ = self._load([{"id": "brand-new-tool"}])
        by_id = {t["id"]: t for t in tools}
        self.assertIn("brand-new-tool", by_id)
        self.assertEqual(by_id["brand-new-tool"]["label"], "brand-new-tool")
        self.assertEqual(by_id["brand-new-tool"]["bin"], "brand-new-tool")

    def test_malformed_file_reports_error_without_raising(self):
        with open(self.tools_file, "w") as f:
            f.write('{"not": "a list"}')
        tools, error = mod.load_tools()
        self.assertIsNotNone(error)
        self.assertTrue(tools)   # falls back to the built-ins

    def test_remote_control_actions_were_removed(self):
        # The "open with remote control" choice moved out of the built-ins
        # entirely -- Claude and Copilot's actions no longer include it (the
        # accordion has no way to start an interactive session any more).
        tools, _ = self._load([])
        by_id = {t["id"]: t for t in tools}
        for tid in ("claude", "copilot"):
            labels = [a.get("label") for a in by_id[tid].get("actions") or []]
            self.assertNotIn("Open with remote control", labels, tid)


class DirOptionsTests(unittest.TestCase):
    """dir_options(): ~ is always first and pre-selected, regardless of
    where dir_choices() would otherwise place it."""

    def test_home_is_first_and_selected(self):
        first_line = mod.dir_options().split("\n", 1)[0]
        self.assertIn(f'value="{mod.esc(mod.HOME)}"', first_line)
        self.assertIn(" selected", first_line)


class ShortcutsAtomicityTests(unittest.TestCase):
    """save_private_json(), through save_shortcuts()/load_shortcuts(): the
    file lands at 0600 and no temp file is left behind."""

    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        self._orig_config_dir = mod.CONFIG_DIR
        self._orig_shortcuts_file = mod.SHORTCUTS_FILE
        mod.CONFIG_DIR = self.cfg
        mod.SHORTCUTS_FILE = os.path.join(self.cfg, "shortcuts.json")

    def tearDown(self):
        mod.CONFIG_DIR = self._orig_config_dir
        mod.SHORTCUTS_FILE = self._orig_shortcuts_file
        shutil.rmtree(self.cfg, ignore_errors=True)

    def test_round_trip_and_permissions(self):
        mod.add_shortcut("Label", "echo hi", "/tmp")
        items = mod.load_shortcuts()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["cmd"], "echo hi")
        self.assertEqual(items[0]["label"], "Label")

        mode = stat.S_IMODE(os.stat(mod.SHORTCUTS_FILE).st_mode)
        self.assertEqual(mode, 0o600)

        leftovers = [f for f in os.listdir(self.cfg) if f != "shortcuts.json"]
        self.assertEqual(leftovers, [], "save_private_json left a temp file behind")

    def test_deleting_all_shortcuts_leaves_an_empty_list(self):
        mod.add_shortcut("Label", "echo hi", "/tmp")
        mod.save_shortcuts([])
        self.assertEqual(mod.load_shortcuts(), [])


class ValidateNameTests(unittest.TestCase):
    """validate_name()'s own rules (tmux's ':'/'.' restriction, the 60-char
    cap, "required"); the not-a-duplicate check calls session_exists(),
    which needs a real tmux binary -- present wherever tests/run.sh runs
    this (it apt-get installs tmux for the browser-test job too)."""

    def test_rejects_tmux_reserved_characters(self):
        _name, err = mod.validate_name("bad:name")
        self.assertIsNotNone(err)
        _name, err = mod.validate_name("bad.name")
        self.assertIsNotNone(err)

    def test_rejects_too_long(self):
        _name, err = mod.validate_name("x" * 61)
        self.assertIsNotNone(err)

    def test_blank_required_is_an_error(self):
        name, err = mod.validate_name("", required=True)
        self.assertIsNone(name)
        self.assertIsNotNone(err)

    def test_blank_not_required_auto_names(self):
        name, err = mod.validate_name("", required=False, base="shell")
        self.assertIsNone(err)
        self.assertTrue(name.startswith("shell"))

    def test_plain_name_accepted(self):
        name, err = mod.validate_name("a-plain-name")
        self.assertIsNone(err)
        self.assertEqual(name, "a-plain-name")


if __name__ == "__main__":
    unittest.main(verbosity=2)
