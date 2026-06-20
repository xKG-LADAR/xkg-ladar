### Root Cause
The `strip_jsonp` regex pattern `r'(?s)^[a-zA-Z0-9_]+\s*\(\s*(.*)\);?\s*?\s*$'` fails to match the second test case `'parseMetadata({"STATUS":"OK"})\n\n\n//epc'` because the string ends with `//epc` (a JavaScript comment), which is not accounted for by the regex. The regex expects optional whitespace and semicolons at the end, but not `//` comments. As a result, `strip_jsonp` returns the input unchanged, and `json.loads` fails with a `JSONDecodeError`.

### Location
`youtube_dl/utils.py`, line 1334

### Fix
```diff
--- a/youtube_dl/utils.py
+++ b/youtube_dl/utils.py
@@ -1331,4 +1331,5 @@
 
 
 def strip_jsonp(code):
-    return re.sub(r'(?s)^[a-zA-Z0-9_]+\s*\(\s*(.*)\);?\s*?\s*$', r'\1', code)
+    return re.sub(
+        r'(?s)^[a-zA-Z0-9_.]+\s*\(\s*(.*)\);?\s*?(?://[^\n]*)?\s*$', r'\1', code)
```

### Explanation
The fix updates the regex in two ways:
1. Adds `(?://[^\n]*)?` before the final `\s*$` to optionally match a JavaScript single-line comment (`//epc`) that may appear after the JSONP call.
2. Adds `.` to the character class `[a-zA-Z0-9_.]` to support function names with dots (though not strictly needed for this test case, it's a common JSONP pattern).

This allows the second test case `'parseMetadata({"STATUS":"OK"})\n\n\n//epc'` to match, extracting `{"STATUS":"OK"}` so that `json.loads` can parse it successfully.