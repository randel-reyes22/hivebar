#!/usr/bin/env python3
# <swiftbar.title>Hivebar</swiftbar.title>
# <swiftbar.version>v0.1.0</swiftbar.version>
# <swiftbar.author>Gino Cortez</swiftbar.author>
# <swiftbar.desc>Claude Code sessions across accounts, Herdr agents, and system load in your menu bar.</swiftbar.desc>
# <swiftbar.abouturl>https://github.com/steamboy/hivebar</swiftbar.abouturl>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
# <swiftbar.environment>[HIVEBAR_STALE_HOURS=24, HIVEBAR_IDLE_CPU=1.0]</swiftbar.environment>
"""Hivebar: a SwiftBar plugin to monitor and stop Claude Code sessions.

Run with no arguments to print the menu. Actions (invoked from the menu):
  stop <pid> <start>      SIGTERM one session, if it is still that same session
  reveal <pid> <start>    open the session's folder in Finder
  stop-idle               confirm, then SIGTERM idle sessions older than HIVEBAR_STALE_HOURS
  stop-account <name>     confirm, then SIGTERM every session in one account

Reads local process information (ps, lsof, sysctl) and token counts from local
transcripts. No network access.
"""
import calendar
import glob
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
SELF = os.path.abspath(__file__)
# SwiftBar runs plugins with a minimal PATH, so also look in the usual install spots.
SEARCH_PATH = os.pathsep.join([os.environ.get("PATH", ""), os.path.join(HOME, ".local/bin"),
                               "/opt/homebrew/bin", "/usr/local/bin"])
# A process counts as the same session if its start time matches within this many seconds.
START_TOLERANCE = 3
SAFE_NAME = re.compile(r"^[\w.@+-]+$")
# Token usage is summed from transcripts into 10-minute buckets and cached between refreshes.
USAGE_CACHE = os.path.join(HOME, "Library/Caches/hivebar/usage.json")
USAGE_WINDOW = 7 * 86400
USAGE_BUCKET = 600
USAGE_CACHE_VERSION = 1
# Plan limits (5-hour and weekly %) as Claude Code hands them to its status line; see `statusline`.
LIMITS_DIR = os.path.join(HOME, "Library/Caches/hivebar/limits")
STATUSLINE_TIMEOUT = 30


def env_number(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


# Demo mode shows made-up data for screenshots; every action in it does nothing.
DEMO = os.environ.get("HIVEBAR_DEMO") == "1"
IDLE_CPU = env_number("HIVEBAR_IDLE_CPU", "1.0")
STALE_SECS = int(env_number("HIVEBAR_STALE_HOURS", "24") * 3600)

# Menu-bar icon: an asterisk in a hexagon, as 36x36 @2x PNGs (regenerate with tools/make_icons.swift).
# "template" lets macOS tint it for light/dark menu bars; the solid colored ones flag load.
ICONS = {
    "template": "iVBORw0KGgoAAAANSUhEUgAAACQAAAAkCAYAAADhAJiYAAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAACQAAAAAQAAAJAAAAABAAKgAgAEAAAAAQAAACSgAwAEAAAAAQAAACQAAAAAQCQK+gAAAAlwSFlzAAAWJQAAFiUBSVIk8AAAA/FJREFUWAndl1mIjlEYx+17KHuSJLJdjDRZI0JyQyKREuXChfWKIinLhWIioZAihVxIydyQJVvKkmQpY82+y779fnqPzrwz833vN8248K9f71mfc87zPud5v69Onf9M/TjPDiiD27ABusI/V2dW3Aof4VeKN9RXQWuodbVghaXwEtIbSdcfMWYONIAaVz0sTocy+Anx4m+pH4SjkPaYY6/COKgxjcDSOfgB8UY+U98N3SCoiIIb+wbxWOu2219t9WKmJ/8KsfHv1E/CQKhK4+nQM2lv6sFt0Akyqz0j18N7iDei8ZswCbKoEYOMIWMptmPZGDQWm0FOzaD3AaQNPKVtITSBQuVtWwPGWmzXA16HsVCpptCaPs0H2swteq0q6bHDUAIGf1XqTsceMPbijen1IVBB+2gJgWuclIJxlE9nGeBpP0GHfIPpd/HzENb6QnkTVNAxWsLOz1DW1Vn0mEFhXpYDaNMMfy2Z52H2wx/FSSt292t63yRj4kcxlcHgLbucdHgLg54lBQ8zGXw9e8FFYz2k4qUJqh8K8YZCW65nCZ094S5sg51gsCq95CEGwBIYCr76u3AaMqnQDemhhtAGlkMnMHaUXpgI88HNBNv9Kdfahm5jXA+5WBdYDGZhVRfWgrfJVxA85pzMiuMmy6RVDLoIvn8XNFbagtJWj+Rp7NwDX6kXJLOCW7NOKGWguWkMmLc6gp4JsuxmToBp5Cy8g8wq1EMGqa/IZ/rmhEX1XBgXXmfoy/ss1EOjsbgAiqB5Yt0NBC9Z9vMyCow1vbQOMnupUA+twLh5qCU414VegdJjZeCmmoLBPRdy/Sqgu7wK3VBvpnvtXfQJbAQ3oWxbBhfAz4K2TQ/OyaxCN3QJy2bxq7AaVkIjUNraB4vgCDyHx3AFMqvQGHKxYeAtOp+s0ip5GkemgXMwG6aCSfMUZFa8IV0e5I95fzx9DA3J05ySziuNozH+TDGmXsDmqD1dbEeD9oP+3tj4lWkobMrA3QF+GvLpQTLAK/4232D6/UXgZvsmY00RHqCCZtHi19pNBRy4FOLTUC2nadRKYQvEByw3iIreWw8m1mDfZxmYaCvVPFrdRDxBd94BF861IN2Vyryk3acQ27V8H4y1nDJ/7AE/AbEBr7KfguGQVRMYeAM8VGxLL5WAXsusQYz0hviOY2NfqB8AM3FVKqbjOKTn+mPuEBhH1ZKvaDLcgvQp/eL7WWgLQV0p7AKve3wIvXsRRkKNyDgwB6WD3kWNDTP2djBpxhvxEPdgJlQn/piWWx3odvH0TYk3EcqmkRXQAmpdfVjBWDAmwgbC09dlDusC/1wjWPEo+NfYb5ffsv7w/+g3ixVGgDdPVGoAAAAASUVORK5CYII=",
    "orange": "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",
    "red": "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",
}


def run(cmd, timeout=5):
    # LC_ALL=C keeps ps from printing decimal commas (2,3) in other locales.
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "LC_ALL": "C"}).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def which(name):
    return shutil.which(name, path=SEARCH_PATH)


def is_claude(exe):
    """True for the Claude Code CLI binary, however it was launched."""
    return (os.path.basename(exe) == "claude"
            or "/.local/share/claude/versions/" in exe)


def is_daemon(args):
    return args.split()[1:2] == ["daemon"]


def is_service(args, cwd):
    """The background daemon and its pre-started spare workers, not user sessions."""
    return is_daemon(args) or "/cc-daemon-" in cwd


def etime_secs(s):
    """Parse ps etime ([[dd-]hh:]mm:ss) into seconds."""
    days, _, rest = s.rpartition("-")
    parts = [int(p) for p in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, sec = parts
    return (int(days) if days else 0) * 86400 + h * 3600 + m * 60 + sec


def fmt_age(secs):
    if secs >= 86400:
        return f"{secs // 86400}d"
    if secs >= 3600:
        return f"{secs // 3600}h"
    return f"{secs // 60}m"


def fmt_mb(mb):
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"


def short_path(p):
    return "~" + p[len(HOME):] if p and p.startswith(HOME) else (p or "?")


def project_label(cwd):
    if not cwd:
        return "?"
    if "/.claude/worktrees/" in cwd:
        repo, wt = cwd.split("/.claude/worktrees/", 1)
        return f"{os.path.basename(repo)} ⎇ {wt}"
    if cwd == HOME:
        return "~"
    return os.path.basename(cwd.rstrip("/")) or cwd


def account_name(config_dir):
    """~/.claude -> default, ~/.claude-work -> work, anything else -> its folder name."""
    name = os.path.basename((config_dir or os.path.join(HOME, ".claude")).rstrip("/"))
    if name == ".claude":
        return "default"
    return name[len(".claude-"):] if name.startswith(".claude-") else name.lstrip(".")


def config_dir_from_env(line):
    """Last CLAUDE_CONFIG_DIR=... in a `ps eww` line; values may contain spaces."""
    found = re.findall(r"CLAUDE_CONFIG_DIR=(.*?)(?= [A-Za-z_][A-Za-z0-9_]*=|$)", line)
    return found[-1] if found else None


def menu_text(s):
    """Make free text safe for a SwiftBar line: '|' splits params, leading '-' sets menu depth."""
    s = str(s).replace("|", "¦").replace("\r", " ").replace("\n", " ")
    return re.sub(r"^-+", lambda m: "‐" * len(m.group()), s)


def current_version():
    exe = which("claude")
    real = os.path.realpath(exe) if exe else ""
    m = re.search(r"/versions/([\w.]+)$", real)
    return m.group(1) if m else ""


def classify(procs, cur_version, stale_secs=STALE_SECS, idle_cpu=IDLE_CPU):
    """Fill in kind/version/idle/stale for each process dict (keyed by pid)."""
    for p in procs.values():
        if is_service(p["args"], p["cwd"]):
            p["kind"] = "service"
        elif "--bg-pty-host" in p["args"]:
            p["kind"] = "host"
    for p in procs.values():
        if "kind" not in p:
            parent = procs.get(p["ppid"], {})
            p["kind"] = "background" if parent.get("kind") == "host" else "interactive"
        m = re.search(r"/versions/([\w.]+)$", p["exe"])
        p["version"] = m.group(1) if m else ""
        p["outdated"] = bool(p["version"] and cur_version and p["version"] != cur_version)
        # Count CPU used by child processes too (a long test run means the session is busy).
        p["idle"] = p.get("tree_cpu", p["cpu"]) < idle_cpu
        # An unknown cwd could hide a daemon spare worker, so never call it stale.
        p["stale"] = (p["idle"] and p["age"] > stale_secs and bool(p["cwd"])
                      and p["kind"] in ("interactive", "background"))
    return procs


def collect_sessions():
    now = time.time()
    uid = str(os.getuid())
    table, procs = {}, {}
    for line in run(["/bin/ps", "-Ao", "pid=,ppid=,uid=,etime=,rss=,pcpu=,tty=,args="]).splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        pid, ppid, puid, et, rss, cpu, tty, args = parts
        try:
            cpu, age, mb = float(cpu.replace(",", ".")), etime_secs(et), int(rss) / 1024
        except ValueError:
            continue
        table[pid] = (ppid, cpu)
        if puid == uid and is_claude(args.split()[0]):
            procs[pid] = dict(pid=pid, ppid=ppid, age=age, start=int(now - age), mb=mb, cpu=cpu,
                              tty=tty, args=args, exe=args.split()[0], account="default", cwd="")
    if not procs:
        return []

    children = {}
    for pid, (ppid, _) in table.items():
        children.setdefault(ppid, []).append(pid)

    def tree_cpu(pid, depth=0):
        if depth > 20:
            return 0.0
        return table[pid][1] + sum(tree_cpu(c, depth + 1) for c in children.get(pid, []))

    for p in procs.values():
        p["tree_cpu"] = tree_cpu(p["pid"])

    ids = ",".join(procs)
    # Each account is a separate CLAUDE_CONFIG_DIR, visible in the process environment.
    for line in run(["/bin/ps", "eww", "-o", "pid=,command=", "-p", ids]).splitlines():
        pid = line.split(None, 1)[0]
        if pid in procs:
            procs[pid]["account"] = account_name(config_dir_from_env(line))

    pid = None
    for line in run(["/usr/sbin/lsof", "-a", "-d", "cwd", "-Fpn", "-p", ids]).splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("n") and pid in procs:
            procs[pid]["cwd"] = line[1:]

    return list(classify(procs, current_version()).values())


def system_stats():
    load = os.getloadavg()
    cores = os.cpu_count() or 1
    swap_used = 0.0
    m = re.search(r"used = ([\d.]+)M", run(["/usr/sbin/sysctl", "-n", "vm.swapusage"]))
    if m:
        swap_used = float(m.group(1)) / 1024
    free_pct = None
    m = re.search(r"free percentage: (\d+)%", run(["/usr/bin/memory_pressure"], timeout=8))
    if m:
        free_pct = int(m.group(1))
    return load, cores, swap_used, free_pct


def herdr_agents():
    """Agents per running Herdr session; empty when Herdr isn't installed."""
    herdr = which("herdr")
    if not herdr:
        return herdr, []
    out = []
    for line in run([herdr, "session", "list"]).splitlines()[1:]:
        cols = line.split()
        if len(cols) < 2 or cols[1] != "running":
            continue
        try:
            agents = json.loads(run([herdr, "--session", cols[0], "agent", "list"]))["result"]["agents"]
            agents = [a for a in agents if isinstance(a, dict)]
        except (ValueError, KeyError, TypeError):
            agents = []
        out.append((cols[0], agents))
    return herdr, out


def config_dirs():
    """~/.claude and every ~/.claude-* that has transcripts."""
    dirs = [os.path.join(HOME, ".claude")] + sorted(glob.glob(os.path.join(HOME, ".claude-*")))
    return [d for d in dirs if os.path.isdir(os.path.join(d, "projects"))]


def usage_entry(line):
    """(epoch, message id, tokens) for a transcript line with API usage, else None.
    Tokens are input + cache writes + output; cache reads are left out (cheap, and they dominate)."""
    if b'"output_tokens"' not in line:
        return None
    try:
        d = json.loads(line)
        u = d["message"]["usage"]
        epoch = calendar.timegm(time.strptime(d["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"))
        tokens = sum(int(u.get(k) or 0) for k in
                     ("input_tokens", "cache_creation_input_tokens", "output_tokens"))
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return None
    return epoch, d["message"].get("id"), tokens


def scan_usage(path, entry, cutoff):
    """Read only the lines appended since the last scan; transcripts are append-only.
    Returns the updated cache entry, or None if the file can't be read."""
    try:
        st = os.stat(path)
        valid = (isinstance(entry, dict) and entry.get("ino") == st.st_ino
                 and isinstance(entry.get("off"), int) and 0 <= entry["off"] <= st.st_size
                 and isinstance(entry.get("b"), dict)
                 and (entry.get("last") is None or isinstance(entry["last"], list)))
        if not valid:
            entry = {"ino": st.st_ino, "off": 0, "last": None, "b": {}}
        buckets = {}
        for k, v in entry["b"].items():
            if str(k).isdigit() and isinstance(v, int) and int(k) + USAGE_BUCKET > cutoff:
                buckets[str(k)] = v
        entry["b"] = buckets
        last_id, last_tokens = (entry["last"] + [None, 0])[:2] if entry["last"] else (None, 0)
        with open(path, "rb") as f:
            f.seek(entry["off"])
            for line in f:  # line by line, so a huge transcript never sits in memory whole
                if not line.endswith(b"\n"):
                    break  # half-written last line: pick it up next time
                entry["off"] += len(line)
                u = usage_entry(line)
                if not u:
                    continue
                epoch, msg_id, tokens = u
                # A streamed reply repeats its message id on consecutive lines, sometimes with a
                # higher final count, so only the increase is added.
                if msg_id and msg_id == last_id:
                    add, last_tokens = max(0, tokens - last_tokens), max(tokens, last_tokens)
                else:
                    add, last_id, last_tokens = tokens, msg_id, tokens
                if add and epoch >= cutoff:
                    bucket = str(epoch - epoch % USAGE_BUCKET)
                    entry["b"][bucket] = entry["b"].get(bucket, 0) + add
        entry["last"] = [last_id, last_tokens]
        return entry
    except (OSError, ValueError, TypeError):
        return None


def account_usage(now=None):
    """{account: (tokens in the last 5h, tokens in the last 7 days)}, cached between refreshes."""
    now = int(now or time.time())
    cutoff = now - USAGE_WINDOW
    five_from = now - 5 * 3600
    try:
        with open(USAGE_CACHE) as f:
            cache = json.load(f)
        files = cache["files"] if cache.get("v") == USAGE_CACHE_VERSION else {}
        if not isinstance(files, dict):
            files = {}
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        files = {}
    fresh, totals = {}, {}
    for d in config_dirs():
        five = week = 0
        for p in glob.glob(os.path.join(d, "projects", "**", "*.jsonl"), recursive=True):
            try:
                if os.path.getmtime(p) < cutoff:
                    continue
            except OSError:
                continue
            entry = scan_usage(p, files.get(p), cutoff)
            if entry is None:
                continue
            fresh[p] = entry
            for bucket, tokens in entry["b"].items():
                week += tokens
                if int(bucket) + USAGE_BUCKET > five_from:  # include the bucket straddling 5h ago
                    five += tokens
        if week:
            name = account_name(d)
            f5, w = totals.get(name, (0, 0))
            totals[name] = (f5 + five, w + week)
    try:
        os.makedirs(os.path.dirname(USAGE_CACHE), exist_ok=True)
        tmp = f"{USAGE_CACHE}.{os.getpid()}.tmp"  # per-process, so overlapping refreshes can't mix
        with open(tmp, "w") as f:
            json.dump({"v": USAGE_CACHE_VERSION, "files": fresh}, f)
        os.replace(tmp, USAGE_CACHE)
    except OSError:
        pass
    return totals


def valid_window(w):
    return (isinstance(w, dict) and isinstance(w.get("used"), (int, float))
            and isinstance(w.get("resets_at"), int))


def read_limits(path):
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("updated"), int):
        return None
    return {k: v for k, v in d.items() if k == "updated" or valid_window(v)}


def save_limits(status, config_dir, now=None):
    """Keep the rate_limits part of a status-line payload, per account. Percentages only."""
    limits = status.get("rate_limits") if isinstance(status, dict) else None
    if not isinstance(limits, dict):
        return
    os.makedirs(LIMITS_DIR, exist_ok=True)
    path = os.path.join(LIMITS_DIR, f"{account_name(config_dir)}.json")
    # Several sessions in one account report; an idle one may still hold older numbers.
    # Usage never drops within a window, so keep the later window, or the higher % in the same one.
    keep = read_limits(path) or {}
    changed = False
    for window in ("five_hour", "seven_day"):
        w = limits.get(window)
        try:
            new = {"used": float(w["used_percentage"]), "resets_at": int(w["resets_at"])}
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        old = keep.get(window)
        if (not old or new["resets_at"] > old["resets_at"]
                or (new["resets_at"] == old["resets_at"] and new["used"] > old["used"])):
            keep[window] = new
            changed = True
        elif new["resets_at"] == old["resets_at"] and new["used"] == old["used"]:
            changed = True  # same numbers, freshly confirmed
    if not changed:
        return
    keep["updated"] = int(now or time.time())
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(keep, f)
    os.replace(tmp, path)


def load_limits():
    """{account: saved limits} from what each account's status line last reported."""
    out = {}
    for path in glob.glob(os.path.join(LIMITS_DIR, "*.json")):
        d = read_limits(path)
        if d and len(d) > 1:
            out[os.path.basename(path)[:-len(".json")]] = d
    return out


def statusline(then):
    """Status-line mode: save the plan limits, then hand the payload to the user's own status
    line (if any) and print its output. Never fails, so the status line can't break."""
    raw = sys.stdin.buffer.read()
    try:
        save_limits(json.loads(raw), os.environ.get("CLAUDE_CONFIG_DIR"))
    except Exception:
        pass
    if not then:
        return
    try:
        proc = subprocess.Popen(["/bin/sh", "-c", then], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, start_new_session=True)
    except OSError:
        return
    try:
        out, _ = proc.communicate(raw, timeout=STATUSLINE_TIMEOUT)
        sys.stdout.buffer.write(out)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # the whole group, e.g. node behind npx
        except OSError:
            pass
        proc.wait()


def wrapped_command(cmd):
    """(hivebar path, the user's original command) if cmd is a Hivebar wrapper, else None."""
    try:
        parts = shlex.split(cmd)
    except ValueError:
        return None
    if len(parts) >= 2 and parts[0].endswith(".py") and "hivebar" in parts[0] and parts[1] == "statusline":
        return parts[0], (parts[3] if len(parts) >= 4 and parts[2] == "--then" else "")
    return None


def write_settings(path, settings):
    """Write in place of a symlink's target, keeping the file's permissions."""
    path = os.path.realpath(path)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
        f.write("\n")
    if os.path.exists(path):
        shutil.copymode(path, tmp)
    else:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def setup_limits(undo=False):
    """Point every account's statusLine at Hivebar (wrapping any existing one), or undo that."""
    me = os.path.realpath(__file__)
    for d in config_dirs():
        acct, path = account_name(d), os.path.join(d, "settings.json")
        try:
            with open(path) as f:
                settings = json.load(f)
        except FileNotFoundError:
            settings = {}
        except (OSError, ValueError) as e:
            print(f"{acct}: skipped, can't read settings.json ({e})")
            continue
        if not isinstance(settings, dict):
            print(f"{acct}: skipped, settings.json isn't a JSON object")
            continue
        current = settings.get("statusLine")
        cmd = current.get("command", "") if isinstance(current, dict) else ""
        wrapped = wrapped_command(cmd) if isinstance(cmd, str) else None
        if undo:
            if wrapped is None:
                print(f"{acct}: not set up, nothing to undo")
                continue
            if wrapped[1]:
                settings["statusLine"] = {**current, "command": wrapped[1]}
            else:
                settings.pop("statusLine", None)
        else:
            if wrapped is not None:
                if wrapped[0] == me:
                    print(f"{acct}: already set up")
                    continue
                cmd = wrapped[1]  # set up from an old location: re-point it here
            elif current is not None and not (isinstance(current, dict) and current.get("type") == "command"
                                              and isinstance(cmd, str)):
                print(f"{acct}: skipped, statusLine isn't a command")
                continue
            new = f"{shlex.quote(me)} statusline" + (f" --then {shlex.quote(cmd)}" if cmd else "")
            settings["statusLine"] = {**(current or {"type": "command"}), "command": new}
            backup = path + ".bak-hivebar"
            if os.path.exists(path) and not os.path.exists(backup):
                shutil.copy2(path, backup)  # the pre-Hivebar original; never overwritten
        write_settings(path, settings)
        print(f"{acct}: {'restored' if undo else 'set up'} ({path})")
    if not undo:
        print("Percentages appear once each account's session makes its next request.")


def fmt_pct(window, now):
    """'42%', or '0%' once the window has reset or wasn't reported (Claude Code omits an
    unused window)."""
    if not window:
        return "0%"
    return "0%" if window["resets_at"] <= now else f"{window['used']:.0f}%"


def fmt_reset(epoch, now):
    t = time.localtime(epoch)
    if epoch - now < 86400:
        return time.strftime("%H:%M", t)
    return time.strftime("%a %H:%M", t)


def usage_lines(usage, limits, now):
    """Menu lines for plan % and token usage per account."""
    out = []
    if not (usage or limits):
        return out
    tooltip = " tooltip=Input + cache writes + output, from local transcripts. Cache reads excluded."

    def worst(acct):
        lim = limits.get(acct, {})
        return max([0] + [lim[w]["used"] for w in ("five_hour", "seven_day")
                          if lim.get(w) and lim[w]["resets_at"] > now])

    out.append(("Plan usage   5h · week" if limits else "Token usage   last 5h · 7 days") + " | disabled=true")
    for acct in sorted(set(usage) | set(limits), key=lambda a: (-worst(a), a)):
        five, week = usage.get(acct, (0, 0))
        tokens = f"{fmt_tokens(five)} · {fmt_tokens(week)}"
        lim = limits.get(acct)
        if not lim:
            # No plan limits reported (not set up yet, or an API-key account): tokens inline.
            out.append(f"{menu_text(acct)}   tokens {tokens} |{tooltip}")
            continue
        pct = worst(acct)
        color = " | color=red" if pct >= 90 else " | color=orange" if pct >= 75 else ""
        out.append(f"{menu_text(acct)}   5h {fmt_pct(lim.get('five_hour'), now)} · "
                   f"week {fmt_pct(lim.get('seven_day'), now)}{color}")
        for key, label in (("five_hour", "5-hour"), ("seven_day", "Weekly")):
            w = lim.get(key)
            if w and w["resets_at"] > now:
                out.append(f"--{label} limit resets {fmt_reset(w['resets_at'], now)} | disabled=true")
        out.append(f"--Updated {fmt_age(int(now - lim['updated']))} ago (refreshes while a session is open)"
                   " | disabled=true")
        out.append(f"--Tokens: {fmt_tokens(five)} last 5h · {fmt_tokens(week)} last 7 days | disabled=true")
    if not limits:
        out.append("Show plan % (5h and weekly limits)…")
        out.append("--Run once: ./hivebar.30s.py setup-limits | disabled=true")
    out.append("---")
    return out


def fmt_tokens(n):
    if n >= 1e9:
        return f"{n / 1e9:.1f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.0f}k"
    return str(n)


def same_session(pid, start):
    """The live process for pid, if it is still the session we showed; never the daemon or host."""
    if not str(pid).isdigit():
        return None
    line = run(["/bin/ps", "-o", "uid=,etime=,args=", "-p", str(pid)]).strip()
    parts = line.split(None, 2)
    if len(parts) < 3 or parts[0] != str(os.getuid()):
        return None
    try:
        started = time.time() - etime_secs(parts[1])
    except ValueError:
        return None
    args = parts[2]
    if not is_claude(args.split()[0]) or "--bg-pty-host" in args or is_daemon(args):
        return None
    if start is not None and abs(started - int(start)) > START_TOLERANCE:
        return None
    cwd = ""
    for out in run(["/usr/sbin/lsof", "-a", "-d", "cwd", "-Fn", "-p", str(pid)]).splitlines():
        if out.startswith("n"):
            cwd = out[1:]
    # Unknown cwd could be a daemon spare worker; refuse rather than guess.
    if not cwd or "/cc-daemon-" in cwd:
        return None
    return cwd


def stop(pid, start):
    if same_session(pid, start) is not None:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass


def reveal(pid, start):
    cwd = same_session(pid, start)
    if cwd:
        run(["/usr/bin/open", cwd])


def osa_quote(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def confirm_and_stop(targets, question, still_wanted=lambda p: True):
    """Ask once, then stop each target that is still the same session and still qualifies."""
    if not targets:
        return
    lines = "\n".join(f"{p['account']}: {project_label(p['cwd'])} ({fmt_age(p['age'])})" for p in targets)
    script = (f'display dialog "{osa_quote(question)}" & return & return & "{osa_quote(lines)}" '
              'buttons {"Cancel", "Stop"} default button "Cancel" with icon caution')
    if "Stop" not in run(["/usr/bin/osascript", "-e", script], timeout=120):
        return
    # Re-check after the dialog: a session may have exited or become busy while it was open.
    fresh = {p["pid"]: p for p in collect_sessions()}
    for t in targets:
        f = fresh.get(t["pid"])
        if f and abs(f["start"] - t["start"]) <= START_TOLERANCE and still_wanted(f):
            stop(f["pid"], f["start"])


def stop_idle():
    stale = [p for p in collect_sessions() if p["stale"]]
    confirm_and_stop(stale, f"Stop {len(stale)} idle Claude Code session(s)?", lambda p: p["stale"])


def stop_account(account):
    mine = [p for p in collect_sessions()
            if p["account"] == account and p["kind"] in ("interactive", "background")]
    confirm_and_stop(mine, f"Stop all {len(mine)} Claude Code session(s) in {account}?",
                     lambda p: p["account"] == account)


def level(load, cores, free_pct):
    ratio = load[0] / cores
    if ratio > 1.2 or (free_pct is not None and free_pct < 15):
        return "red"
    if ratio > 0.8 or (free_pct is not None and free_pct < 30):
        return "orange"
    return None


def action(label, *params):
    """A menu line that re-runs this script. Params must be fixed verbs, numbers or SAFE_NAME."""
    if DEMO:
        return f"{label} | refresh=false"
    ps = " ".join(f'param{i}="{v}"' for i, v in enumerate(params, 1))
    return f'{label} | bash="{SELF}" {ps} terminal=false refresh=true'


def demo_data():
    """Made-up sessions, limits and agents for screenshots (HIVEBAR_DEMO=1). Stop actions
    point at PIDs that don't exist, so the safety checks turn them into no-ops."""
    now, day = int(time.time()), 86400
    rows = [  # account, project folder, age, MB, CPU, kind, version
        ("work", "~/Code/web-app", 2 * 3600, 314, 3.0, "interactive", ""),
        ("work", "~/Code/api/.claude/worktrees/fix-login", 3 * 3600, 280, 12.0, "interactive", ""),
        ("work", "~/Code/billing", 26 * 3600, 245, 0.0, "background", ""),
        ("personal", "~/Code/blog", 40 * 60, 198, 0.4, "interactive", ""),
        ("personal", "~/Code/planner/.claude/worktrees/new-ui", 22 * day, 288, 0.0, "background", "2.1.293"),
    ]
    sessions = []
    for i, (acct, cwd, age, mb, cpu, kind, version) in enumerate(rows):
        sessions.append(dict(pid=str(999900 + i), ppid="1", start=now - age, age=age, mb=mb, cpu=cpu,
                             tree_cpu=cpu, tty="ttys00%d" % i, args="claude", exe="claude", account=acct,
                             cwd=cwd.replace("~", HOME, 1), kind=kind, version=version,
                             outdated=bool(version), idle=cpu < IDLE_CPU,
                             stale=cpu < IDLE_CPU and age > STALE_SECS))
    sessions.append(dict(sessions[0], pid="999990", kind="service", mb=120, account="work"))
    stats = ((7.2, 6.8, 6.1), 10, 4.2, 48)
    usage = {"work": (1_400_000, 26_100_000), "personal": (90_000, 3_200_000), "api-key": (0, 850_000)}
    limits = {"work": {"five_hour": {"used": 78.0, "resets_at": now + 2 * 3600},
                       "seven_day": {"used": 41.0, "resets_at": now + 3 * day}, "updated": now - 60},
              "personal": {"five_hour": {"used": 6.0, "resets_at": now + 4 * 3600},
                           "seven_day": {"used": 12.0, "resets_at": now + 5 * day}, "updated": now - 1800}}
    agents = [("work", [{"agent_status": "working", "cwd": HOME + "/Code/api", "terminal_title_stripped": "api"},
                        {"agent_status": "done", "cwd": HOME + "/Code/web-app"}])]
    return sessions, stats, usage, limits, agents


def render():
    demo = demo_data() if DEMO else None
    sessions = demo[0] if demo else collect_sessions()
    load, cores, swap, free_pct = demo[1] if demo else system_stats()
    color = level(load, cores, free_pct)
    visible = [s for s in sessions if s["kind"] in ("interactive", "background")]
    stale = [s for s in visible if s["stale"]]
    total_mb = sum(s["mb"] for s in sessions)

    title = f"{len(visible)}" + (f" · {len(stale)} idle" if stale else "")
    if color:
        # Text keeps the system color; a red title vanishes on warm wallpapers.
        print(f"{title} | image={ICONS[color]}")
    else:
        print(f"{title} | templateImage={ICONS['template']}")
    print("---")

    print(f"Load {load[0]:.1f} / {cores} cores  (5m {load[1]:.1f}, 15m {load[2]:.1f})"
          + (f" | color={color}" if color else ""))
    mem = f"{free_pct}% memory free · " if free_pct is not None else ""
    print(f"{mem}swap {swap:.1f} GB used")
    print("---")

    print(f"Claude Code sessions: {len(visible)} · {fmt_mb(total_mb)} total   (hold ⌥ to stop)")
    for acct in sorted({s["account"] for s in sessions}):
        mine = [s for s in visible if s["account"] == acct]
        services = [s for s in sessions if s["account"] == acct and s["kind"] == "service"]
        mb = sum(s["mb"] for s in sessions if s["account"] == acct)
        print(f"{menu_text(acct)} — {len(mine)} session(s) · {fmt_mb(mb)}")
        for s in sorted(mine, key=lambda s: s["age"]):
            tags = []
            if s["kind"] == "background":
                tags.append("bg")
            if s["stale"]:
                tags.append("idle")
            if s["outdated"]:
                tags.append(f"old v{s['version']}")
            tag = f"  [{', '.join(tags)}]" if tags else ""
            gray = " | color=gray" if s["stale"] else ""
            label = menu_text(f"{project_label(s['cwd'])} · {fmt_age(s['age'])}")
            print(f"--{label} · {fmt_mb(s['mb'])} · {s['tree_cpu']:.0f}%{tag}{gray}")
            print(action("----Stop session", "stop", s["pid"], s["start"]))
            print(action("----Reveal folder", "reveal", s["pid"], s["start"]).replace("refresh=true", "refresh=false"))
            print("-----")
            print(f"----{menu_text(short_path(s['cwd']))} | disabled=true")
            print(f"----PID {s['pid']} · {s['tty']} · {s['kind']} | disabled=true")
            # Holding Option swaps the row for a one-click Stop.
            print(action(f"--Stop {label}", "stop", s["pid"], s["start"]) + " alternate=true")
        if len(mine) > 1 and SAFE_NAME.match(acct):
            print("-----")
            print(action(f"--Stop all {len(mine)} {acct} sessions…", "stop-account", acct))
        if services:
            print(f"--background service ({len(services)} proc) · "
                  f"{fmt_mb(sum(s['mb'] for s in services))} | color=gray")
    print("---")

    try:
        usage = demo[2] if demo else account_usage()
    except Exception:  # usage is a nice-to-have; never let it blank the session list
        usage = {}
    try:
        for line in usage_lines(usage, demo[3] if demo else load_limits(), time.time()):
            print(line)
    except Exception:  # never let a malformed cache blank the session list
        pass

    herdr, workspaces = (None, demo[4]) if demo else herdr_agents()
    if workspaces:
        print("Herdr agents")
        for name, agents in workspaces:
            line = f"--{menu_text(name)} — {len(agents)} agent(s)"
            if herdr and SAFE_NAME.match(name):
                line += f' | bash="{herdr}" param1=session param2=attach param3="{name}" terminal=true'
            print(line)
            for a in agents:
                status = str(a.get("agent_status", "?"))
                icon = {"working": "⏳", "done": "✅", "idle": "💤"}.get(status, "🔔")
                where = project_label(str(a.get("cwd", "")))
                label = a.get("terminal_title_stripped") or where
                print(f"----{icon} {menu_text(label)} · {menu_text(status)} · {menu_text(where)} | disabled=true")
        print("---")

    hours = STALE_SECS // 3600
    if stale:
        print(action(f"Stop {len(stale)} idle session(s) older than {hours}h…", "stop-idle"))
    else:
        print(f"No idle sessions older than {hours}h | disabled=true")
    print('Open Activity Monitor | bash=/usr/bin/open param1=-a param2="Activity Monitor" terminal=false')
    print("Refresh | refresh=true")
    print("---")
    # SwiftBar's own submenu is hidden above, so this is the way out. Hivebar runs inside
    # SwiftBar, so quitting it quits SwiftBar; `open -a SwiftBar` brings it back.
    print("Quit Hivebar | bash=/usr/bin/pkill param1=-x param2=SwiftBar terminal=false")


if __name__ == "__main__":
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "stop" and len(args) >= 2:
        stop(args[0], args[1])
    elif cmd == "reveal" and len(args) >= 2:
        reveal(args[0], args[1])
    elif cmd == "stop-idle":
        stop_idle()
    elif cmd == "stop-account" and args:
        stop_account(args[0])
    elif cmd == "statusline":
        statusline(args[1] if len(args) >= 2 and args[0] == "--then" else "")
    elif cmd == "setup-limits":
        setup_limits(undo="--undo" in args)
    else:
        render()
