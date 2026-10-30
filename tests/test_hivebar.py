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


class LimitsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = [mock.patch.object(hivebar, "HOME", self.tmp),
                        mock.patch.object(hivebar, "LIMITS_DIR", os.path.join(self.tmp, "limits"))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def payload(self):
        return {"model": {"id": "x"}, "rate_limits": {
            "five_hour": {"used_percentage": 42.4, "resets_at": 2000},
            "seven_day": {"used_percentage": "junk", "resets_at": 3000}}}

    def test_save_and_load(self):
        hivebar.save_limits(self.payload(), os.path.join(self.tmp, ".claude-work"), now=1000)
        hivebar.save_limits({"rate_limits": None}, os.path.join(self.tmp, ".claude-free"), now=1000)
        self.assertEqual(hivebar.load_limits(),
                         {"work": {"five_hour": {"used": 42.4, "resets_at": 2000}, "updated": 1000}})
        self.assertEqual(hivebar.fmt_pct({"used": 42.4, "resets_at": 2000}, 1500), "42%")
        self.assertEqual(hivebar.fmt_pct({"used": 42.4, "resets_at": 2000}, 2500), "0%")

    def test_statusline_passes_through(self):
        env = {**os.environ, "CLAUDE_CONFIG_DIR": os.path.join(self.tmp, ".claude-work")}
        code = (f"import importlib.util,sys; s=importlib.util.spec_from_file_location('h',{PLUGIN!r});"
                f"h=importlib.util.module_from_spec(s); s.loader.exec_module(h);"
                f"h.LIMITS_DIR={os.path.join(self.tmp, 'limits')!r}; h.statusline(sys.argv[1])")
        out = subprocess.run([sys.executable, "-c", code, "tr a-z A-Z"], input=b"not json", env=env,
                             capture_output=True).stdout
        self.assertEqual(out, b"NOT JSON")  # broken payload: still runs the user's status line

    def test_setup_and_undo(self):
        work = os.path.join(self.tmp, ".claude-work")
        plain = os.path.join(self.tmp, ".claude-plain")
        for d in (work, plain):
            os.makedirs(os.path.join(d, "projects"))
        with open(os.path.join(work, "settings.json"), "w") as f:
            json.dump({"model": "x", "statusLine": {"type": "command", "command": "bash 'my line.sh'",
                                                    "padding": 1}}, f)
        with mock.patch("sys.stdout"):
            hivebar.setup_limits()
            hivebar.setup_limits()  # idempotent
        with open(os.path.join(work, "settings.json")) as f:
            cmd = json.load(f)["statusLine"]["command"]
        self.assertEqual(hivebar.wrapped_command(cmd)[1], "bash 'my line.sh'")
        with open(os.path.join(plain, "settings.json")) as f:
            self.assertEqual(hivebar.wrapped_command(json.load(f)["statusLine"]["command"])[1], "")
        with mock.patch("sys.stdout"):
            hivebar.setup_limits(undo=True)
        with open(os.path.join(work, "settings.json")) as f:
            self.assertEqual(json.load(f), {"model": "x", "statusLine": {
                "type": "command", "command": "bash 'my line.sh'", "padding": 1}})
        with open(os.path.join(plain, "settings.json")) as f:
            self.assertEqual(json.load(f), {})


    def test_stale_session_cannot_lower_numbers(self):
        work = os.path.join(self.tmp, ".claude-work")
        fresh = {"rate_limits": {"five_hour": {"used_percentage": 60, "resets_at": 2000}}}
        stale = {"rate_limits": {"five_hour": {"used_percentage": 20, "resets_at": 2000}}}
        hivebar.save_limits(fresh, work, now=1000)
        hivebar.save_limits(stale, work, now=1100)
        self.assertEqual(hivebar.load_limits()["work"],
                         {"five_hour": {"used": 60.0, "resets_at": 2000}, "updated": 1000})
        nxt = {"rate_limits": {"five_hour": {"used_percentage": 5, "resets_at": 9000}}}
        hivebar.save_limits(nxt, work, now=2100)  # new window: lower is right
        self.assertEqual(hivebar.load_limits()["work"]["five_hour"]["used"], 5.0)

    def test_malformed_cache_is_ignored(self):
        os.makedirs(hivebar.LIMITS_DIR)
        with open(os.path.join(hivebar.LIMITS_DIR, "x.json"), "w") as f:
            json.dump({"updated": 1, "five_hour": {"used": "a"}}, f)
        self.assertEqual(hivebar.load_limits(), {})

    def test_setup_keeps_symlink_mode_and_skips_non_objects(self):
        work = os.path.join(self.tmp, ".claude-work")
        odd = os.path.join(self.tmp, ".claude-odd")
        for d in (work, odd):
            os.makedirs(os.path.join(d, "projects"))
        real = os.path.join(self.tmp, "dotfiles.json")
        with open(real, "w") as f:
            json.dump({"name": "é"}, f)
        os.chmod(real, 0o600)
        os.symlink(real, os.path.join(work, "settings.json"))
        with open(os.path.join(odd, "settings.json"), "w") as f:
            f.write("[]")
        with mock.patch("sys.stdout"):
            hivebar.setup_limits()
            hivebar.setup_limits(undo=True)
        self.assertTrue(os.path.islink(os.path.join(work, "settings.json")))
        self.assertEqual(os.stat(real).st_mode & 0o777, 0o600)
        with open(real) as f:
            self.assertIn("é", f.read())
        with open(os.path.join(odd, "settings.json")) as f:
            self.assertEqual(f.read(), "[]")

    def test_usage_lines(self):
        now = 1000
        lines = hivebar.usage_lines({"api": (5, 9000)}, {}, now)
        self.assertIn("api   tokens 5 · 9k", lines[1])
        self.assertTrue(lines[0].endswith("disabled=true"))
        limits = {"work": {"five_hour": {"used": 92.0, "resets_at": 2000},
                           "seven_day": {"used": 99.0, "resets_at": 500}, "updated": 900}}
        lines = hivebar.usage_lines({"api": (5, 9000)}, limits, now)
        self.assertTrue(lines[1].startswith("work   5h 92% · week 0% | color=red"), lines[1])
        self.assertTrue(any(l.startswith("api   tokens") for l in lines))
        self.assertEqual(hivebar.usage_lines({}, {}, now), [])


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
