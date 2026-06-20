#!/usr/bin/env python3
"""
Agentic debugger: Sonnet plans reads, Opus diagnoses (up to 2 Opus calls).

Flow:
  1. Sonnet sees KG → outputs structured reading plan with contingencies
  2. Execute plan locally (no LLM)
  3. Opus sees KG + gathered code → diagnosis OR requests more reads
  4. (Optional) Execute additional reads → Opus sees previous output + new code → final diagnosis

Usage:
    python3 debug_agent.py --kg trace_kg --workdir /path/to/project
"""

import os
import re
import ast
import json
import argparse
import subprocess
from pathlib import Path

import anthropic


# ── env ──────────────────────────────────────────────────────────────────────

def _load_dotenv(path: Path) -> None:
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


# ── code-fetching primitives ────────────────────────────────────────────────

def _grep(pattern: str, directory: str, file_glob: str = "*.py") -> list[dict]:
    cmd = ["grep", "-rn", "--include=" + file_glob, pattern, directory]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return []
    results = []
    for ln in out.splitlines()[:60]:
        parts = ln.split(":", 2)
        if len(parts) >= 3:
            try:
                results.append({"file": parts[0], "line": int(parts[1]), "text": parts[2]})
            except ValueError:
                pass
    return results


def _extract_function_source(file_path: str, func_name: str) -> str | None:
    try:
        src = Path(file_path).read_text(errors="replace")
    except OSError:
        return None
    try:
        tree = ast.parse(src)
        lines = src.splitlines(keepends=True)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == func_name:
                    return "".join(lines[node.lineno - 1:node.end_lineno])
    except SyntaxError:
        pass
    pattern = re.compile(r"^(\s*)def\s+" + re.escape(func_name) + r"\s*\(")
    src_lines = src.splitlines(keepends=True)
    for i, line in enumerate(src_lines):
        m = pattern.match(line)
        if m:
            indent = m.group(1)
            body = [line]
            for j in src_lines[i + 1:]:
                if j.strip() == "" or j.startswith(indent + " ") or j.startswith(indent + "\t"):
                    body.append(j)
                else:
                    break
            return "".join(body)
    return None


def fetch_function(function_name: str, workdir: str, file_hint: str | None = None) -> str:
    if file_hint:
        candidate = Path(workdir) / file_hint
        if candidate.is_file():
            src = _extract_function_source(str(candidate), function_name)
            if src:
                return f"# {file_hint}\n{src}"
    hits = _grep(f"def {function_name}", workdir)
    for hit in hits:
        src = _extract_function_source(hit["file"], function_name)
        if src:
            rel = Path(hit["file"]).relative_to(workdir) if Path(hit["file"]).is_relative_to(workdir) else hit["file"]
            return f"# {rel}:{hit['line']}\n{src}"
    return f"[NOT FOUND] {function_name}"


def read_file(file_path: str, workdir: str,
              start_line: int | None = None, end_line: int | None = None) -> str:
    p = Path(file_path) if Path(file_path).is_absolute() else Path(workdir) / file_path
    if not p.exists():
        return f"[NOT FOUND] {p}"
    lines = p.read_text(errors="replace").splitlines(keepends=True)
    sl = (start_line - 1) if start_line else 0
    el = end_line if end_line else len(lines)
    chunk = "".join(lines[sl:el])
    rel = p.relative_to(workdir) if p.is_relative_to(workdir) else p
    header = f"# {rel}"
    if start_line or end_line:
        header += f":{sl+1}-{el}"
    return f"{header}\n{chunk}"


def search_code(pattern: str, workdir: str,
                directory: str | None = None, file_glob: str = "*.py") -> str:
    search_dir = str(Path(workdir) / directory) if directory else workdir
    hits = _grep(pattern, search_dir, file_glob)
    if not hits:
        return f"[NO MATCHES] {pattern}"
    out = []
    for h in hits:
        rel = Path(h["file"]).relative_to(workdir) if Path(h["file"]).is_relative_to(workdir) else h["file"]
        out.append(f"{rel}:{h['line']}: {h['text']}")
    return "\n".join(out)


# ── reading plan executor ────────────────────────────────────────────────────

def _execute_read(read: dict, workdir: str) -> str:
    action = read.get("action", "")
    if action == "fetch_function":
        return fetch_function(
            read["name"], workdir, file_hint=read.get("file_hint"))
    elif action == "read_file":
        return read_file(
            read["path"], workdir,
            start_line=read.get("start_line"),
            end_line=read.get("end_line"))
    elif action == "search_code":
        return search_code(
            read["pattern"], workdir,
            directory=read.get("directory"),
            file_glob=read.get("file_glob", "*.py"))
    elif action == "list_dir":
        p = Path(workdir) / read.get("path", "")
        if p.is_dir():
            files = sorted(f.name for f in p.iterdir() if f.is_file())
            return "\n".join(files[:50])
        return f"[NOT A DIR] {p}"
    return f"[UNKNOWN ACTION] {action}"


def _check_condition(condition: str, result: str) -> bool:
    cond = condition.strip()
    m = re.match(r"""contains\s+['"](.+?)['"]""", cond)
    if m:
        return m.group(1) in result
    if cond == "not_found":
        return result.startswith("[NOT FOUND]") or result.startswith("[NO MATCHES]")
    if cond == "found":
        return not (result.startswith("[NOT FOUND]") or result.startswith("[NO MATCHES]"))
    m = re.match(r"line_count\s*>\s*(\d+)", cond)
    if m:
        return len(result.splitlines()) > int(m.group(1))
    m = re.match(r"length\s*>\s*(\d+)", cond)
    if m:
        return len(result) > int(m.group(1))
    return True


def execute_plan(plan: list[dict], workdir: str) -> dict[str, str]:
    gathered: dict[str, str] = {}

    def _walk(node: dict):
        label = node.get("label", node.get("name", node.get("path", f"read_{len(gathered)}")))
        result = _execute_read(node, workdir)
        gathered[label] = result
        print(f"  [read] {label}: {len(result)} chars")

        for cont in node.get("contingencies", []):
            condition = cont.get("if", "")
            if _check_condition(condition, result):
                for child in cont.get("then", []):
                    _walk(child)
            else:
                for child in cont.get("else", []):
                    _walk(child)

    for node in plan:
        _walk(node)

    return gathered


def _parse_json_plan(text: str) -> list[dict] | None:
    """Extract and parse a JSON array from LLM output."""
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    raw = json_match.group(1) if json_match else text.strip()
    try:
        plan = json.loads(raw)
        if isinstance(plan, list):
            return plan
    except json.JSONDecodeError:
        pass
    return None


def _extract_additional_reads(text: str) -> list[dict] | None:
    """Check if the diagnosis contains a NEED_MORE_CODE JSON block."""
    m = re.search(r"NEED_MORE_CODE\s*```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if not m:
        # Also try without code fence
        m = re.search(r"NEED_MORE_CODE\s*(\[.*?\])", text, re.DOTALL)
    if not m:
        return None
    try:
        reads = json.loads(m.group(1))
        if isinstance(reads, list) and len(reads) > 0:
            return reads
    except json.JSONDecodeError:
        pass
    return None


def _format_context(gathered: dict[str, str]) -> str:
    parts = []
    for label, content in gathered.items():
        parts.append(f"### {label}\n```\n{content}\n```")
    return "\n\n".join(parts)


# ── prompts ──────────────────────────────────────────────────────────────────

PLAN_SYSTEM = """\
You are a debugging planner. Given a Knowledge Graph (DOT format) from a failing test, \
produce a reading plan to gather all source code needed to diagnose the bug.

Output ONLY a JSON array. Each element is a read action:

{
  "action": "fetch_function" | "read_file" | "search_code" | "list_dir",
  "label": "short_unique_label",
  // for fetch_function:
  "name": "function_name",
  "file_hint": "optional/relative/path.py",
  // for read_file:
  "path": "relative/path",
  "start_line": null,
  "end_line": null,
  // for search_code:
  "pattern": "regex",
  "directory": "optional/subdir",
  // for list_dir:
  "path": "relative/dir",
  // contingencies (optional): conditional follow-up reads
  "contingencies": [
    {
      "if": "contains 'pattern'" | "not_found" | "found" | "line_count > N",
      "then": [ ...more read actions... ],
      "else": [ ...more read actions... ]
    }
  ]
}

Rules:
- Read the KG carefully. Identify which functions are on the error path.
- Start with the function that RAISES the error, then its callers.
- Use file_hint from KG node labels (e.g. "common.py:1768") to speed up lookups.
- Add contingencies for: function not found at hint → search without hint; \
file path from test data → read the test data file.
- Keep the plan MINIMAL. Only read what's needed to understand the error path.
- Do NOT include explanations, only the JSON array.
- Use descriptive labels (e.g. "parse_mpd_formats_src", "test_data_float_duration").
"""

DIAGNOSE_SYSTEM = """\
You are an expert Python debugger. You will be given:
1. A Knowledge Graph (KG) trace from a failing test (DOT format).
2. Source code gathered from the codebase.

Your task: identify the root cause and propose a minimal fix.

## Output format (STRICT)

Your response MUST have exactly these sections:

### Root Cause
1-3 sentences explaining WHY the bug occurs. Reference specific variable names from the KG.

### Location
File path and line number(s) where the fix should be applied.

### Fix
A unified diff showing the minimal change.

```diff
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -line,count +line,count @@
 context
-old line
+new line
 context
```

### Explanation
Brief explanation of why this fix works, referencing the KG error path.

## Requesting more code (use sparingly)

If you CANNOT diagnose the bug with the provided code — for example, a critical \
function body is missing or a referenced file was not included — you may request \
additional reads INSTEAD of guessing. To do this, end your response with:

NEED_MORE_CODE
```json
[
  {"action": "fetch_function", "label": "...", "name": "...", "file_hint": "..."},
  {"action": "read_file", "label": "...", "path": "..."}
]
```

Rules for NEED_MORE_CODE:
- Only use this if the missing code is CRITICAL to the diagnosis.
- Do NOT request code you can infer from the KG.
- Maximum 4 additional reads.
- Include your partial analysis BEFORE the NEED_MORE_CODE block so it is preserved.
"""


# ── main agent ───────────────────────────────────────────────────────────────

def run_agent(kg_text: str, workdir: str, api_key: str,
              verbose: bool = True, trace_text: str = "") -> str:
    client = anthropic.Anthropic(api_key=api_key)
    total_in = 0
    total_out = 0
    opus_calls = 0

    # ── Step 0: Empty-KG fallback ─────────────────────────────────────────────
    empty_kg = _is_empty_kg(kg_text)
    if empty_kg:
        print("\n[Step 0] KG is empty — switching to trace-based fallback...")

    # ── Step 1: Sonnet generates reading plan ────────────────────────────────
    print("\n[Step 1] Generating reading plan from KG...")

    # If KG is empty, try to derive a plan from the trace instead of asking
    # Sonnet to plan from a KG that has no nodes.
    if empty_kg and trace_text:
        import_plan = _import_error_plan(trace_text)
        if import_plan:
            print("  [empty-KG] detected ImportError — using import-error plan")
            plan = import_plan
            plan_text = "(import-error fallback, no LLM call)"
        else:
            print("  [empty-KG] no ImportError detected — using trace as KG context")
            plan_response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=PLAN_SYSTEM,
                messages=[{"role": "user", "content":
                    f"The KG is empty. Here is the raw test output:\n```\n{trace_text[:4000]}\n```\n"
                    f"Produce a reading plan to find and fix the bug."}],
            )
            total_in += plan_response.usage.input_tokens
            total_out += plan_response.usage.output_tokens
            plan_text = "".join(b.text for b in plan_response.content if b.type == "text")
            plan = _parse_json_plan(plan_text)
            if plan is None:
                plan = []
    else:
        plan_response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=PLAN_SYSTEM,
            messages=[{"role": "user", "content": f"```dot\n{kg_text}\n```"}],
        )
        total_in += plan_response.usage.input_tokens
        total_out += plan_response.usage.output_tokens
        print(f"  tokens: in={plan_response.usage.input_tokens} out={plan_response.usage.output_tokens}")

        plan_text = "".join(b.text for b in plan_response.content if b.type == "text")
        if verbose:
            print(f"  raw plan:\n{plan_text[:2000]}")

        plan = _parse_json_plan(plan_text)
        if plan is None:
            print("  [warn] JSON parse failed, falling back to basic plan")
            plan = _fallback_plan(kg_text)

    print(f"  plan has {len(plan)} top-level reads")

    # ── Step 2: Execute plan locally ─────────────────────────────────────────
    print("\n[Step 2] Executing reading plan...")
    gathered = execute_plan(plan, workdir)
    print(f"  gathered {len(gathered)} items, {sum(len(v) for v in gathered.values())} total chars")

    # ── Step 3: Opus diagnosis (call 1) ──────────────────────────────────────
    print("\n[Step 3] Opus diagnosis (call 1)...")

    context_block = _format_context(gathered)
    if empty_kg and trace_text:
        kg_section = (
            f"## Test Output (KG unavailable — trace below)\n```\n{trace_text[:3000]}\n```"
        )
    else:
        kg_section = f"## Knowledge Graph\n```dot\n{kg_text}\n```"
    diagnose_msg = (
        f"{kg_section}\n\n"
        f"## Gathered Source Code\n\n{context_block}\n\n"
        f"---\nDiagnose the bug and propose a fix following the output format strictly."
    )

    print(f"  prompt: {len(diagnose_msg)} chars")
    try:
        diag_response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=16384,
            system=DIAGNOSE_SYSTEM,
            messages=[{"role": "user", "content": diagnose_msg}],
        )
    except Exception as e:
        print(f"  [ERROR] API call failed: {e}")
        return f"API call failed: {e}"

    opus_calls += 1
    total_in += diag_response.usage.input_tokens
    total_out += diag_response.usage.output_tokens
    print(f"  tokens: in={diag_response.usage.input_tokens} out={diag_response.usage.output_tokens}")
    print(f"  stop_reason: {diag_response.stop_reason}")

    diagnosis = "".join(b.text for b in diag_response.content if b.type == "text")
    print(f"  diagnosis: {len(diagnosis)} chars")

    # ── Step 4 (conditional): Check if Opus needs more code ──────────────────
    additional_reads = _extract_additional_reads(diagnosis)
    if additional_reads and opus_calls < 2:
        print(f"\n[Step 4] Opus requested {len(additional_reads)} additional reads...")

        # Execute the additional reads
        extra_gathered = execute_plan(additional_reads, workdir)
        print(f"  gathered {len(extra_gathered)} additional items")

        # Build follow-up message with previous output + new code
        extra_context = _format_context(extra_gathered)

        # Strip the NEED_MORE_CODE block from the previous diagnosis
        # Handle various fence endings: ```\n, ``` EOF, trailing whitespace
        clean_diagnosis = re.sub(
            r"NEED_MORE_CODE.*", "", diagnosis, flags=re.DOTALL
        ).rstrip()

        # Merge all gathered code (original + extra) into one context block
        all_gathered = {**gathered, **extra_gathered}
        full_context = _format_context(all_gathered)

        followup_msg = (
            f"## Knowledge Graph\n```dot\n{kg_text}\n```\n\n"
            f"## All Source Code\n\n{full_context}\n\n"
            f"## Your previous analysis (for reference)\n\n{clean_diagnosis}\n\n"
            f"---\n"
            f"You now have all the code. Produce your FINAL answer.\n"
            f"You MUST include all four sections: Root Cause, Location, Fix (unified diff), Explanation.\n"
            f"Do NOT request more code. Do NOT continue analyzing. Output the fix NOW."
        )

        print(f"  followup prompt: {len(followup_msg)} chars")
        try:
            followup_response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=16384,
                system=DIAGNOSE_SYSTEM,
                messages=[{"role": "user", "content": followup_msg}],
            )
        except Exception as e:
            print(f"  [ERROR] Follow-up API call failed: {e}")
            # Return the partial diagnosis we have
            return clean_diagnosis

        opus_calls += 1
        total_in += followup_response.usage.input_tokens
        total_out += followup_response.usage.output_tokens
        print(f"  tokens: in={followup_response.usage.input_tokens} out={followup_response.usage.output_tokens}")
        print(f"  stop_reason: {followup_response.stop_reason}")

        followup_text = "".join(b.text for b in followup_response.content if b.type == "text")
        # Strip any NEED_MORE_CODE the model repeated despite instructions
        followup_text = re.sub(
            r"NEED_MORE_CODE.*", "", followup_text, flags=re.DOTALL
        ).rstrip()
        print(f"  followup text: {len(followup_text)} chars")
        print(f"  --- FOLLOW-UP RAW OUTPUT ---")
        print(followup_text)
        print(f"  --- END FOLLOW-UP ---")

        # Combine with clear markers
        diagnosis = (
            "# CALL 1: Initial Analysis\n\n"
            + clean_diagnosis
            + "\n\n---\n\n"
            + "# CALL 2: Final Diagnosis (with additional code)\n\n"
            + followup_text
        )
        print(f"  combined diagnosis: {len(diagnosis)} chars")

    # ── Done ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("  AGENT FINISHED")
    print(f"{'='*70}")
    print(f"  LLM calls     : {1 + opus_calls} (1 Sonnet + {opus_calls} Opus)")
    print(f"  Total input   : {total_in}")
    print(f"  Total output  : {total_out}")
    print(f"  Total tokens  : {total_in + total_out}")
    print(f"  Reads executed: {len(gathered)}")
    print(f"{'='*70}\n")

    if verbose:
        print(diagnosis)

    return diagnosis


def _fallback_plan(kg_text: str) -> list[dict]:
    plan = []
    for m in re.finditer(r'(\w+)\s*\[label="(\w+)\\n.*?(\w+\.py):(\d+)', kg_text):
        fn_name = m.group(2)
        file_hint = m.group(3)
        plan.append({
            "action": "fetch_function",
            "label": f"{fn_name}_src",
            "name": fn_name,
            "file_hint": file_hint,
        })
        if len(plan) >= 8:
            break
    return plan


def _is_empty_kg(kg_text: str) -> bool:
    """Return True if the KG has no function/variable/error nodes."""
    return not re.search(r'\bshape\s*=', kg_text)


def _import_error_plan(trace_text: str) -> list[dict] | None:
    """If the trace shows an ImportError for a missing symbol, return a plan
    that reads the test file and the target module so the agent can implement
    the missing function."""
    m = re.search(
        r"ImportError: cannot import name '(\w+)' from '([\w.]+)'\s+\(([^)]+)\)",
        trace_text,
    )
    if not m:
        return None
    symbol = m.group(1)
    module_path = m.group(3)  # absolute path like /path/to/utils.py
    # Try to find which test file is being run from the trace header
    test_m = re.search(r"Running: python -m unittest -q ([\w.]+)", trace_text)
    test_module = test_m.group(1) if test_m else None

    plan: list[dict] = []

    # Read the source module where the function should be added
    rel = Path(module_path)
    plan.append({
        "action": "read_file",
        "label": "target_module_tail",
        "path": str(rel.name),
        "start_line": None,
        "end_line": None,
        "contingencies": [
            {
                "if": "not_found",
                "then": [{"action": "search_code", "label": "module_search",
                           "pattern": f"def {symbol}"}],
            }
        ],
    })

    # Search for uses of the missing symbol in tests
    plan.append({
        "action": "search_code",
        "label": f"{symbol}_usage",
        "pattern": symbol,
        "directory": "test",
    })

    # If we know the test module, also read it
    if test_module:
        test_path = "test/" + test_module.split(".")[-2].replace(".", "/") + ".py"
        plan.append({
            "action": "read_file",
            "label": "test_file",
            "path": test_path,
            "start_line": None,
            "end_line": None,
        })

    return plan


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    here = Path(__file__).parent.resolve()

    parser = argparse.ArgumentParser(description="Agentic debugger: Sonnet plans, Opus diagnoses")
    parser.add_argument("--kg", default=str(here / "trace_kg"),
                        help="Path to the DOT KG file (default: trace_kg)")
    parser.add_argument("--trace", default=None,
                        help="Path to condensed trace log (used as fallback when KG is empty)")
    parser.add_argument("--workdir", required=True,
                        help="Path to the buggy project checkout")
    parser.add_argument("--env", default=str(here / ".env"),
                        help="Path to .env file with CLAUDE_API_KEY")
    parser.add_argument("--verbose", action="store_true", default=True)
    parser.add_argument("--output", default=str(here / "fix_suggestions" / "diagnosis.md"),
                        help="Save diagnosis to this file (default: fix_suggestions/diagnosis.md)")
    args = parser.parse_args()

    _load_dotenv(Path(args.env))
    api_key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ERROR: CLAUDE_API_KEY not set.")

    kg_path = Path(args.kg)
    if not kg_path.exists():
        raise SystemExit(f"ERROR: KG not found: {kg_path}")
    kg_text = kg_path.read_text()

    if not Path(args.workdir).is_dir():
        raise SystemExit(f"ERROR: workdir not found: {args.workdir}")

    trace_text = ""
    if args.trace:
        tp = Path(args.trace)
        if tp.exists():
            trace_text = tp.read_text(errors="replace")

    diagnosis = run_agent(kg_text, args.workdir, api_key,
                          verbose=args.verbose, trace_text=trace_text)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(diagnosis)
    print(f"[saved to {out_path}]")


if __name__ == "__main__":
    main()
