### Root Cause

The `js_to_json` function's regex for matching double-quoted strings is incorrect. The pattern `"(?:[^"\\]*(?:\\\\|\\")?)*"` fails to properly handle all escape sequences within double-quoted strings (like `\n`, `\u0027`). When the input is a double-quoted string containing `\n` and `\u0027`, the regex doesn't match the entire string as one token. Instead, it breaks it into fragments, and `fix_kv` wraps unquoted word fragments in additional quotes, producing invalid JSON like `""SAND" "Number": ...` which causes `json.decoder.JSONDecodeError`.

### Location

`youtube_dl/utils.py`, line 1565 (the regex in `re.sub`)

### Fix

```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1562,7 +1562,7 @@ def js_to_json(code):
         return '"%s"' % v
 
     res = re.sub(r'''(?x)
-        "(?:[^"\\]*(?:\\\\|\\")?)*"|
+        "(?:[^"\\]*(?:\\\\|\\[^\\])?)*"|
         '(?:[^'\\]*(?:\\\\|\\')?)*'|
         [a-zA-Z_][.a-zA-Z_0-9]*
         ''', fix_kv, code)
```

### Explanation

The original regex pattern for double-quoted strings only recognized `\\\\` (escaped backslash) and `\\"` (escaped quote) as valid escape sequences inside double-quoted strings. Any other escape sequence like `\\n`, `\\u0027`, etc., would cause the regex to fail to match the full string. By changing `\\"` to `\\[^\\]` (a backslash followed by any character that isn't a backslash), the regex now correctly handles all escape sequences (`\n`, `\u0027`, `\'`, etc.) within double-quoted strings. This ensures the entire input string `"SAND Number: SAND 2013-7800P\nPresenter: ..."` is matched as a single double-quoted token and passed through unchanged by `fix_kv`, producing valid JSON.