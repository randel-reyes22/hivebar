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


def env_number(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


IDLE_CPU = env_number("HIVEBAR_IDLE_CPU", "1.0")
STALE_SECS = int(env_number("HIVEBAR_STALE_HOURS", "24") * 3600)

# Menu-bar icon: an asterisk in a hexagon, as 36x36 @2x PNGs (regenerate with tools/make_icons.swift).
# "template" lets macOS tint it for light/dark menu bars; the colored ones flag load.
ICONS = {
    "template": "iVBORw0KGgoAAAANSUhEUgAAACQAAAAkCAYAAADhAJiYAAAAAXNSR0IArs4c6QAAAGxlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAACQAAAAAQAAAJAAAAABAAKgAgAEAAAAAQAAACSgAwAEAAAAAQAAACQAAAAAQCQK+gAAAAlwSFlzAAAWJQAAFiUBSVIk8AAABDFJREFUWAnd1mmIVlUYwHHXQUzNTM3dycEWKlcKRdySTPxg1LiFFkmhiBuEoH5RKCgVxC8uSBRZRoTLGIjBCCpZmAoqmuZSOGV7isukqaOj///wHr28zvvOueMY4gM/7nbuOec+97nnfevVu8ei/h3O5xHuH4lhqMBXKMVZ/K/RgtFew15U4nrGVbZfYxSa4K5HASMMxxZcQZhI9vYC19ajPxqgzsNX2wdrUI4wATPyDWZiLvYhmbFTHC/D46iz6EZPi/AnwkTcHsJkPIQQ7dlxYieQbOux571e62jDnT75MSQ7/5Xjd9AZueIJLpgZMxTuNXNm8HU0R3Q8QMsx+A7XEDo8w/6HeAYx0ZBG1pC1dBGhH2vPGrQWGyNv9OXqWlxC6MD9TRiCRkgbfm0vYQesudDvefZX4TFUGz05uwHhBrOzG2Nh1nKFGZuNcci3rrXi+hQcRnIMs94Vt8U0zvwNG1sn82Ad1RTv08CnPYhmNTXmuoMvxj9wrKN4FbfFfM5YeKb1PZjqmPiSRnZsRmMewD5d4VfA+yz86aiK5KLlvim36Fz6rZ3s6MSJwWifuGDBhvg3s+PD9IM1Wd1rPMd5GY57cx5pi3QqN7tAHsI67MJpGE7Mh+iIV/A8fLg5KENUpJ2Qy0EXDIDZWo2QIZeFp1GMSWgLYznK3ImJtBPaSqeuH4V4EdbCfzAKMAsj0A7l2Ie/EB1pJ7SKnq2vQSjEc/AjMPysfVUuiD/gAEpQhuhIO6Ej9PwJ9mM8/C/UFIarrr9r3+MzmM0TuIzouFndkXdU0s7PW+4rO8L1sM2+nvc4bYZc5kfDL6gQTug8WqACF9AVE/AkfGWliM5S2glNpnOLuQgW7V44CQvdz38LXoBfW0f4JfqajyMq0r4yJ2MG/NS3YREOwqjAUnwMv6zmGIgOiI60GdpIz31h4bowfguzY7SExW6mTsHX6sJ4EtGRdkIuct1xFGGghzOj+Y/An4xfsBK74YT80qIjOaHr3KUC2Hlj+BqS8TMHSoZtvc9oBhdKX+kO5Arvsa0Rxq06SNbQGc6oISbgLVgHNcUxGjjxn3CppsZcb4MpeDnTNoybOby1cdXdjDBj010Ka8Rs5YreXJiHiaifqxHnzcoY7ILLRRhnDfuWQbUxiLNOwp+DcIPrzKdw4HwDcrnasCzsdxPMYOjX/S/QC3mjFVdN6WGEm93+gYV4FLHxFA0/gK8l9OUKvgfjYNaiowst38VvCJ25daGbgdbIFS6IC3ASyXuPc/w2rKNaha+oBz7CWYTOfcqdKEb4cWW3ai16k62LZWjr1oVyCYpQJ2EdDIVF7+9SGMxP3NoYjzewHcn6K+f4czyL2tQft+UP1w4Hd9GrRJhY9tZlYCtGwnXtrkdbRrAWfkRyMk7yACbhQaSOO01jN0Yci2HwVfn6SvA77o+4AVdTMtvBwFHLAAAAAElFTkSuQmCC",
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
    ps = " ".join(f'param{i}="{v}"' for i, v in enumerate(params, 1))
    return f'{label} | bash="{SELF}" {ps} terminal=false refresh=true'


def render():
    sessions = collect_sessions()
    load, cores, swap, free_pct = system_stats()
    color = level(load, cores, free_pct)
    visible = [s for s in sessions if s["kind"] in ("interactive", "background")]
    stale = [s for s in visible if s["stale"]]
    total_mb = sum(s["mb"] for s in sessions)

    title = f"{len(visible)}" + (f" · {len(stale)} idle" if stale else "")
    if color:
        print(f"{title} | image={ICONS[color]} color={color}")
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
        usage = account_usage()
    except Exception:  # usage is a nice-to-have; never let it blank the session list
        usage = {}
    if usage:
        print("Token usage   last 5h · 7 days | disabled=true")
        for acct, (five, week) in sorted(usage.items(), key=lambda kv: -kv[1][1]):
            print(f"{menu_text(acct)}   {fmt_tokens(five)} · {fmt_tokens(week)}"
                  " | tooltip=Input + cache writes + output, from local transcripts. Cache reads excluded.")
        print("---")

    herdr, workspaces = herdr_agents()
    if workspaces:
        print("Herdr agents")
        for name, agents in workspaces:
            line = f"--{menu_text(name)} — {len(agents)} agent(s)"
            if SAFE_NAME.match(name):
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
    # SwiftBar's own submenu is hidden above, so keep a way to quit it (hold Option).
    print("Quit SwiftBar | bash=/usr/bin/pkill param1=-x param2=SwiftBar terminal=false alternate=true")


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
    else:
        render()
