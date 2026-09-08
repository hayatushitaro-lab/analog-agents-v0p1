#!/usr/bin/env python3
"""
DSH/Codex PostToolUse equivalent for analog-agents.

In Claude Code the hooks/ folder fires automatically after Spectre runs and
after netlist edits. DSH/OpenCode/Codex sessions have no native PostToolUse
hooks, so agents call this tool explicitly at the same points.

Usage:
  python tools/post_tool_use.py after-sim \
      --psf-dir <dir> --spec <spec.yml> --sim-log <sim-log.yml> \
      [--block-dir <blocks/name>] [--netlist <name>] [--corner <corner>] [--level <L1|L2|L3>]

  python tools/post_tool_use.py after-netlist-edit \
      --file <path.scs> --iteration-log <iteration-log.yml>
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def _save_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def cmd_after_sim(args):
    psf_dir = Path(args.psf_dir).resolve()
    if not psf_dir.exists():
        print(f"[post-tool-use] ERROR: PSF dir not found: {psf_dir}")
        return 1

    # 1. Standard spec check -> sim-log.yml (same as Claude Code post-sim.sh)
    spec = Path(args.spec).resolve()
    sim_log = Path(args.sim_log).resolve()
    env = dict(os.environ)
    env.update({
        "ANALOG_NETLIST": args.netlist or psf_dir.name,
        "ANALOG_CORNER": args.corner or "tt_27c",
        "ANALOG_LEVEL": args.level or "L1",
        "PYTHONUTF8": "1",
    })
    checker = REPO_ROOT / "hooks" / "post_sim_check.py"
    print(f"[post-tool-use] running spec check: {checker} {psf_dir} {spec} {sim_log}")
    r = subprocess.run([sys.executable, str(checker), str(psf_dir), str(spec), str(sim_log)], env=env)
    if r.returncode != 0:
        print(f"[post-tool-use] WARNING: post_sim_check.py exited {r.returncode}")

    # 2. Designer's per-block custom hook (same as Claude Code post-sim.sh)
    block_dir = Path(args.block_dir).resolve() if args.block_dir else None
    hook = block_dir / "post-sim-hook.py" if block_dir else None
    if hook and hook.exists():
        print(f"[post-tool-use] running block hook: {hook}")
        subprocess.run(
            [sys.executable, str(hook), str(psf_dir), str(spec), str(sim_log), str(block_dir)],
            env=env,
        )
    else:
        print("[post-tool-use] no post-sim-hook.py found; skipping block hook")

    print(f"[post-tool-use] done; sim-log: {sim_log}")
    return 0


def _spectre_check(file: Path):
    """Run local spectre -check if available; otherwise return a clear note."""
    if shutil.which("spectre"):
        r = subprocess.run(["spectre", "-check", str(file)], capture_output=True, text=True)
        out = (r.stdout or "") + (r.stderr or "")
        if "error" in out.lower():
            return f"[analog-agents] Netlist syntax error in {file.name}:\n{out[:500]}"
        return f"[analog-agents] Netlist syntax check passed: {file.name}"
    return (
        f"[analog-agents] Netlist written: {file.name}. "
        "No local spectre; run syntax validation with the spectre skill or remote spectre -check before simulating."
    )


def _param_lines(file: Path) -> list:
    """Return parameter declaration lines (parameters / .param) from a netlist."""
    if not file.exists():
        return []
    out = []
    for line in file.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\s*(parameters\s+|\.param\s+)", line):
            out.append(line.strip())
    return out


def _git_param_diff(file: Path):
    """Return (old_params, new_params) from git diff when available."""
    try:
        r = subprocess.run(
            ["git", "-C", str(file.parent), "diff", "HEAD", "--", file.name],
            capture_output=True, text=True, timeout=20,
        )
        diff = r.stdout or ""
    except Exception:
        diff = ""

    old = []
    new = []
    for line in diff.splitlines():
        if re.match(r"^\+\+\+", line) or re.match(r"^---", line):
            continue
        if re.match(r"^\+", line) and re.search(r"(parameters\s+|\.param\s+)", line):
            new.append(line[1:].strip())
        elif re.match(r"^-", line) and re.search(r"(parameters\s+|\.param\s+)", line):
            old.append(line[1:].strip())
    return old, new


def cmd_after_netlist_edit(args):
    file = Path(args.file).resolve()
    if not file.exists():
        print(f"[post-tool-use] ERROR: file not found: {file}")
        return 1

    log_path = Path(args.iteration_log).resolve()
    syntax_msg = _spectre_check(file)
    print(syntax_msg)

    old, new = _git_param_diff(file)
    if not old and not new:
        # File may be untracked; record current param lines as additions.
        new = _param_lines(file)

    block = file.parent.name
    entry = {
        "timestamp": _ts(),
        "file": file.name,
        "block": block,
        "param_removed": old,
        "param_added": new,
    }

    data = _load_yaml(log_path)
    edits = data.setdefault("netlist_edits", [])
    if not isinstance(edits, list):
        edits = []
        data["netlist_edits"] = edits
    edits.append(entry)
    _save_yaml(log_path, data)

    print(f"[post-tool-use] netlist edit recorded to {log_path}: {file.name} (block={block})")
    return 0


def main():
    parser = argparse.ArgumentParser(description="DSH/Codex PostToolUse equivalent for analog-agents")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sim = sub.add_parser("after-sim", help="Run after every Spectre simulation")
    p_sim.add_argument("--psf-dir", required=True)
    p_sim.add_argument("--spec", required=True)
    p_sim.add_argument("--sim-log", required=True)
    p_sim.add_argument("--block-dir", default="")
    p_sim.add_argument("--netlist", default="")
    p_sim.add_argument("--corner", default="tt_27c")
    p_sim.add_argument("--level", default="L1")
    p_sim.set_defaults(func=cmd_after_sim)

    p_edit = sub.add_parser("after-netlist-edit", help="Run after every .scs/.sp/.net edit")
    p_edit.add_argument("--file", required=True)
    p_edit.add_argument("--iteration-log", required=True)
    p_edit.set_defaults(func=cmd_after_netlist_edit)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
