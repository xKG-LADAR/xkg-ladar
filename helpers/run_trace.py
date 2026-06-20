#!/usr/bin/env python3
"""Run a BugsInPy checkout test and capture the pysnooper log.

Assumes the test method is already decorated with @pysnooper.snoop().

Usage:
  python3 run_trace.py --workdir /path/to/checkout
"""

from pathlib import Path
import argparse
import subprocess
import shutil


import re


def _normalize_test_cmd(cmd: str) -> str:
    """Rewrite test commands for compatibility with the current Python.

    - 'tox <args>'       -> 'python -m pytest <args>'  (tox is broken on 3.12)
    - 'py.test <args>'   -> 'python -m pytest <args>'
    - 'pytest <args>'    -> 'python -m pytest <args>'

    Also adds '-o addopts=' to clear any coverage/plugin flags from setup.cfg
    that would fail without pytest-cov installed.
    """
    cmd = cmd.strip()
    # tox path/to/test.py::func  ->  python -m pytest path/to/test.py::func
    m = re.match(r"tox\s+(.*)", cmd)
    if m:
        return f"python -m pytest -o addopts= {m.group(1)}"
    # py.test / pytest  ->  python -m pytest (ensures correct interpreter)
    m = re.match(r"(?:py\.test|pytest)\s+(.*)", cmd)
    if m:
        return f"python -m pytest -o addopts= {m.group(1)}"
    return cmd


def read_test_command(workdir: Path) -> str:
    run_file = workdir / "bugsinpy_run_test.sh"
    if not run_file.exists():
        raise FileNotFoundError(f"{run_file} not found")
    cmds = [l.strip() for l in run_file.read_text().splitlines() if l.strip()]
    if not cmds:
        raise ValueError("No commands found in bugsinpy_run_test.sh")
    raw = cmds[0]
    normalized = _normalize_test_cmd(raw)
    if normalized != raw:
        print(f"  Rewriting test cmd: '{raw}' -> '{normalized}'")
    return normalized


def main():
    ap = argparse.ArgumentParser(description="Run a BugsInPy test (already decorated with @pysnooper.snoop) and print output.")
    ap.add_argument("--workdir", required=True, type=Path, help="Project checkout directory (contains bugsinpy_run_test.sh)")
    ap.add_argument("--save-dir", type=Path, default=Path("./fix_suggestions"), help="Directory to clear before running (default: ./fix_suggestions)")
    args = ap.parse_args()

    workdir = args.workdir.resolve()

    # Clear fix_suggestions directory
    save_dir = args.save_dir
    if save_dir.exists():
        shutil.rmtree(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    print(f"Cleared: {save_dir}")

    test_cmd = read_test_command(workdir)
    print(f"Running: {test_cmd}")
    print(f"Workdir: {workdir}")

    # Set PYTHONPATH from compile step (saved by compile_project)
    import os
    env = os.environ.copy()
    pythonpath_file = workdir / "bugsinpy_pythonpath.txt"
    if pythonpath_file.exists():
        extra = pythonpath_file.read_text().strip()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{extra}:{existing}" if existing else extra
        print(f"PYTHONPATH: {env['PYTHONPATH']}")

    proc = subprocess.run(
        test_cmd,
        shell=True,
        cwd=str(workdir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = proc.stdout.decode("utf-8", errors="ignore")
    print(output)
    print(f"\nExit code: {proc.returncode}")


if __name__ == "__main__":
    main()
