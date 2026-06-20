#!/usr/bin/env python3
"""
Evaluate Claude Code (CLI) as a baseline bug-fixing agent on BugsInPy.

For each bug in each project:
1. Checkout the buggy version via BugsInPy
2. Apply Python 3.12 compatibility patches
3. Run Claude Code (--print mode) with a bug-fixing prompt in the workdir
4. Run the test and record pass/fail

Results are saved to:  ./fix_output/<project>/bug<bug_id>/claude_code_result.json
Combined:              ./fix_output/claude_code_evaluation.json

Usage:
    python3 run_claude_code.py                          # all projects
    python3 run_claude_code.py --project youtube-dl     # one project
    python3 run_claude_code.py --start 44               # skip first 43 global bugs
    python3 run_claude_code.py --skip-checkout          # reuse existing checkouts
    python3 run_claude_code.py --budget 2.0             # max USD per bug (default 1.5)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUGSINPY_DIR = (HERE / ".." / "BugsInPy").resolve()
BUGSINPY_CHECKOUT = BUGSINPY_DIR / "framework" / "bin" / "bugsinpy-checkout"
WORKSPACE = BUGSINPY_DIR / "workspace"

PROJECTS = [
    {"project": "youtube-dl",   "num_bugs": 43},
    {"project": "tornado",      "num_bugs": 16},
    {"project": "scrapy",       "num_bugs": 37},
    {"project": "sanic",        "num_bugs": 2},
    {"project": "cookiecutter", "num_bugs": 4},
    {"project": "ansible",      "num_bugs": 5},
    {"project": "fastapi",      "num_bugs": 4},
    {"project": "httpie",       "num_bugs": 4},
    {"project": "keras",        "num_bugs": 5},
    {"project": "luigi",        "num_bugs": 4},
    {"project": "matplotlib",   "num_bugs": 5},
    {"project": "pandas",       "num_bugs": 5},
    {"project": "spacy",        "num_bugs": 4},
    {"project": "thefuck",      "num_bugs": 4},
]

DEFAULT_BUDGET_USD = 1.5   # per bug
CLAUDE_MODEL = "claude-opus-4-5"  # use a capable model for autonomous fixing
KG_MIN_BYTES = 200  # trace_kg must be larger than this to be considered non-empty


def kg_has_content(project: str, bug_id: int) -> bool:
    """Return True if the trace_kg for this bug is non-trivial (> KG_MIN_BYTES)."""
    kg_path = HERE / "fix_output" / project / f"bug{bug_id}" / "trace_kg"
    return kg_path.exists() and kg_path.stat().st_size > KG_MIN_BYTES


CLAUDE_PROMPT_TEMPLATE = """\
You are fixing a bug in a Python project.

The test command below is currently FAILING because of a bug in the source code:

    {test_cmd}

Your task:
1. Run the test to see the failure
2. Identify the root cause in the source code
3. Fix the bug (edit source files only — do NOT modify test files)
4. Verify the test passes after your fix

Working directory: {workdir}
PYTHONPATH is already set. Run the test with: {test_cmd}

Important constraints:
- Fix only the source code bug; do not change or add tests
- Keep the fix minimal and correct
- When you are confident the test passes, stop
"""


def _shim_insert_point(lines: list[str]) -> int:
    """Return insertion index after docstrings/comments/encoding/future imports."""
    insert_at = 0
    in_docstring = False
    docstring_char = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not in_docstring:
            if stripped.startswith('"""') or stripped.startswith("'''"):
                docstring_char = stripped[:3]
                if stripped.count(docstring_char) >= 2 and len(stripped) > 3:
                    insert_at = idx + 1; continue
                in_docstring = True; insert_at = idx + 1; continue
            if stripped.startswith('#') or stripped == '':
                insert_at = idx + 1; continue
            if stripped.startswith('from __future__'):
                insert_at = idx + 1; continue
            break
        else:
            insert_at = idx + 1
            if docstring_char and stripped.endswith(docstring_char):
                in_docstring = False
            continue
    return insert_at


def patch_py312_compat(workdir: Path) -> int:
    """Fix Python 3.12 breaking changes. Returns count of files modified."""
    import re as _re
    _ABC_NAMES = (
        "Callable", "Iterator", "Iterable", "Generator",
        "MutableMapping", "MutableSequence", "MutableSet",
        "Mapping", "Sequence", "Set", "Awaitable", "Coroutine",
        "AsyncIterator", "AsyncIterable", "AsyncGenerator",
        "Hashable", "Sized", "Container", "Collection",
        "Reversible", "KeysView", "ItemsView", "ValuesView",
    )
    _ABC_PAT = _re.compile(r'(?<![a-zA-Z_.])collections\.(' + "|".join(_ABC_NAMES) + r')(?![a-zA-Z_])')
    _FROM_PAT = _re.compile(r'^([ \t]*)from collections import (.*?)$', _re.MULTILINE)

    modified = 0
    for py_file in workdir.rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        original = text
        text = _ABC_PAT.sub(r'collections.abc.\1', text)

        def _fix_from_import(m):
            indent = m.group(1)
            names_str = m.group(2).rstrip("\\").strip()
            names = [n.strip().rstrip("\\").strip() for n in names_str.split(",") if n.strip()]
            abc_names = [n for n in names if n in _ABC_NAMES]
            plain_names = [n for n in names if n not in _ABC_NAMES]
            lines = []
            if plain_names: lines.append(f"{indent}from collections import {', '.join(plain_names)}")
            if abc_names: lines.append(f"{indent}from collections.abc import {', '.join(abc_names)}")
            return "\n".join(lines) if lines else m.group(0)

        text = _FROM_PAT.sub(_fix_from_import, text)

        if 'backports.ssl_match_hostname' in text:
            text = text.replace('import backports.ssl_match_hostname', 'import ssl as _ssl_backport_shim')
            text = text.replace('ssl_match_hostname = backports.ssl_match_hostname.match_hostname',
                                'ssl_match_hostname = getattr(_ssl_backport_shim, "match_hostname", None)')
            text = text.replace('SSLCertificateError = backports.ssl_match_hostname.CertificateError',
                                'SSLCertificateError = getattr(_ssl_backport_shim, "SSLCertificateError", ssl.SSLError)')

        if 'from six.moves import' in text or 'six.moves.' in text:
            shim = (
                'import six as _six_shim, sys as _sys_shim, importlib as _il_shim; '
                '_sys_shim.modules.setdefault("six.moves", _six_shim.moves); '
                '[(lambda _k, _m: _sys_shim.modules.setdefault(_k, _il_shim.import_module(_m)))(f"six.moves.{_d.name}", _d.mod) '
                'for _d in type(_six_shim.moves).__dict__.values() '
                'if isinstance(_d, _six_shim.MovedModule) and hasattr(_d, "mod") '
                'and not _d.mod.startswith("six.") and not _sys_shim.modules.get(f"six.moves.{_d.name}")]; '
                '[_sys_shim.modules.setdefault("six.moves.urllib", _six_shim.Module_six_moves_urllib("six.moves.urllib")), '
                '_sys_shim.modules.setdefault("six.moves.urllib.parse", _six_shim.Module_six_moves_urllib_parse("six.moves.urllib.parse")), '
                '_sys_shim.modules.setdefault("six.moves.urllib.error", _six_shim.Module_six_moves_urllib_error("six.moves.urllib.error")), '
                '_sys_shim.modules.setdefault("six.moves.urllib.request", _six_shim.Module_six_moves_urllib_request("six.moves.urllib.request")), '
                '_sys_shim.modules.setdefault("six.moves.urllib.response", _six_shim.Module_six_moves_urllib_response("six.moves.urllib.response")), '
                '_sys_shim.modules.setdefault("six.moves.urllib.robotparser", _six_shim.Module_six_moves_urllib_robotparser("six.moves.urllib.robotparser"))]\n'
            )
            if '_sys_shim.modules.setdefault("six.moves"' not in text:
                lines_tmp = text.splitlines(keepends=True)
                lines_tmp.insert(_shim_insert_point(lines_tmp), shim)
                text = "".join(lines_tmp)

        if ('from imp import' in text or '\nimport imp\n' in text or text.startswith('import imp\n')) \
                and '_iss.modules.setdefault("imp"' not in text:
            imp_shim = (
                'import sys as _iss, types as _ist; '
                '_iss.modules.setdefault("imp", type(_ist)("imp")); '
                '_iss.modules["imp"].find_module = lambda n, p=None: (None, None, None); '
                '_iss.modules["imp"].load_module = lambda n, *a: _iss.modules.get(n) or __import__(n); '
                '_iss.modules["imp"].load_source = lambda n, p, f=None: _iss.modules.get(n) or __import__(n); '
                '_iss.modules["imp"].acquire_lock = lambda: None; _iss.modules["imp"].release_lock = lambda: None; '
                '_iss.modules["imp"].PY_SOURCE = 1; _iss.modules["imp"].C_EXTENSION = 3; _iss.modules["imp"].PKG_DIRECTORY = 5\n'
            )
            lines_tmp = text.splitlines(keepends=True)
            lines_tmp.insert(_shim_insert_point(lines_tmp), imp_shim)
            text = "".join(lines_tmp)

        if ('inspect.getargspec' in text or 'inspect.ArgSpec' in text) \
                and '_ins_compat.getargspec' not in text:
            argspec_shim = (
                'import inspect as _ins_compat, collections as _col_compat; '
                'setattr(_ins_compat, "getargspec", '
                'getattr(_ins_compat, "getargspec", '
                'lambda f: _col_compat.namedtuple("ArgSpec",["args","varargs","keywords","defaults"])'
                '(*_ins_compat.getfullargspec(f)[:4]))); '
                'setattr(_ins_compat, "ArgSpec", '
                'getattr(_ins_compat, "ArgSpec", '
                '_col_compat.namedtuple("ArgSpec",["args","varargs","keywords","defaults"])))\n'
            )
            lines_tmp = text.splitlines(keepends=True)
            lines_tmp.insert(_shim_insert_point(lines_tmp), argspec_shim)
            text = "".join(lines_tmp)

        # assertRaisesRegexp / assertRegexpMatches removed in Python 3.12
        text = text.replace('self.assertRaisesRegexp(', 'self.assertRaisesRegex(')
        text = text.replace('self.assertRegexpMatches(', 'self.assertRegex(')
        text = text.replace('self.assertNotRegexpMatches(', 'self.assertNotRegex(')

        if text != original:
            try:
                py_file.write_text(text, encoding="utf-8")
                modified += 1
            except Exception:
                pass

    return modified


def checkout_buggy(project: str, bug_id: int) -> bool:
    ret = subprocess.run(
        ["bash", str(BUGSINPY_CHECKOUT),
         "-p", project, "-i", str(bug_id), "-v", "0", "-w", str(WORKSPACE)],
        capture_output=True, text=True, timeout=120,
    )
    return ret.returncode == 0


def get_test_command(workdir: Path) -> str | None:
    run_file = workdir / "bugsinpy_run_test.sh"
    if not run_file.exists():
        return None
    cmds = [l.strip() for l in run_file.read_text().splitlines()
            if l.strip() and not l.strip().startswith('#')]
    if not cmds:
        return None
    cmd = cmds[0]
    m = re.match(r"tox\s+(.*)", cmd)
    if m:
        return f"python -m pytest -o addopts= {m.group(1)}"
    m = re.match(r"(?:py\.test|pytest)\s+(.*)", cmd)
    if m:
        return f"python -m pytest -o addopts= {m.group(1)}"
    return cmd


def build_pythonpath(workdir: Path) -> str:
    paths = []
    bug_info = workdir / "bugsinpy_bug.info"
    if bug_info.exists():
        for line in bug_info.read_text().splitlines():
            if "pythonpath" in line and "=" in line:
                _, _, val = line.partition("=")
                val = val.strip().strip('"')
                if val:
                    for p in val.split(";"):
                        p = p.strip()
                        if p:
                            full = (workdir.parent / p).resolve()
                            paths.append(str(full))
    for candidate in ["lib", "src", "."]:
        full = (workdir / candidate).resolve()
        if full.is_dir() and str(full) not in paths:
            paths.append(str(full))
    wd = str(workdir.resolve())
    if wd not in paths:
        paths.append(wd)
    return ":".join(paths)


def run_test(workdir: Path, test_cmd: str) -> tuple[bool, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = build_pythonpath(workdir)
    try:
        ret = subprocess.run(
            test_cmd, shell=True, cwd=str(workdir),
            capture_output=True, text=True, timeout=120, env=env,
        )
        return ret.returncode == 0, ret.stdout + "\n" + ret.stderr
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT (120s)"
    except Exception as e:
        return False, f"ERROR: {e}"


def run_claude_code(workdir: Path, test_cmd: str,
                    budget_usd: float, output_dir: Path) -> dict:
    """Run Claude Code in --print mode on the bug. Returns result dict."""
    prompt = CLAUDE_PROMPT_TEMPLATE.format(
        test_cmd=test_cmd,
        workdir=str(workdir),
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = build_pythonpath(workdir)

    claude_cmd = [
        "claude",
        "--print",
        "--dangerously-skip-permissions",
        "--output-format", "json",
        "--max-budget-usd", str(budget_usd),
        "--model", CLAUDE_MODEL,
        prompt,
    ]

    print(f"  Running Claude Code (budget=${budget_usd})...")
    try:
        ret = subprocess.run(
            claude_cmd,
            cwd=str(workdir),
            capture_output=True, text=True,
            timeout=600,   # 10 min max
            env=env,
        )
        raw_output = ret.stdout
        stderr_output = ret.stderr

        # Save raw Claude Code output
        (output_dir / "claude_code_output.txt").write_text(
            raw_output + "\n---STDERR---\n" + stderr_output
        )

        # Parse JSON output for cost/token info
        cost_usd = None
        try:
            data = json.loads(raw_output)
            cost_usd = data.get("cost_usd") or data.get("total_cost_usd")
        except Exception:
            pass

        return {
            "exit_code": ret.returncode,
            "cost_usd": cost_usd,
            "raw_output_len": len(raw_output),
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "cost_usd": None, "error": "claude timeout (600s)"}
    except Exception as e:
        return {"exit_code": -1, "cost_usd": None, "error": str(e)}


def evaluate_bug(project: str, bug_id: int,
                 skip_checkout: bool, budget_usd: float) -> dict:
    """Run Claude Code on one bug and return result dict."""
    workdir = WORKSPACE / project
    output_dir = HERE / "fix_output" / project / f"bug{bug_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "project": project,
        "bug_id": bug_id,
        "checkout_ok": False,
        "test_failed_before": False,
        "claude_exit_code": None,
        "cost_usd": None,
        "test_passed": False,
        "error": None,
    }

    # Skip if already passed
    existing = output_dir / "claude_code_result.json"
    if existing.exists():
        try:
            prev = json.loads(existing.read_text())
            if prev.get("test_passed"):
                print(f"  SKIP: already passed (cached result)")
                return prev
        except Exception:
            pass

    # Step 1: Checkout
    if not skip_checkout:
        print(f"  Checking out {project} bug {bug_id}...")
        if not checkout_buggy(project, bug_id):
            result["error"] = "checkout failed"
            return result

    result["checkout_ok"] = True

    # Step 2: Py312 compat patches
    n_patched = patch_py312_compat(workdir)
    if n_patched:
        print(f"  py312-compat: patched {n_patched} file(s)")

    # Step 3: Get test command
    test_cmd = get_test_command(workdir)
    if not test_cmd:
        result["error"] = "no test command"
        return result

    # Step 4: Confirm test fails before Claude Code
    print(f"  Confirming test fails...")
    failed_before, _ = run_test(workdir, test_cmd)
    result["test_failed_before"] = not failed_before  # True if test fails (expected)
    if failed_before:
        print(f"  WARNING: test passes on buggy version — skipping Claude Code run")
        result["error"] = "test passes on buggy version (not a useful bug)"
        return result

    # Step 5: Run Claude Code
    cc_result = run_claude_code(workdir, test_cmd, budget_usd, output_dir)
    result["claude_exit_code"] = cc_result.get("exit_code")
    result["cost_usd"] = cc_result.get("cost_usd")
    if "error" in cc_result:
        result["error"] = cc_result["error"]

    # Step 6: Run test after Claude Code
    print(f"  Running test after Claude Code...")
    passed, output = run_test(workdir, test_cmd)
    result["test_passed"] = passed
    result["test_output_snippet"] = output[-500:] if len(output) > 500 else output

    if passed:
        print(f"  PASS: test passes after Claude Code fix!")
    else:
        print(f"  FAIL: test still fails after Claude Code")

    # Save per-bug result
    (output_dir / "claude_code_result.json").write_text(json.dumps(result, indent=2))
    return result


def main():
    ap = argparse.ArgumentParser(
        description="Evaluate Claude Code as a baseline bug-fixer on BugsInPy."
    )
    ap.add_argument("--project", default=None,
                    help="Evaluate only this project.")
    ap.add_argument("--skip-checkout", action="store_true",
                    help="Reuse existing checkouts.")
    ap.add_argument("--start", type=int, default=1, metavar="N",
                    help="Global bug index to start from (1-based, default 1).")
    ap.add_argument("--budget", type=float, default=DEFAULT_BUDGET_USD,
                    help=f"Max USD per bug for Claude Code (default {DEFAULT_BUDGET_USD}).")
    args = ap.parse_args()

    projects_to_run = PROJECTS
    if args.project:
        projects_to_run = [p for p in PROJECTS if p["project"] == args.project]
        if not projects_to_run:
            print(f"ERROR: unknown project '{args.project}'")
            sys.exit(1)

    # Build global index-aware queue for --start
    global_idx = 0
    all_results = []

    for proj in projects_to_run:
        project = proj["project"]
        num_bugs = proj["num_bugs"]
        proj_results = []

        print(f"\n{'#'*70}")
        print(f"  PROJECT: {project}  ({num_bugs} bugs)")
        print(f"{'#'*70}")

        for bug_id in range(1, num_bugs + 1):
            global_idx += 1
            if global_idx < args.start:
                print(f"  Skipping global #{global_idx} ({project} bug {bug_id})")
                continue

            print(f"\n{'─'*60}")
            print(f"  Global #{global_idx}: [{project}] Bug {bug_id}/{num_bugs}")
            print(f"{'─'*60}")

            # Skip bugs where the pipeline produced no useful trace/KG
            if not kg_has_content(project, bug_id):
                print(f"  SKIP: KG is empty for {project} bug {bug_id} — not eligible")
                result_skip = {
                    "project": project, "bug_id": bug_id,
                    "checkout_ok": False, "test_failed_before": False,
                    "claude_exit_code": None, "cost_usd": None,
                    "test_passed": False, "error": "KG empty — excluded",
                    "kg_has_content": False,
                }
                proj_results.append(result_skip)
                all_results.append(result_skip)
                continue

            result = evaluate_bug(project, bug_id, args.skip_checkout, args.budget)
            result["kg_has_content"] = True
            proj_results.append(result)
            all_results.append(result)

            status = "PASS" if result["test_passed"] else "FAIL"
            cost = f"${result['cost_usd']:.3f}" if result["cost_usd"] else "N/A"
            print(f"  => {status}  cost={cost}  error={result.get('error','')}")

        # Per-project summary
        passed = sum(1 for r in proj_results if r["test_passed"])
        total = len(proj_results)
        if total:
            total_cost = sum(r["cost_usd"] or 0 for r in proj_results)
            print(f"\n  {project}: {passed}/{total} ({100*passed/total:.1f}%)  "
                  f"total_cost=${total_cost:.2f}")

        # Save per-project results
        fix_output = HERE / "fix_output" / project
        fix_output.mkdir(parents=True, exist_ok=True)
        with open(fix_output / "claude_code_report.json", "w") as f:
            json.dump(proj_results, f, indent=2)

    # Combined report
    print("\n\n")
    print("=" * 70)
    print("  CLAUDE CODE EVALUATION — COMBINED REPORT")
    print("=" * 70)

    total = len(all_results)
    if total == 0:
        print("No bugs evaluated.")
        return

    eligible = [r for r in all_results if r.get("kg_has_content", True)
                and r.get("error") != "KG empty — excluded"]
    n_eligible = len(eligible)
    passed = sum(1 for r in eligible if r["test_passed"])
    total_cost = sum(r["cost_usd"] or 0 for r in eligible)
    skipped = sum(1 for r in eligible if r.get("error") == "test passes on buggy version (not a useful bug)")

    print(f"  Total bugs in dataset: {total}")
    print(f"  Eligible (real KG):    {n_eligible}")
    fix_rate = f"{100*passed/n_eligible:.1f}%" if n_eligible > 0 else "N/A"
    print(f"  Tests passed:          {passed} / {n_eligible}  ({fix_rate})")
    print(f"  Skipped (not reproducible): {skipped}")
    print(f"  Total cost:            ${total_cost:.2f}")

    print(f"\n  {'Project':<16}  {'Bug':>4}  {'Test':>6}  {'Cost':>7}  Error")
    print(f"  {'─'*16}  {'─'*4}  {'─'*6}  {'─'*7}  {'─'*25}")
    for r in all_results:
        test = "PASS" if r["test_passed"] else "FAIL"
        cost = f"${r['cost_usd']:.3f}" if r["cost_usd"] else "N/A"
        err = (r.get("error") or "")[:30]
        print(f"  {r['project']:<16}  {r['bug_id']:>4}  {test:>6}  {cost:>7}  {err}")

    combined_path = HERE / "fix_output" / "claude_code_evaluation.json"
    with open(combined_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Combined results: {combined_path}")


if __name__ == "__main__":
    main()
