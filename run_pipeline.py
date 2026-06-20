#!/usr/bin/env python3
"""
End-to-end debugging pipeline for BugsInPy: youtube-dl bugs.

Iterates over all 43 youtube-dl bugs.
Saves results to:  ./fix_output/<project>/bug<bug_id>/
Pauses every 5 bugs to ask the user whether to continue.
Supports resuming from a given global bug counter.

Usage:
    python3 run_pipeline.py                        # interactive start
    python3 run_pipeline.py --workspace /tmp/bugs  # custom workspace
    python3 run_pipeline.py --skip-checkout        # reuse existing checkouts

Single-bug mode (original behaviour):
    python3 run_pipeline.py --spec test_spec.json
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ────────────────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent
BUGSINPY_DIR = (HERE / ".." / "BugsInPy").resolve()
BUGSINPY_CHECKOUT = BUGSINPY_DIR / "framework" / "bin" / "bugsinpy-checkout"

_SNOOP_IMPORT = "import pysnooper"
_CUSTOM_REPR_CODE = (
    "_xkg_repr = lambda obj: ("
    "f'{type(obj).__name__}(len={len(obj)})' "
    "if isinstance(obj, (list, dict, set, tuple, frozenset, bytes)) and len(obj) > 20 "
    "else repr(obj))"
)
_SNOOP_DECORATOR = (
    "@pysnooper.snoop("
    "prefix='IE_TRACE: ', depth=10, color=False, "
    "max_variable_length=500, "
    "custom_repr=((object, _xkg_repr),))"
)

# ────────────────────────────────────────────────────────────────────────────
# BugsInPy dataset: all 17 projects with their total bug counts.
# Bug IDs range from 1 .. max_bugs for each project.
# ────────────────────────────────────────────────────────────────────────────

BUGSINPY_PROJECTS = [
    {"project": "youtube-dl",   "max_bugs": 43},
    {"project": "tornado",      "max_bugs": 16},
    {"project": "scrapy",       "max_bugs": 37},
    {"project": "sanic",        "max_bugs": 2},
    {"project": "cookiecutter", "max_bugs": 4},
    # Additional projects to reach ~100 eligible bugs
    {"project": "ansible",      "max_bugs": 5},
    {"project": "fastapi",      "max_bugs": 4},
    {"project": "httpie",       "max_bugs": 4},
    {"project": "keras",        "max_bugs": 5},
    {"project": "luigi",        "max_bugs": 4},
    {"project": "matplotlib",   "max_bugs": 5},
    {"project": "pandas",       "max_bugs": 5},
    {"project": "spacy",        "max_bugs": 4},
    {"project": "thefuck",      "max_bugs": 4},
]
# Total: 102 (original) + 40 (new) = 142 bugs; targeting ~100 eligible after empty-KG exclusion

BUGS_PER_PROJECT = 50  # max bugs to run per project (capped by max_bugs above)
PAUSE_EVERY = 10      # ask user to continue after this many bugs


# ────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ────────────────────────────────────────────────────────────────────────────

def run(cmd, **kwargs):
    """Run a command, print it, and return the CompletedProcess."""
    print(f"\n{'='*60}")
    print(f"  CMD: {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
    print(f"{'='*60}\n")
    return subprocess.run(cmd, **kwargs)


def ask_continue() -> bool:
    """Prompt the user to decide whether to continue processing."""
    while True:
        answer = input("\n>>> 5 bugs completed. Continue? [y/n]: ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  Please enter 'y' or 'n'.")


def build_bug_queue() -> list[dict]:
    """Build the full ordered list of (project, bug_id) entries.

    Each project contributes min(BUGS_PER_PROJECT, max_bugs) entries.
    Returns a list of dicts with keys: project, bug_id, version,
    source_dirs, coverage_file  (ready to be used as a spec).
    """
    queue = []
    for proj in BUGSINPY_PROJECTS:
        count = min(BUGS_PER_PROJECT, proj["max_bugs"])
        for bug_id in range(1, count + 1):
            queue.append({
                "project": proj["project"],
                "bug_id": bug_id,
                "version": 0,           # always buggy
                "source_dirs": [],
                "coverage_file": None,
            })
    return queue


def print_bug_table(queue: list[dict]):
    """Pretty-print the full bug queue with global indices."""
    print("\n" + "=" * 70)
    print("  FULL BUG QUEUE")
    print("=" * 70)
    print(f"  {'#':>4}  {'Project':<16}  {'Bug ID':>6}")
    print(f"  {'─'*4}  {'─'*16}  {'─'*6}")
    for i, entry in enumerate(queue, start=1):
        print(f"  {i:>4}  {entry['project']:<16}  {entry['bug_id']:>6}")
    print("=" * 70)
    print(f"  Total bugs in queue: {len(queue)}")
    print("=" * 70 + "\n")


# ────────────────────────────────────────────────────────────────────────────
# PySnooper auto-decoration (unchanged from original)
# ────────────────────────────────────────────────────────────────────────────

def _parse_test_targets(run_test_sh: Path, workdir: Path) -> list[tuple[Path, str]]:
    """Parse bugsinpy_run_test.sh and return [(abs_file_path, function_name), ...].

    Handles formats:
      python -m unittest -q module.path.Class.method
      py.test file.py::function
      pytest file.py::function
      tox file.py::function
    """
    targets = []
    for line in run_test_sh.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # pytest/tox style: tox/pytest/py.test path/file.py::Class::method or ::func
        m = re.match(r"(?:tox|py\.?test|python\s+-m\s+pytest)\s+(.+?\.py)::(.+)", line)
        if m:
            file_path = m.group(1)
            # Could be "func" or "Class::method" — take the last part
            func_name = m.group(2).split("::")[-1]
            targets.append((workdir / file_path, func_name))
            continue

        # unittest style
        m = re.match(r"python\s+-m\s+unittest.*?\s+([\w.]+)", line)
        if m:
            dotted = m.group(1)
            parts = dotted.split(".")
            func_name = parts[-1]
            for split_at in range(2, len(parts)):
                candidate = workdir / (os.sep.join(parts[:split_at]) + ".py")
                if candidate.exists():
                    targets.append((candidate, func_name))
                    break
            else:
                mod_path = os.sep.join(parts[:-2]) + ".py"
                targets.append((workdir / mod_path, func_name))

    return targets


def _find_function_line(source: str, func_name: str) -> int | None:
    """Return the line number (1-indexed) of `def func_name(...)` in source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return node.lineno
    return None


def _find_import_insert_point(lines: list[str]) -> int:
    """Find the line index *after* the last top-level import using AST.

    Uses the AST to find real import statements (not text inside docstrings).
    """
    source = "\n".join(lines)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Fallback: after the first blank line
        for i, line in enumerate(lines):
            if not line.strip():
                return i
        return 0

    last_import_end = 0
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import_end = node.end_lineno  # 1-indexed
    return last_import_end  # already the correct 0-indexed insert point


def _ensure_import(lines: list[str]) -> int:
    """Add 'import pysnooper' and _xkg_repr helper after imports if missing."""
    has_import = any("import pysnooper" in l for l in lines)
    has_repr = any("_xkg_repr" in l for l in lines)
    if has_import and has_repr:
        return 0

    insert_at = _find_import_insert_point(lines)
    inserted = 0
    if not has_import:
        lines.insert(insert_at, _SNOOP_IMPORT)
        inserted += 1
    if not has_repr:
        lines.insert(insert_at + inserted, _CUSTOM_REPR_CODE)
        inserted += 1
    return inserted


def decorate_test(workdir: Path, run_test_sh: Path) -> list[Path]:
    """Add @pysnooper.snoop() decorator to test functions AND setUp/tearDown.

    Decorating setUp is critical: many BugsInPy bugs raise errors in setUp
    (e.g. fixture/middleware construction) before the test method runs.
    Without decorating setUp the pysnooper trace is empty.

    Returns list of modified files.
    """
    targets = _parse_test_targets(run_test_sh, workdir)
    if not targets:
        print("WARNING: Could not parse any test targets from run_test.sh")
        return []

    modified = []
    for test_file, func_name in targets:
        if not test_file.exists():
            print(f"  WARNING: {test_file} not found, skipping decoration")
            continue

        source = test_file.read_text()

        # Build the list of functions to decorate: primary + setUp helpers
        funcs_to_decorate = [func_name] + [
            h for h in ("setUp", "tearDown", "setUpClass", "tearDownClass")
            if re.search(rf"^\s+def\s+{h}\b", source, re.MULTILINE)
            and not re.search(rf"@pysnooper\.snoop.*\n[^\n]*def\s+{h}\b", source)
        ]

        # Find all line numbers first (before we start inserting)
        lines = source.splitlines()
        to_insert = []  # list of (orig_line_idx, indent, decorator)
        for fn in funcs_to_decorate:
            if re.search(rf"@pysnooper\.snoop.*\n[^\n]*def\s+{fn}\b", source):
                print(f"  Already decorated: {test_file.name}:{fn}")
                continue
            fl = _find_function_line(source, fn)
            if fl is None:
                if fn == func_name:
                    print(f"  WARNING: function '{fn}' not found in {test_file}")
                continue
            def_line = lines[fl - 1]
            indent = def_line[: len(def_line) - len(def_line.lstrip())]
            to_insert.append((fl - 1, indent, fn))

        if not to_insert:
            continue

        # Insert pysnooper import + repr helper
        import_offset = _ensure_import(lines)

        # Insert decorators in reverse order so earlier line indices stay valid
        for orig_idx, indent, fn in sorted(to_insert, key=lambda x: x[0], reverse=True):
            adj_idx = orig_idx + import_offset
            lines.insert(adj_idx, f"{indent}{_SNOOP_DECORATOR}")
            print(f"  Decorated: {test_file.name}:{fn} (line {orig_idx + 1})")

        test_file.write_text("\n".join(lines) + "\n")
        modified.append(test_file)

    return modified


# ────────────────────────────────────────────────────────────────────────────
# Compile: create venv, install deps, run setup
# ────────────────────────────────────────────────────────────────────────────

def _parse_bug_info(workdir: Path) -> dict:
    """Parse bugsinpy_bug.info and return a dict of key=value pairs."""
    info = {}
    bug_info = workdir / "bugsinpy_bug.info"
    if not bug_info.exists():
        return info
    for line in bug_info.read_text().splitlines():
        line = line.strip()
        if "=" in line:
            key, _, val = line.partition("=")
            info[key.strip()] = val.strip().strip('"')
    return info


def _build_pythonpath(workdir: Path) -> str:
    """Build PYTHONPATH from bugsinpy_bug.info + common fallback paths.

    BugsInPy projects rely on PYTHONPATH (not pip install) to make the
    project source importable. This reads the 'pythonpath' field from
    bugsinpy_bug.info and also adds common source roots.

    The 'pythonpath' field in bug info uses paths relative to the *workspace*
    (parent of workdir), e.g. 'ansible/build/lib/' where 'ansible' is the
    project directory name. We resolve relative to workdir.parent (workspace).
    """
    paths = []
    info = _parse_bug_info(workdir)
    workspace = workdir.parent  # e.g. .../BugsInPy/workspace

    # Add paths from bugsinpy_bug.info (semicolon-separated)
    # These are relative to workspace, e.g. 'ansible/build/lib/'
    pythonpath_raw = info.get("pythonpath", "")
    if pythonpath_raw:
        for p in pythonpath_raw.split(";"):
            p = p.strip()
            if p:
                full = (workspace / p).resolve()
                paths.append(str(full))

    # Common source roots used by BugsInPy projects
    for candidate in ["lib", "src", "."]:
        full = (workdir / candidate).resolve()
        if full.is_dir() and str(full) not in paths:
            paths.append(str(full))

    # Always include workdir itself
    wd = str(workdir.resolve())
    if wd not in paths:
        paths.append(wd)

    return ":".join(paths)


def _shim_insert_point(lines: list[str]) -> int:
    """Return the line index to insert a shim so it runs early but after:
      - module docstrings / encoding comments
      - `from __future__ import ...` lines  (must be first real statements)
    """
    insert_at = 0
    in_docstring = False
    docstring_char = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        # Track triple-quoted docstrings at file top
        if not in_docstring:
            if stripped.startswith('"""') or stripped.startswith("'''"):
                docstring_char = stripped[:3]
                if stripped.count(docstring_char) >= 2 and len(stripped) > 3:
                    insert_at = idx + 1  # single-line docstring
                    continue
                in_docstring = True
                insert_at = idx + 1
                continue
            if stripped.startswith('#') or stripped == '':
                insert_at = idx + 1
                continue
            # from __future__ must stay before any shim
            if stripped.startswith('from __future__'):
                insert_at = idx + 1
                continue
            break
        else:
            insert_at = idx + 1
            if docstring_char and docstring_char in stripped[stripped.find(docstring_char[0]):]:
                # End of multi-line docstring
                if stripped.endswith(docstring_char) or stripped.count(docstring_char) >= 2:
                    in_docstring = False
            continue
    return insert_at


def patch_py312_compat(workdir: Path) -> int:
    """Fix Python 3.12 breaking changes in project source so tests can run.

    Covers: collections.abc migration, distutils shim.
    Returns count of files modified.
    """
    import re as _re
    _ABC_NAMES = (
        "Callable", "Iterator", "Iterable", "Generator",
        "MutableMapping", "MutableSequence", "MutableSet",
        "Mapping", "Sequence", "Set", "Awaitable", "Coroutine",
        "AsyncIterator", "AsyncIterable", "AsyncGenerator",
        "Hashable", "Sized", "Container", "Collection",
        "Reversible", "KeysView", "ItemsView", "ValuesView",
    )
    _ABC_PAT = _re.compile(
        r'(?<![a-zA-Z_.])collections\.(' + "|".join(_ABC_NAMES) + r')(?![a-zA-Z_])'
    )
    _FROM_PAT = _re.compile(
        r'^([ \t]*)from collections import (.*?)$',
        _re.MULTILINE,
    )

    modified = 0
    for py_file in workdir.rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        original = text

        # Replace collections.Xxx with collections.abc.Xxx
        text = _ABC_PAT.sub(r'collections.abc.\1', text)

        # Fix `from collections import Mapping, Sequence, ...` style imports
        def _fix_from_import(m):
            indent = m.group(1)
            names_str = m.group(2).rstrip("\\").strip()
            # split on comma, classify each name
            names = [n.strip().rstrip("\\").strip() for n in names_str.split(",") if n.strip()]
            abc_names = [n for n in names if n in _ABC_NAMES]
            plain_names = [n for n in names if n not in _ABC_NAMES]
            lines = []
            if plain_names:
                lines.append(f"{indent}from collections import {', '.join(plain_names)}")
            if abc_names:
                lines.append(f"{indent}from collections.abc import {', '.join(abc_names)}")
            return "\n".join(lines) if lines else m.group(0)

        text = _FROM_PAT.sub(_fix_from_import, text)

        # assertRaisesRegexp / assertRegexpMatches removed in Python 3.12
        text = text.replace('self.assertRaisesRegexp(', 'self.assertRaisesRegex(')
        text = text.replace('self.assertRegexpMatches(', 'self.assertRegex(')
        text = text.replace('self.assertNotRegexpMatches(', 'self.assertNotRegex(')

        # Fix `import backports.ssl_match_hostname` → use stdlib ssl
        if 'backports.ssl_match_hostname' in text:
            text = text.replace(
                'import backports.ssl_match_hostname',
                'import ssl as _ssl_backport_shim',
            )
            text = text.replace(
                'ssl_match_hostname = backports.ssl_match_hostname.match_hostname',
                'ssl_match_hostname = getattr(_ssl_backport_shim, "match_hostname", None)',
            )
            text = text.replace(
                'SSLCertificateError = backports.ssl_match_hostname.CertificateError',
                'SSLCertificateError = getattr(_ssl_backport_shim, "SSLCertificateError", ssl.SSLError)',
            )

        # Fix six.moves not in sys.modules on Python 3.12
        # Registers six.moves AND all MovedModule submodules (http_cookies etc.)
        # using their .mod attribute (stdlib name) to avoid the circular import.
        if 'from six.moves import' in text or 'six.moves.' in text:
            shim = (
                'import six as _six_shim, sys as _sys_shim, importlib as _il_shim; '
                '_sys_shim.modules.setdefault("six.moves", _six_shim.moves); '
                # Register all MovedModule entries — skip those whose .mod starts with 'six.'
                # (those are internal six self-references like moves.urllib → six.moves.urllib)
                '[(lambda _k, _m: _sys_shim.modules.setdefault(_k, _il_shim.import_module(_m)))(f"six.moves.{_d.name}", _d.mod) '
                'for _d in type(_six_shim.moves).__dict__.values() '
                'if isinstance(_d, _six_shim.MovedModule) and hasattr(_d, "mod") '
                'and not _d.mod.startswith("six.") '
                'and not _sys_shim.modules.get(f"six.moves.{_d.name}")]; '
                # urllib submodules use special Module_six_moves_urllib* classes
                '[_sys_shim.modules.setdefault("six.moves.urllib", _six_shim.Module_six_moves_urllib("six.moves.urllib")), '
                '_sys_shim.modules.setdefault("six.moves.urllib.parse", _six_shim.Module_six_moves_urllib_parse("six.moves.urllib.parse")), '
                '_sys_shim.modules.setdefault("six.moves.urllib.error", _six_shim.Module_six_moves_urllib_error("six.moves.urllib.error")), '
                '_sys_shim.modules.setdefault("six.moves.urllib.request", _six_shim.Module_six_moves_urllib_request("six.moves.urllib.request")), '
                '_sys_shim.modules.setdefault("six.moves.urllib.response", _six_shim.Module_six_moves_urllib_response("six.moves.urllib.response")), '
                '_sys_shim.modules.setdefault("six.moves.urllib.robotparser", _six_shim.Module_six_moves_urllib_robotparser("six.moves.urllib.robotparser"))]\n'
            )
            if '_sys_shim.modules.setdefault("six.moves"' not in text:
                lines_tmp = text.splitlines(keepends=True)
                insert_at = _shim_insert_point(lines_tmp)
                lines_tmp.insert(insert_at, shim)
                text = "".join(lines_tmp)

        # Fix ansible vendored six — register ansible.module_utils.six.moves.
        # The shim is already in module_utils/six/__init__.py (six.moves registration),
        # but we also need to alias it under the ansible-namespaced path.
        # Only patch files that are inside ansible's vendored six package.
        if str(py_file).endswith(('ansible/module_utils/six/__init__.py',)) and \
                '_sys_shim.modules.setdefault("ansible.module_utils.six.moves"' not in text:
            # Append ansible-namespaced aliases after the existing six.moves shim line
            ansible_extra = (
                'import sys as _sys_am; '
                '[_sys_am.modules.setdefault(f"ansible.module_utils.six.{_k}", _sys_am.modules[_k]) '
                'for _k in list(_sys_am.modules) if _k.startswith("six.moves") '
                'and f"ansible.module_utils.six.{_k}" not in _sys_am.modules]\n'
            )
            lines_tmp = text.splitlines(keepends=True)
            # Insert right after the existing six.moves shim
            for idx, ln in enumerate(lines_tmp):
                if '_sys_shim.modules.setdefault("six.moves"' in ln:
                    lines_tmp.insert(idx + 1, ansible_extra)
                    break
            else:
                lines_tmp.insert(_shim_insert_point(lines_tmp), ansible_extra)
            text = "".join(lines_tmp)

        # Fix `imp` module removed in Python 3.12
        if ('from imp import' in text or '\nimport imp\n' in text or text.startswith('import imp\n')) \
                and '_iss.modules.setdefault("imp"' not in text:
            imp_shim = (
                'import sys as _iss, types as _ist; '
                '_iss.modules.setdefault("imp", type(_ist)("imp")); '
                '_iss.modules["imp"].find_module = lambda n, p=None: (None, None, None); '
                '_iss.modules["imp"].load_module = lambda n, *a: _iss.modules.get(n) or __import__(n); '
                '_iss.modules["imp"].load_source = lambda n, p, f=None: _iss.modules.get(n) or __import__(n); '
                '_iss.modules["imp"].acquire_lock = lambda: None; '
                '_iss.modules["imp"].release_lock = lambda: None; '
                '_iss.modules["imp"].PY_SOURCE = 1; '
                '_iss.modules["imp"].C_EXTENSION = 3; '
                '_iss.modules["imp"].PKG_DIRECTORY = 5\n'
            )
            lines_tmp = text.splitlines(keepends=True)
            insert_at = _shim_insert_point(lines_tmp)
            lines_tmp.insert(insert_at, imp_shim)
            text = "".join(lines_tmp)

        # Fix SafeConfigParser removed in Python 3.12 (use RawConfigParser alias)
        if 'SafeConfigParser' in text and '_cfgp_compat' not in text:
            cfgp_shim = (
                'import configparser as _cfgp_compat; '
                'setattr(_cfgp_compat, "SafeConfigParser", '
                'getattr(_cfgp_compat, "SafeConfigParser", _cfgp_compat.RawConfigParser))\n'
            )
            lines_tmp = text.splitlines(keepends=True)
            lines_tmp.insert(_shim_insert_point(lines_tmp), cfgp_shim)
            text = "".join(lines_tmp)

        # Fix `inspect.getargspec` and `inspect.ArgSpec` removed in 3.11+
        # Strategy: restore inspect.getargspec as a shim (returning a 4-field namedtuple)
        # rather than replacing every call site — avoids "too many values to unpack" errors.
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

        if text != original:
            try:
                py_file.write_text(text, encoding="utf-8")
                modified += 1
            except Exception:
                pass

    if modified:
        print(f"  py312-compat: patched {modified} file(s)")
    return modified


def compile_project(workdir: Path) -> bool:
    """Prepare a BugsInPy checkout for testing using the current Python.

    No venvs, no pip install (to avoid trashing the environment with old
    pinned versions). Just:
      - Build PYTHONPATH from bugsinpy_bug.info so project source is importable
      - Save it for run_trace.py

    Returns True on success, False on hard failure.
    """
    # Build PYTHONPATH from bugsinpy_bug.info
    pythonpath = _build_pythonpath(workdir)
    print(f"  PYTHONPATH: {pythonpath}")

    # Save PYTHONPATH for run_trace.py to use
    (workdir / "bugsinpy_pythonpath.txt").write_text(pythonpath + "\n")

    print("  Compile complete.")
    return True


# ────────────────────────────────────────────────────────────────────────────
# Pipeline: process a single bug
# ────────────────────────────────────────────────────────────────────────────

def process_single_bug(
    spec: dict,
    workspace: Path,
    skip_checkout: bool = False,
) -> bool:
    """Run the full 5-step pipeline for one bug.

    Output is saved to:  ./fix_output/<project>/bug<bug_id>/

    Returns True on success, False on failure (pipeline continues either way).
    """
    project = spec["project"]
    bug_id = spec["bug_id"]
    version = spec.get("version", 0)
    source_dirs = spec.get("source_dirs", [])
    coverage_file = spec.get("coverage_file", None)

    workdir = workspace / project

    # ── Per-bug output directory ───────────────────────────────────────
    bug_dir = HERE / "fix_output" / project / f"bug{bug_id}"
    bug_dir.mkdir(parents=True, exist_ok=True)

    # Save the spec as a record of what was run
    (bug_dir / "spec.json").write_text(json.dumps(spec, indent=2) + "\n")

    raw_trace     = bug_dir / "trace_raw.log"
    condensed     = bug_dir / "trace_condensed.log"
    kg_out        = bug_dir / "trace_kg"
    diagnosis_out = bug_dir / "diagnosis.md"
    summary_file  = bug_dir / "summary.txt"

    print(f"\n{'#'*60}")
    print(f"  Project : {project}")
    print(f"  Bug ID  : {bug_id}")
    print(f"  Version : {version} ({'buggy' if version == 0 else 'fixed'})")
    print(f"  Workdir : {workdir}")
    print(f"  Output  : {bug_dir}")
    print(f"{'#'*60}")

    summary_lines = [
        f"Project : {project}",
        f"Bug ID  : {bug_id}",
        f"Version : {version} ({'buggy' if version == 0 else 'fixed'})",
        f"Workdir : {workdir}",
        f"Output  : {bug_dir}",
        "",
    ]

    # ── Step 0: Checkout ───────────────────────────────────────────────
    if not skip_checkout:
        print("\n>>> STEP 0: bugsinpy-checkout")
        summary_lines.append("STEP 0: bugsinpy-checkout")
        workspace.mkdir(parents=True, exist_ok=True)
        ret = run(
            ["bash", str(BUGSINPY_CHECKOUT),
             "-p", project,
             "-i", str(bug_id),
             "-v", str(version),
             "-w", str(workspace)],
        )
        if ret.returncode != 0:
            msg = "FAILED at STEP 0: bugsinpy-checkout returned non-zero"
            print(f"ERROR: {msg}", file=sys.stderr)
            summary_lines.append(f"  RESULT: {msg}")
            summary_file.write_text("\n".join(summary_lines) + "\n")
            return False
        summary_lines.append("  RESULT: OK")
    else:
        print("\n>>> STEP 0: Skipping checkout (--skip-checkout)")
        summary_lines.append("STEP 0: skipped (--skip-checkout)")

    if not workdir.exists():
        msg = f"workdir does not exist: {workdir}"
        print(f"ERROR: {msg}", file=sys.stderr)
        summary_lines.append(f"  ERROR: {msg}")
        summary_file.write_text("\n".join(summary_lines) + "\n")
        return False

    # ── Step 0.15: Python 3.12 compatibility patches ──────────────────
    n_patched = patch_py312_compat(workdir)
    summary_lines.append(f"STEP 0.15: py312-compat patched {n_patched} files")

    # ── Step 0.1: Compile (create venv, install deps) ───────────────
    if not skip_checkout:
        print("\n>>> STEP 0.1: compile (create venv + install deps)")
        summary_lines.append("STEP 0.1: compile")
        ok = compile_project(workdir)
        if not ok:
            msg = "FAILED at STEP 0.1: compile returned non-zero"
            print(f"ERROR: {msg}", file=sys.stderr)
            summary_lines.append(f"  RESULT: {msg}")
            summary_file.write_text("\n".join(summary_lines) + "\n")
            return False
        summary_lines.append("  RESULT: OK")
    else:
        print("\n>>> STEP 0.1: Skipping compile (--skip-checkout)")
        summary_lines.append("STEP 0.1: skipped (--skip-checkout)")

    # ── Step 0.5: Auto-decorate ────────────────────────────────────────
    print("\n>>> STEP 0.5: Auto-decorate test functions with pysnooper")
    summary_lines.append("STEP 0.5: auto-decorate test functions")
    run_test_sh = workdir / "bugsinpy_run_test.sh"
    if not run_test_sh.exists():
        msg = f"bugsinpy_run_test.sh not found in {workdir}"
        print(f"ERROR: {msg}", file=sys.stderr)
        summary_lines.append(f"  ERROR: {msg}")
        summary_file.write_text("\n".join(summary_lines) + "\n")
        return False
    decorated_files = decorate_test(workdir, run_test_sh)
    if decorated_files:
        summary_lines.append(f"  Modified {len(decorated_files)} file(s)")
    else:
        summary_lines.append("  No files modified (already decorated or targets not found)")

    # ── Step 1: Run trace ──────────────────────────────────────────────
    print("\n>>> STEP 1: run_trace.py")
    summary_lines.append("STEP 1: run_trace.py")
    ret = run(
        [sys.executable, str(HERE / "helpers" / "run_trace.py"),
         "--workdir", str(workdir),
         "--save-dir", str(bug_dir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    trace_output = ret.stdout.decode("utf-8", errors="ignore")
    print(trace_output[-2000:] if len(trace_output) > 2000 else trace_output)

    raw_trace.write_text(trace_output)
    summary_lines.append(f"  Raw trace: {len(trace_output)} chars")

    if ret.returncode != 0:
        summary_lines.append(
            f"  WARNING: run_trace.py exited {ret.returncode} "
            "(expected for buggy version)")
        print(f"WARNING: run_trace.py exited with code {ret.returncode}. "
              "Continuing (test may fail as expected for buggy version).")

    # ── Step 2: Condense trace ─────────────────────────────────────────
    print("\n>>> STEP 2: trace_condense.py")
    summary_lines.append("STEP 2: trace_condense.py")
    ret = run(
        [sys.executable, str(HERE / "helpers" / "trace_condense.py"),
         "--log", str(raw_trace),
         "--out", str(condensed)],
    )
    if ret.returncode != 0:
        msg = "trace_condense.py failed"
        print(f"ERROR: {msg}", file=sys.stderr)
        summary_lines.append(f"  RESULT: FAILED ({msg})")
        summary_file.write_text("\n".join(summary_lines) + "\n")
        return False
    summary_lines.append(f"  Condensed trace: {condensed}")

    # ── Step 3: Build KG ───────────────────────────────────────────────
    print("\n>>> STEP 3: build_trace_kg.py")
    summary_lines.append("STEP 3: build_trace_kg.py")
    kg_cmd = [
        sys.executable, str(HERE / "helpers" / "build_trace_kg.py"),
        "--trace", str(condensed),
        "--out", str(kg_out),
    ]
    all_source_dirs = [str(workdir)] + [str(Path(d).resolve()) for d in source_dirs]
    for d in all_source_dirs:
        kg_cmd.extend(["--source", d])
    if coverage_file:
        kg_cmd.extend(["--coverage", str(Path(coverage_file).resolve())])

    ret = run(kg_cmd)
    if ret.returncode != 0:
        msg = "build_trace_kg.py failed"
        print(f"ERROR: {msg}", file=sys.stderr)
        summary_lines.append(f"  RESULT: FAILED ({msg})")
        summary_file.write_text("\n".join(summary_lines) + "\n")
        return False
    summary_lines.append(f"  KG output: {kg_out}")

    # ── Step 4: Debug agent ────────────────────────────────────────────
    print("\n>>> STEP 4: debug_agent.py")
    summary_lines.append("STEP 4: debug_agent.py")
    ret = run(
        [sys.executable, str(HERE / "helpers" / "debug_agent.py"),
         "--kg", str(kg_out),
         "--trace", str(condensed),
         "--workdir", str(workdir),
         "--output", str(diagnosis_out)],
    )
    if ret.returncode != 0:
        msg = "debug_agent.py failed"
        print(f"ERROR: {msg}", file=sys.stderr)
        summary_lines.append(f"  RESULT: FAILED ({msg})")
        summary_file.write_text("\n".join(summary_lines) + "\n")
        return False
    summary_lines.append(f"  Diagnosis: {diagnosis_out}")

    # ── Done ───────────────────────────────────────────────────────────
    summary_lines.append("")
    summary_lines.append("PIPELINE COMPLETE - all steps succeeded.")
    summary_file.write_text("\n".join(summary_lines) + "\n")

    print(f"\n{'='*60}")
    print(f"  BUG COMPLETE: {project} / bug {bug_id}")
    print(f"  Diagnosis : {diagnosis_out}")
    print(f"  KG        : {kg_out}")
    print(f"  Summary   : {summary_file}")
    print(f"{'='*60}")
    return True


# ────────────────────────────────────────────────────────────────────────────
# Single-spec mode (backward-compatible with original CLI)
# ────────────────────────────────────────────────────────────────────────────

def run_single_spec(spec_path: Path, workspace: Path, skip_checkout: bool):
    """Run the pipeline on a single JSON spec file (original behaviour)."""
    spec = json.loads(spec_path.read_text())
    ok = process_single_bug(spec, workspace, skip_checkout)
    if not ok:
        sys.exit(1)


# ────────────────────────────────────────────────────────────────────────────
# Batch mode: iterate over all projects
# ────────────────────────────────────────────────────────────────────────────

def run_batch(workspace: Path, skip_checkout: bool,
              start_from_arg: int | None = None, yes: bool = False):
    """Iterate over all BugsInPy projects (up to BUGS_PER_PROJECT bugs each).

    - Prints the full queue with global indices at startup.
    - Asks the user which global bug number to start from (unless --start given).
    - Pauses every PAUSE_EVERY bugs to ask if user wants to continue (unless --yes).
    - Logs per-bug results and a final summary.
    """
    queue = build_bug_queue()
    total = len(queue)

    print_bug_table(queue)

    # ── Determine start position ───────────────────────────────────────
    if start_from_arg is not None:
        start_from = start_from_arg
    else:
        while True:
            raw = input(
                f"Enter the global bug number to start from [1-{total}] "
                f"(default: 1): "
            ).strip()
            if raw == "":
                start_from = 1
                break
            try:
                start_from = int(raw)
                if 1 <= start_from <= total:
                    break
                print(f"  Please enter a number between 1 and {total}.")
            except ValueError:
                print("  Please enter a valid integer.")

    print(f"\nStarting from global bug #{start_from}\n")

    # ── Main loop ──────────────────────────────────────────────────────
    results = []           # list of (global_idx, project, bug_id, success)
    bugs_since_pause = 0   # counter for the "pause every 5" feature

    for global_idx in range(start_from, total + 1):
        entry = queue[global_idx - 1]  # queue is 0-indexed
        project = entry["project"]
        bug_id = entry["bug_id"]

        print(f"\n{'*'*60}")
        print(f"  GLOBAL BUG #{global_idx} / {total}")
        print(f"  Project: {project}  |  Bug ID: {bug_id}")
        print(f"{'*'*60}")

        ok = process_single_bug(entry, workspace, skip_checkout)
        results.append((global_idx, project, bug_id, ok))
        bugs_since_pause += 1

        # ── Pause every PAUSE_EVERY bugs ───────────────────────────────
        if bugs_since_pause >= PAUSE_EVERY and global_idx < total:
            print(f"\n{'─'*60}")
            print(f"  Progress: {global_idx}/{total} bugs processed")
            successes = sum(1 for *_, s in results if s)
            failures = len(results) - successes
            print(f"  Results so far: {successes} succeeded, {failures} failed")
            print(f"{'─'*60}")

            if not yes and not ask_continue():
                print("\nUser chose to stop. Printing final summary.\n")
                break
            bugs_since_pause = 0

    # ── Final summary ──────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  BATCH RUN COMPLETE")
    print(f"{'='*60}")
    print(f"  {'#':>4}  {'Project':<16}  {'Bug':>4}  {'Result':<8}")
    print(f"  {'─'*4}  {'─'*16}  {'─'*4}  {'─'*8}")
    for idx, proj, bid, ok in results:
        status = "OK" if ok else "FAIL"
        print(f"  {idx:>4}  {proj:<16}  {bid:>4}  {status:<8}")

    successes = sum(1 for *_, s in results if s)
    failures = len(results) - successes
    print(f"\n  Total: {len(results)} processed, "
          f"{successes} succeeded, {failures} failed")
    print(f"{'='*60}\n")

    # Save batch summary
    summary_path = HERE / "fix_output" / "batch_summary.txt"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w") as f:
        f.write("BATCH RUN SUMMARY\n")
        f.write(f"{'='*50}\n")
        for idx, proj, bid, ok in results:
            status = "OK" if ok else "FAIL"
            f.write(f"#{idx:>4}  {proj:<16}  bug {bid:>3}  {status}\n")
        f.write(f"\nTotal: {len(results)} processed, "
                f"{successes} succeeded, {failures} failed\n")
    print(f"  Batch summary saved to: {summary_path}")


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="xKG-LADAR pipeline - batch or single-bug mode."
    )
    ap.add_argument(
        "--spec", type=Path, default=None,
        help="JSON spec file for single-bug mode. "
             "If omitted, runs batch mode over all 17 BugsInPy projects.")
    ap.add_argument(
        "--workspace", type=Path,
        default=BUGSINPY_DIR / "workspace",
        help="Directory where projects are checked out "
             "(default: BugsInPy/workspace)")
    ap.add_argument(
        "--skip-checkout", action="store_true",
        help="Skip bugsinpy-checkout (reuse existing workdir)")
    ap.add_argument(
        "--start", type=int, default=None, metavar="N",
        help="Global bug index to start from (1-based). Skips the interactive prompt.")
    ap.add_argument(
        "--yes", action="store_true",
        help="Non-interactive: auto-continue without pausing every PAUSE_EVERY bugs.")
    args = ap.parse_args()

    if args.spec:
        # Single-bug mode (backward-compatible)
        run_single_spec(args.spec, args.workspace, args.skip_checkout)
    else:
        # Batch mode
        run_batch(args.workspace, args.skip_checkout,
                  start_from_arg=args.start, yes=args.yes)


if __name__ == "__main__":
    main()
