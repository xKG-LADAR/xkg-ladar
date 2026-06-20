import re
import ast
import json
import os
import argparse
import networkx as nx
from graphviz import Digraph


CALL_RE = re.compile(r'\bcall\s+\d+\s+def\s+([a-zA-Z0-9_]+)')
VAR_NEW_RE = re.compile(r'New var:\.*\s+([a-zA-Z0-9_]+)\s*=\s*(.*)')
VAR_MOD_RE = re.compile(r'Modified var:\.*\s+([a-zA-Z0-9_]+)\s*=\s*(.*)')
RETURN_RE = re.compile(r'\breturn\s+\d+')
EXCEPTION_EVENT_RE = re.compile(r'\bexception\s+\d+')
EXCEPTION_TYPE_RE = re.compile(r'Exception:\.*\s+([^\s:]+)(?::\s*(.*))?')
CONDENSED_RE = re.compile(
    r"\[CONDENSED\] (\d+) identical loop iterations skipped "
    r"\((\d+) total iterations, showing first and last\)"
)
STARTING_VAR_RE = re.compile(r'Starting var:\.*\s+([a-zA-Z0-9_]+)')

# Maximum characters shown per individual variable value in the graph.
# Long enough to be meaningful; truncation is flagged with '…' so the
# agent knows to fetch the full value rather than trusting a cut-off repr.
_VAL_DISPLAY_LEN = 120
# Maximum number of distinct per-iteration values to list on a node before
# summarising the remainder as "+N more".
_MAX_VALUES_SHOWN = 6


def _clip(s, n=_VAL_DISPLAY_LEN):
    """Clip a string to n chars, appending '…' when cut."""
    s = str(s).strip()
    return s if len(s) <= n else s[:n] + '\u2026'


def _short(s, n=55):
    """Short clip used for docstrings and branch descriptions."""
    return _clip(s, n)


def indent_level(line):
    """Indentation = spaces immediately after the 'IE_TRACE:' prefix.

    PySnooper nests calls by prepending extra spaces after the prefix:
      IE_TRACE: <ts> ...          → depth 0  (1 space)
      IE_TRACE:     <ts> ...      → depth 1  (5 spaces)
      IE_TRACE:         <ts> ...  → depth 2  (9 spaces)
    """
    if line.startswith('IE_TRACE:'):
        after = line[len('IE_TRACE:'):]
        return len(after) - len(after.lstrip(' '))
    return len(line) - len(line.lstrip())


def parse_trace(trace_path):
    G = nx.DiGraph()

    call_stack = []   # function names in call order
    indent_stack = [] # matching indentation levels
    var_last_writer = {}
    call_counts = {}  # (caller, callee) -> int
    call_seq = [0]    # mutable global sequence counter

    # Error propagation state
    # error_node -> fn that most recently raised/re-raised it
    active_errors = {}
    # fn that just saw an 'exception' event line, waiting for the type line
    pending_exc_fn = [None]
    # ONE-SHOT catch detection: error_node -> raiser, set right after an
    # exception type line is parsed. Consumed by the very next normal-execution
    # line (var write / call / return). If that line is in the same function
    # that raised → exception was caught internally (mark edge gray). If it's
    # in a different function, or if another exception event fires first
    # (propagation), the entry is discarded without marking caught.
    pending_catch: dict = {}
    # Parameter names seen in 'Starting var' lines before the next call line
    pending_params: list = []

    with open(trace_path) as f:
        for line in f:
            indent = indent_level(line)

            # ── Exception type line: "Exception:..... ExcType: msg" ──────────
            # This immediately follows an exception event line.
            exc_type_match = EXCEPTION_TYPE_RE.search(line)
            if exc_type_match and pending_exc_fn[0] is not None:
                exc_type = exc_type_match.group(1).rstrip(':')
                exc_msg = (exc_type_match.group(2) or '').strip()
                error_node = f"ERROR:{exc_type}"
                if not G.has_node(error_node):
                    G.add_node(error_node, type="error", exc_type=exc_type,
                               exc_msg=exc_msg)
                elif exc_msg and not G.nodes[error_node].get('exc_msg'):
                    G.nodes[error_node]['exc_msg'] = exc_msg
                raiser = pending_exc_fn[0]
                if error_node in active_errors:
                    # Same exception propagating up the stack:
                    # draw a propagates_error edge from previous raiser to current
                    prev_raiser = active_errors[error_node]
                    if prev_raiser != raiser:
                        G.add_edge(prev_raiser, raiser,
                                   type="propagates_error", error=error_node)
                else:
                    # First occurrence: direct raises edge
                    G.add_edge(raiser, error_node, type="raises")
                active_errors[error_node] = raiser
                # Arm one-shot catch detection for the next normal-exec line.
                # Clear stale entries first so only the latest raise is tracked.
                pending_catch.clear()
                pending_catch[error_node] = raiser
                pending_exc_fn[0] = None
                continue

            # ── Pop functions exited by indentation drop ──────────────────────
            while indent_stack and indent < indent_stack[-1]:
                indent_stack.pop()
                call_stack.pop()

            # ── Explicit return line ───────────────────────────────────────────
            if (RETURN_RE.search(line)
                    and call_stack and indent_stack
                    and indent == indent_stack[-1]):
                call_stack.pop()
                indent_stack.pop()
                continue

            # ── Exception event line: "exception  <lineno>  <code>" ───────────
            # Record which function raised but do NOT pop the stack yet.
            # The exception may be caught within the same function (try/except),
            # in which case execution continues at the same indent and the function
            # never actually exits. We only pop via the indent-drop logic above.
            if EXCEPTION_EVENT_RE.search(line):
                if call_stack:
                    pending_exc_fn[0] = call_stack[-1]
                # A new exception event means the exception is propagating, not
                # being caught. Discard any pending catch-check so we don't
                # wrongly mark the previous raise as caught.
                pending_catch.clear()
                continue

            # ── Starting var: parameter being passed into the next call ─────────
            sv_match = STARTING_VAR_RE.search(line)
            if sv_match:
                pending_params.append(sv_match.group(1))
                continue

            # ── Condensed loop annotation ─────────────────────────────────────
            cond_match = CONDENSED_RE.search(line)
            if cond_match and call_stack:
                current_fn = call_stack[-1]
                total_iters = int(cond_match.group(2))
                if G.has_edge(current_fn, current_fn):
                    G[current_fn][current_fn]['loop_count'] = G[current_fn][current_fn].get('loop_count', 0) + total_iters
                else:
                    G.add_edge(
                        current_fn, current_fn,
                        type="loops",
                        loop_count=total_iters,
                    )
                continue

            # ── Call line ─────────────────────────────────────────────────────
            call_match = CALL_RE.search(line)
            if call_match:
                fn = call_match.group(1)
                depth = len(call_stack)

                if not G.has_node(fn):
                    G.add_node(fn, type="function", depth=depth)
                else:
                    # Track minimum depth (shallowest first appearance in tree)
                    if G.nodes[fn].get('depth', depth) > depth:
                        G.nodes[fn]['depth'] = depth

                if call_stack:
                    caller = call_stack[-1]
                    # One-shot catch check: caller is making a new call,
                    # so it's executing normally → any pending exception was caught.
                    for e, r in list(pending_catch.items()):
                        if r == caller:
                            if G.has_edge(r, e):
                                G[r][e]['caught'] = True
                            active_errors.pop(e, None)
                        del pending_catch[e]
                    key = (caller, fn)
                    call_counts[key] = call_counts.get(key, 0) + 1
                    call_seq[0] += 1
                    if G.has_edge(caller, fn):
                        G[caller][fn]['weight'] = call_counts[key]
                    else:
                        G.add_edge(caller, fn, type="calls", weight=1,
                                   call_seq=call_seq[0])

                # Wire up any variables that were passed as arguments.
                # pending_params holds parameter names from 'Starting var' lines
                # that appeared immediately before this call at the callee's indent.
                for param in pending_params:
                    if param in var_last_writer:
                        if not G.has_node(param):
                            G.add_node(param, type="variable")
                        G.add_edge(param, fn, type="passed_to")
                pending_params.clear()

                call_stack.append(fn)
                indent_stack.append(indent)
                continue

            if not call_stack:
                continue

            current_fn = call_stack[-1]

            # ── One-shot caught detection ─────────────────────────────────────
            # pending_catch entries were armed on the last exception type line.
            # This is the first normal-execution line since then. If the current
            # function is the one that raised, the exception was caught internally.
            # Either way, consume all entries — they are only valid for one step.
            for e, r in list(pending_catch.items()):
                if r == current_fn:
                    if G.has_edge(r, e):
                        G[r][e]['caught'] = True
                    active_errors.pop(e, None)
                del pending_catch[e]

            # ── Variable writes ───────────────────────────────────────────────
            new_match = VAR_NEW_RE.search(line)
            mod_match = VAR_MOD_RE.search(line)
            var = None
            val = None
            if new_match:
                var = new_match.group(1)
                val = new_match.group(2).strip()
            elif mod_match:
                var = mod_match.group(1)
                val = mod_match.group(2).strip()

            if var:
                # Track ALL distinct values across every loop iteration so the
                # graph shows the full value history rather than just the final
                # write (which may be from a non-buggy iteration).
                if not G.has_node(var):
                    G.add_node(var, type="variable",
                               values_seen=[], write_count=0)
                nd = G.nodes[var]
                nd['write_count'] = nd.get('write_count', 0) + 1
                seen = nd.setdefault('values_seen', [])
                if val not in seen:
                    seen.append(val)

                # Writes edge: record all distinct values assigned via this edge
                # (same variable written multiple times by the same function).
                if G.has_edge(current_fn, var):
                    ev = G[current_fn][var]
                    ev['write_count'] = ev.get('write_count', 0) + 1
                    all_v = ev.setdefault('all_values', [])
                    if val not in all_v:
                        all_v.append(val)
                else:
                    G.add_edge(current_fn, var, type="writes",
                               all_values=[val], write_count=1)

                var_last_writer[var] = current_fn

    return G


# ── Source enrichment ──────────────────────────────────────────────────────────

def _iter_functions(tree_node, parent_fn=None):
    """Yield (fn_ast_node, parent_fn_name) for every function in the AST.

    Recurses into nested functions so that closures are attributed to their
    enclosing function rather than appearing as orphaned top-level definitions.
    """
    for child in ast.iter_child_nodes(tree_node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield child, parent_fn
            yield from _iter_functions(child, child.name)
        else:
            yield from _iter_functions(child, parent_fn)


def extract_function_info(source_dirs):
    """Crawl source directories and return per-function metadata.

    Returns:
        {func_name: {'docstring': str, 'filepath': str, 'lineno': int,
                     'end_lineno': int, 'defined_within': str|None}}

    'defined_within' is the name of the enclosing function for closures, or
    None for top-level / class-method definitions.

    When the same name appears in multiple files the definition with the
    smallest lineno wins (top-level helpers preferred over nested ones).
    """
    result = {}
    for src_dir in source_dirs:
        for root, _, files in os.walk(src_dir):
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, encoding='utf-8', errors='ignore') as f:
                        source = f.read()
                    tree = ast.parse(source, filename=fpath)
                    for fn_node, parent_fn in _iter_functions(tree):
                        doc = ast.get_docstring(fn_node) or ''
                        end = getattr(fn_node, 'end_lineno', fn_node.lineno)
                        entry = {
                            'docstring': doc,
                            'filepath': fpath,
                            'lineno': fn_node.lineno,
                            'end_lineno': end,
                            'defined_within': parent_fn,
                        }
                        existing = result.get(fn_node.name)
                        if existing is None or fn_node.lineno < existing['lineno']:
                            result[fn_node.name] = entry
                except Exception:
                    pass
    return result


def extract_missed_branches(source_dirs, coverage_file):
    """Identify untaken conditional branches using coverage.py data.

    For each function that has at least one missed line coinciding with a
    branch point (if/elif/else/for/while/except), return a human-readable
    description of the untaken branch.

    Returns:
        {func_name: [branch_description, ...]}

    Requires the ``coverage`` package and a .coverage data file produced
    with ``coverage run`` (branch=True recommended but not required).
    """
    try:
        import coverage as cov_module
    except ImportError:
        print("Warning: 'coverage' package not found — install with: "
              "pip install coverage")
        return {}

    try:
        cov = cov_module.Coverage(data_file=coverage_file)
        cov.load()
    except Exception as exc:
        print(f"Warning: could not load coverage data from {coverage_file!r}: {exc}")
        return {}

    # Build filepath -> set(missed_line_numbers)
    missed_per_file: dict[str, set] = {}
    for fpath in cov.get_data().measured_files():
        try:
            _, _, _, missing, _ = cov.analysis2(fpath)
            if missing:
                missed_per_file[fpath] = set(missing)
        except Exception:
            pass

    if not missed_per_file:
        return {}

    def _branch_lines(fpath: str, source: str) -> dict:
        """Return {lineno: description} for every conditional branch."""
        lines = source.splitlines()
        bmap: dict[int, str] = {}
        try:
            tree = ast.parse(source, filename=fpath)
        except Exception:
            return bmap
        for node in ast.walk(tree):
            if not hasattr(node, 'lineno'):
                continue
            snip = lines[node.lineno - 1].strip()[:55]
            if isinstance(node, ast.If):
                bmap[node.lineno] = f"if (line {node.lineno}): {snip}"
                if node.orelse:
                    eln = node.orelse[0].lineno
                    bmap[eln] = (
                        f"else/elif (line {eln}): {lines[eln-1].strip()[:55]}"
                    )
            elif isinstance(node, ast.For):
                bmap[node.lineno] = f"for (line {node.lineno}): {snip}"
            elif isinstance(node, ast.While):
                bmap[node.lineno] = f"while (line {node.lineno}): {snip}"
            elif isinstance(node, ast.ExceptHandler):
                exc_name = (getattr(node.type, 'id', '...')
                            if node.type else '...')
                bmap[node.lineno] = (
                    f"except {exc_name} (line {node.lineno}): {snip}"
                )
        return bmap

    result: dict[str, list] = {}

    for src_dir in source_dirs:
        for root, _, files in os.walk(src_dir):
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(root, fname)
                if fpath not in missed_per_file:
                    continue
                try:
                    with open(fpath, encoding='utf-8', errors='ignore') as f:
                        source = f.read()
                    tree = ast.parse(source, filename=fpath)
                    missed = missed_per_file[fpath]
                    branches = _branch_lines(fpath, source)

                    for fn_node, _ in _iter_functions(tree):
                        end = getattr(fn_node, 'end_lineno', fn_node.lineno)
                        fn_missed = [
                            branches[ln]
                            for ln in range(fn_node.lineno, end + 1)
                            if ln in missed and ln in branches
                        ]
                        if fn_missed:
                            result[fn_node.name] = fn_missed
                except Exception:
                    pass

    return result


def _collect_body_skips(stmts) -> set:
    """Return line numbers of continue/break directly within stmts.

    Recurses into if/try/with blocks but NOT into nested for/while loops or
    nested function definitions, so a break inside a nested loop is not
    confused with a continue that skips the outer iteration.
    """
    lines: set[int] = set()
    for stmt in stmts:
        if isinstance(stmt, (ast.Continue, ast.Break)):
            lines.add(stmt.lineno)
        elif isinstance(stmt, ast.If):
            lines |= _collect_body_skips(stmt.body)
            lines |= _collect_body_skips(stmt.orelse)
        elif isinstance(stmt, ast.With):
            lines |= _collect_body_skips(stmt.body)
        elif isinstance(stmt, ast.Try):
            lines |= _collect_body_skips(stmt.body)
            for handler in stmt.handlers:
                lines |= _collect_body_skips(handler.body)
            lines |= _collect_body_skips(stmt.orelse)
            lines |= _collect_body_skips(
                getattr(stmt, 'finalbody', []) or []
            )
        # ast.For, ast.While, ast.FunctionDef, ast.AsyncFunctionDef → do not recurse
    return lines


def extract_skip_branches(source_dirs, coverage_file):
    """Find if-continue/break branches that fired during test execution.

    Uses coverage.py arc data (requires ``coverage run --branch``) to detect
    which conditional-skip patterns were exercised.  Each result becomes an
    orange SKIP node in the graph, directly representing the silent iteration
    skip rather than leaving the agent to infer it from a count mismatch.

    Arc data gives us binary information only (taken vs not-taken, no counts).
    The condition text is extracted from source via ``ast.unparse`` (Python
    ≥3.9) with a raw-line fallback for older interpreters.

    Returns:
        {func_name: [{'if_line': int, 'skip_line': int,
                      'condition': str, 'source_snippet': str}]}
    """
    try:
        import coverage as cov_module
    except ImportError:
        return {}

    try:
        cov = cov_module.Coverage(data_file=coverage_file)
        cov.load()
    except Exception as exc:
        print(f"Warning: could not load coverage data: {exc}")
        return {}

    data = cov.get_data()

    # arcs() returns None when branch tracking was not enabled
    taken_arcs: dict[str, set] = {}
    for fpath in data.measured_files():
        arcs = data.arcs(fpath)
        if arcs:
            taken_arcs[fpath] = set(arcs)

    if not taken_arcs:
        print("Warning: no arc data — re-run with "
              "'coverage run --branch' to enable skip-branch detection")
        return {}

    result: dict[str, list] = {}

    for src_dir in source_dirs:
        for root, _, files in os.walk(src_dir):
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(root, fname)
                if fpath not in taken_arcs:
                    continue
                try:
                    with open(fpath, encoding='utf-8', errors='ignore') as f:
                        source = f.read()
                    lines = source.splitlines()
                    tree = ast.parse(source, filename=fpath)
                    arcs = taken_arcs[fpath]

                    for fn_node, _ in _iter_functions(tree):
                        fn_skips = []
                        seen_if_lines: set[int] = set()

                        for node in ast.walk(fn_node):
                            if not isinstance(node, ast.If):
                                continue
                            if_line = node.lineno
                            if if_line in seen_if_lines:
                                continue

                            skip_lines = _collect_body_skips(node.body)
                            if not skip_lines:
                                continue

                            # Collect all line numbers within the if body
                            body_lines: set[int] = set()
                            for stmt in node.body:
                                for n in ast.walk(stmt):
                                    if hasattr(n, 'lineno'):
                                        body_lines.add(n.lineno)

                            # Check whether any arc leads to one of the skip lines.
                            # Coverage records (from_line, to_line) pairs; a pair
                            # ending at a continue/break line means that skip fired.
                            for skip_line in skip_lines:
                                sources = body_lines | {if_line}
                                if any((f, skip_line) in arcs for f in sources):
                                    if hasattr(ast, 'unparse'):
                                        cond = ast.unparse(node.test)
                                    else:
                                        cond = lines[if_line - 1].strip()
                                    fn_skips.append({
                                        'if_line': if_line,
                                        'skip_line': skip_line,
                                        'condition': cond,
                                        'source_snippet': lines[if_line - 1].strip(),
                                    })
                                    seen_if_lines.add(if_line)
                                    break

                        if fn_skips:
                            result[fn_node.name] = fn_skips
                except Exception:
                    pass

    return result


def _load_skip_events(path: str) -> dict:
    """Load skip_tracer JSON output and group by (function, if_line).

    Returns::

        {
          (fn_name, if_line): {
              'condition':  str,
              'if_line':    int,
              'skip_line':  int,
              'file':       str,
              'snapshots':  [{'var': 'repr_value', ...}, ...],
          },
          ...
        }
    """
    with open(path) as fh:
        events = json.load(fh)

    grouped: dict[tuple, dict] = {}
    for ev in events:
        key = (ev['function'], ev['if_line'])
        if key not in grouped:
            grouped[key] = {
                'condition':  ev['condition'],
                'if_line':    ev['if_line'],
                'skip_line':  ev['skip_line'],
                'file':       ev['file'],
                'snapshots':  [],
            }
        grouped[key]['snapshots'].append(ev['locals'])
    return grouped


def enrich_graph(G, source_dirs, coverage_file=None, skip_events_file=None):
    """Attach docstrings, closure annotations, and optional coverage data
    to KG nodes.

    Args:
        G: the NetworkX DiGraph built by parse_trace
        source_dirs: list of directories to crawl for .py source files
        coverage_file: path to a coverage.py .coverage data file (optional)
        skip_events_file: path to skip_tracer JSON output (optional).
            When provided, SKIP nodes are built from precise frame.f_locals
            snapshots instead of the approximate coverage-arc detection.
    """
    func_info = extract_function_info(source_dirs)

    for node, data in G.nodes(data=True):
        if data.get('type') != 'function':
            continue
        info = func_info.get(node)
        if not info:
            continue
        if info['docstring']:
            G.nodes[node]['docstring'] = info['docstring']
        G.nodes[node]['source_file'] = os.path.basename(info['filepath'])
        G.nodes[node]['source_lineno'] = info['lineno']
        parent = info.get('defined_within')
        if parent:
            G.nodes[node]['defined_within'] = parent
            # Add a structural "defines" edge from the enclosing function so
            # the nesting is visible in the graph and an agent's code-fetch
            # tool knows to look inside the parent rather than at the module level.
            if G.has_node(parent):
                if not G.has_edge(parent, node) or \
                        G[parent][node].get('type') != 'defines':
                    G.add_edge(parent, node, type="defines")

    if coverage_file:
        print("Analysing branch coverage...")
        missed = extract_missed_branches(source_dirs, coverage_file)
        for fn, branches in missed.items():
            if G.has_node(fn) and G.nodes[fn].get('type') == 'function':
                G.nodes[fn]['missed_branches'] = branches

        print("Detecting skip branches...")
        skips = extract_skip_branches(source_dirs, coverage_file)
        for fn, fn_skips in skips.items():
            if not G.has_node(fn):
                continue
            for skip in fn_skips:
                skip_id = f"SKIP:{fn}:L{skip['if_line']}"
                G.add_node(skip_id,
                           type="skip",
                           fn=fn,
                           condition=skip['condition'],
                           if_line=skip['if_line'],
                           skip_line=skip['skip_line'],
                           source_snippet=skip['source_snippet'])
                G.add_edge(fn, skip_id, type="skip_branch")

    if skip_events_file:
        print("Loading skip events from tracer...")
        grouped = _load_skip_events(skip_events_file)
        for (fn, if_line), info in grouped.items():
            if not G.has_node(fn):
                continue
            skip_id = f"SKIP:{fn}:L{if_line}"
            # Overwrite any coverage-based node with the richer tracer data
            G.add_node(skip_id,
                       type="skip",
                       fn=fn,
                       condition=info['condition'],
                       if_line=if_line,
                       skip_line=info['skip_line'],
                       snapshots=info['snapshots'],
                       skip_count=len(info['snapshots']))
            if not G.has_edge(fn, skip_id):
                G.add_edge(fn, skip_id, type="skip_branch")


# ── Visualization ──────────────────────────────────────────────────────────────

def _var_label(node_name: str, data: dict) -> str:
    """Build the label for a variable node.

    Shows every distinct value the variable held across all loop iterations,
    ordered by first appearance.  This avoids the 'last-write lies' problem
    where the final value (from a non-buggy iteration) masks the buggy one.

    Values are displayed untruncated up to _VAL_DISPLAY_LEN characters so
    that an agent does not need a follow-up tool call to see the full value.
    If the value is longer than that limit the clip is marked with '…'.
    """
    values_seen: list = data.get('values_seen', [])
    write_count: int = data.get('write_count', 0)

    if not values_seen:
        return node_name

    parts = [node_name]

    # Summarise write/distinct counts when the variable changed across iterations
    if write_count > 1:
        n_distinct = len(values_seen)
        parts.append(
            f"({write_count} writes"
            + (f", {n_distinct} distinct)" if n_distinct > 1 else ")")
        )

    shown = values_seen[:_MAX_VALUES_SHOWN]
    for v in shown:
        parts.append(_clip(v))
    if len(values_seen) > _MAX_VALUES_SHOWN:
        parts.append(f"  \u2026+{len(values_seen) - _MAX_VALUES_SHOWN} more values")

    return '\n'.join(parts)


def visualize_graph(G, out_file="trace_kg", var_threshold: int = 15):
    """Render the KG to a Graphviz file.

    Args:
        G: NetworkX DiGraph from parse_trace / enrich_graph
        out_file: output file stem
        var_threshold: variable nodes with more writes than this are hidden
            from the graph.  Their write counts still appear on the
            'writes×N' edge labels and are suppressed only from the
            separate node rendering.  Default: 15.
    """
    hidden_vars: set[str] = {
        n for n, d in G.nodes(data=True)
        if d.get('type') == 'variable'
        and d.get('write_count', 0) > var_threshold
    }

    # Graphviz interprets "name:port" syntax in DOT node IDs.  Any colon in a
    # node name (ERROR:AssertionError, SKIP:fn:L42) causes a spurious warning
    # and broken rendering.  We sanitize IDs here while keeping the original
    # name in the human-readable label.
    def _gv(name: str) -> str:
        return name.replace(':', '__')

    dot = Digraph(
        graph_attr={
            'rankdir': 'TB',
            # 'ortho' constrains edges to right angles but does not support
            # inline edge labels — Graphviz warns and drops them.  'spline'
            # gives curved edges that route around nodes and support labels.
            'splines': 'spline',
            'nodesep': '0.5',
            'ranksep': '1.0',
        }
    )

    # ── Add all nodes ─────────────────────────────────────────────────────────
    for node, data in G.nodes(data=True):
        if node in hidden_vars:
            continue
        node_type = data.get("type")

        if node_type == "function":
            parts = [node]
            closure_parent = data.get('defined_within')
            if closure_parent:
                parts.append(f'[closure inside {closure_parent}]')
            doc = data.get('docstring', '')
            if doc:
                parts.append(_short(doc.strip().split('\n')[0]))
            src = data.get('source_file', '')
            lineno = data.get('source_lineno', '')
            if src and lineno:
                parts.append(f"{src}:{lineno}")
            missed = data.get('missed_branches', [])
            if missed:
                parts.append('\u26a0 NOT TAKEN:')
                for b in missed[:4]:
                    parts.append(f'  {_short(b)}')
                if len(missed) > 4:
                    parts.append(f'  \u2026+{len(missed) - 4} more')
            label = '\n'.join(parts)
            fillcolor = 'lightyellow' if missed else 'white'
            dot.node(_gv(node), label=label, shape="box", style="filled",
                     fillcolor=fillcolor)

        elif node_type == "error":
            exc_type = data.get('exc_type', node.replace('ERROR:', ''))
            exc_msg = data.get('exc_msg', '')
            label = exc_type
            if exc_msg:
                label += f'\n{_clip(exc_msg, 200)}'
            dot.node(_gv(node), label=label, shape="doubleoctagon",
                     style="filled", fillcolor="red", fontcolor="white")

        elif node_type == "skip":
            # Orange hexagon: a taken if-continue/break branch that silently
            # skipped an iteration.  The condition is shown verbatim and, when
            # skip_tracer data is available, the local-variable state at the
            # moment of the skip is listed directly on the node.
            cond = data.get('condition', '')
            if_line = data.get('if_line', '?')
            skip_count = data.get('skip_count', '')
            snapshots: list = data.get('snapshots', [])

            header = f"SKIPPED (line {if_line})"
            if skip_count:
                header += f" \u00d7{skip_count}"
            parts = [header, f"if {_clip(cond, 80)}", "\u2192 continue/break"]

            if snapshots:
                # Collect unique repr values per variable across all snapshots.
                # Skip dunder attrs and values whose repr is too long to be readable.
                var_vals: dict[str, list[str]] = {}
                for snap in snapshots:
                    for k, v in snap.items():
                        if k.startswith('_') or len(v) > 80:
                            continue
                        var_vals.setdefault(k, [])
                        if v not in var_vals[k]:
                            var_vals[k].append(v)

                if var_vals:
                    # Show variables that vary across snapshots first (most
                    # diagnostic), then stable variables, up to 6 total.
                    varying = [(k, vs) for k, vs in var_vals.items() if len(vs) > 1]
                    stable  = [(k, vs) for k, vs in var_vals.items() if len(vs) == 1]
                    ordered = varying + stable
                    parts.append("locals at skip:")
                    for k, vs in ordered[:6]:
                        val_str = ', '.join(vs[:3])
                        if len(vs) > 3:
                            val_str += f', \u2026+{len(vs) - 3}'
                        parts.append(f"  {k} = {val_str}")

            label = '\n'.join(parts)
            dot.node(_gv(node), label=label, shape="hexagon", style="filled",
                     fillcolor="orange", fontcolor="black")

        else:
            dot.node(_gv(node), label=_var_label(node, data), shape="ellipse")

    # ── rank=same subgraphs to enforce tree depth levels ─────────────────────
    depths: dict = {}
    for node, data in G.nodes(data=True):
        if data.get("type") == "function":
            d = data.get("depth", 0)
            depths.setdefault(d, []).append(node)

    for nodes in [depths[k] for k in sorted(depths)]:
        with dot.subgraph() as s:
            s.attr(rank='same')
            for node in nodes:
                s.node(_gv(node))

    # ── Add edges ─────────────────────────────────────────────────────────────
    for u, v, data in G.edges(data=True):
        if u in hidden_vars or v in hidden_vars:
            continue
        edge_type = data.get("type")
        gu, gv = _gv(u), _gv(v)

        if edge_type == "calls":
            weight = data.get("weight", 1)
            seq = data.get("call_seq", 0)
            label = (f"calls\u00d7{weight} [#{seq}]"
                     if weight > 1 else f"calls [#{seq}]")
            penwidth = str(1.0 + min(weight / 10.0, 4.0))
            dot.edge(gu, gv, label=label, color="blue", penwidth=penwidth)

        elif edge_type == "writes":
            wc = data.get('write_count', 1)
            label = f"writes\u00d7{wc}" if wc > 1 else "writes"
            dot.edge(gu, gv, label=label, color="black")

        elif edge_type == "defines":
            dot.edge(gu, gv, label="defines", color="#aaaaaa",
                     style="dashed", penwidth="1")

        elif edge_type == "skip_branch":
            # Bold orange edge: function → SKIP node.
            # "taken ≥1×" because arc data gives binary presence, not count.
            dot.edge(gu, gv, label="skip branch\ntaken \u22651\u00d7",
                     color="darkorange", style="bold", penwidth="2.5")

        elif edge_type == "propagates":
            dot.edge(gu, gv, label="propagates", color="red")

        elif edge_type == "raises":
            if data.get("caught"):
                dot.edge(gu, gv, label="raises (caught)", color="gray",
                         style="dashed", penwidth="1")
            else:
                dot.edge(gu, gv, label="raises", color="orange",
                         style="dashed", penwidth="2")

        elif edge_type == "propagates_error":
            error = data.get("error", "")
            label = f"propagates\n{error}"
            dot.edge(gu, gv, label=label, color="orange", style="dashed",
                     penwidth="2.5", fontcolor="orange")

        elif edge_type == "passed_to":
            dot.edge(gu, gv, label="passed to", color="green", style="dashed")

        elif edge_type == "loops":
            loop_count = data.get("loop_count", "?")
            loop_var = data.get("loop_var")
            if loop_var:
                label = f"loops({loop_var}, \u00d7{loop_count})"
            else:
                label = f"loops(\u00d7{loop_count})"
            dot.edge(gu, gv, label=label, color="purple", style="dashed")

        else:
            dot.edge(gu, gv, label=edge_type or "", color="gray")

    dot.render(out_file, view=True)


def main():
    parser = argparse.ArgumentParser(
        description="Build a Knowledge Graph from a PySnooper execution trace."
    )
    parser.add_argument("--trace", required=True,
                        help="Path to the PySnooper trace file")
    parser.add_argument("--out", default="trace_kg",
                        help="Output file stem for Graphviz render "
                             "(default: trace_kg)")
    parser.add_argument("--source", nargs='+', metavar="DIR",
                        help="Source directories to crawl for docstrings, "
                             "closure detection, and branch information")
    parser.add_argument("--coverage", metavar="FILE",
                        help="coverage.py .coverage data file; enables "
                             "missed-branch annotation and skip-branch nodes "
                             "(requires --source and 'coverage run --branch')")
    parser.add_argument("--var-threshold", type=int, default=15,
                        metavar="N",
                        help="Hide variable nodes written more than N times "
                             "(default: 15)")
    args = parser.parse_args()

    print("Parsing trace...")
    G = parse_trace(args.trace)
    print(f"Nodes: {len(G.nodes)}  Edges: {len(G.edges)}")

    if args.source:
        print("Enriching with source info...")
        enrich_graph(G, source_dirs=args.source, coverage_file=args.coverage)

    visualize_graph(G, out_file=args.out, var_threshold=args.var_threshold)


if __name__ == "__main__":
    main()
