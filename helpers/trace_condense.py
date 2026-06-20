#!/usr/bin/env python3
"""Condense repetitive PySnooper trace log blocks.

Usage:
    python trace_condense.py --log /path/to/trace.log

Output defaults to:
    fix_suggestions/trace_condensed.log
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List, Sequence, Tuple

# Source path markers
SOURCE_PATH_RE = re.compile(r"Source path:.*?(?P<path>/.*)")

# Variable lines (New var, Modified var, Starting var)
VAR_LINE_RE = re.compile(r"IE_TRACE:\s+(?:New var|Modified var|Starting var)")

# Lines where repr was skipped (value is '...')
ELLIPSIS_VAR_RE = re.compile(r"=\s*\.\.\.\s*$")

# Timestamp in trace lines
TIMESTAMP_RE = re.compile(r"\b\d{2}:\d{2}:\d{2}\.\d+\b")

# Source location: either "common.py:1939" or just a bare line number after "line"
# pysnooper format: "IE_TRACE:     05:00:30.469015 line      1939    ..."
CODE_LINE_RE = re.compile(r"IE_TRACE:.*\b(line|call|return|exception)\s+(\d+)")


def remove_library_traces(lines: Sequence[str]) -> List[str]:
    """Remove sections belonging to library source paths (/usr/lib, <frozen)."""
    filtered: List[str] = []
    inside_lib = False

    for line in lines:
        source_match = SOURCE_PATH_RE.search(line)

        if source_match:
            path = source_match.group("path").strip()
            if path.startswith("/usr/lib") or path.startswith("<frozen"):
                inside_lib = True
                continue
            else:
                inside_lib = False
                filtered.append(line)
                continue

        if inside_lib:
            continue

        filtered.append(line)

    return filtered


def collapse_ellipsis_vars(lines: Sequence[str]) -> List[str]:
    """Remove variable lines where the value is just '...' (no info)."""
    output: List[str] = []
    for line in lines:
        if VAR_LINE_RE.search(line) and ELLIPSIS_VAR_RE.search(line):
            continue
        output.append(line)
    return output


def condense_repeated_blocks(lines: Sequence[str]) -> List[str]:
    """Detect repeating multi-line blocks (loop iterations) and condense them.

    A loop iteration typically looks like a repeating sequence of traced
    source lines (with interspersed variable lines). We detect when the
    same sequence of (file, lineno) repeats and collapse.
    """
    # Build list of (line_index, source_key) for code lines only
    # Track current source file from Source path lines
    current_source = "unknown"
    code_line_indices: List[Tuple[int, str]] = []
    for i, line in enumerate(lines):
        sp = SOURCE_PATH_RE.search(line)
        if sp:
            current_source = sp.group("path").strip()
            continue
        m = CODE_LINE_RE.search(line)
        if m and m.group(1) == "line":
            code_line_indices.append((i, f"{current_source}:{m.group(2)}"))

    if not code_line_indices:
        return list(lines)

    # Find repeating subsequences in the code_line_indices
    # Strategy: for each position, try to find the longest repeating pattern
    # starting here

    # Build a simpler approach: look at the sequence of source keys
    keys = [k for _, k in code_line_indices]

    # Find repeating patterns
    # For each starting position, check if keys[i:i+L] == keys[i+L:i+2L]
    # and find maximal runs

    # Mark which original line ranges to keep vs condense
    # condensed_ranges: list of (start_orig_idx, end_orig_idx, repeat_count)
    condensed_ranges: List[Tuple[int, int, int]] = []

    i = 0
    while i < len(keys):
        best_period = 0
        best_count = 0

        # Try pattern lengths from 2 to 50
        for period in range(2, min(51, (len(keys) - i) // 2 + 1)):
            pattern = keys[i:i + period]
            count = 1
            j = i + period
            while j + period <= len(keys) and keys[j:j + period] == pattern:
                count += 1
                j += period

            if count >= 3 and count * period > best_count * best_period:
                best_period = period
                best_count = count

        if best_count >= 3:
            # Found a repeating block of best_period keys, repeating best_count times
            # Map back to original line indices
            first_block_start = code_line_indices[i][0]
            first_block_end_key_idx = i + best_period
            if first_block_end_key_idx < len(code_line_indices):
                first_block_end = code_line_indices[first_block_end_key_idx][0]
            else:
                first_block_end = len(lines)

            # Last block
            last_block_start_key_idx = i + best_period * (best_count - 1)
            last_block_start = code_line_indices[last_block_start_key_idx][0]
            last_block_end_key_idx = i + best_period * best_count
            if last_block_end_key_idx < len(code_line_indices):
                last_block_end = code_line_indices[last_block_end_key_idx][0]
            else:
                last_block_end = len(lines)

            condensed_ranges.append((
                first_block_end,   # skip from after first block
                last_block_start,  # skip until last block starts
                best_count
            ))
            i += best_period * best_count
        else:
            i += 1

    if not condensed_ranges:
        return list(lines)

    # Build output, skipping condensed ranges
    result: List[str] = []
    prev_end = 0
    for skip_start, skip_end, count in condensed_ranges:
        # Add everything before the skip
        result.extend(lines[prev_end:skip_start])
        # Add condensation marker
        skipped = count - 2
        result.append(
            f"IE_TRACE:     [CONDENSED] {skipped} identical loop iterations skipped "
            f"({count} total iterations, showing first and last)\n"
        )
        prev_end = skip_end

    # Add remainder
    result.extend(lines[prev_end:])

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Condense repetitive PySnooper trace loop blocks"
    )
    parser.add_argument(
        "--log",
        required=True,
        help="Path to input PySnooper log file",
    )
    parser.add_argument(
        "--out",
        default="fix_suggestions/trace_condensed.log",
        help="Path to output condensed log file",
    )
    args = parser.parse_args()

    in_path = Path(args.log)
    out_path = Path(args.out)

    if not in_path.exists():
        raise FileNotFoundError(f"Input log not found: {in_path}")

    lines = in_path.read_text(encoding="utf-8", errors="replace").splitlines(True)

    # Step 1: Remove library internals
    filtered = remove_library_traces(lines)
    lib_removed = len(lines) - len(filtered)

    # Step 2: Remove ellipsis-only variable lines (no info)
    cleaned = collapse_ellipsis_vars(filtered)
    ellipsis_removed = len(filtered) - len(cleaned)

    # Step 3: Condense repeated blocks (loop iterations)
    condensed = condense_repeated_blocks(cleaned)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(condensed), encoding="utf-8")

    print(f"Original lines: {len(lines)}")
    print(f"Library traces removed: {lib_removed}")
    print(f"Ellipsis vars removed: {ellipsis_removed}")
    print(f"After condensation: {len(condensed)}")
    print(f"Wrote condensed log: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
