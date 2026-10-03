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
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from unittest import mock

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
    # Set, not deleted: _ttyd_extra_args_env() falls back to reading
    # ~/.config/serverjack/env directly when TTYD_EXTRA_ARGS isn't in
    # os.environ at all -- an ambient value here (this exact shell has had
    # one) would make TTYD_EXTRA_ARGS_HAS_THEME nondeterministic at import
    # time, and deleting it outright would make this import read the real
    # ~/.config/serverjack/env instead. An explicit empty string avoids both.
    os.environ["TTYD_EXTRA_ARGS"] = ""

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

class IconPngTests(unittest.TestCase):
    def test_png_decodes_to_the_plug_and_separate_prompt(self):
        for size in (64, 180):
            with self.subTest(size=size):
                png = mod.icon_png(size)
                self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
                offset, compressed = 8, bytearray()
                while offset < len(png):
                    length = struct.unpack(">I", png[offset:offset+4])[0]
                    kind = png[offset+4:offset+8]
                    data = png[offset+8:offset+8+length]
                    crc = struct.unpack(">I", png[offset+8+length:offset+12+length])[0]
                    self.assertEqual(crc, zlib.crc32(kind + data) & 0xffffffff)
                    if kind == b"IHDR":
                        self.assertEqual(struct.unpack(">IIBBBBB", data), (size, size, 8, 2, 0, 0, 0))
                    elif kind == b"IDAT":
                        compressed.extend(data)
                    offset += length + 12
                raw = zlib.decompress(compressed)
                stride = 1 + size*3
                self.assertEqual(len(raw), size*stride)
                self.assertTrue(all(raw[y*stride] == 0 for y in range(size)))

                def pixel(x, y):
                    start = int(y*size/64)*stride + 1 + int(x*size/64)*3
                    return tuple(raw[start:start+3])

                # Two prongs, connector, stem, hook, and the detached chevron.
                for point in ((40, 9), (47, 9), (36, 17), (43, 30), (14, 44), (27, 53), (28, 30)):
                    self.assertEqual(pixel(*point), (57, 255, 136))
                # The prong gap, open bowl, and space beside the prompt stay clear.
                for point in ((43, 10), (25, 42), (35, 30), (5, 5)):
                    self.assertEqual(pixel(*point), (8, 15, 14))
                pixels = {tuple(raw[y*stride+x:y*stride+x+3])
                          for y in range(size) for x in range(1, stride, 3)}
                self.assertGreater(len(pixels), 2, "edges should be antialiased")


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


class DirSearchTests(unittest.TestCase):
    """GET /api/dirs?q= (dir_search() and the mode functions it dispatches
    to): the directory-picker combobox's only data source. A temp tree
    stands in for DIR_ROOTS/HOME so nothing here depends on this machine's
    real filesystem."""

    def setUp(self):
        self.old_home, self.old_roots = mod.HOME, mod.DIR_ROOTS
        self.old_depth = mod.DIR_DEPTH
        self.old_prefs_file = mod.PREFS_FILE
        self.fake_home = tempfile.mkdtemp(prefix="sj-unit-dirsearch-home-")
        _tmpdirs.append(self.fake_home)
        self.root = os.path.join(self.fake_home, "work")
        # Ranking fixture: an exact, a prefix, and a substring match for "alpha".
        os.makedirs(os.path.join(self.root, "alpha"))
        os.makedirs(os.path.join(self.root, "alphabet"))
        os.makedirs(os.path.join(self.root, "my-alpha-thing"))
        # Nested match at depth 3 (root=0, projects=1, ai=2, 3d-lab=3).
        os.makedirs(os.path.join(self.root, "projects", "ai", "3d-lab"))
        # Hidden and pruned -- never indexed, even the pruned dir's own children.
        os.makedirs(os.path.join(self.root, ".hidden"))
        os.makedirs(os.path.join(self.root, "node_modules", "should-not-appear"))
        # A second root, for the empty-q "HOME first, then roots+children" order.
        self.root2 = os.path.join(self.fake_home, "extra")
        os.makedirs(os.path.join(self.root2, "child-b"))
        os.makedirs(os.path.join(self.root2, "child-a"))
        # A directory directly under HOME, for path-mode "~/pro" completion.
        os.makedirs(os.path.join(self.fake_home, "projects"))
        mod.HOME = self.fake_home
        mod.DIR_ROOTS = [self.root, self.root2]
        # No prefs.json yet -- points at a file that doesn't exist, so
        # default_dir() falls back to HOME. That would make _index_roots()
        # add fake_home (an ancestor of both self.root and self.root2, so
        # "not already under one" of DIR_ROOTS) as an extra index root,
        # double-indexing everything under it at different depths and
        # breaking depth-sensitive assertions elsewhere in this class --
        # so pin the default to self.root instead, already a DIR_ROOTS
        # entry, leaving every existing fixture/assertion untouched. Tests
        # that care about the default dir itself set their own prefs.json.
        self.prefs_file = os.path.join(self.fake_home, "prefs.json")
        mod.PREFS_FILE = self.prefs_file
        with open(self.prefs_file, "w") as f:
            json.dump({"default_dir": self.root}, f)
        mod._DIR_INDEX_CACHE = None

    def tearDown(self):
        mod.HOME, mod.DIR_ROOTS, mod.DIR_DEPTH = self.old_home, self.old_roots, self.old_depth
        mod.PREFS_FILE = self.old_prefs_file
        mod._DIR_INDEX_CACHE = None

    def names(self, q):
        paths, _truncated = mod._dir_search_name(q)
        return [os.path.basename(p) for p in paths]

    def test_ranking_is_exact_then_prefix_then_substring(self):
        self.assertEqual(self.names("alpha"), ["alpha", "alphabet", "my-alpha-thing"])

    def test_least_nested_wins_even_over_a_better_rank(self):
        # A depth-2 prefix match ("gamma-extra") must sort ahead of a
        # depth-3 exact match ("gamma") -- nesting depth is the primary key,
        # exact-vs-prefix only breaks ties within the very same depth.
        os.makedirs(os.path.join(self.root, "x", "gamma-extra"))   # depth 2, prefix
        os.makedirs(os.path.join(self.root, "y", "z", "gamma"))    # depth 3, exact
        mod._DIR_INDEX_CACHE = None
        self.assertEqual(self.names("gamma"), ["gamma-extra", "gamma"])

    def test_path_only_matches_come_after_every_name_match(self):
        # "host-thing" is a rank-1 (prefix) name match at depth 1; its child
        # "leaf" matches only via the relative path ("host-thing/leaf" ->
        # rank 3), and must sort after every name match -- including one
        # much deeper, like "a/b/c/host" -- not just after shallower ones.
        os.makedirs(os.path.join(self.root, "host-thing", "leaf"))
        os.makedirs(os.path.join(self.root, "a", "b", "c", "host"))
        mod._DIR_INDEX_CACHE = None
        self.assertEqual(self.names("host"), ["host-thing", "host", "leaf"])

    def test_nested_match_at_depth_3(self):
        status, obj = mod.dir_search("3d-lab")
        self.assertEqual(status, 200)
        paths = [d["path"] for d in obj["dirs"]]
        self.assertIn(os.path.join(self.root, "projects", "ai", "3d-lab"), paths)

    def test_path_mode_completes_children_of_tilde_relative(self):
        paths, _truncated = mod._dir_search_path("~/pro")
        self.assertEqual(paths, [os.path.join(self.fake_home, "projects")])

    def test_path_mode_completes_children_of_an_absolute_dir(self):
        paths, _truncated = mod._dir_search_path(os.path.join(self.root, "al"))
        self.assertEqual([os.path.basename(p) for p in paths], ["alpha", "alphabet"])

    def test_hidden_and_pruned_dirs_never_appear(self):
        entries, _truncated = mod.dir_index()
        paths = [p for p, _depth, _root in entries]
        self.assertFalse(any(os.sep + ".hidden" in p for p in paths))
        self.assertFalse(any("node_modules" in p for p in paths))
        self.assertFalse(any("should-not-appear" in p for p in paths))
        # And a name search for the hidden/pruned dirs' own names finds nothing.
        self.assertEqual(self.names("hidden"), [])
        self.assertEqual(self.names("should-not-appear"), [])

    def test_depth_cap_is_respected(self):
        deep = self.root
        for i in range(1, 8):
            deep = os.path.join(deep, f"deep{i}")
            os.makedirs(deep)
        mod.DIR_DEPTH = 3
        mod._DIR_INDEX_CACHE = None
        entries, _truncated = mod.dir_index()
        depths = {os.path.basename(p): d for p, d, _root in entries}
        self.assertIn("deep3", depths)
        self.assertEqual(depths["deep3"], 3)
        self.assertNotIn("deep4", depths)

    def test_a_path_indexed_by_two_overlapping_roots_is_not_duplicated(self):
        # A root nested under another root (SERVERJACK_DIRS="~/projects/x:~",
        # the demo fixture's own shape) walks "alpha" twice -- once as its
        # own root, once again as a descendant of self.root. It must still
        # appear only once in the results (alphabet and my-alpha-thing are
        # unrelated paths and legitimately still both match too).
        mod.DIR_ROOTS = [self.root, os.path.join(self.root, "alpha")]
        mod._DIR_INDEX_CACHE = None
        results = self.names("alpha")
        self.assertEqual(results.count("alpha"), 1, results)
        self.assertEqual(sorted(results), sorted(set(results)), results)

    def test_empty_q_starts_with_the_default_dir_then_home_then_roots(self):
        # setUp pins the default dir to self.root, so it -- and its own
        # first-level children -- must lead the list, ahead of even HOME.
        status, obj = mod.dir_search("")
        self.assertEqual(status, 200)
        paths = [d["path"] for d in obj["dirs"]]
        self.assertEqual(paths[0], self.root)
        self.assertIn(os.path.join(self.root, "alpha"), paths[1:6])
        # ...then HOME...
        self.assertIn(self.fake_home, paths)
        self.assertLess(paths.index(self.fake_home), paths.index(self.root2))
        # ...then dir_choices()'s own order for whatever isn't already
        # listed: self.root2, then its (alphabetically sorted) first-level
        # children (self.root and its own children were already listed
        # above and must not repeat here).
        i = paths.index(self.root2)
        self.assertEqual(paths[i:i + 3],
                         [self.root2,
                          os.path.join(self.root2, "child-a"),
                          os.path.join(self.root2, "child-b")])
        self.assertEqual(paths.count(self.root), 1)

    def test_empty_q_default_dir_outside_every_root_still_leads(self):
        # The default dir doesn't have to be one of DIR_ROOTS at all -- a
        # standalone directory works too, and still leads the list (with
        # HOME and the configured roots following, unrepeated).
        outside = os.path.join(self.fake_home, "outside-default")
        os.makedirs(os.path.join(outside, "only-child"))
        with open(self.prefs_file, "w") as f:
            json.dump({"default_dir": outside}, f)
        status, obj = mod.dir_search("")
        paths = [d["path"] for d in obj["dirs"]]
        self.assertEqual(paths[0], outside)
        self.assertEqual(paths[1], os.path.join(outside, "only-child"))
        self.assertIn(self.fake_home, paths[2:])
        self.assertIn(self.root, paths[2:])

    def test_default_dir_outside_every_root_is_added_to_the_search_index(self):
        # Not just _dir_search_empty()'s own list -- dir_index() (backing
        # name search) must reach into it too, so typing a name finds
        # something under a default dir picked from outside SERVERJACK_DIRS.
        outside = os.path.join(self.fake_home, "outside-default")
        os.makedirs(os.path.join(outside, "marker-child"))
        with open(self.prefs_file, "w") as f:
            json.dump({"default_dir": outside}, f)
        mod._DIR_INDEX_CACHE = None
        entries, _truncated = mod.dir_index()
        paths = [p for p, _d, _r in entries]
        self.assertIn(outside, paths)
        self.assertIn(os.path.join(outside, "marker-child"), paths)

    def test_default_dir_that_is_an_ancestor_of_a_root_is_not_re_added(self):
        # fake_home is the parent of both self.root and self.root2 -- if it
        # were the default, adding it as a THIRD index root would re-walk
        # self.root's own content a second time under a different root tag,
        # at different (index-relative) depths, corrupting depth-sensitive
        # results elsewhere. _index_roots() must recognize it's already
        # reachable (in the other direction) and leave DIR_ROOTS alone.
        with open(self.prefs_file, "w") as f:
            json.dump({"default_dir": self.fake_home}, f)
        self.assertEqual(mod._index_roots(), mod.DIR_ROOTS)

    def test_query_over_512_chars_is_rejected(self):
        status, obj = mod.dir_search("x" * 513)
        self.assertEqual(status, 400)
        self.assertIn("error", obj)

    def test_index_is_cached_for_the_ttl(self):
        mod.dir_index()   # build and cache
        os.makedirs(os.path.join(self.root, "late-arrival"))
        with mock.patch("time.time", return_value=time.time()):
            entries, _truncated = mod.dir_index()
            self.assertFalse(any(p.endswith("late-arrival") for p, _d, _r in entries),
                             "a cache hit should not see a directory created after it was built")
        with mock.patch("time.time", return_value=time.time() + mod.DIR_INDEX_TTL + 1):
            entries, _truncated = mod.dir_index()
            self.assertTrue(any(p.endswith("late-arrival") for p, _d, _r in entries),
                            "past the TTL, the index should rebuild and see the new directory")

    # ------------------------------------- "create": the + New folder row
    def test_a_name_with_no_folder_offers_the_one_a_submit_would_create(self):
        # setUp pins the default dir to self.root: a bare name resolves there.
        status, obj = mod.dir_search("brand-new")
        self.assertEqual(status, 200)
        self.assertEqual(obj["create"]["path"], os.path.join(self.root, "brand-new"))
        self.assertEqual(obj["create"]["show"], "~/work/brand-new")
        self.assertFalse(os.path.exists(os.path.join(self.root, "brand-new")),
                         "offering it must not create it")

    def test_a_typed_path_offers_its_own_new_folder(self):
        # ~ is the module's HOME (patched by setUp), not the real $HOME.
        with mock.patch.dict(os.environ, {"HOME": "/nonexistent-home"}):
            _status, obj = mod.dir_search("~/projects/fresh/deeper")
        self.assertEqual(obj["create"]["path"],
                         os.path.join(self.fake_home, "projects", "fresh", "deeper"))

    def test_no_create_offer_for_an_existing_folder_a_file_or_an_empty_query(self):
        self.assertNotIn("create", mod.dir_search("alpha")[1])        # self.root/alpha exists
        # ~ is the module's HOME, where projects/ exists -- whatever the real
        # $HOME holds (it used to follow that, so this passed or failed by machine).
        with mock.patch.dict(os.environ, {"HOME": "/nonexistent-home"}):
            self.assertNotIn("create", mod.dir_search("~/projects")[1])
        self.assertNotIn("create", mod.dir_search("")[1])
        with open(os.path.join(self.root, "a-file"), "w"):
            pass
        self.assertNotIn("create", mod.dir_search("a-file")[1])

    def test_a_relative_path_completes_against_the_default_dir(self):
        # The same base resolve_dir() submits it against -- not HOME.
        os.makedirs(os.path.join(self.root, "projects", "ai", "notes"))
        paths, _truncated = mod._dir_search_path("projects/ai/")
        self.assertEqual([os.path.basename(p) for p in paths], ["3d-lab", "notes"])


class TermThemeTests(unittest.TestCase):
    """_term_theme()/TERM_THEME/ttyd_src(): the terminal color theme is
    generated from TOKENS (single source of truth -- see docs/design/
    DESIGN.md's "Terminal theme" section), and the cursorAccent/cursor bug
    (glyph drawn in the same color as its own cursor cell, invisible) stays
    fixed."""

    def test_cursor_accent_is_the_background_not_the_cursor_color(self):
        # The bug this replaced: cursorAccent == cursor made the character
        # under a non-blinking block cursor invisible (same color as its own
        # fill). Regression guard at the value level; tests/pwtest.py proves
        # it in a real rendered terminal.
        self.assertNotEqual(mod.TERM_THEME["cursorAccent"], mod.TERM_THEME["cursor"])
        self.assertEqual(mod.TERM_THEME["cursorAccent"], mod._token("bg-primary"))

    def test_theme_colors_come_from_the_named_tokens(self):
        t = mod.TERM_THEME
        self.assertEqual(t["background"], mod._token("bg-primary"))
        self.assertEqual(t["foreground"], mod._token("text-primary"))
        self.assertEqual(t["cursor"], mod._token("accent"))
        self.assertEqual(t["green"], mod._token("accent"))
        self.assertEqual(t["black"], mod._token("surface-alt"))
        self.assertEqual(t["white"], mod._token("text-secondary"))
        self.assertEqual(t["brightWhite"], mod._token("text-primary"))
        self.assertEqual(t["red"], mod._token("danger"))
        self.assertEqual(t["yellow"], mod._token("warning"))
        self.assertEqual(t["blue"], mod._token("info"))
        self.assertEqual(t["magenta"], mod._token("agent-purple"))

    def test_selection_background_is_translucent_accent(self):
        r, g, b = mod._hex_rgb(mod._token("accent"))
        self.assertEqual(mod.TERM_THEME["selectionBackground"], f"rgba({r},{g},{b},0.3)")

    def test_missing_token_raises(self):
        with self.assertRaises(SystemExit):
            mod._token("not-a-real-token")

    def test_ttyd_src_never_carries_a_theme(self):
        # The theme is a -t theme=... server option now (bin/serverjack-ttyd
        # asks for it via `serverjack --print-theme`), not a ?theme=... URL
        # query: an earlier version delivered it that way, but ttyd clients
        # too old to read a URL query at all (still what some distros' apt
        # packages ship) silently ignore it -- exactly the gap that let this
        # pass locally against a newer ttyd while failing CI's pinned one.
        # ttyd_src() must never reintroduce it, regardless of TERM_THEME_JSON.
        self.assertEqual(mod.ttyd_src("mysession"), mod.TERM_PATH + "?arg=mysession")
        old = mod.TERM_THEME_JSON
        try:
            mod.TERM_THEME_JSON = '{"background":"#123456"}'
            self.assertEqual(mod.ttyd_src("mysession"), mod.TERM_PATH + "?arg=mysession")
        finally:
            mod.TERM_THEME_JSON = old


class TtydExtraArgsThemeTests(unittest.TestCase):
    """_ttyd_extra_args_has_theme()/_ttyd_extra_args_env(): a user's own ttyd
    -t/--client-option theme=... in TTYD_EXTRA_ARGS must be detected so
    bin/serverjack skips appending its own &theme=... on top of it (ttyd
    applies the URL query last, so ours would otherwise silently win)."""

    def test_detects_dash_t_form(self):
        self.assertTrue(mod._ttyd_extra_args_has_theme('-t theme={"background":"#123456"}'))

    def test_detects_long_form_with_space(self):
        self.assertTrue(mod._ttyd_extra_args_has_theme('--client-option theme={"a":1}'))

    def test_detects_long_form_with_equals(self):
        self.assertTrue(mod._ttyd_extra_args_has_theme('--client-option=theme={"a":1}'))

    def test_detects_theme_option_alongside_others(self):
        self.assertTrue(mod._ttyd_extra_args_has_theme(
            '-t screenReaderMode=true -t theme={"background":"#123456"} -m 4'))

    def test_no_theme_option_present(self):
        self.assertFalse(mod._ttyd_extra_args_has_theme('-t screenReaderMode=true -m 4'))

    def test_empty_string(self):
        self.assertFalse(mod._ttyd_extra_args_has_theme(""))

    def test_none(self):
        self.assertFalse(mod._ttyd_extra_args_has_theme(None))

    def test_dash_t_with_no_value_does_not_crash(self):
        self.assertFalse(mod._ttyd_extra_args_has_theme('-t'))

    def test_unrelated_client_option_not_mistaken_for_theme(self):
        # "thememaker=1" starts with "theme" but not "theme=" -- must not match.
        self.assertFalse(mod._ttyd_extra_args_has_theme('-t thememaker=1'))

    def test_malformed_quoting_is_treated_as_no_theme_found(self):
        # bin/serverjack-ttyd itself refuses to start on this; here, the
        # safe fallback is "no theme option found" -- still generate the
        # usual default theme rather than silently going dark.
        self.assertFalse(mod._ttyd_extra_args_has_theme("'unterminated"))

    def test_env_reads_os_environ_when_present(self):
        old = os.environ.get("TTYD_EXTRA_ARGS")
        try:
            os.environ["TTYD_EXTRA_ARGS"] = '-t theme={"x":1}'
            self.assertEqual(mod._ttyd_extra_args_env(), '-t theme={"x":1}')
        finally:
            if old is None:
                del os.environ["TTYD_EXTRA_ARGS"]
            else:
                os.environ["TTYD_EXTRA_ARGS"] = old

    def test_env_falls_back_to_config_file_when_var_is_unset(self):
        # A plain, non-systemd invocation wouldn't have TTYD_EXTRA_ARGS in
        # its environment at all (unlike the serverjack-ttyd unit, which
        # reads the same EnvironmentFile) -- del, not set to "", so the
        # fallback path in _ttyd_extra_args_env() actually triggers.
        old_home, old_ttyd_args = mod.HOME, os.environ.pop("TTYD_EXTRA_ARGS", None)
        fake_home = tempfile.mkdtemp(prefix="sj-unit-home-")
        _tmpdirs.append(fake_home)
        try:
            cfg_dir = os.path.join(fake_home, ".config", "serverjack")
            os.makedirs(cfg_dir)
            with open(os.path.join(cfg_dir, "env"), "w") as f:
                # install.sh's cfg() convention: last matching line wins, one
                # leading/trailing '"' each stripped independently.
                f.write('SOMETHING_ELSE=1\n')
                f.write('TTYD_EXTRA_ARGS="-t theme={\\"old\\":1}"\n')
                f.write('TTYD_EXTRA_ARGS=-t theme={"background":"#123456"}\n')
            mod.HOME = fake_home
            got = mod._ttyd_extra_args_env()
        finally:
            mod.HOME = old_home
            if old_ttyd_args is not None:
                os.environ["TTYD_EXTRA_ARGS"] = old_ttyd_args
        self.assertEqual(got, '-t theme={"background":"#123456"}')
        self.assertTrue(mod._ttyd_extra_args_has_theme(got))

    def test_env_fallback_missing_file_is_empty(self):
        old_home, old_ttyd_args = mod.HOME, os.environ.pop("TTYD_EXTRA_ARGS", None)
        fake_home = tempfile.mkdtemp(prefix="sj-unit-home-")
        _tmpdirs.append(fake_home)
        try:
            mod.HOME = fake_home   # no .config/serverjack/env under here
            got = mod._ttyd_extra_args_env()
        finally:
            mod.HOME = old_home
            if old_ttyd_args is not None:
                os.environ["TTYD_EXTRA_ARGS"] = old_ttyd_args
        self.assertEqual(got, "")


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


class DefaultDirTests(unittest.TestCase):
    """load_prefs()/save_prefs()/default_dir()/validate_default_dir(), and
    resolve_dir()'s use of default_dir() as its fallback -- the /prefs
    "change the default directory" feature."""

    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        self._orig_config_dir = mod.CONFIG_DIR
        self._orig_prefs_file = mod.PREFS_FILE
        self._orig_home = mod.HOME
        self._orig_env = os.environ.pop("SERVERJACK_DEFAULT_DIR", None)
        # resolve_dir()/validate_default_dir() expand "~" with the plain
        # os.path.expanduser(), which reads the real process environment's
        # HOME, not mod.HOME -- so the "~" tests below need the real
        # os.environ["HOME"] patched too, not just the module attribute.
        self._orig_env_home = os.environ.get("HOME")
        mod.CONFIG_DIR = self.cfg
        mod.PREFS_FILE = os.path.join(self.cfg, "prefs.json")
        self.fake_home = tempfile.mkdtemp(prefix="sj-unit-defaultdir-home-")
        mod.HOME = self.fake_home
        os.environ["HOME"] = self.fake_home
        _tmpdirs.extend([self.cfg, self.fake_home])

    def tearDown(self):
        mod.CONFIG_DIR = self._orig_config_dir
        mod.PREFS_FILE = self._orig_prefs_file
        mod.HOME = self._orig_home
        if self._orig_env_home is not None:
            os.environ["HOME"] = self._orig_env_home
        else:
            os.environ.pop("HOME", None)
        if self._orig_env is not None:
            os.environ["SERVERJACK_DEFAULT_DIR"] = self._orig_env
        else:
            os.environ.pop("SERVERJACK_DEFAULT_DIR", None)

    def mkdir(self, *parts):
        p = os.path.join(self.fake_home, *parts)
        os.makedirs(p, exist_ok=True)
        return p

    # ---------------------------------------------------------- load_prefs
    def test_missing_prefs_file_is_not_an_error(self):
        self.assertEqual(mod.load_prefs(), {})

    def test_malformed_prefs_file_falls_back_without_raising(self):
        with open(mod.PREFS_FILE, "w") as f:
            f.write("{not json")
        self.assertEqual(mod.load_prefs(), {})

    def test_prefs_file_that_is_not_an_object_is_ignored(self):
        with open(mod.PREFS_FILE, "w") as f:
            json.dump(["a", "list", "not", "a", "dict"], f)
        self.assertEqual(mod.load_prefs(), {})

    # --------------------------------------------------------- default_dir
    def test_default_dir_is_home_when_nothing_is_set(self):
        self.assertEqual(mod.default_dir(), self.fake_home)

    def test_default_dir_reads_prefs_json(self):
        d = self.mkdir("projects")
        mod.save_prefs({"default_dir": d})
        self.assertEqual(mod.default_dir(), os.path.realpath(d))

    def test_env_var_is_the_fallback_when_prefs_has_no_default(self):
        d = self.mkdir("from-env")
        os.environ["SERVERJACK_DEFAULT_DIR"] = d
        self.assertEqual(mod.default_dir(), os.path.realpath(d))

    def test_prefs_default_wins_over_the_env_var(self):
        from_prefs, from_env = self.mkdir("from-prefs"), self.mkdir("from-env")
        os.environ["SERVERJACK_DEFAULT_DIR"] = from_env
        mod.save_prefs({"default_dir": from_prefs})
        self.assertEqual(mod.default_dir(), os.path.realpath(from_prefs))

    def test_stale_prefs_entry_falls_back_to_home(self):
        # The saved directory was removed after being set as the default --
        # default_dir() must fall back quietly, not surface the dangling path.
        gone = os.path.join(self.fake_home, "removed-later")
        mod.save_prefs({"default_dir": gone})
        self.assertEqual(mod.default_dir(), self.fake_home)

    # ------------------------------------------------------ save_prefs I/O
    def test_save_prefs_round_trips_and_is_mode_600(self):
        d = self.mkdir("projects")
        mod.save_prefs({"default_dir": d})
        self.assertEqual(mod.load_prefs(), {"default_dir": d})
        mode = stat.S_IMODE(os.stat(mod.PREFS_FILE).st_mode)
        self.assertEqual(mode, 0o600)

    # ------------------------------------------------ validate_default_dir
    def test_validate_rejects_a_directory_that_does_not_exist(self):
        target = os.path.join(self.fake_home, "not-there")
        d, err = mod.validate_default_dir(target)
        self.assertIsNone(d)
        self.assertIn("Not a directory", err)
        self.assertFalse(os.path.exists(target), "validate_default_dir must never create one")

    def test_validate_rejects_an_empty_value(self):
        d, err = mod.validate_default_dir("  ")
        self.assertIsNone(d)
        self.assertTrue(err)

    def test_validate_accepts_an_existing_directory_and_returns_its_realpath(self):
        target = self.mkdir("projects")
        d, err = mod.validate_default_dir(target)
        self.assertIsNone(err)
        self.assertEqual(d, os.path.realpath(target))

    def test_validate_expands_tilde_against_home(self):
        self.mkdir("projects")
        d, err = mod.validate_default_dir("~/projects")
        self.assertIsNone(err)
        self.assertEqual(d, os.path.realpath(os.path.join(self.fake_home, "projects")))

    def test_validate_resolves_a_relative_path_against_the_current_default(self):
        base = self.mkdir("projects")
        self.mkdir("projects", "sub")
        mod.save_prefs({"default_dir": base})
        d, err = mod.validate_default_dir("sub")
        self.assertIsNone(err)
        self.assertEqual(d, os.path.realpath(os.path.join(base, "sub")))

    # ------------------------------------------- resolve_dir() uses it too
    def test_resolve_dir_empty_falls_back_to_the_default_not_home(self):
        target = self.mkdir("projects")
        mod.save_prefs({"default_dir": target})
        d, err = mod.resolve_dir("", None)
        self.assertIsNone(err)
        self.assertEqual(d, os.path.realpath(target))
        self.assertNotEqual(d, self.fake_home)

    def test_resolve_dir_relative_path_resolves_against_the_default(self):
        target = self.mkdir("projects")
        mod.save_prefs({"default_dir": target})
        d, err = mod.resolve_dir("newproj", None)
        self.assertIsNone(err)
        self.assertEqual(d, os.path.realpath(os.path.join(target, "newproj")))
        # Resolving never creates it: that waits for a session to really
        # start there (ensure_dir(), from create_session()).
        self.assertFalse(os.path.exists(d))
        self.assertIsNone(mod.ensure_dir(d))
        self.assertTrue(os.path.isdir(d))

    # ------------------------------------- creating a typed new folder
    def test_resolve_dir_must_exist_refuses_a_missing_folder_in_tilde_form(self):
        d, err = mod.resolve_dir("~/projects/gmae", must_exist=True)
        self.assertIsNone(d)
        self.assertEqual(err, "Not a directory: ~/projects/gmae")
        self.assertFalse(os.path.exists(os.path.join(self.fake_home, "projects")))

    def test_resolve_dir_names_an_existing_file_in_tilde_form(self):
        with open(os.path.join(self.fake_home, "notes.txt"), "w"):
            pass
        d, err = mod.resolve_dir("~/notes.txt")
        self.assertIsNone(d)
        self.assertEqual(err, "Not a directory: ~/notes.txt")

    def test_resolve_dir_with_a_nul_byte_is_an_error_not_an_exception(self):
        d, err = mod.resolve_dir("bad\x00name")
        self.assertIsNone(d)
        self.assertTrue(err)

    def test_validate_default_dir_names_the_path_in_tilde_form(self):
        _d, err = mod.validate_default_dir("~/nope")
        self.assertEqual(err, "Not a directory: ~/nope")

    def test_ensure_dir_reports_a_failure_in_tilde_form(self):
        with open(os.path.join(self.fake_home, "afile"), "w"):
            pass
        err = mod.ensure_dir(os.path.join(self.fake_home, "afile", "sub"))
        self.assertTrue(err.startswith("Couldn't create ~/afile/sub:"), err)

    def _fake_tmux(self, calls):
        def tmux(*args, **_kw):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")
        return tmux

    def test_create_session_creates_a_new_folder_right_before_tmux(self):
        calls, where = [], os.path.join(self.fake_home, "brand", "new")
        def tmux(*args, **_kw):
            calls.append(os.path.isdir(where))      # does it exist when tmux runs?
            return subprocess.CompletedProcess(args, 0, "", "")
        with mock.patch.object(mod, "tmux", tmux), \
                mock.patch.object(mod, "tool_kinds", return_value={"shell": (None, "Shell")}):
            self.assertIsNone(mod.create_session("shell", "s", where))
        self.assertEqual(calls, [True])

    def test_create_session_with_an_unknown_kind_creates_nothing(self):
        calls, where = [], os.path.join(self.fake_home, "never")
        with mock.patch.object(mod, "tmux", self._fake_tmux(calls)), \
                mock.patch.object(mod, "tool_kinds", return_value={"shell": (None, "Shell")}):
            self.assertEqual(mod.create_session("nope", "s", where), "Unknown session type.")
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(where))

    def test_create_session_that_cannot_make_the_folder_never_runs_tmux(self):
        with open(os.path.join(self.fake_home, "afile"), "w"):
            pass
        calls = []
        with mock.patch.object(mod, "tmux", self._fake_tmux(calls)), \
                mock.patch.object(mod, "tool_kinds", return_value={"shell": (None, "Shell")}):
            err = mod.create_session("shell", "s", os.path.join(self.fake_home, "afile", "x"))
        self.assertTrue(err.startswith("Couldn't create ~/afile/x"), err)
        self.assertEqual(calls, [])

    def test_create_command_session_creates_its_folder_too(self):
        calls, where = [], os.path.join(self.fake_home, "srv")
        with mock.patch.object(mod, "tmux", self._fake_tmux(calls)):
            self.assertIsNone(mod.create_command_session("s", where, "true"))
        self.assertTrue(os.path.isdir(where))
        self.assertEqual(len(calls), 1)


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

    def test_rejects_a_leading_dollar(self):
        # tmux reads "=$x" as session id $x: such a session could be created
        # and then never opened, killed or renamed. It must be refused before
        # session_exists() is asked at all (it misreads the name the same way).
        asked = []
        with mock.patch.object(mod, "session_exists", lambda n: asked.append(n) or False):
            name, err = mod.validate_name("$x")
            self.assertIsNone(name)
            self.assertIn("$", err)
            name, err = mod.validate_name("  $3  ")
            self.assertIsNone(name)
        self.assertEqual(asked, [])

    def test_dollar_elsewhere_is_fine(self):
        with mock.patch.object(mod, "session_exists", lambda n: False):
            self.assertEqual(mod.validate_name("a$b"), ("a$b", None))

    def test_duplicate_message_is_context_free(self):
        # "Open it instead." made no sense for a rename; the landing page adds
        # an Open button of its own next to it.
        with mock.patch.object(mod, "session_exists", lambda n: n == "main"):
            name, err = mod.validate_name("main")
        self.assertIsNone(name)
        self.assertEqual(err, mod.taken_msg("main"))
        self.assertIn("already exists", err)
        self.assertNotIn("instead", err)


class CommandArgsTests(unittest.TestCase):
    """command_args(): a tool only reachable via TOOL_PATH (nvm's bin dir, a
    tool's private "paths" entry) must still start, because Debian's
    /etc/profile resets PATH inside the `bash -lc` login shell that runs the
    command. Fixed by re-exporting TOOL_PATH as the first thing inside that
    login shell, after its own startup files (and their PATH reset) have
    already run. The configured command text itself is never rewritten --
    not even to an absolute path -- since the echoed "$ <cmd>" line and the
    pane's reported process name are user-facing (and, for the demo GIF,
    public): a resolved path would bake in TOOL_PATH's real location (a
    throwaway fixture directory, someone's home directory) instead of just
    naming the tool."""

    def setUp(self):
        self._orig_tool_path = mod.TOOL_PATH
        mod.TOOL_PATH = "/tmp/sj-unit-example-toolpath"

    def tearDown(self):
        mod.TOOL_PATH = self._orig_tool_path

    def _env(self, args):
        """The "-e SERVERJACK_CMD=..." value out of a command_args() list."""
        return args[args.index("-e") + 1].split("=", 1)[1]

    def test_command_text_is_never_rewritten(self):
        args = mod.command_args("claude --remote-control")
        self.assertEqual(self._env(args), "claude --remote-control")

    def test_command_text_is_preserved_even_when_the_tool_exists(self):
        # Same assertion, spelled out: there is no shutil.which() check left
        # in command_args() itself that could special-case a resolvable bin.
        args = mod.command_args("bash")
        self.assertEqual(self._env(args), "bash")

    def test_window_name_is_the_commands_first_word(self):
        args = mod.command_args("claude --remote-control")
        self.assertEqual(args[args.index("-n") + 1], "claude")

    def test_multi_word_commands_pass_through_verbatim(self):
        args = mod.command_args("codex remote-control pair")
        self.assertEqual(self._env(args), "codex remote-control pair")

    def test_login_shell_exports_tool_path_before_running_the_command(self):
        script = mod.command_args("claude")[-1]
        self.assertIn("export PATH=", script)
        self.assertIn(mod.TOOL_PATH, script)
        self.assertIn('eval "$SERVERJACK_CMD"', script)
        # The export has to land first inside the login shell -- it must run
        # after bash -lc's own startup files (and their PATH reset), and
        # before the command is looked up -- or it fixes nothing.
        self.assertLess(script.index("export PATH="), script.index('eval "$SERVERJACK_CMD"'))


class DefaultSessionNameTests(unittest.TestCase):
    """default_session_name(): the "<type>-<directory>" default, from the
    spec's own examples -- HOME handling, skipping sudo/env/nohup/nice/time
    to find the real command, sanitizing, and the auto_name() uniqueness
    suffix (session_exists monkeypatched so no real tmux server is needed)."""

    def setUp(self):
        self._orig_home = mod.HOME
        self._orig_exists = mod.session_exists
        self._existing = set()
        mod.HOME = "/home/x"
        mod.session_exists = lambda name: name in self._existing

    def tearDown(self):
        mod.HOME = self._orig_home
        mod.session_exists = self._orig_exists

    def test_shell_in_home_has_no_directory_part(self):
        self.assertEqual(mod.default_session_name("shell", "/home/x"), "shell")

    def test_shell_in_a_subdirectory_adds_it(self):
        self.assertEqual(
            mod.default_session_name("shell", "/home/x/projects/3d-lab"), "shell-3d-lab")

    def test_agent_kind_uses_the_tool_id(self):
        self.assertEqual(
            mod.default_session_name("claude", "/home/x/projects/game"), "claude-game")

    def test_sudo_is_skipped_for_the_command_word(self):
        self.assertEqual(
            mod.default_session_name("shell", "/home/x", "sudo apt install ffmpeg"), "apt")

    def test_sudo_skipped_with_a_directory_too(self):
        self.assertEqual(
            mod.default_session_name("shell", "/home/x/src", "sudo apt install ffmpeg"), "apt-src")

    def test_only_wrapper_words_fall_back_to_shell(self):
        self.assertEqual(mod.default_session_name("shell", "/home/x", "sudo env nohup"), "shell")

    def test_no_command_falls_back_to_shell(self):
        self.assertEqual(mod.default_session_name("shell", "/home/x"), "shell")

    def test_directory_basename_is_sanitized(self):
        self.assertEqual(
            mod.default_session_name("shell", "/home/x/My Dir!"), "shell-my-dir")

    def test_uniqueness_suffix_via_session_exists(self):
        self._existing.add("apt-src")
        self.assertEqual(
            mod.default_session_name("shell", "/home/x/src", "sudo apt install ffmpeg"), "apt-src-2")

    def test_a_wrappers_options_and_their_values_are_skipped(self):
        name = mod.default_session_name
        self.assertEqual(name("shell", "/home/x", "sudo -u nobody true; echo after"), "true")
        self.assertEqual(name("shell", "/home/x", "sudo -E apt update"), "apt")
        self.assertEqual(name("shell", "/home/x", "nice -n 10 make"), "make")
        self.assertEqual(name("shell", "/home/x", "sudo -u postgres psql"), "psql")
        self.assertEqual(name("shell", "/home/x", "sudo -- ls"), "ls")

    def test_variable_assignments_are_skipped(self):
        name = mod.default_session_name
        self.assertEqual(name("shell", "/home/x", "env FOO=1 printenv FOO"), "printenv")
        self.assertEqual(name("shell", "/home/x", "FOO=1 make"), "make")
        self.assertEqual(name("shell", "/home/x", "sudo env A=1 B=2 nohup ./run.sh"), "run-sh")

    def test_an_unbalanced_quote_never_raises(self):
        self.assertEqual(mod.default_session_name("shell", "/home/x", "echo 'oops"), "echo")


class InstallChannelTests(unittest.TestCase):
    """_install_channel() backs update_available()/UPDATE_CMD and the
    "channel" field in /api/status -- see bin/serverjack-ctl and
    bootstrap/serverjack-bootstrap.sh.in for the install.json writers this
    reads. Each test points mod.HOME/mod.REPO at fresh throwaway
    directories (never the real ones setUpModule already redirected
    XDG_RUNTIME_DIR/SERVERJACK_CONFIG to) so it never reads this machine's
    actual install, whatever channel it happens to be on.

    The channel is decided by WHERE mod.REPO physically is first (under
    HOME/.local/share/serverjack/releases/ -> release), never by
    install.json alone -- see the precedence note on _install_channel()
    itself. install.json (or, failing that, a RELEASE file next to REPO) is
    consulted only for the version to report once "release" is already
    established that way."""

    def setUp(self):
        self._orig_home = mod.HOME
        self._orig_repo = mod.REPO

    def tearDown(self):
        mod.HOME = self._orig_home
        mod.REPO = self._orig_repo

    def _fresh_dirs(self):
        home = tempfile.mkdtemp(prefix="sj-unit-home-")
        repo = tempfile.mkdtemp(prefix="sj-unit-repo-")
        _tmpdirs.extend([home, repo])
        return home, repo

    def _release_dir(self, home, version):
        """A repo path that is physically under home's releases/ tree, the
        way a real managed install's bin/serverjack is."""
        releases = os.path.join(home, ".local", "share", "serverjack", "releases")
        repo = os.path.join(releases, version)
        os.makedirs(repo)
        return repo

    def _channel_for(self, home, repo):
        mod.HOME, mod.REPO = home, repo
        return mod._install_channel()

    def test_release_channel_when_repo_is_under_releases(self):
        home = tempfile.mkdtemp(prefix="sj-unit-home-")
        _tmpdirs.append(home)
        repo = self._release_dir(home, "1.4.0")
        share = os.path.join(home, ".local", "share", "serverjack")
        with open(os.path.join(share, "install.json"), "w", encoding="utf-8") as fh:
            json.dump({"channel": "release", "version": "1.4.0", "installed_at": "x",
                       "previous": None}, fh)
        self.assertEqual(self._channel_for(home, repo), ("release", "1.4.0"))

    def test_git_channel_when_no_install_json(self):
        home, repo = self._fresh_dirs()
        os.makedirs(os.path.join(repo, ".git"))
        self.assertEqual(self._channel_for(home, repo), ("git", None))

    def test_unknown_channel_when_neither(self):
        home, repo = self._fresh_dirs()
        self.assertEqual(self._channel_for(home, repo), ("unknown", None))

    def test_repo_location_wins_over_a_stale_install_json(self):
        # The bug this precedence fixes: an account that ALSO has an
        # unrelated managed install sitting in ~/.local/share/serverjack
        # must not have its plain git checkout misclassified as "release"
        # just because install.json happens to exist there. REPO is a git
        # checkout, nowhere near HOME's releases/ tree.
        home = tempfile.mkdtemp(prefix="sj-unit-home-")
        repo = tempfile.mkdtemp(prefix="sj-unit-repo-")
        _tmpdirs.extend([home, repo])
        share = os.path.join(home, ".local", "share", "serverjack")
        os.makedirs(share)
        with open(os.path.join(share, "install.json"), "w", encoding="utf-8") as fh:
            json.dump({"channel": "release", "version": "2.0.0"}, fh)
        os.makedirs(os.path.join(repo, ".git"))
        self.assertEqual(self._channel_for(home, repo), ("git", None))

    def test_release_channel_falls_back_to_release_file(self):
        # No install.json at all (e.g. a tarball extracted into releases/ by
        # hand) -- REPO's own RELEASE file is the fallback for the version.
        home = tempfile.mkdtemp(prefix="sj-unit-home-")
        _tmpdirs.append(home)
        repo = self._release_dir(home, "3.1.0")
        with open(os.path.join(repo, "RELEASE"), "w", encoding="utf-8") as fh:
            fh.write("version=3.1.0\ngit_sha=deadbeef\nbuild_date=x\n")
        self.assertEqual(self._channel_for(home, repo), ("release", "3.1.0"))

    def test_malformed_install_json_falls_back_to_release_file(self):
        home = tempfile.mkdtemp(prefix="sj-unit-home-")
        _tmpdirs.append(home)
        repo = self._release_dir(home, "1.5.0")
        share = os.path.join(home, ".local", "share", "serverjack")
        with open(os.path.join(share, "install.json"), "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        with open(os.path.join(repo, "RELEASE"), "w", encoding="utf-8") as fh:
            fh.write("version=1.5.0\n")
        self.assertEqual(self._channel_for(home, repo), ("release", "1.5.0"))

    def test_install_json_with_other_channel_falls_back_to_release_file(self):
        # Only "release" is a channel value this file recognizes; anything
        # else (a future channel value, a hand-edited file) must not be
        # trusted for the version -- but REPO's physical location still
        # makes this "release", falling back to the RELEASE file.
        home = tempfile.mkdtemp(prefix="sj-unit-home-")
        _tmpdirs.append(home)
        repo = self._release_dir(home, "1.6.0")
        share = os.path.join(home, ".local", "share", "serverjack")
        with open(os.path.join(share, "install.json"), "w", encoding="utf-8") as fh:
            json.dump({"channel": "something-else"}, fh)
        with open(os.path.join(repo, "RELEASE"), "w", encoding="utf-8") as fh:
            fh.write("version=1.6.0\n")
        self.assertEqual(self._channel_for(home, repo), ("release", "1.6.0"))

    def test_valid_json_non_object_install_json_falls_back_to_release_file(self):
        # install.json that parses as JSON but isn't an object (a bare
        # number, string, list, ...) used to crash the whole import: doc.get()
        # doesn't exist on those types, raising AttributeError, which wasn't
        # one of the exceptions this caught. A corrupted install.json must
        # degrade to "treat it as absent", not take down the process at
        # startup -- REPO's physical location still makes this "release",
        # falling back to the RELEASE file exactly like a missing file would.
        for bad_doc in (42, "just a string", [1, 2, 3], True, None):
            with self.subTest(bad_doc=bad_doc):
                home = tempfile.mkdtemp(prefix="sj-unit-home-")
                _tmpdirs.append(home)
                repo = self._release_dir(home, "1.7.0")
                share = os.path.join(home, ".local", "share", "serverjack")
                with open(os.path.join(share, "install.json"), "w", encoding="utf-8") as fh:
                    json.dump(bad_doc, fh)
                with open(os.path.join(repo, "RELEASE"), "w", encoding="utf-8") as fh:
                    fh.write("version=1.7.0\n")
                self.assertEqual(self._channel_for(home, repo), ("release", "1.7.0"))


class UpdateAvailableTests(unittest.TestCase):
    """A15: CHANNEL == "release" only means this process physically lives
    under ~/.local/share/serverjack/releases/ -- not that
    ~/.local/bin/serverjack-ctl (what UPDATE_CMD actually runs) exists. A
    tarball extracted by hand into releases/<v>/, never run through the
    bootstrap or install.sh, is exactly that case: the "Update serverjack"
    row used to show anyway and launch a command that doesn't exist."""

    def setUp(self):
        self._orig_channel = mod.CHANNEL
        self._orig_ctl_path = mod.SERVERJACK_CTL_PATH

    def tearDown(self):
        mod.CHANNEL = self._orig_channel
        mod.SERVERJACK_CTL_PATH = self._orig_ctl_path

    def test_release_channel_with_serverjack_ctl_present(self):
        d = tempfile.mkdtemp(prefix="sj-unit-ctl-")
        _tmpdirs.append(d)
        ctl = os.path.join(d, "serverjack-ctl")
        with open(ctl, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n")
        os.chmod(ctl, 0o755)
        mod.CHANNEL, mod.SERVERJACK_CTL_PATH = "release", ctl
        self.assertTrue(mod.update_available())

    def test_release_channel_with_serverjack_ctl_missing(self):
        d = tempfile.mkdtemp(prefix="sj-unit-ctl-")
        _tmpdirs.append(d)
        mod.CHANNEL = "release"
        mod.SERVERJACK_CTL_PATH = os.path.join(d, "does-not-exist")
        self.assertFalse(mod.update_available())

    def test_git_channel_is_always_available(self):
        mod.CHANNEL = "git"
        mod.SERVERJACK_CTL_PATH = "/nonexistent/serverjack-ctl"
        self.assertTrue(mod.update_available())

    def test_unknown_channel_is_never_available(self):
        mod.CHANNEL = "unknown"
        self.assertFalse(mod.update_available())


class ServerjackCtlUsageTests(unittest.TestCase):
    """bin/serverjack-ctl's usage() used to print its header comment via a
    hardcoded `sed -n '2,34p'` -- one line short of where the header
    actually ends (found by exactly that: the last sentence of --help's
    output was silently missing), and every future edit to the header
    risked drifting the same way again with nothing to catch it. Fixed to
    derive the range from the header's own end (the first non-"#" line)
    instead of a number that has to be kept in sync by hand."""

    CTL = os.path.join(os.path.dirname(HERE), "bin", "serverjack-ctl")

    def _help_output(self):
        result = subprocess.run(
            ["bash", self.CTL, "--help"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_help_includes_the_last_line_of_the_header_comment(self):
        out = self._help_output()
        self.assertIn("~/.local/share/serverjack/.lock.", out)

    def test_help_stops_before_the_first_line_of_real_code(self):
        out = self._help_output()
        self.assertNotIn("set -Eeuo pipefail", out)
        self.assertNotIn("XDG_RUNTIME_DIR", out)


class ServerjackSetupUsageTests(unittest.TestCase):
    """A13: bin/serverjack-setup's usage() had the same hardcoded-range bug
    as bin/serverjack-ctl's (ServerjackCtlUsageTests above, fixed first) --
    a fixed `sed -n '2,52p'` silently truncates the printed header by
    however many lines it grows past 52, with nothing to catch it. Fixed to
    the same awk-derived-from-the-header's-own-end approach."""

    SETUP = os.path.join(os.path.dirname(HERE), "bin", "serverjack-setup")

    def _help_output(self):
        result = subprocess.run(
            ["bash", self.SETUP, "--help"],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_help_includes_the_last_line_of_the_header_comment(self):
        out = self._help_output()
        self.assertIn("-h/--help prints this.", out)

    def test_help_stops_before_the_first_line_of_real_code(self):
        out = self._help_output()
        self.assertNotIn("set -Eeuo pipefail", out)
        self.assertNotIn("XDG_RUNTIME_DIR", out)


class GuidedInstallDriverTests(unittest.TestCase):
    """tests/guided-install-driver.py's own core loop, driven against a tiny
    real child process (not the container) -- fast, and exercises the exact
    bug that mattered: the child printing its LAST expected text and exiting
    in the same breath. The driver's while loop broke out to "one last
    drain" once pump() saw the child had exited, but used to never re-check
    buf for a match AFTER that drain -- so text delivered only in that final
    read was still sitting in buf, yet the exchange was reported as a
    timeout anyway. Found by exactly that happening against the real
    container (a spurious TIMEOUT on the very last expected line)."""

    DRIVER = os.path.join(HERE, "guided-install-driver.py")

    def _run_driver(self, exchanges, child_argv, timeout=5):
        exfile = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        _tmpdirs.append(exfile.name)
        json.dump(exchanges, exfile)
        exfile.close()
        return subprocess.run(
            [sys.executable, self.DRIVER, str(timeout), exfile.name, "--", *child_argv],
            capture_output=True, text=True, timeout=timeout + 10)

    def test_text_delivered_in_the_same_read_as_exit_is_not_a_timeout(self):
        # A plain "print then exit" child is caught by pump()'s own select()
        # almost every time (data becomes readable the instant it's
        # written, well before poll() is even consulted), so it can't
        # reliably force the race. What actually hit this in the real
        # container was `script`/`docker exec` layering: the tracked
        # process is gone but a descendant still holds the pty's write end
        # a beat longer, so output keeps arriving AFTER poll() already
        # shows the child dead. os.fork() reproduces exactly that
        # deterministically: the immediate child (the one Popen tracks)
        # exits right away, so proc.poll() goes non-None almost instantly,
        # while a forked-off grandchild -- which inherits the same stdout
        # pipe, keeping it open -- sleeps just past pump()'s own 0.2s
        # select() window and only then prints and exits. The text is
        # therefore guaranteed to land in the SECOND pump() call (the "one
        # last drain" after poll() already said the child was gone), never
        # the first -- the exact case the old code dropped on the floor.
        child = [sys.executable, "-c", (
            "import os, time\n"
            "if os.fork() == 0:\n"
            "    time.sleep(0.3)\n"
            "    print('READY', flush=True)\n"
            "    os._exit(0)\n"
            "os._exit(0)\n"
        )]
        result = self._run_driver([["READY", None]], child)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("TIMEOUT", result.stderr)
        self.assertIn("EXIT 0", result.stderr)

    def test_genuine_timeout_still_reported_as_one(self):
        # The fix must not make a REAL timeout (text that never arrives)
        # silently pass -- a child that prints nothing for the expected
        # text at all.
        child = [sys.executable, "-c", "pass"]
        result = self._run_driver([["NEVER_PRINTED", None]], child, timeout=2)
        self.assertEqual(result.returncode, 1)
        self.assertIn("TIMEOUT", result.stderr)

    def test_ordinary_multi_exchange_dialogue_still_works(self):
        # Not just the edge case: a normal send/expect exchange (the driver's
        # everyday job) must still behave -- one prompt, one reply, one final
        # confirmation with nothing to send.
        child = [sys.executable, "-c",
                 "name = input('Name? '); print('Hello, ' + name, flush=True)"]
        result = self._run_driver(
            [["Name? ", "World"], ["Hello, World", None]], child)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("EXIT 0", result.stderr)



# ------------------------------------------------------- agent servers ---

def _wait(fn, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    return fn()


@unittest.skipUnless(shutil.which("tmux"), "needs tmux")
class ServerSessionTests(unittest.TestCase):
    """Real tmux, on a private socket (TMUX unset, TMUX_TMPDIR in a temp
    dir) so nothing here can reach a tmux server anybody is using.

    The bug these pin down: command_args() ran the command inside an inner
    `bash -lc` without job control, so tmux named the pane "bash" for as long
    as the command ran. The card read every server started from the page as
    "exited", and Start / autostart then killed the live server and started
    a new one (dropping the phone app's sessions). Servers were also found by
    session name alone."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sj-unit-tmux-")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.tmp, "tmux"), mode=0o700)
        for d in ("a/app", "b/app", "remote-tools"):
            os.makedirs(os.path.join(self.home, d))
        self.env = mock.patch.dict(os.environ, {"TMUX_TMPDIR": os.path.join(self.tmp, "tmux"),
                                                "HOME": self.home})
        self.env.start()
        os.environ.pop("TMUX", None)
        self._home = mod.HOME
        mod.HOME = self.home
        self.per_dir = {"id": "pd", "label": "PD",
                        "server": {"label": "PD server", "cmd": "sleep 300",
                                   "session": "pd-remote", "per_dir": True}}
        self.single = {"id": "solo", "label": "Solo",
                       "server": {"label": "Solo server", "cmd": "sleep 300",
                                  "session": "solo-serve"}}

    def tearDown(self):
        mod.tmux("kill-server")
        mod.HOME = self._home
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def d(self, rel):
        return os.path.realpath(os.path.join(self.home, rel))

    def pane(self, name, fmt):
        return mod.tmux("display-message", "-p", "-t", f"={name}:", fmt).stdout.strip()

    def test_running_command_is_what_the_pane_reports(self):
        self.assertIsNone(mod.create_command_session("t1", self.home, "sleep 300"))
        self.assertEqual(_wait(lambda: self.pane("t1", "#{pane_current_command}") == "sleep"
                               and "sleep"), "sleep")
        self.assertFalse(mod.session_idle("t1"))

    def test_compound_command_is_reported_too(self):
        mod.create_command_session("t2", self.home, "echo hi; sleep 300")
        self.assertTrue(_wait(lambda: self.pane("t2", "#{pane_current_command}") == "sleep"))
        self.assertFalse(mod.session_idle("t2"))

    def test_a_command_that_exited_reads_as_idle(self):
        mod.create_command_session("t3", self.home, "true")
        self.assertTrue(_wait(lambda: mod.session_idle("t3")))

    def test_a_server_started_by_the_old_wrapper_is_still_running(self):
        # serverjack 1.5.0's wrapper: no `set -m` in the inner shell, so the
        # pane says "bash" while the command runs. Such servers are still
        # out there after an upgrade and must not be read as exited.
        args = mod.command_args("sleep 300")
        self.assertIn("'set -m; export", args[-1])
        args[-1] = args[-1].replace("'set -m; export", "'export", 1)
        mod.tmux("new-session", "-d", "-s", "old", "-c", self.home, *args)
        self.assertTrue(_wait(lambda: self.pane("old", "#{pane_current_command}") == "bash"
                              and mod.tmux("list-panes", "-a").returncode == 0))
        time.sleep(0.5)
        self.assertFalse(mod.session_idle("old"))

    def test_start_server_is_marked_and_running(self):
        name, err, started = mod.start_server(self.per_dir, self.d("a/app"))
        self.assertEqual((name, err, started), ("pd-remote-app", None, True))
        insts = _wait(lambda: [i for i in mod.server_instances(self.per_dir, mod.server_panes())
                               if i["state"] == "on"])
        self.assertEqual([(i["session"], i["dir"]) for i in insts], [("pd-remote-app", "~/a/app")])

    def test_second_start_in_the_same_dir_leaves_the_server_alone(self):
        name, _, _ = mod.start_server(self.per_dir, self.d("a/app"))
        _wait(lambda: self.pane(name, "#{pane_current_command}") == "sleep")
        pid = self.pane(name, "#{pane_pid}")
        name2, err, started = mod.start_server(self.per_dir, self.d("a/app"))
        self.assertEqual((name2, err, started), (name, "already running", False))
        self.assertEqual(self.pane(name, "#{pane_pid}"), pid)

    def test_same_basename_dirs_get_a_server_each(self):
        n1, _, _ = mod.start_server(self.per_dir, self.d("a/app"))
        n2, err, started = mod.start_server(self.per_dir, self.d("b/app"))
        self.assertEqual((n1, n2, err, started), ("pd-remote-app", "pd-remote-app-2", None, True))
        dirs = {i["session"]: i["dir"] for i in mod.server_instances(self.per_dir, mod.server_panes())}
        self.assertEqual(dirs, {"pd-remote-app": "~/a/app", "pd-remote-app-2": "~/b/app"})

    def test_an_exited_server_is_replaced(self):
        tool = {"id": "pd", "server": dict(self.per_dir["server"], cmd="true")}
        name, _, _ = mod.start_server(tool, self.d("a/app"))
        self.assertTrue(_wait(lambda: [i for i in mod.server_instances(tool, mod.server_panes())
                                       if i["state"] == "exited"]))
        created = self.pane(name, "#{pane_pid}")
        name2, err, started = mod.start_server(tool, self.d("a/app"))
        self.assertEqual((name2, err, started), (name, None, True))
        self.assertNotEqual(self.pane(name2, "#{pane_pid}"), created)

    def test_a_renamed_server_is_still_found(self):
        name, _, _ = mod.start_server(self.single, self.d("a/app"))
        mod.rename_session(name, "oc-server")
        insts = _wait(lambda: [i for i in mod.server_instances(self.single, mod.server_panes())
                               if i["state"] == "on"])
        self.assertEqual([i["session"] for i in insts], ["oc-server"])
        self.assertEqual(mod.start_server(self.single, self.d("b/app"))[:2],
                         ("oc-server", "already running"))
        self.assertFalse(mod.session_exists("solo-serve"))

    def test_an_interactive_session_is_never_taken_for_a_server(self):
        # default_session_name("pd-remote" tool...) can produce a name inside
        # the server's prefix; and an interactive session can even have the
        # single server's exact name. Neither carries the marks, nor the
        # server's command.
        mod.create_command_session("pd-remote-tools", self.d("remote-tools"), "sleep 300")
        mod.create_command_session("solo-serve", self.d("remote-tools"), "bash")
        panes = mod.server_panes()
        self.assertEqual(mod.server_instances(self.per_dir, panes), [])
        self.assertEqual(mod.server_instances(self.single, panes), [])
        # ...so Start makes its own session beside it, never kills it.
        name, err, _ = mod.start_server(self.single, self.d("a/app"))
        self.assertEqual((name, err), ("solo-serve-2", None))
        self.assertTrue(mod.session_exists("solo-serve"))

    def test_an_unmarked_server_from_an_older_version_is_adopted(self):
        mod.create_command_session("pd-remote-app", self.d("a/app"), "sleep 300")
        insts = _wait(lambda: [i for i in mod.server_instances(self.per_dir, mod.server_panes())
                               if i["state"] == "on"])
        self.assertEqual([i["session"] for i in insts], ["pd-remote-app"])

    def test_autostart_leaves_a_running_server_alone(self):
        name, _, _ = mod.start_server(self.per_dir, self.d("a/app"))
        _wait(lambda: self.pane(name, "#{pane_current_command}") == "sleep")
        pid = self.pane(name, "#{pane_pid}")
        with mock.patch.object(mod, "find_tool", lambda tid: self.per_dir):
            line = mod.autostart_start_one({"tool": "pd", "kind": "server", "dir": self.d("a/app")})
        self.assertIn("already running", line)
        self.assertEqual(self.pane(name, "#{pane_pid}"), pid)

    def test_a_trailing_semicolon_in_a_directory_survives_the_mark(self):
        os.makedirs(os.path.join(self.home, "odd;"))
        name, err, _ = mod.start_server(self.per_dir, self.d("odd;"))
        self.assertIsNone(err)
        dirs = [i["dir"] for i in mod.server_instances(self.per_dir, mod.server_panes())]
        self.assertEqual(dirs, ["~/odd;"])


    def test_a_command_ending_in_an_escaped_semicolon_reaches_the_shell_intact(self):
        # `find . -exec rm {} \;` pasted into Start: tmux used to eat the
        # final ";" of any argument as a command separator.
        cmd = "echo one \\;"
        self.assertIsNone(mod.create_command_session("semi", self.home, cmd))
        env = mod.tmux("show-environment", "-t", "=semi", "SERVERJACK_CMD").stdout.strip()
        self.assertEqual(env, "SERVERJACK_CMD=" + cmd)

    def _running(self, tool, name):
        return _wait(lambda: [i for i in mod.server_instances(tool, mod.server_panes())
                              if i["session"] == name and i["state"] == "on"])

    def test_a_window_opened_beside_a_server_does_not_make_it_exited(self):
        # prefix+c or the window tabs: a plain shell becomes the session's
        # active pane. Judged by that, the live server read "exited", and
        # Start / Remove / autostart killed it.
        name, _, _ = mod.start_server(self.per_dir, self.d("a/app"))
        self.assertTrue(self._running(self.per_dir, name))
        mod.tmux("new-window", "-t", f"={name}:", "-c", self.home, "exec bash")
        self.assertTrue(_wait(lambda: self.pane(name, "#{pane_current_command}") == "bash"))
        time.sleep(0.3)
        self.assertEqual([i["state"] for i in mod.server_instances(self.per_dir, mod.server_panes())],
                         ["on"])
        created = self.pane(name, "#{session_created}")
        self.assertEqual(mod.start_server(self.per_dir, self.d("a/app"))[1], "already running")
        self.assertEqual((self.pane(name, "#{session_created}"), self.pane(name, "#{session_windows}")),
                         (created, "2"))

    def test_a_split_beside_a_server_does_not_make_it_exited(self):
        name, _, _ = mod.start_server(self.single, self.d("a/app"))
        self.assertTrue(self._running(self.single, name))
        mod.tmux("split-window", "-t", f"={name}:", "-c", self.home, "exec bash")
        self.assertTrue(_wait(lambda: self.pane(name, "#{pane_current_command}") == "bash"))
        time.sleep(0.3)
        self.assertEqual([i["state"] for i in mod.server_instances(self.single, mod.server_panes())],
                         ["on"])

    def test_a_server_whose_own_pane_is_gone_reads_exited(self):
        # ...even when what is left in the session is not a shell.
        name, _, _ = mod.start_server(self.per_dir, self.d("a/app"))
        self.assertTrue(self._running(self.per_dir, name))
        pane = mod.tmux("show-options", "-v", "-t", f"={name}:", mod.SERVER_PANE_MARK).stdout.strip()
        self.assertRegex(pane, r"^%[0-9]+$")
        mod.tmux("new-window", "-t", f"={name}:", "-c", self.home, "sleep 300")
        mod.tmux("kill-pane", "-t", pane)
        self.assertTrue(_wait(lambda: [i for i in mod.server_instances(self.per_dir, mod.server_panes())
                                       if i["state"] == "exited"]))

    def test_an_unmarked_server_is_judged_by_its_first_pane(self):
        mod.create_command_session("pd-remote-app", self.d("a/app"), "sleep 300")
        self.assertTrue(self._running(self.per_dir, "pd-remote-app"))
        mod.tmux("new-window", "-t", "=pd-remote-app:", "-c", self.home, "exec bash")
        self.assertTrue(_wait(lambda: self.pane("pd-remote-app", "#{pane_current_command}") == "bash"))
        time.sleep(0.3)
        self.assertEqual([i["state"] for i in mod.server_instances(self.per_dir, mod.server_panes())],
                         ["on"])


class TmuxArgTests(unittest.TestCase):
    def test_trailing_semicolons_are_escaped_and_separators_are_not(self):
        self.assertEqual(mod._tmux_arg("a;"), "a\\;")
        self.assertEqual(mod._tmux_arg("a\\;"), "a\\\\;")
        self.assertEqual(mod._tmux_arg(";"), ";")
        self.assertEqual(mod._tmux_arg("a;b"), "a;b")


class PaneExitedTests(unittest.TestCase):
    def test_a_non_shell_is_never_exited(self):
        self.assertFalse(mod.pane_exited("sleep", "1"))

    def test_a_shell_with_no_pid_falls_back_to_the_name(self):
        self.assertTrue(mod.pane_exited("bash", ""))

    def test_a_shell_holding_its_terminal_is_exited_and_one_with_a_job_is_not(self):
        with mock.patch.object(mod, "_shell_has_terminal", lambda pid: True):
            self.assertTrue(mod.pane_exited("bash", "42"))
        with mock.patch.object(mod, "_shell_has_terminal", lambda pid: False):
            self.assertFalse(mod.pane_exited("bash", "42"))

    def test_stat_is_parsed_after_the_last_paren(self):
        # comm can contain spaces and ")" -- tpgid is the 6th field after it.
        line = "42 (we ird) (x)) S 1 42 42 34816 42 4194560 0 0\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=line)):
            self.assertTrue(mod._shell_has_terminal(42))
        line = "42 (bash) S 1 42 42 34816 77 4194560 0 0\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=line)):
            self.assertFalse(mod._shell_has_terminal(42))

    def test_no_proc_means_unknown(self):
        with mock.patch("builtins.open", side_effect=OSError):
            self.assertIsNone(mod._shell_has_terminal(42))


class LoginStateCacheTests(unittest.TestCase):
    """tool_state()'s login check: stale-while-revalidate, never stale
    across a login/install that is still running."""

    def setUp(self):
        mod.clear_tool_cache()
        self.calls = 0
        self.answer = True
        self.delay = 0.0
        self._orig = mod.run_check

        def fake(cmd, timeout=15):
            self.calls += 1
            time.sleep(self.delay)
            return self.answer
        mod.run_check = fake
        self.tool = {"id": "x", "login_check": "check"}

    def tearDown(self):
        mod.run_check = self._orig
        mod.clear_tool_cache()

    def expire(self):
        with mod._STATE_LOCK:
            _exp, val = mod._STATE_CACHE["x"]
            mod._STATE_CACHE["x"] = (time.time() - 1, val)

    def test_first_check_is_inline_and_then_cached(self):
        self.assertIs(mod.logged_in_state(self.tool, []), True)
        self.assertIs(mod.logged_in_state(self.tool, []), True)
        self.assertEqual(self.calls, 1)

    def test_an_expired_answer_is_served_at_once_and_refreshed_once(self):
        mod.logged_in_state(self.tool, [])
        self.expire()
        self.answer, self.delay = False, 0.6
        t0 = time.time()
        got = [mod.logged_in_state(self.tool, []) for _ in range(3)]
        self.assertLess(time.time() - t0, 0.3, "a slow login check blocked the page")
        self.assertEqual(got, [True, True, True])
        self.assertTrue(_wait(lambda: mod.logged_in_state(self.tool, []) is False, 3))
        self.assertEqual(self.calls, 2, "one background refresh, not one per request")

    def test_a_refresh_from_before_a_button_press_cannot_write_back(self):
        mod.logged_in_state(self.tool, [])
        self.expire()
        self.answer, self.delay = False, 0.4
        mod.logged_in_state(self.tool, [])          # starts the slow refresh
        mod.clear_tool_cache("x")                    # e.g. Log in was pressed
        time.sleep(0.6)
        self.assertNotIn("x", mod._STATE_CACHE)

    def age(self, secs):
        """Make the cached answer secs old."""
        with mod._STATE_LOCK:
            _exp, val = mod._STATE_CACHE["x"]
            mod._STATE_CACHE["x"] = (time.time() - secs + mod.STATE_TTL, val)

    def test_an_open_login_session_wants_a_fresh_answer(self):
        panes = [{"name": "login-x", "cmd": "sleep", "pid": ""}]
        mod.logged_in_state(self.tool, [])          # cached True
        self.answer = False
        self.age(mod.FLOW_TTL + 1)
        self.assertIs(mod.logged_in_state(self.tool, panes), False)
        self.assertEqual(self.calls, 2)
        # a burst of renders during the flow shares that answer...
        self.assertIs(mod.logged_in_state(self.tool, panes), False)
        self.assertEqual(self.calls, 2)
        # ...for FLOW_TTL, not STATE_TTL
        self.age(mod.FLOW_TTL + 1)
        panes = [{"name": "install-x-2", "cmd": "curl", "pid": ""}]
        self.assertIs(mod.logged_in_state(self.tool, panes), False)
        self.assertEqual(self.calls, 3)

    def test_an_answer_from_during_a_flow_is_not_kept_after_it(self):
        # the login finishes: the card must say so now, not a minute later
        self.answer = False
        self.assertIs(mod.logged_in_state(self.tool, [{"name": "login-x", "cmd": "sleep", "pid": ""}]), False)
        self.answer = True
        self.assertIs(mod.logged_in_state(self.tool, [{"name": "login-x", "cmd": "bash", "pid": ""}]), True)
        self.assertEqual(self.calls, 2)
        self.assertIs(mod.logged_in_state(self.tool, []), True)
        self.assertEqual(self.calls, 2, "an answer from outside the flow is cached as usual")

    def run_together(self, n, panes):
        import threading
        got = []
        ts = [threading.Thread(target=lambda: got.append(mod.logged_in_state(self.tool, panes)))
              for _ in range(n)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(5)
        return got

    def test_concurrent_cold_requests_share_one_check(self):
        # e.g. three tabs reloading at once after an Update restarted serverjack
        self.delay = 0.4
        t0 = time.time()
        got = self.run_together(4, [])
        self.assertEqual(got, [True] * 4)
        self.assertEqual(self.calls, 1, "one check, not one per request")
        self.assertLess(time.time() - t0, 0.8)

    def test_concurrent_requests_during_a_flow_share_one_check(self):
        mod.logged_in_state(self.tool, [])
        self.age(mod.FLOW_TTL + 1)
        self.answer, self.delay = False, 0.4
        got = self.run_together(4, [{"name": "login-x", "cmd": "sleep", "pid": ""}])
        self.assertEqual(got, [False] * 4)
        self.assertEqual(self.calls, 2)

    def test_status_runs_no_login_check(self):
        # /api/status answers without an identity even under SERVERJACK_ALLOW,
        # and reports no login state: it must not be a way to run checks.
        tool = {"id": "x", "bin": "sh", "login_check": "check"}
        with mock.patch.object(mod, "load_tools", return_value=([tool], None)):
            mod.status()
            mod.status()
        self.assertEqual(self.calls, 0)

    def test_the_warm_up_checks_each_tool_once(self):
        tool = {"id": "x", "bin": "sh", "login_check": "check"}
        with mock.patch.object(mod, "load_tools", return_value=([tool], None)):
            mod.warm_login_cache()
        self.assertEqual(self.calls, 1)
        self.assertIs(mod.logged_in_state(tool, []), True)
        self.assertEqual(self.calls, 1)

    def test_a_finished_login_session_does_not(self):
        panes = [{"name": "login-x", "cmd": "bash", "pid": ""}]
        mod.logged_in_state(self.tool, panes)
        mod.logged_in_state(self.tool, panes)
        self.assertEqual(self.calls, 1)

    def test_a_nul_byte_never_reaches_tmux(self):
        # subprocess raises on one; a %00 in a URL is a session that isn't there
        self.assertEqual(mod.tmux("has-session", "-t", "=a\0b").returncode, 1)
        self.assertFalse(mod.session_exists("a\0b"))

    def test_only_this_tools_flow_sessions_count(self):
        self.assertFalse(mod._login_flow_open("x", [{"name": "login-xy", "cmd": "sleep"}]))
        self.assertFalse(mod._login_flow_open("x", [{"name": "relogin-x", "cmd": "sleep"}]))
        self.assertTrue(mod._login_flow_open("x", [{"name": "login-x-3", "cmd": "sleep"}]))


class ToolCardTests(unittest.TestCase):
    def setUp(self):
        self._home = mod.HOME
        mod.HOME = "/home/x"
        mod.save_autostart([])
        self.tool = {"id": "cc", "label": "Claude",
                     "server": {"label": "Remote Control server", "cmd": "claude remote-control",
                                "session": "claude-remote", "per_dir": True, "note": "n"},
                     "actions": [{"label": "hello", "cmd": "echo hi"}], "login": "l"}

    def tearDown(self):
        mod.HOME = self._home
        mod.save_autostart([])

    def st(self, servers, state="on"):
        return {"id": "cc", "label": "Claude", "installed": True, "logged_in": True,
                "needs_ok": True, "daemon_running": False, "server_state": state,
                "server_session": servers[0]["session"] if servers else "claude-remote",
                "servers": servers}

    def summary(self, html_):
        return html_[html_.index("<summary>"):html_.index("</summary>")]

    def test_one_counted_pill_for_every_instance(self):
        insts = [{"session": "claude-remote-a", "dir": "~/p/a", "state": "on"},
                 {"session": "claude-remote-b", "dir": "~/p/b", "state": "on"},
                 {"session": "claude-remote-c", "dir": "~/p/c", "state": "exited"}]
        out = mod.tool_card(self.tool, self.st(insts))
        summ = self.summary(out)
        self.assertEqual(summ.count('class="pill'), 1)
        self.assertIn("2 running · 1 exited", summ)
        self.assertIn('class="pill warn"', summ)
        for d in ("~/p/a", "~/p/b", "~/p/c"):
            self.assertIn(f"<code>{d}</code>", out)
        self.assertIn('data-confirm="Stop Remote Control server in “~/p/a”?"', out)
        self.assertIn('data-confirm="Remove the exited Remote Control server in “~/p/c”?"', out)

    def test_no_instances_reads_stopped(self):
        summ = self.summary(mod.tool_card(self.tool, self.st([], "off")))
        self.assertIn("<span>stopped</span>", summ)

    def test_picker_is_labelled_and_only_drives_the_start_button(self):
        out = mod.tool_card(self.tool, self.st([], "off"))
        self.assertEqual(out.count('class="dirpick"'), 1)
        self.assertIn('<label for="dp-cc">Directory</label>', out)
        self.assertIn('<input form="d-cc" id="dp-cc" name="dir"', out)
        self.assertIn('form="d-cc" name="do" value="/tools/server">Start', out)
        # the non-directory action stays on the card's main form
        self.assertIn('name="do" value="/tools/action:0">Run', out)
        self.assertNotIn('form="d-cc" name="do" value="/tools/action:0"', out)
        # per-directory: "start at boot" only on rows that name a directory
        self.assertNotIn("data-picker", out)

    def test_no_picker_when_nothing_reads_a_directory(self):
        tool = {"id": "cx", "label": "Codex", "actions": [{"label": "Pair", "cmd": "p"}],
                "daemon": {"label": "D", "start": "s", "stop": "t", "pidfile": "/nonexistent"}}
        out = mod.tool_card(tool, dict(self.st([], "off"), id="cx", label="Codex"))
        self.assertNotIn("dirpick", out)
        self.assertNotIn('id="d-cx"', out)

    def test_a_saved_boot_directory_with_nothing_running_gets_its_own_row(self):
        tmp = tempfile.mkdtemp(prefix="sj-unit-boot-")
        self.addCleanup(shutil.rmtree, tmp, True)
        mod.set_autostart("cc", "server", tmp, True)
        out = mod.tool_card(self.tool, self.st([], "off"))
        self.assertIn(f"<code>{tmp}</code>", out)
        self.assertIn("Starts at boot; not running now.", out)
        self.assertIn(f'<input type="hidden" name="dir" value="{tmp}">', out)
        self.assertRegex(out, r'id="a-cc-server-p0".*?name="dir" value="%s"' % tmp)
        self.assertIn('form="a-cc-server-p0" name="on" value="1" checked', out)

    def test_single_server_box_shows_its_one_entry(self):
        tool = {"id": "oc", "label": "OpenCode",
                "server": {"label": "Server", "cmd": "opencode serve", "session": "opencode-serve"}}
        tmp = tempfile.mkdtemp(prefix="sj-unit-boot-")
        self.addCleanup(shutil.rmtree, tmp, True)
        out = mod.tool_card(tool, dict(self.st([], "off"), id="oc"))
        self.assertIn('data-picker="1"', out)
        mod.set_autostart("oc", "server", tmp, True, per_dir=False)
        out = mod.tool_card(tool, dict(self.st([], "off"), id="oc"))
        self.assertIn("Starts at boot in <code>", out)
        self.assertIn('form="a-oc-server" name="on" value="1" checked', out)
        self.assertNotIn('data-picker="1"', out)

    def test_a_running_single_server_names_the_directory_it_starts_in_at_boot(self):
        # Running in one directory, the boot entry for another: the ticked
        # box alone read as "this one comes back at boot".
        tool = {"id": "oc", "label": "OpenCode",
                "server": {"label": "Server", "cmd": "opencode serve", "session": "opencode-serve",
                           "note": "n"}}
        tmp = tempfile.mkdtemp(prefix="sj-unit-boot-")
        self.addCleanup(shutil.rmtree, tmp, True)
        mod.set_autostart("oc", "server", tmp, True, per_dir=False)
        live = [{"session": "oc-server", "dir": "~/projects/game", "state": "on"}]
        out = mod.tool_card(tool, dict(self.st(live, "on"), id="oc"))
        self.assertIn('form="a-oc-server" name="on" value="1" checked', out)
        self.assertIn(f"n Starts at boot in <code>{tmp}</code>.", out)
        self.assertIn(">Stop</button>", out)


class _ToolRouteStub:
    """Handler.do_tool() needs only redirect() and fail() from its instance."""

    def __init__(self):
        self.redirected = self.failed = None

    def redirect(self, url):
        self.redirected = url

    def fail(self, msg, status=400, tid="", dir=""):
        self.failed = (msg, status)


class AutostartUntickTests(unittest.TestCase):
    """The row for a boot directory that is gone says "Untick to forget it".
    The untick went through resolve_dir(), which re-created a deleted
    directory, and failed with 400 (keeping the entry) when it couldn't --
    a project on a drive that is not mounted."""

    def setUp(self):
        self.tool = {"id": "cc", "label": "Claude",
                     "server": {"label": "S", "cmd": "c", "session": "cc-remote", "per_dir": True}}
        self.tmp = tempfile.mkdtemp(prefix="sj-unit-untick-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.p1 = mock.patch.object(mod, "find_tool", lambda tid: self.tool if tid == "cc" else None)
        self.p2 = mock.patch.object(mod, "tool_state", lambda t, names=None: {"servers": []})
        self.p1.start()
        self.p2.start()
        mod.save_autostart([])

    def tearDown(self):
        self.p1.stop()
        self.p2.stop()
        mod.save_autostart([])

    def post(self, **form):
        stub = _ToolRouteStub()
        mod.Handler.do_tool(stub, "/tools/autostart", dict(id="cc", kind="server", **form))
        return stub

    def test_unticking_a_deleted_directory_forgets_it_without_re_creating_it(self):
        gone = os.path.join(self.tmp, "deleted-proj")
        mod.save_autostart([{"tool": "cc", "kind": "server", "dir": gone}])
        stub = self.post(dir=gone)
        self.assertIsNone(stub.failed)
        self.assertTrue(stub.redirected.startswith("/?done=boot-off&"), stub.redirected)
        self.assertEqual(mod.load_autostart(), [])
        self.assertFalse(os.path.exists(gone))

    def test_unticking_a_directory_that_cannot_be_created_still_forgets_it(self):
        gone = "/proc/sj-unit-not-mounted/proj"
        mod.save_autostart([{"tool": "cc", "kind": "server", "dir": gone},
                            {"tool": "cc", "kind": "server", "dir": self.tmp}])
        stub = self.post(dir=gone)
        self.assertIsNone(stub.failed)
        self.assertTrue(stub.redirected.startswith("/?done=boot-off&"), stub.redirected)
        self.assertEqual([e["dir"] for e in mod.load_autostart()], [os.path.realpath(self.tmp)])

    def test_a_nul_byte_in_the_directory_is_an_error_not_a_crash(self):
        mod.save_autostart([{"tool": "cc", "kind": "server", "dir": self.tmp}])
        stub = self.post(dir="a\0b")
        self.assertEqual(stub.failed[1], 400)
        self.assertEqual(len(mod.load_autostart()), 1)
        self.assertEqual(mod._auto_dir("a\0b"), "a\0b")

    def test_ticking_still_checks_the_directory(self):
        stub = self.post(dir="/proc/sj-unit-not-mounted/proj", on="1")
        self.assertEqual(stub.failed[1], 400)
        self.assertEqual(mod.load_autostart(), [])
        stub = self.post(dir=self.tmp, on="1")
        self.assertTrue(stub.redirected.startswith("/?done=boot-on&"), stub.redirected)
        self.assertEqual([e["dir"] for e in mod.load_autostart()], [os.path.realpath(self.tmp)])


class AutostartSingleServerTests(unittest.TestCase):
    def tearDown(self):
        mod.save_autostart([])

    def test_a_single_server_keeps_one_entry(self):
        mod.set_autostart("oc", "server", "/tmp", True, per_dir=False)
        mod.set_autostart("oc", "server", "/", True, per_dir=False)
        self.assertEqual([e["dir"] for e in mod.load_autostart()], ["/"])
        mod.set_autostart("oc", "server", "/tmp", False, per_dir=False)
        self.assertEqual(mod.load_autostart(), [])

    def test_a_per_dir_server_keeps_one_per_directory(self):
        mod.set_autostart("cc", "server", "/tmp", True)
        mod.set_autostart("cc", "server", "/", True)
        self.assertEqual(sorted(e["dir"] for e in mod.load_autostart()), ["/", "/tmp"])


class ServerStopStaleCardTests(unittest.TestCase):
    """/tools/server's Stop from a card older than the session list: Rename
    and Kill happen in place, so a card can still post a server's old name.
    The server is found by its marks and the card's directory instead (a
    single server: there is one); with nothing of it left, the route says so
    and leaves the boot entry alone. It used to kill nothing, drop the boot
    entry and say "stopped"."""

    def setUp(self):
        self.tools = {
            "cc": {"id": "cc", "label": "Claude",
                   "server": {"label": "S", "cmd": "c", "session": "cc-remote", "per_dir": True}},
            "oc": {"id": "oc", "label": "OpenCode",
                   "server": {"label": "Server", "cmd": "c", "session": "oc-serve"}}}
        self.servers, self.killed = [], []
        self.tmp = tempfile.mkdtemp(prefix="sj-unit-stop-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for p in (mock.patch.object(mod, "find_tool", lambda tid: self.tools.get(tid)),
                  mock.patch.object(mod, "tool_state", lambda t, names=None: {"servers": self.servers}),
                  mock.patch.object(mod, "tmux", lambda *a, **k: self.killed.append(a)),
                  mock.patch.object(mod, "clear_tool_cache", lambda tid: None)):
            p.start()
            self.addCleanup(p.stop)
        mod.save_autostart([])
        self.addCleanup(mod.save_autostart, [])

    def stop(self, tid, **form):
        stub = _ToolRouteStub()
        mod.Handler.do_tool(stub, "/tools/server", dict(id=tid, action="stop", **form))
        return stub

    def test_a_renamed_per_dir_server_is_found_by_its_directory(self):
        self.servers = [{"session": "cc-other", "dir": "/", "state": "on"},
                        {"session": "renamed", "dir": self.tmp, "state": "on"}]
        mod.set_autostart("cc", "server", self.tmp, True)
        stub = self.stop("cc", session="cc-remote-x", dir=self.tmp)
        self.assertEqual(self.killed, [("kill-session", "-t", "=renamed")])
        self.assertEqual(mod.load_autostart(), [])
        self.assertTrue(stub.redirected.startswith("/?done=server-stop&n=renamed&"), stub.redirected)

    def test_a_renamed_single_server_is_the_one_there_is(self):
        self.servers = [{"session": "renamed", "dir": "/", "state": "on"}]
        mod.set_autostart("oc", "server", self.tmp, True, per_dir=False)
        stub = self.stop("oc", session="oc-serve", dir="/")
        self.assertEqual(self.killed, [("kill-session", "-t", "=renamed")])
        self.assertEqual(mod.load_autostart(), [])
        self.assertTrue(stub.redirected.startswith("/?done=server-stop&n=renamed&"), stub.redirected)

    def test_nothing_running_is_an_error_and_keeps_the_boot_entry(self):
        mod.set_autostart("cc", "server", self.tmp, True)
        mod.set_autostart("oc", "server", self.tmp, True, per_dir=False)
        self.servers = [{"session": "cc-other", "dir": "/", "state": "on"}]
        stub = self.stop("cc", session="cc-remote-x", dir=self.tmp)
        self.assertIsNone(stub.redirected)
        self.assertEqual(stub.failed[1], 400)
        self.assertIn("isn’t running", stub.failed[0])
        self.servers = []
        stub = self.stop("oc", session="oc-serve", dir=self.tmp)
        self.assertIsNone(stub.redirected)
        self.assertEqual(self.killed, [])
        self.assertEqual(len(mod.load_autostart()), 2)

    def test_a_name_that_is_no_server_of_its_own_is_never_killed(self):
        # An interactive session that only shares the prefix, no directory.
        self.servers = [{"session": "cc-remote-app", "dir": self.tmp, "state": "on"}]
        stub = self.stop("cc", session="cc-remote-tools")
        self.assertEqual(self.killed, [])
        self.assertEqual(stub.failed[1], 400)


class CleanCmdTests(unittest.TestCase):
    """clean_cmd(): browsers submit every <textarea> newline as CRLF, and bash
    kept the CR glued to the last word of every line but the last."""

    def test_crlf_and_lone_cr_become_newlines(self):
        self.assertEqual(mod.clean_cmd("cd projects\r\nls -d game\r\necho done"),
                         "cd projects\nls -d game\necho done")
        # A lone CR (old Mac line ending) must split lines, not join them.
        self.assertEqual(mod.clean_cmd("a\rb"), "a\nb")

    def test_outer_whitespace_is_stripped_and_none_is_empty(self):
        self.assertEqual(mod.clean_cmd("  echo hi \r\n"), "echo hi")
        self.assertEqual(mod.clean_cmd(None), "")


class ShortcutEditTests(unittest.TestCase):
    """load_shortcuts() repairing CRLF commands saved before clean_cmd(),
    add_shortcut()/update_shortcut() (edit in place: same id, same position;
    the built-in Update row and unknown ids refused), and runs named after
    the shortcut's label."""

    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        self._orig = (mod.CONFIG_DIR, mod.SHORTCUTS_FILE)
        mod.CONFIG_DIR = self.cfg
        mod.SHORTCUTS_FILE = os.path.join(self.cfg, "shortcuts.json")

    def tearDown(self):
        mod.CONFIG_DIR, mod.SHORTCUTS_FILE = self._orig
        shutil.rmtree(self.cfg, ignore_errors=True)

    def test_old_crlf_entry_is_cleaned_on_load(self):
        with open(mod.SHORTCUTS_FILE, "w") as f:
            json.dump([{"id": "a", "label": "Two lines", "cmd": "cd /tmp\r\npwd", "dir": "/tmp"}], f)
        self.assertEqual(mod.load_shortcuts()[0]["cmd"], "cd /tmp\npwd")

    def test_add_stores_a_clean_command_and_returns_the_label(self):
        self.assertEqual(mod.add_shortcut("", "ls -la\r\npwd", "/tmp"), "ls")
        self.assertEqual(mod.load_shortcuts()[0]["cmd"], "ls -la\npwd")

    def test_update_replaces_in_place(self):
        mod.add_shortcut("First", "echo 1", "/tmp")
        mod.add_shortcut("Second", "echo 2", "/tmp")
        mod.add_shortcut("Third", "echo 3", "/tmp")
        before = mod.load_shortcuts()
        label, err = mod.update_shortcut(before[1]["id"], "Second, fixed", "echo two\r\n", "/var")
        self.assertIsNone(err)
        self.assertEqual(label, "Second, fixed")
        after = mod.load_shortcuts()
        self.assertEqual([x["id"] for x in after], [x["id"] for x in before])
        self.assertEqual(after[1], {"id": before[1]["id"], "label": "Second, fixed",
                                    "cmd": "echo two", "dir": "/var"})
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[2], before[2])

    def test_update_refuses_an_unknown_id_and_the_builtin_row(self):
        mod.add_shortcut("Only", "echo 1", "/tmp")
        before = mod.load_shortcuts()
        for sid in ("nope", mod.UPDATE_ID):
            label, err = mod.update_shortcut(sid, "x", "echo x", "/tmp")
            self.assertIsNone(label)
            self.assertTrue(err)
        self.assertEqual(mod.load_shortcuts(), before)

    def test_a_run_is_named_after_the_label(self):
        existing = {"logs"}
        with mock.patch.object(mod, "session_exists", lambda n: n in existing):
            sc = {"label": "Logs", "cmd": "echo SHORTCUT_RAN; date"}
            self.assertEqual(mod.shortcut_session_name(sc, "/tmp"), "logs-2")
            sc = {"label": "Build the game!", "cmd": "make"}
            self.assertEqual(mod.shortcut_session_name(sc, "/tmp"), "build-the-game")
            # nothing usable in the label: named after the command, as before
            sc = {"label": "★★", "cmd": "sudo -u x df -h"}
            self.assertEqual(mod.shortcut_session_name(sc, mod.HOME), "df")


class UpdateRowTests(unittest.TestCase):
    """The built-in Update row shows its command with ~ for the home
    directory; UPDATE_CMD (what actually runs) is untouched."""

    def test_git_checkout_shows_the_tilde_form(self):
        with mock.patch.object(mod, "CHANNEL", "git"), mock.patch.object(mod, "HOME", "/home/u"), \
                mock.patch.object(mod, "REPO", "/home/u/projects/serverjack"):
            self.assertEqual(mod.update_cmd_show(),
                             "cd ~/projects/serverjack && git pull --ff-only && bash install.sh")

    def test_release_install_shows_serverjack_ctl(self):
        with mock.patch.object(mod, "CHANNEL", "release"), mock.patch.object(mod, "HOME", "/home/u"), \
                mock.patch.object(mod, "SERVERJACK_CTL_PATH", "/home/u/.local/bin/serverjack-ctl"):
            self.assertEqual(mod.update_cmd_show(), "~/.local/bin/serverjack-ctl update")


class DoneNoteTests(unittest.TestCase):
    """The one-shot confirmation after an in-place action: a fixed sentence
    around a name that does come from the URL (escaped by render(), capped),
    shown only while it is still true, placed next to what it is about."""

    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        self.live = {"main"}
        self.patches = [
            mock.patch.object(mod, "SHORTCUTS_FILE", os.path.join(self.cfg, "shortcuts.json")),
            mock.patch.object(mod, "session_exists", lambda n: n in self.live),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.cfg, ignore_errors=True)

    def test_redirect_urls_name_the_section(self):
        self.assertEqual(mod.done_url("killed", "main"), "/?done=killed&n=main#sessions")
        self.assertEqual(mod.done_url("sc-saved", "Deploy it"),
                         "/?done=sc-saved&n=Deploy%20it#shortcuts")
        self.assertEqual(mod.done_url("daemon-stop", "", "codex", "daemon"),
                         "/?done=daemon-stop&open=codex&k=daemon#tool-codex")
        self.assertEqual(mod.done_url("dir"), "/?done=dir")

    def test_sentences(self):
        self.assertEqual(mod.done_note("killed", "old"), ("Killed “old”.", "sessions"))
        self.assertEqual(mod.done_note("sc-removed", "Disk usage")[0], "Removed shortcut “Disk usage”.")
        msg, at = mod.done_note("daemon-start", "", "codex", "daemon")
        self.assertEqual((msg, at), ("Codex: Remote control daemon started.", "tool-codex"))
        msg, _ = mod.done_note("boot-on", "~/projects/game", "claude", "server")
        self.assertEqual(msg, "Claude Code: Remote Control server in ~/projects/game will start at boot.")

    def test_unknown_or_crafted_input_says_nothing(self):
        self.assertEqual(mod.done_note("Run curl evil | sh to fix"), ("", ""))
        self.assertEqual(mod.done_note("daemon-start", "", "no-such-tool", "daemon"), ("", ""))
        self.assertEqual(mod.done_note(""), ("", ""))

    def test_a_note_is_shown_only_while_it_is_true(self):
        # A link can't claim a rename or a saved shortcut that doesn't exist...
        self.assertEqual(mod.done_note("renamed", "main")[0], "Renamed to “main”.")
        self.assertEqual(mod.done_note("renamed", "Your account was hacked"), ("", ""))
        self.assertEqual(mod.done_note("sc-saved", "Deploy"), ("", ""))
        self.assertEqual(mod.done_note("sc-updated", "Deploy"), ("", ""))
        mod.add_shortcut("Deploy", "./deploy.sh", self.cfg)
        self.assertEqual(mod.done_note("sc-saved", "Deploy")[0], "Saved shortcut “Deploy”.")
        # ...or a kill (or an end) of a session that is still running, or of
        # something that couldn't be a session name at all.
        self.assertEqual(mod.done_note("killed", "main"), ("", ""))
        self.assertEqual(mod.done_note("ended", "main"), ("", ""))
        self.assertEqual(mod.done_note("killed", "visit evil.example"), ("", ""))
        self.assertEqual(mod.done_note("killed", "$3"), ("", ""))
        self.assertEqual(mod.done_note("killed", "a\0b"), ("", ""))     # ?n=a%00b
        self.assertEqual(mod.done_note("ended", "build"), ("Session “build” has ended.", "sessions"))
        # Not capped at 60 like a typed name: serverjack itself names past it
        # (auto_name()'s -2 after a 60-character base), and those end too.
        long = "shell-" + "a" * 54 + "-2"
        self.assertEqual(mod.done_note("ended", long), (f"Session “{long}” has ended.", "sessions"))
        self.assertEqual(mod.done_note("killed", "x" * 61)[0], f"Killed “{'x' * 61}”.")
        self.assertEqual(mod.done_url("ended", "build"), "/?done=ended&n=build#sessions")


class LandingHandlerTests(unittest.TestCase):
    """The landing page's POST routes, through a Handler with no socket: what
    a failing form re-renders (nothing typed lost, the directory included),
    where an in-place action lands, and that the commands reaching tmux are
    clean. sessions(), the tool registry and tmux itself are stubbed."""

    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        self.dir = tempfile.mkdtemp()
        self.existing = {"main"}
        self.created = []
        self.patches = [
            mock.patch.object(mod, "CONFIG_DIR", self.cfg),
            mock.patch.object(mod, "SHORTCUTS_FILE", os.path.join(self.cfg, "shortcuts.json")),
            mock.patch.object(mod, "PREFS_FILE", os.path.join(self.cfg, "prefs.json")),
            mock.patch.object(mod, "sessions", lambda: []),
            mock.patch.object(mod, "load_tools", lambda: ([], None)),
            mock.patch.object(mod, "session_exists", lambda n: n in self.existing),
            mock.patch.object(mod, "create_session",
                              lambda kind, name, cwd, command=None:
                              self.created.append((kind, name, cwd, command))),
            mock.patch.object(mod, "tmux", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", "")),
        ]
        for p in self.patches:
            p.start()

        test = self

        class Stub(mod.Handler):
            def __init__(self, path):
                self.path = path
                self.sent = None

            def gate(self):
                return True, ""

            def same_site(self):
                return True

            def form(self):
                return test.body

            def send_html(self, body, status=200):
                self.sent = ("html", status, body)

            def send_json(self, obj, status=200):
                self.sent = ("json", status, obj)

            def redirect(self, location):
                self.sent = ("redirect", 303, location)
        self.Stub = Stub

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.cfg, ignore_errors=True)
        shutil.rmtree(self.dir, ignore_errors=True)

    def post(self, path, **body):
        self.body = body
        h = self.Stub(path)
        h.do_POST()
        return h.sent

    def get(self, path):
        h = self.Stub(path)
        h.do_GET()
        return h.sent

    def test_start_error_keeps_the_typed_directory_and_the_shortcut_tick(self):
        kind, status, page = self.post("/start", what="shell", dir=self.dir, name="main",
                                       cmd="echo hi", save="1", label="")
        self.assertEqual((kind, status), ("html", 400))
        self.assertIn('id="dir" name="dir"', page)
        self.assertIn(f'value="{self.dir}"', page)
        self.assertIn('id="save" name="save" value="1" checked', page)
        self.assertIn('href="/s/main"', page)          # the duplicate error's Open button
        self.assertEqual(self.created, [])

    def test_naming_the_shortcut_saves_it_without_the_tick(self):
        kind, _, _where = self.post("/start", what="shell", dir=self.dir, name="",
                                    cmd="echo one\r\necho two", label="Two lines")
        self.assertEqual(kind, "redirect")
        self.assertEqual(self.created[0][3], "echo one\necho two")
        self.assertEqual([x["label"] for x in mod.load_shortcuts()], ["Two lines"])
        self.assertEqual(mod.load_shortcuts()[0]["cmd"], "echo one\necho two")

    def test_saving_a_shortcut_with_no_command_is_refused(self):
        kind, status, page = self.post("/start", what="shell", dir=self.dir, cmd="",
                                       save="1", label="Empty")
        self.assertEqual((kind, status), ("html", 400))
        self.assertIn("type a command first", page)
        self.assertIn('value="Empty"', page)
        self.assertEqual(self.created, [])
        self.assertEqual(mod.load_shortcuts(), [])

    def test_new_error_keeps_the_directory(self):
        _, status, page = self.post("/new", kind="shell", dir=self.dir, name="main")
        self.assertEqual(status, 400)
        self.assertIn(f'value="{self.dir}"', page)

    def test_shortcut_errors_keep_the_whole_form(self):
        _, status, page = self.post("/shortcuts/add", label="Deploy", cmd="", dir=self.dir)
        self.assertEqual(status, 400)
        self.assertIn(f'value="{self.dir}"', page)
        self.assertIn('value="Deploy"', page)
        self.assertIn('data-at="addsc"', page)

    def test_shortcut_save_edit_and_delete_land_on_shortcuts(self):
        _, _, where = self.post("/shortcuts/add", label="Deploy", cmd="./deploy.sh", dir=self.dir)
        self.assertEqual(where, "/?done=sc-saved&n=Deploy#shortcuts")
        sid = mod.load_shortcuts()[0]["id"]
        _, _, where = self.post("/shortcuts/add", id=sid, label="Deploy", cmd="./deploy.sh --fast",
                                dir=self.dir)
        self.assertEqual(where, "/?done=sc-updated&n=Deploy#shortcuts")
        self.assertEqual(len(mod.load_shortcuts()), 1)
        self.assertEqual(mod.load_shortcuts()[0]["cmd"], "./deploy.sh --fast")
        _, status, _ = self.post("/shortcuts/add", id=mod.UPDATE_ID, label="x", cmd="x", dir=self.dir)
        self.assertEqual(status, 404)
        _, _, where = self.post("/shortcuts/del", id=sid)
        self.assertEqual(where, "/?done=sc-removed&n=Deploy#shortcuts")

    def test_kill_and_rename_land_on_sessions(self):
        self.assertEqual(self.post("/kill", name="main")[2], "/?done=killed&n=main#sessions")
        self.existing = set()
        self.assertEqual(self.post("/kill", name="gone")[2], "/#sessions")

    def test_post_to_root_redirects_home(self):
        # WebKit reloads a replaceState'd error page as a POST to its new URL.
        self.assertEqual(self.post("/", what="shell", name="main"), ("redirect", 303, "/"))
        # ...including a refused shortcut edit, whose page sits at /?edit_sc=<id>.
        self.assertEqual(self.post("/?edit_sc=sc1", label="x", cmd="x"),
                         ("redirect", 303, "/?edit_sc=sc1"))

    def test_prefs_error_is_shown_inside_the_change_form(self):
        _, status, page = self.post("/prefs", dir=os.path.join(self.dir, "missing"))
        self.assertEqual(status, 400)
        dd = page.index('class="inline ddchange"')
        self.assertGreater(page.index("Not a directory"), dd)

    def test_with_the_page_script_the_keep_box_alone_decides(self):
        # The script ticks the box when a shortcut name is typed and sends
        # save_ui; unticking it afterwards must win over the typed name.
        kind, _, _ = self.post("/start", what="shell", dir=self.dir, cmd="echo a",
                               label="Not this one", save_ui="1")
        self.assertEqual(kind, "redirect")
        self.assertEqual(len(self.created), 1)
        self.assertEqual(mod.load_shortcuts(), [])
        self.post("/start", what="shell", dir=self.dir, cmd="echo b", label="This one",
                  save="1", save_ui="1")
        self.assertEqual([x["label"] for x in mod.load_shortcuts()], ["This one"])
        self.assertTrue(mod.wants_save({"label": "No script"}))
        self.assertFalse(mod.wants_save({"label": "Unticked", "save_ui": "1"}))
        self.assertFalse(mod.wants_save({}))

    def test_an_edit_of_a_removed_shortcut_comes_back_as_an_add(self):
        _, status, page = self.post("/shortcuts/add", id="gone-123", label="Deploy",
                                    cmd="./deploy.sh", dir=self.dir)
        self.assertEqual(status, 404)
        self.assertIn("no longer exists", page)
        self.assertNotIn('value="gone-123"', page)      # not an edit that 404s on every retry
        self.assertIn(">Add a shortcut<", page)
        self.assertNotIn(">Edit shortcut<", page)
        self.assertIn('value="Deploy"', page)
        self.assertIn("./deploy.sh", page)
        _, _, where = self.post("/shortcuts/add", label="Deploy", cmd="./deploy.sh", dir=self.dir)
        self.assertEqual(where, "/?done=sc-saved&n=Deploy#shortcuts")

    def test_a_hand_edited_file_with_numbers_for_text(self):
        with open(mod.SHORTCUTS_FILE, "w") as f:
            json.dump([{"id": 7, "label": 42, "cmd": "uptime", "dir": self.dir}], f)
        kind, status, page = self.get("/")
        self.assertEqual((kind, status), ("html", 200))
        self.assertIn("/?edit_sc=7#addsc", page)
        _, _, page = self.get("/?edit_sc=7")
        self.assertIn('name="id" value="7"', page)
        self.assertIn(">Edit shortcut<", page)
        sc = mod.load_shortcuts()[0]
        self.assertEqual(mod.shortcut_session_name(sc, self.dir), "42")
        _, _, where = self.post("/shortcuts/add", id="7", label="Up", cmd="uptime -p", dir=self.dir)
        self.assertEqual(where, "/?done=sc-updated&n=Up#shortcuts")
        self.assertEqual([(x["id"], x["cmd"]) for x in mod.load_shortcuts()], [("7", "uptime -p")])
        _, _, where = self.post("/shortcuts/del", id="7")
        self.assertEqual(where, "/?done=sc-removed&n=Up#shortcuts")
        self.assertEqual(mod.load_shortcuts(), [])

    def test_done_notes_from_a_link_are_text_and_only_while_true(self):
        _, _, page = self.get("/?done=killed&n=main")         # still running
        self.assertNotIn('class="flash"', page)
        _, _, page = self.get("/?done=sc-removed&n=%3Cb%3Ex%3C%2Fb%3E")
        self.assertIn("Removed shortcut “&lt;b&gt;x&lt;/b&gt;”.", page)
        self.assertNotIn("<b>x</b>", page)
        _, _, page = self.get("/?ended=gone")
        self.assertIn("Session “gone” has ended.", page)
        _, _, page = self.get("/?ended=main")
        self.assertNotIn('class="flash"', page)


class PageChromeTests(unittest.TestCase):
    """Landing-layout fixes that are pure functions of module state: the header
    title, the dark color-scheme in the shared tokens, and a client hanging up
    mid-response."""

    def setUp(self):
        self._title = mod.TITLE

    def tearDown(self):
        mod.TITLE = self._title

    def test_title_is_dropped_when_it_repeats_the_wordmark(self):
        # SERVERJACK_TITLE defaults to the hostname; a box called serverjack
        # used to render "serverjack serverjack".
        for t in ("serverjack", "Serverjack", " SERVERJACK "):
            mod.TITLE = t
            self.assertEqual(mod.title_small(), "", t)

    def test_other_titles_are_kept_and_escaped(self):
        mod.TITLE = "homeserver"
        self.assertEqual(mod.title_small(), " <small>homeserver</small>")
        mod.TITLE = "<b>x</b>"
        self.assertEqual(mod.title_small(), " <small>&lt;b&gt;x&lt;/b&gt;</small>")

    def test_tokens_declare_a_dark_color_scheme(self):
        # Without it Chromium/Firefox draw light scrollbars and white
        # checkboxes on the dark-only UI. TOKENS is shared by both pages.
        self.assertIn("color-scheme:dark;", mod.TOKENS)
        self.assertEqual(mod._token("bg-primary"), "#080f0e")

    def test_landing_and_deny_pages_render_the_header_once(self):
        mod.TITLE = "serverjack"
        with mock.patch.object(mod, "sessions", return_value=[]), \
                mock.patch.object(mod, "load_tools", return_value=([], None)), \
                mock.patch.object(mod, "load_shortcuts", return_value=[]), \
                mock.patch.object(mod, "update_available", return_value=False):
            page = mod.render()
        self.assertNotIn("<small>serverjack</small>", page)
        self.assertNotIn("<small>serverjack</small>", mod.render_deny("x@y"))

    def test_deny_page_without_identity_says_so(self):
        # 127.0.0.1, an SSH forward or an untrusted proxy carry no login: that
        # is usually the owner, who must not be told they are someone else.
        page = mod.render_deny("")
        self.assertIn("No Tailscale identity", page)
        self.assertIn("tailscale serve", page)
        self.assertNotIn("another tailnet user", page)
        self.assertNotIn("nobody", page)

    def test_deny_page_with_a_wrong_login_names_it_escaped(self):
        page = mod.render_deny("<mallory>@example.com")
        self.assertIn("another tailnet user", page)
        self.assertIn("&lt;mallory&gt;@example.com", page)
        self.assertNotIn("<mallory>", page)

    def test_client_hangup_mid_response_is_swallowed(self):
        stub = mock.Mock(close_connection=False)
        for exc in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            with mock.patch.object(mod.BaseHTTPRequestHandler, "handle", side_effect=exc()):
                mod.Handler.handle(stub)          # must not raise
            self.assertTrue(stub.close_connection)

    def test_other_errors_still_surface(self):
        with mock.patch.object(mod.BaseHTTPRequestHandler, "handle", side_effect=ValueError("bug")):
            with self.assertRaises(ValueError):
                mod.Handler.handle(mock.Mock())


class SessionRowTests(unittest.TestCase):
    """The landing page's session rows: what the meta line says, in which
    order, and the per-row names assistive tech and Voice Control get."""

    def _page(self, sess):
        with mock.patch.object(mod, "sessions", return_value=sess), \
                mock.patch.object(mod, "load_tools", return_value=([], None)), \
                mock.patch.object(mod, "load_shortcuts", return_value=[]), \
                mock.patch.object(mod, "update_available", return_value=False):
            return mod.render()

    def test_age_is_labelled_as_uptime_in_one_unit(self):
        now = 1_000_000
        self.assertEqual(mod.session_age(now - 5, now), "up <1m")
        self.assertEqual(mod.session_age(now - 600, now), "up 10m")
        self.assertEqual(mod.session_age(now - 3 * 3600 - 59, now), "up 3h")
        self.assertEqual(mod.session_age(now - 2 * 86400, now), "up 2d")
        self.assertEqual(mod.session_age(0, now), "")
        self.assertEqual(mod.session_age(now + 30, now), "up <1m")   # clock skew

    def test_short_facts_come_first_and_attached_is_a_word(self):
        now = int(time.time())
        page = self._page([{"name": "main", "windows": 3, "attached": True,
                            "created": now - 120, "cmd": "bash", "path": "~/projects/game"}])
        facts = page.split('class="facts">', 1)[1].split("</span><span", 1)[0]
        self.assertTrue(facts.startswith('<span aria-hidden="true"><b class="att">attached</b>'), facts)
        self.assertIn("3 windows &middot; up 2m", facts)
        where = page.split('class="where">', 1)[1].split("</span>", 1)[0]
        self.assertIn("bash", where)
        self.assertIn("~/projects/game", where)
        self.assertNotIn(" ago", page.split("<h2", 1)[1].split("Agent servers", 1)[0])
        self.assertIn('role="img" aria-label="attached"', page)

    def test_a_single_window_is_not_spelled_out(self):
        now = int(time.time())
        one = {"name": "x", "windows": 1, "attached": False, "created": now - 60,
               "cmd": "bash", "path": "~"}
        self.assertEqual(mod.session_facts(one), "up 1m")
        self.assertEqual(mod.session_facts(dict(one, windows=2)), "2 windows &middot; up 1m")
        self.assertIn("attached</b> &middot; </span>up 1m", mod.session_facts(dict(one, attached=True)))
        self.assertEqual(mod.session_facts(dict(one, attached=True, created=0)),
                         '<span aria-hidden="true"><b class="att">attached</b></span>')

    def test_row_controls_are_named_for_their_row_and_escaped(self):
        page = self._page([{"name": 'a"b<c>', "windows": 1, "attached": False,
                            "created": 0, "cmd": "bash", "path": "~"}])
        self.assertIn('aria-label="More actions for a&quot;b&lt;c&gt;"', page)
        self.assertIn('aria-label="Open a&quot;b&lt;c&gt;"', page)
        self.assertIn('title="a&quot;b&lt;c&gt;"', page)
        self.assertIn('data-session="a&quot;b&lt;c&gt;"', page)
        self.assertIn('aria-label="not attached"', page)
        self.assertNotIn('a"b<c>', page)


if __name__ == "__main__":
    unittest.main(verbosity=2)
