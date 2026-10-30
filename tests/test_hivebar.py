import calendar
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(HERE, "..", "hivebar.30s.py")
spec = importlib.util.spec_from_file_location("hivebar", PLUGIN)
hivebar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hivebar)
HOME = hivebar.HOME


def proc(pid, ppid="1", args="claude", cwd="/tmp/x", age=60, cpu=0.0, tree_cpu=None):
    p = dict(pid=pid, ppid=ppid, args=args, exe=args.split()[0], cwd=cwd, age=age,
             cpu=cpu, mb=100.0, tty="ttys001", account="default", start=1000)
    if tree_cpu is not None:
        p["tree_cpu"] = tree_cpu
    return p


class ParsingTest(unittest.TestCase):
    def test_etime(self):
        self.assertEqual(hivebar.etime_secs("05:07"), 307)
        self.assertEqual(hivebar.etime_secs("02:00:00"), 7200)
        self.assertEqual(hivebar.etime_secs("3-01:02:03"), 3 * 86400 + 3723)

    def test_is_claude(self):
        self.assertTrue(hivebar.is_claude("claude"))
        self.assertTrue(hivebar.is_claude(f"{HOME}/.local/bin/claude"))
        self.assertTrue(hivebar.is_claude(f"{HOME}/.local/share/claude/versions/2.1.293"))
        self.assertFalse(hivebar.is_claude("/Applications/Claude.app/Contents/MacOS/Claude"))
        self.assertFalse(hivebar.is_claude("node"))

    def test_daemon_is_matched_by_subcommand_only(self):
        self.assertTrue(hivebar.is_daemon("claude daemon run --json-path x"))
        self.assertFalse(hivebar.is_daemon("claude restart the daemon"))

    def test_account_name(self):
        self.assertEqual(hivebar.account_name(None), "default")
        self.assertEqual(hivebar.account_name(f"{HOME}/.claude"), "default")
        self.assertEqual(hivebar.account_name(f"{HOME}/.claude-work/"), "work")
        self.assertEqual(hivebar.account_name("/opt/agents/acme"), "acme")

    def test_config_dir_from_env(self):
        line = "123 claude fix CLAUDE_CONFIG_DIR=/x/bogus HOME=/u CLAUDE_CONFIG_DIR=/u/My Stuff/.claude-w TERM=xterm"
        self.assertEqual(hivebar.config_dir_from_env(line), "/u/My Stuff/.claude-w")
        self.assertIsNone(hivebar.config_dir_from_env("123 claude HOME=/u"))

    def test_project_label(self):
        self.assertEqual(hivebar.project_label(f"{HOME}/Code/app"), "app")
        self.assertEqual(hivebar.project_label(f"{HOME}/Code/app/.claude/worktrees/fix-1"), "app ⎇ fix-1")
        self.assertEqual(hivebar.project_label(HOME), "~")
        self.assertEqual(hivebar.project_label("/"), "/")
        self.assertEqual(hivebar.project_label(""), "?")

    def test_menu_text_is_safe(self):
        for raw in ("a|b", "--scratch", "---", "x\ny"):
            out = hivebar.menu_text(raw)
            self.assertNotIn("|", out)
            self.assertNotIn("\n", out)
            self.assertFalse(out.startswith("-"), out)

    def test_bad_settings_fall_back(self):
        os.environ["HIVEBAR_TEST_NUM"] = "abc"
        self.assertEqual(hivebar.env_number("HIVEBAR_TEST_NUM", "24"), 24.0)


class ClassifyTest(unittest.TestCase):
    def test_kinds_and_staleness(self):
        day = 86400
        procs = {
            "10": proc("10", args="claude daemon run --json-path x"),
            "11": proc("11", args="claude", cwd="/private/tmp/cc-daemon-501/d1/spare"),
            "20": proc("20", args="claude --bg-pty-host /tmp/s", age=30 * day),
            "21": proc("21", ppid="20", args=f"{HOME}/.local/share/claude/versions/2.1.0 --session-id x",
                       age=30 * day),
            "30": proc("30", args="claude", age=2 * day, cpu=0.2),
            "31": proc("31", args="claude", age=2 * day, cpu=40.0),
            "32": proc("32", args="claude", age=600, cpu=0.0),
            "33": proc("33", args="claude", age=2 * day, cpu=0.0, tree_cpu=95.0),  # busy child
            "34": proc("34", args="claude", age=2 * day, cpu=0.0, cwd=""),         # lsof failed
        }
        hivebar.classify(procs, "2.2.0", stale_secs=day, idle_cpu=1.0)
        kinds = {pid: p["kind"] for pid, p in procs.items()}
        self.assertEqual(kinds["10"], "service")
        self.assertEqual(kinds["11"], "service")
        self.assertEqual(kinds["20"], "host")
        self.assertEqual(kinds["21"], "background")
        stale = sorted(pid for pid, p in procs.items() if p["stale"])
        self.assertEqual(stale, ["21", "30"])
        self.assertTrue(procs["21"]["outdated"])
        self.assertFalse(procs["30"]["outdated"])

    def test_level(self):
        self.assertIsNone(hivebar.level((4.0, 0, 0), 10, 60))
        self.assertEqual(hivebar.level((9.0, 0, 0), 10, 60), "orange")
        self.assertEqual(hivebar.level((13.0, 0, 0), 10, 60), "red")
        self.assertEqual(hivebar.level((1.0, 0, 0), 10, 10), "red")


def usage_line(msg_id, out, ts="2026-10-30T10:00:00.000Z"):
    return json.dumps({"type": "assistant", "timestamp": ts, "message": {"id": msg_id, "usage": {
        "input_tokens": 10, "cache_creation_input_tokens": 100,
        "cache_read_input_tokens": 99999, "output_tokens": out}}}) + "\n"


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "s.jsonl")
        self.cutoff = calendar.timegm((2026, 10, 1, 0, 0, 0))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def total(self, entry):
        return sum(entry["b"].values())

    def test_counts_repeats_once_and_skips_cache_reads(self):
        with open(self.path, "w") as f:
            f.write(usage_line("a", 5) + usage_line("a", 7) + '{"type":"user"}\n' + usage_line("b", 1))
        entry = hivebar.scan_usage(self.path, {}, self.cutoff)
        self.assertEqual(self.total(entry), (110 + 7) + (110 + 1))

    def test_incremental_and_partial_lines(self):
        with open(self.path, "w") as f:
            f.write(usage_line("a", 5) + usage_line("b", 5)[:20])  # second line half-written
        entry = hivebar.scan_usage(self.path, {}, self.cutoff)
        self.assertEqual(self.total(entry), 115)
        with open(self.path, "w") as f:
            f.write(usage_line("a", 5) + usage_line("b", 5))
        entry = hivebar.scan_usage(self.path, entry, self.cutoff)
        self.assertEqual(self.total(entry), 230)
        self.assertEqual(self.total(hivebar.scan_usage(self.path, entry, self.cutoff)), 230)

    def test_drops_old_entries(self):
        with open(self.path, "w") as f:
            f.write(usage_line("a", 5, ts="2026-09-01T00:00:00Z") + usage_line("b", 5))
        self.assertEqual(self.total(hivebar.scan_usage(self.path, {}, self.cutoff)), 115)

    def test_bad_input_never_raises(self):
        with open(self.path, "w") as f:
            f.write('{"type":"assistant","timestamp":"2026-10-30T10:00:00Z","message":'
                    '{"id":"x","usage":{"output_tokens":Infinity}}}\n' + usage_line("b", 5))
        self.assertEqual(self.total(hivebar.scan_usage(self.path, {}, self.cutoff)), 115)
        for junk in ({"ino": os.stat(self.path).st_ino, "off": 0}, {"b": {"x": "y"}}, "nope", None):
            self.assertEqual(self.total(hivebar.scan_usage(self.path, junk, self.cutoff)), 115)
        os.chmod(self.path, 0)
        self.assertIsNone(hivebar.scan_usage(self.path, {}, self.cutoff))
        self.assertIsNone(hivebar.scan_usage(os.path.join(self.tmp, "gone.jsonl"), {}, self.cutoff))

    def test_account_usage_round_trip(self):
        now = calendar.timegm((2026, 10, 30, 12, 0, 0))
        for acct, ts in (("work", "2026-10-30T10:00:00Z"), ("old", "2026-10-29T10:00:00Z")):
            os.makedirs(os.path.join(self.tmp, f".claude-{acct}", "projects", "p"))
            with open(os.path.join(self.tmp, f".claude-{acct}", "projects", "p", "s.jsonl"), "w") as f:
                f.write(usage_line("a", 5, ts=ts))
        cache = os.path.join(self.tmp, "cache", "usage.json")
        with mock.patch.object(hivebar, "HOME", self.tmp), mock.patch.object(hivebar, "USAGE_CACHE", cache):
            first = hivebar.account_usage(now)
            with open(cache, "w") as f:
                f.write("[1, 2")  # corrupt cache: rescan, don't crash
            self.assertEqual(hivebar.account_usage(now), first)
            self.assertEqual(hivebar.account_usage(now), first)
        self.assertEqual(first, {"work": (115, 115), "old": (0, 115)})

    def test_fmt_tokens(self):
        self.assertEqual(hivebar.fmt_tokens(950), "950")
        self.assertEqual(hivebar.fmt_tokens(12_300), "12k")
        self.assertEqual(hivebar.fmt_tokens(4_560_000), "4.6M")


class StopGuardTest(unittest.TestCase):
    def test_rejects_non_numeric_pid(self):
        self.assertIsNone(hivebar.same_session("1; rm -rf /", None))
        hivebar.stop("1; rm -rf /", 0)  # no-op, must not raise

    def test_rejects_non_claude_process(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.assertIsNone(hivebar.same_session(child.pid, None))
            hivebar.stop(str(child.pid), 0)
            self.assertIsNone(child.poll())  # still running
        finally:
            child.kill()
            child.wait()

    def test_rejects_exited_pid(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.assertIsNone(hivebar.same_session(child.pid, None))


if __name__ == "__main__":
    unittest.main()
