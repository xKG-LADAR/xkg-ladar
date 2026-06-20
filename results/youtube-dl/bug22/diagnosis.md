# CALL 1: Initial Analysis



I need to see the `_match_one` function to understand how filter parts are parsed, since the error is `ValueError: Invalid filter part 'uploader = "變態妍字幕版 太妍 тест"'`.

---

# CALL 2: Final Diagnosis (with additional code)

### Root Cause

The `_match_one` function's regex for matching string comparison values (`strval`) only accepts ASCII alphanumeric characters (`[a-z0-9A-Z]*`), and doesn't support quoted strings at all. When the filter contains `uploader = "變態妍字幕版 太妍 тест"`, the regex fails to match because the value contains Unicode characters and spaces (within quotes), causing the function to raise `ValueError('Invalid filter part %r' % filter_part)`.

### Location

`youtube_dl/utils.py`, lines 2400-2416 (the `_match_one` function's regex and value extraction)

### Fix

```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -2399,7 +2399,9 @@ def _match_one(filter_part, dct):
     operator_rex = re.compile(r'''(?x)\s*
         (?P<key>[a-z_]+)
         \s*(?P<op>%s)(?P<none_inclusive>\s*\?)?\s*
         (?:
             (?P<intval>[0-9.]+(?:[kKmMgGtTpPeEzZyY]i?[Bb]?)?)|
+            (?P<quote>["\'])(?P<quotedstrval>(?:(?!(?P=quote)).|\\.)*?)(?P=quote)|
             (?P<strval>(?![0-9.])[a-z0-9A-Z]*)
         )
         \s*$
@@ -2414,7 +2416,7 @@ def _match_one(filter_part, dct):
             if m.group('op') not in ('=', '!='):
                 raise ValueError(
                     'Operator %s does not support string values!' % m.group('op'))
-            comparison_value = m.group('strval') or m.group('intval')
+            comparison_value = m.group('quotedstrval') or m.group('strval') or m.group('intval')
         else:
             try:
                 comparison_value = int(m.group('intval'))
@@ -2407,7 +2409,9 @@ def _match_one(filter_part, dct):
     if m:
         op = COMPARISON_OPERATORS[m.group('op')]
         actual_value = dct.get(m.group('key'))
-        if (m.group('strval') is not None or
+        if (m.group('quotedstrval') is not None or
+            m.group('strval') is not None or
             # If the original field is a string and matching comparisonvalue is
             # a number we should respect the origin of the original field
             # and process comparison value as a string (see
```

Let me provide a cleaner unified diff:

```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -2397,9 +2397,11 @@ def _match_one(filter_part, dct):
     operator_rex = re.compile(r'''(?x)\s*
         (?P<key>[a-z_]+)
         \s*(?P<op>%s)(?P<none_inclusive>\s*\?)?\s*
         (?:
             (?P<intval>[0-9.]+(?:[kKmMgGtTpPeEzZyY]i?[Bb]?)?)|
+            (?P<quote>["\'])(?P<quotedstrval>(?:(?!(?P=quote)).|\\.)*?)(?P=quote)|
             (?P<strval>(?![0-9.])[a-z0-9A-Z]*)
         )
         \s*$
         ''' % '|'.join(map(re.escape, COMPARISON_OPERATORS.keys())))
     m = operator_rex.search(filter_part)
     if m:
         op = COMPARISON_OPERATORS[m.group('op')]
         actual_value = dct.get(m.group('key'))
-        if (m.group('strval') is not None or
+        if (m.group('quotedstrval') is not None or
+            m.group('strval') is not None or
             # If the original field is a string and matching comparisonvalue is
             # a number we should respect the origin of the original field
             # and process comparison value as a string (see
@@ -2414,7 +2416,9 @@ def _match_one(filter_part, dct):
             if m.group('op') not in ('=', '!='):
                 raise ValueError(
                     'Operator %s does not support string values!' % m.group('op'))
-            comparison_value = m.group('strval') or m.group('intval')
+            comparison_value = m.group('quotedstrval') or m.group('strval') or m.group('intval')
+            if comparison_value is not None:
+                comparison_value = comparison_value.replace(r"\'", "'").replace(r'\"', '"')
         else:
             try:
                 comparison_value = int(m.group('intval'))
```

### Explanation

The regex in `_match_one` only supported bare alphanumeric string values via `(?P<strval>(?![0-9.])[a-z0-9A-Z]*)`. The test calls `match_filter_func('uploader = "變態妍字幕版 太妍 тест"')`, which contains a quoted string with Unicode characters and spaces. Since the regex couldn't match this, `m` was `None`, and the function fell through to `raise ValueError('Invalid filter part ...')`.

The fix adds a new regex alternative `(?P<quotedstrval>...)` that matches single or double-quoted strings (with escaped quote support), placed before the bare `strval` alternative. The extracted value has escape sequences for quotes unescaped. The condition checks are updated to also consider `quotedstrval` as a string value.