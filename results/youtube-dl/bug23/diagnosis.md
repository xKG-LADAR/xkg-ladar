### Root Cause

The regex in `js_to_json` does not match single-line comments (`// comment\n`). When processing `'{ 0: // comment\n1 }'`, the `//` and `comment` are not stripped out, causing invalid JSON output that leads to a `json.decoder.JSONDecodeError`.

### Location

File: `youtube_dl/utils.py`, lines 2136-2142 (the `re.sub` pattern in `js_to_json`)

### Fix

```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -2108,7 +2108,7 @@ def js_to_json(code):
         if v in ('true', 'false', 'null'):
             return v
-        elif v.startswith('/*') or v == ',':
+        elif v.startswith('/*') or v.startswith('//') or v == ',':
             return ""
 
         if v[0] in ("'", '"'):
@@ -2133,7 +2133,7 @@ def js_to_json(code):
     return re.sub(r'''(?sx)
         "(?:[^"\\]*(?:\\\\|\\['"nurtbfx/\n]))*[^"\\]*"|
         '(?:[^'\\]*(?:\\\\|\\['"nurtbfx/\n]))*[^'\\]*'|
-        /\*.*?\*/|,(?=\s*[\]}])|
+        /\*.*?\*/|//[^\n]*|,(?=\s*[\]}])|
         [a-zA-Z_][.a-zA-Z_0-9]*|
         \b(?:0[xX][0-9a-fA-F]+|0+[0-7]+)(?:\s*:)?|
         [0-9]+(?=\s*:)
```

### Explanation

The regular expression in `js_to_json` only handled block comments (`/* ... */`) but not single-line comments (`// ...`). When encountering `// comment`, it was not matched and thus not removed from the output, producing invalid JSON. The fix adds `//[^\n]*` to the regex pattern to match single-line comments, and updates the `fix_kv` function to recognize and strip them (return empty string) just like block comments.